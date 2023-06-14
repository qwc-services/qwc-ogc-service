import os
import re
from urllib.parse import urljoin, urlencode, urlparse
from xml.etree import ElementTree

from flask import Response, stream_with_context
import requests

from qwc_services_core.permissions_reader import PermissionsReader
from qwc_services_core.runtime_config import RuntimeConfig
from wfs_response_filters import wfs_describefeaturetype, \
    wfs_getcapabilities, wfs_getfeature
from wms_response_filters import wms_getcapabilities, wms_getfeatureinfo


class OGCService:
    """OGCService class

    Provide OGC services (WMS, WFS) with permission filters.
    Acts as a proxy to a QGIS server.
    """

    def __init__(self, tenant, logger):
        """Constructor

        :param str tenant: Tenant ID
        :param Logger logger: Application logger
        """
        self.tenant = tenant
        self.logger = logger

        config_handler = RuntimeConfig("ogc", logger)
        config = config_handler.tenant_config(tenant)

        # get internal QGIS server URL from config
        # (default: local qgis-server container)
        self.default_qgis_server_url = config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'
        self.public_ogc_url_pattern = config.get(
            'public_ogc_url_pattern', '$origin$/.*/?$mountpoint$')
        self.qgis_server_identity_parameter = config.get("qgis_server_identity_parameter", None)

        self.resources = self.load_resources(config)
        self.permissions_handler = PermissionsReader(tenant, logger)

    def get(self, identity, service_name, host_url, params, script_root, origin):
        """Check and filter OGC GET request and forward to QGIS server.

        :param str identity: User identity
        :param str service_name: OGC service name
        :param str host_url: host url
        :param obj params: Request parameters
        :param str script_root: Request root path
        :param str origin: The origin of the original request
        """
        return self.request(
            identity, 'GET', service_name, host_url, params, script_root, origin
        )

    def post(self, identity, service_name, host_url, params, script_root, origin):
        """Check and filter OGC POST request and forward to QGIS server.

        :param str identity: User identity
        :param str service_name: OGC service name
        :param str host_url: host url
        :param obj params: Request parameters
        :param str script_root: Request root path
        :param str origin: The origin of the original request
        """
        return self.request(
            identity, 'POST', service_name, host_url, params, script_root, origin
        )

    def request(self, identity, method, service_name, host_url, params,
                script_root, origin):
        """Check and filter OGC request and forward to QGIS server.

        :param str identity: User identity
        :param str method: Request method 'GET' or 'POST'
        :param str service_name: OGC service name
        :param str host_url: host url
        :param obj params: Request parameters
        :param str script_root: Request root path
        :param str origin: The origin of the original request
        """
        # normalize parameter keys to upper case
        params = {k.upper(): v for k, v in params.items()}

        if self.qgis_server_identity_parameter is not None:
            parameter_name = self.qgis_server_identity_parameter.upper()
            if parameter_name in params:
                del params[parameter_name]

            if identity:
                params[parameter_name] = identity

        # get permission
        permission = self.service_permissions(
            identity, service_name, params.get('SERVICE')
        )

        # check request
        exception = self.check_request(params, permission)
        if exception:
            return Response(
                self.service_exception(
                    exception['code'], exception['message']),
                content_type='text/xml; charset=utf-8',
                status=200
            )

        # adjust request parameters
        self.adjust_params(params, permission, origin)

        # forward request and return filtered response
        return self.forward_request(
            method, host_url, params, script_root, permission
        )

    def check_request(self, params, permission):
        """Check request parameters and permissions.

        :param obj params: Request parameters
        :param obj permission: OGC service permission
        """
        exception = {}

        if permission.get('service_name') is None:
            # service unknown or not permitted
            exception = {
                'code': "Service configuration error",
                'message': "Service unknown or unsupported"
            }
        elif not params.get('REQUEST'):
            # REQUEST missing or blank
            exception = {
                'code': "OperationNotSupported",
                'message': "Please check the value of the REQUEST parameter"
            }
        else:
            service = params.get('SERVICE', '')
            request = params.get('REQUEST', '').upper()

            if service == 'WMS' and request == 'GETFEATUREINFO':
                # check info format
                info_format = params.get('INFO_FORMAT', 'text/plain')
                if re.match('^application/vnd.ogc.gml.+$', info_format):
                    # do not support broken GML3 info format
                    # i.e. 'application/vnd.ogc.gml/3.1.1'
                    exception = {
                        'code': "InvalidFormat",
                        'message': (
                            "Feature info format '%s' is not supported. "
                            "Possibilities are 'text/plain', 'text/html' or "
                            "'text/xml'."
                            % info_format
                        )
                    }
            elif service == 'WMS' and request == 'GETPRINT':
                # check print templates
                template = params.get('TEMPLATE')
                if template and template not in permission['print_templates']:
                    # allow only permitted print templates
                    exception = {
                        'code': "Error",
                        'message': (
                            'Composer template not found or not permitted'
                        )
                    }
            elif service == 'WFS' and request == 'TRANSACTION':
                # WFS-T not supported
                exception = {
                    'code': "OperationNotSupported",
                    'message': "WFS Transaction is not supported"
                }

        if not exception:
            # check layers params

            # lookup for layers params by request
            # {
            #     <SERVICE>: {
            #         <REQUEST>: [
            #            <optional layers param>, <mandatory layers param>
            #         ]
            #     }
            # }
            ogc_layers_params = {
                'WMS': {
                    'GETMAP': ['LAYERS', None],
                    'GETFEATUREINFO': ['LAYERS', 'QUERY_LAYERS'],
                    'GETLEGENDGRAPHIC': [None, 'LAYER'],
                    'GETLEGENDGRAPHICS': [None, 'LAYER'],  # QGIS legacy request
                    'DESCRIBELAYER': [None, 'LAYERS'],
                    'GETSTYLES': [None, 'LAYERS']
                },
                'WFS': {
                    'DESCRIBEFEATURETYPE': ['TYPENAME', None],
                    'GETFEATURE': [None, 'TYPENAME']
                }
            }

            layer_params = ogc_layers_params.get(service, {}).get(request, {})

            if service == 'WMS' and request == 'GETPRINT':
                mapname = self.get_map_param_prefix(params)

                if mapname and (mapname + ":LAYERS") in params:
                    layer_params = [mapname + ":LAYERS", None]

            if layer_params:
                permitted_layers = permission['public_layers'].copy()
                filename = params.get('FILENAME', '')
                if (service == 'WMS' and (
                    (request == 'GETMAP' and filename) or request == 'GETPRINT'
                )):
                    # When doing a raster export (GetMap with FILENAME)
                    # or printing (GetPrint), also allow background or external layers
                    permitted_layers += permission['internal_print_layers']
                if layer_params[0] is not None:
                    # check optional layers param
                    exception = self.check_layers(
                        layer_params[0], params, permitted_layers, False
                    )
                if not exception and layer_params[1] is not None:
                    # check mandatory layers param
                    exception = self.check_layers(
                        layer_params[1], params, permitted_layers, True
                    )

        return exception

    def check_layers(self, layer_param, params, permitted_layers, mandatory):
        """Check presence and permitted layers for requested layers parameter.

        :param str layer_param: Name of layers parameter
        :param obj params: Request parameters
        :param list(str) permitted_layers: List of permitted layer names
        :param bool mandatory: Layers parameter is mandatory
        """
        exception = None
        wms_layer_pattern = re.compile("^wms:(.+)#(.+)$")
        wfs_layer_pattern = re.compile("^wfs:(.+)#(.+)$")

        requested_layers = params.get(layer_param)
        if requested_layers:
            requested_layers = requested_layers.split(',')
            for layer in requested_layers:
                # allow only permitted layers
                if (
                    layer
                    and not wms_layer_pattern.match(layer)
                    and not wfs_layer_pattern.match(layer)
                    and not layer.startswith('EXTERNAL_WMS:')
                    and layer not in permitted_layers
                ):
                    exception = {
                        'code': "LayerNotDefined",
                        'message': (
                            'Layer "%s" does not exist or is not permitted'
                            % layer
                        )
                    }
                    break
        elif mandatory:
            # mandatory layers param is missing or blank
            exception = {
                'code': "MissingParameterValue",
                'message': (
                    '%s is mandatory for %s operation'
                    % (layer_param, params.get('REQUEST'))
                )
            }

        return exception

    def service_exception(self, code, message):
        """Create ServiceExceptionReport XML

        :param str code: ServiceException code
        :param str message: ServiceException text
        """
        return (
            '<ServiceExceptionReport version="1.3.0">\n'
            ' <ServiceException code="%s">%s</ServiceException>\n'
            '</ServiceExceptionReport>'
            % (code, message)
        )

    def adjust_params(self, params, permission, origin):
        """Adjust parameters depending on request and permissions.

        :param obj params: Request parameters
        :param obj permission: OGC service permission
        :param str origin: The origin of the original request
        """
        ogc_service = params.get('SERVICE', '')
        ogc_request = params.get('REQUEST', '').upper()

        if ogc_service == 'WFS':
            # always use version 1.0.0 for WFS requests
            self.logger.warning("Overriding WFS VERSION=1.0.0")
            params['VERSION'] = '1.0.0'

        if ogc_service == 'WMS' and ogc_request == 'GETMAP':
            requested_layers = params.get('LAYERS')
            if requested_layers:
                # collect requested layers and opacities
                requested_layers = requested_layers.split(',')
                requested_layers_opacities = self.padded_opacities(
                    requested_layers, params.get('OPACITIES')
                )

                # replace restricted group layers with permitted sublayers
                restricted_group_layers = permission['restricted_group_layers']
                hidden_sublayer_opacities = permission[
                    'hidden_sublayer_opacities'
                ]
                permitted_layers_opacities = \
                    self.expand_group_layers_and_opacities(
                        requested_layers_opacities, restricted_group_layers,
                        hidden_sublayer_opacities
                    )

                permitted_layers = [
                    l['layer'] for l in permitted_layers_opacities
                ]
                permitted_opacities = [
                    l['opacity'] for l in permitted_layers_opacities
                ]

                params['LAYERS'] = ",".join(permitted_layers)
                params['OPACITIES'] = ",".join(
                    [str(o) for o in permitted_opacities]
                )

        elif ogc_service == 'WMS' and ogc_request == 'GETFEATUREINFO':
            requested_layers = params.get('QUERY_LAYERS')
            if requested_layers:
                # replace restricted group layers with permitted sublayers
                requested_layers = requested_layers.split(',')
                restricted_group_layers = permission['restricted_group_layers']
                permitted_layers = self.expand_group_layers(
                    reversed(requested_layers), restricted_group_layers
                )

                # filter by queryable layers
                queryable_layers = permission['queryable_layers']
                permitted_layers = [
                    l for l in permitted_layers if l in queryable_layers
                ]

                # reverse layer order
                permitted_layers = reversed(permitted_layers)

                params['QUERY_LAYERS'] = ",".join(permitted_layers)

        elif (ogc_service == 'WMS' and
                ogc_request in ['GETLEGENDGRAPHIC', 'GETLEGENDGRAPHICS']):
            requested_layers = params.get('LAYER')
            if requested_layers:
                # replace restricted group layers with permitted sublayers
                requested_layers = requested_layers.split(',')
                restricted_group_layers = permission['restricted_group_layers']
                permitted_layers = self.expand_group_layers(
                    requested_layers, restricted_group_layers
                )

                params['LAYER'] = ",".join(permitted_layers)

        elif ogc_service == 'WMS' and ogc_request == 'GETPRINT':
            mapname = self.get_map_param_prefix(params)

            if mapname and (mapname + ":LAYERS") in params:
                requested_layers = params.get(mapname + ":LAYERS")

            if requested_layers:
                # collect requested layers and opacities
                requested_layers = requested_layers.split(',')
                requested_layers_opacities = self.padded_opacities(
                    requested_layers, params.get('OPACITIES')
                )

                # replace restricted group layers with permitted sublayers
                restricted_group_layers = permission['restricted_group_layers']
                hidden_sublayer_opacities = permission[
                    'hidden_sublayer_opacities'
                ]
                permitted_layers_opacities = \
                    self.expand_group_layers_and_opacities(
                        requested_layers_opacities, restricted_group_layers,
                        hidden_sublayer_opacities
                    )

                permitted_layers = [
                    l['layer'] for l in permitted_layers_opacities
                ]
                permitted_opacities = [
                    l['opacity'] for l in permitted_layers_opacities
                ]

                params[mapname + ":LAYERS"] = ",".join(permitted_layers)
                # NOTE: also set LAYERS, so QGIS Server applies OPACITIES
                #       correctly
                params['LAYERS'] = params[mapname + ":LAYERS"]
                params['OPACITIES'] = ",".join(
                    [str(o) for o in permitted_opacities]
                )

            # Rewrite URLs of EXTERNAL_WMS which point to the ogc service:
            #     <...>?REQUEST=GetPrint&map0:LAYERS=EXTERNAL_WMS:A&A:URL=http://<ogc_service_url>/theme
            # And point the URLs directly to the qgis server.
            # This because:
            # - ogc_service_url may not be resolvable in the qgis server container
            # - Even if ogc_service_url were resolvable, qgis-server doesn't know about the identity of the logged in user,
            #   hence it won't be able to load any restricted layers over the ogc service
            pattern = self.public_ogc_url_pattern\
                .replace("$origin$", re.escape(origin.rstrip("/")))\
                .replace("$tenant$", self.tenant)\
                .replace("$mountpoint$", re.escape(os.getenv("SERVICE_MOUNTPOINT", "").lstrip("/").rstrip("/") + "/"))
            for layer in params[mapname + ":LAYERS"].split(","):
                if not layer.startswith("EXTERNAL_WMS:"):
                    continue
                urlparam = layer[13:] + ":URL"
                if not urlparam in params:
                    continue
                params[urlparam] = re.sub(
                    pattern, self.default_qgis_server_url, params[urlparam])

        elif ogc_service == 'WMS' and ogc_request == 'DESCRIBELAYER':
            requested_layers = params.get('LAYERS')
            if requested_layers:
                # replace restricted group layers with permitted sublayers
                requested_layers = requested_layers.split(',')
                restricted_group_layers = permission['restricted_group_layers']
                permitted_layers = self.expand_group_layers(
                    reversed(requested_layers), restricted_group_layers
                )

                # reverse layer order
                permitted_layers = reversed(permitted_layers)

                params['LAYERS'] = ",".join(permitted_layers)

        elif ogc_service == 'WFS' and ogc_request == 'GETFEATURE':
            requested_layers = params.get('TYPENAME')
            if requested_layers:
                requested_layers = requested_layers.split(',')
                if len(requested_layers) == 1:
                    # single layer requested
                    # get permitted attributes for layer
                    permitted_attributes = permission['layers'].get(
                        requested_layers[0], {}
                    )

                    propertyname = params.get('PROPERTYNAME')
                    if propertyname:
                        # filter requested attributes
                        requested_attributes = propertyname.split(',')
                        attributes = [
                            attr for attr in requested_attributes
                            if attr in permitted_attributes
                        ]
                        params['PROPERTYNAME'] = ",".join(attributes)
                    else:
                        # add PROPERTYNAME to filter attributes in WFS server
                        params['PROPERTYNAME'] = ",".join(permitted_attributes)

    def padded_opacities(self, requested_layers, opacities_param):
        """Complement requested opacities to match number of requested layers.

        :param list(str) requested_layers: List of requested layer names
        :param str opacities_param: Value of OPACITIES request parameter
        """
        requested_layers_opacities = []

        requested_opacities = []
        if opacities_param:
            requested_opacities = opacities_param.split(',')

        for i, layer in enumerate(requested_layers):
            if i < len(requested_opacities):
                try:
                    opacity = int(requested_opacities[i])
                    if opacity < 0 or opacity > 255:
                        opacity = 255
                except ValueError as e:
                    opacity = 0
            else:
                # pad missing opacities with 255
                if i == 0 and opacities_param is not None:
                    # empty OPACITIES param
                    opacity = 0
                else:
                    opacity = 255
            requested_layers_opacities.append({
                'layer': layer,
                'opacity': opacity
            })

        return requested_layers_opacities

    def expand_group_layers(self, requested_layers, restricted_group_layers):
        """Recursively replace group layers with permitted sublayers and
        return resulting layer list.

        :param list(str) requested_layers: List of requested layer names
        :param obj restricted_group_layers: Lookup for group layers with
                                            restricted sublayers
        """
        permitted_layers = []

        for layer in requested_layers:
            if layer in restricted_group_layers.keys():
                # expand sublayers and reorder from bottom to top
                sublayers = reversed(restricted_group_layers.get(layer))
                permitted_layers += self.expand_group_layers(
                    sublayers, restricted_group_layers
                )
            else:
                # leaf layer or permitted group layer
                permitted_layers.append(layer)

        return permitted_layers

    def expand_group_layers_and_opacities(self, requested_layers_opacities,
                                          restricted_group_layers,
                                          hidden_sublayer_opacities):
        """Recursively replace group layers and opacities with permitted
        sublayers and return resulting layers and opacities list.

        :param list(obj) requested_layers_opacities: List of requested
            layer names and opacities as

                {
                    'layer': <layer name>
                    'opacity': <opacity>
                }

        :param obj restricted_group_layers: Lookup for group layers with
                                            restricted sublayers
        :param obj hidden_sublayer_opacities: Lookup for custom opacities of
                                              hidden sublayers
        """
        permitted_layers_opacities = []

        for lo in requested_layers_opacities:
            layer = lo['layer']
            opacity = lo['opacity']

            if layer in restricted_group_layers.keys():
                # expand sublayers ordered from bottom to top,
                # use opacity from group
                sublayers = reversed(restricted_group_layers.get(layer))
                sublayers_opacities = []

                for sublayer in sublayers:
                    sub_opacity = opacity
                    if sublayer in hidden_sublayer_opacities:
                        # scale opacity by custom opacity for hidden sublayer
                        custom_opacity = hidden_sublayer_opacities.get(
                            sublayer
                        )
                        sub_opacity = int(
                            opacity * custom_opacity / 100
                        )

                    sublayers_opacities.append({
                        'layer': sublayer,
                        'opacity': sub_opacity
                    })
                permitted_layers_opacities += \
                    self.expand_group_layers_and_opacities(
                        sublayers_opacities, restricted_group_layers,
                        hidden_sublayer_opacities
                    )
            else:
                # leaf layer or permitted group layer
                permitted_layers_opacities.append({
                    'layer': layer,
                    'opacity': opacity
                })

        return permitted_layers_opacities

    def forward_request(self, method, host_url, params, script_root,
                        permission):
        """Forward request to QGIS server and return filtered response.

        :param str method: Request method 'GET' or 'POST'
        :param str host_url: host url
        :param obj params: Request parameters
        :param str script_root: Request root path
        :param obj permission: OGC service permission
        """
        ogc_service = params.get('SERVICE', '')
        ogc_request = params.get('REQUEST', '').upper()

        stream = True
        if ogc_request in [
            'GETCAPABILITIES', 'GETPROJECTSETTINGS', 'GETFEATUREINFO',
            'DESCRIBEFEATURETYPE'
        ]:
            # do not stream if response is filtered
            stream = False

        # forward to QGIS server
        url = permission['ogc_url']
        if (ogc_service == 'WMS' and (
            (ogc_request == 'GETMAP' and params.get('FILENAME')) or
            ogc_request == 'GETPRINT'
        )):
            # use any custom print URL when doing a
            # raster export (GetMap with FILENAME) or printing
            url = permission['print_url']

        if method == 'POST':
            # log forward URL and params
            self.logger.info("Forward POST request to %s" % url)
            self.logger.info("  %s" % ("\n  ").join(
                ("%s = %s" % (k, v) for k, v, in params.items()))
            )

            response = requests.post(url, headers={'host': urlparse(host_url).netloc},
                                     data=params, stream=stream)
        else:
            # log forward URL and params
            self.logger.info("Forward GET request to %s?%s" %
                             (url, urlencode(params)))

            response = requests.get(url, headers={'host': urlparse(host_url).netloc},
                                    params=params, stream=stream)

        if response.status_code != requests.codes.ok:
            # handle internal server error
            self.logger.error("Internal Server Error:\n\n%s" % response.text)

            exception = {
                'code': "UnknownError",
                'message': "The server encountered an internal error or "
                           "misconfiguration and was unable to complete your "
                           "request."
            }
            return Response(
                self.service_exception(
                    exception['code'], exception['message']),
                content_type='text/xml; charset=utf-8',
                status=200
            )
        # return filtered response
        elif ogc_service == 'WMS' and ogc_request in [
            'GETCAPABILITIES', 'GETPROJECTSETTINGS'
        ]:
            return wms_getcapabilities(
                response, host_url, params, script_root, permission
            )
        elif ogc_service == 'WMS' and ogc_request == 'GETFEATUREINFO':
            return wms_getfeatureinfo(response, params, permission)
        # TODO: filter DescribeFeatureInfo
        elif ogc_service == 'WFS' and ogc_request == 'GETCAPABILITIES':
            return wfs_getcapabilities(response, params, permission)
        elif ogc_service == 'WFS' and ogc_request == 'DESCRIBEFEATURETYPE':
            return wfs_describefeaturetype(response, params, permission)
        elif (ogc_service == 'WFS' and ogc_request == 'GETFEATURE' and
                len(params.get('TYPENAME', '').split(',')) > 1):
            # filter response if multiple layers requested
            return wfs_getfeature(response, params, permission)
        else:
            # unfiltered streamed response
            return Response(
                stream_with_context(response.iter_content(chunk_size=16*1024)),
                content_type=response.headers['content-type'],
                status=response.status_code
            )

    def load_resources(self, config):
        """Load service resources from config.

        :param RuntimeConfig config: Config handler
        """
        wms_services = {}
        wfs_services = {}

        # collect WMS service resources
        for wms in config.resources().get('wms_services', []):
            # get any custom WMS URL
            wms_url = wms.get(
                'wms_url', urljoin(self.default_qgis_server_url, wms['name'])
            )

            # get any custom online resources
            online_resources = wms.get('online_resources', {})

            resources = {
                # WMS URL
                'wms_url': wms_url,
                # custom online resources
                'online_resources': {
                    'service': online_resources.get('service'),
                    'feature_info': online_resources.get('feature_info'),
                    'legend': online_resources.get('legend')
                },
                # root layer name
                'root_layer': wms['root_layer']['name'],
                # public layers without hidden sublayers: [<layers>]
                'public_layers': [],
                # layers with available attributes: {<layer>: [<attrs>]}
                'layers': {},
                # queryable layers: [<layers>]
                'queryable_layers': [],
                # layer aliases for feature info results:
                #     {<feature info layer>: <layer>}
                'feature_info_aliases': {},
                # lookup for complete group layers
                # sub layers ordered from top to bottom:
                #     {<group>: [<sub layers]}
                'group_layers': {},
                # custom opacities for hidden sublayers:
                #     {<layer>: <opacity (0-100)>}
                'hidden_sublayer_opacities': {},
                # print URL, e.g. if using a separate QGIS project for printing
                'print_url': wms.get('print_url', wms_url),
                # internal layers for printing: [<layers>]
                'internal_print_layers': wms.get('internal_print_layers', []),
                # print templates: [<template name>]
                'print_templates': wms.get('print_templates', [])
            }

            # collect WMS layers
            self.collect_layers(wms['root_layer'], resources, False)

            wms_services[wms['name']] = resources

        # collect WFS service resources
        for wfs in config.resources().get('wfs_services', []):
            # get any custom WFS URL
            wfs_url = wfs.get(
                'wfs_url', urljoin(self.default_qgis_server_url, wfs['name'])
            )

            # collect WFS layers and attributes
            layers = {}
            for layer in wfs['layers']:
                layers[layer['name']] = layer.get('attributes', [])

            resources = {
                # WMS URL
                'wfs_url': wfs_url,
                # custom online resource
                'online_resource': wfs.get('online_resource'),
                # layers with available attributes: {<layer>: [<attrs>]}
                'layers': layers
            }

            wfs_services[wfs['name']] = resources

        return {
            'wms_services': wms_services,
            'wfs_services': wfs_services
        }

    def collect_layers(self, layer, resources, hidden):
        """Recursively collect layer info for layer subtree from config.

        :param obj layer: Layer or group layer
        :param obj resources: Partial lookups for layer resources
        :param bool hidden: Whether layer is a hidden sublayer
        """
        if not hidden:
            resources['public_layers'].append(layer['name'])

        if layer.get('layers'):
            # group layer

            hidden |= layer.get('hide_sublayers', False)

            # collect sub layers
            queryable = False
            sublayers = []
            for sublayer in layer['layers']:
                sublayers.append(sublayer['name'])
                # recursively collect sub layer
                self.collect_layers(sublayer, resources, hidden)
                if sublayer['name'] in resources['queryable_layers']:
                    # group is queryable if any sub layer is queryable
                    queryable = True

            resources['group_layers'][layer['name']] = sublayers
            if queryable:
                resources['queryable_layers'].append(layer['name'])
        else:
            # layer

            # attributes
            resources['layers'][layer['name']] = layer.get('attributes', [])

            if hidden and layer.get('opacity'):
                # add custom opacity for hidden sublayer
                resources['hidden_sublayer_opacities'][layer['name']] = \
                    layer.get('opacity')

            if layer.get('queryable', False) is True:
                resources['queryable_layers'].append(layer['name'])
                layer_title = layer.get('title', layer['name'])
                resources['feature_info_aliases'][layer_title] = layer['name']

    def service_permissions(self, identity, service_name, ows_type):
        """Return permissions for a OGC service.

        :param str identity: User identity
        :param str service_name: OGC service name
        :param str ows_type: OWS type (WMS or WFS)
        """
        self.logger.debug("Getting permissions for identity %s", identity)

        if ows_type == 'WMS':
            if not self.resources['wms_services'].get(service_name):
                # WMS service unknown
                return {}

            # get permissions for WMS
            wms_permissions = self.permissions_handler.resource_permissions(
                'wms_services', identity, service_name
            )
            if not wms_permissions:
                # WMS not permitted
                return {}

            wms_resources = self.resources['wms_services'][service_name].copy()

            # get available layers
            available_layers = set(
                list(wms_resources['layers'].keys()) +
                list(wms_resources['group_layers'].keys()) +
                wms_resources['internal_print_layers']
            )

            # combine permissions
            # permitted layers with permitted attributes: {<layer>: [<attrs>]}
            permitted_layers = {}
            permitted_print_templates = set()
            for permission in wms_permissions:
                # collect available and permitted layers
                for layer in permission['layers']:
                    name = layer['name']
                    if name in available_layers:
                        if name not in permitted_layers:
                            # add permitted layer
                            permitted_layers[name] = set()

                        # collect available and permitted attributes
                        attributes = [
                            attr for attr in layer.get('attributes', [])
                            if attr in wms_resources['layers'][name]
                        ]
                        # add any attributes
                        permitted_layers[name].update(attributes)

                # collect available and permitted print templates
                print_templates = [
                    template for template in permission.get('print_templates', [])
                    if template in wms_resources['print_templates']
                ]
                permitted_print_templates.update(print_templates)

            # filter by permissions

            public_layers = [
                layer for layer in wms_resources['public_layers']
                if layer in permitted_layers
            ]

            # layer attributes
            layers = {}
            for layer, attrs in wms_resources['layers'].items():
                if layer in permitted_layers:
                    # filter attributes by permissions
                    layers[layer] = [
                        attr for attr in attrs
                        if attr in permitted_layers[layer]
                    ]

            queryable_layers = [
                layer for layer in wms_resources['queryable_layers']
                if layer in permitted_layers
            ]

            feature_info_aliases = {}
            for alias, layer in wms_resources['feature_info_aliases'].items():
                if layer in permitted_layers:
                    feature_info_aliases[alias] = layer

            # restricted group layers
            restricted_group_layers = {}
            # NOTE: always expand all group layers
            for group, sublayers in wms_resources['group_layers'].items():
                if group in permitted_layers:
                    # filter sublayers by permissions
                    restricted_group_layers[group] = [
                        layer for layer in sublayers
                        if layer in permitted_layers
                    ]

            hidden_sublayer_opacities = {}
            for layer, opacity in wms_resources['hidden_sublayer_opacities'].items():
                if layer in permitted_layers:
                    hidden_sublayer_opacities[layer] = opacity

            internal_print_layers = [
                layer for layer in wms_resources['internal_print_layers']
                if layer in permitted_layers
            ]

            print_templates = [
                template for template in wms_resources['print_templates']
                if template in permitted_print_templates
            ]

            return {
                'service_name': service_name,
                # WMS URL
                'ogc_url': wms_resources['wms_url'],
                # print URL
                'print_url': wms_resources['print_url'],
                # custom online resource
                'online_resources': wms_resources['online_resources'],
                # public layers without hidden sublayers
                'public_layers': public_layers,
                # layers with permitted attributes
                'layers': layers,
                # queryable layers
                'queryable_layers': queryable_layers,
                # layer aliases for feature info results
                'feature_info_aliases': feature_info_aliases,
                # lookup for group layers with restricted sublayers
                # sub layers ordered from top to bottom:
                #     {<group>: [<sub layers>]}
                'restricted_group_layers': restricted_group_layers,
                # custom opacities for hidden sublayers
                'hidden_sublayer_opacities': hidden_sublayer_opacities,
                # internal layers for printing
                'internal_print_layers': internal_print_layers,
                # print templates
                'print_templates': print_templates
            }
        elif ows_type == 'WFS':
            if not self.resources['wfs_services'].get(service_name):
                # WFS service unknown
                return {}

            # get permissions for WFS
            wfs_permissions = self.permissions_handler.resource_permissions(
                'wfs_services', identity, service_name
            )
            if not wfs_permissions:
                # WFS not permitted
                return {}

            wfs_resources = self.resources['wfs_services'][service_name].copy()

            # get available layers
            available_layers = set(list(wfs_resources['layers'].keys()))

            # combine permissions
            # permitted layers with permitted attributes: {<layer>: [<attrs>]}
            permitted_layers = {}
            for permission in wfs_permissions:
                # collect available and permitted layers
                for layer in permission['layers']:
                    name = layer['name']
                    if name in available_layers:
                        if name not in permitted_layers:
                            # add permitted layer
                            permitted_layers[name] = set()

                        # collect available and permitted attributes
                        attributes = [
                            attr for attr in layer.get('attributes', [])
                            if attr in wfs_resources['layers'][name]
                        ]
                        # add any attributes
                        permitted_layers[name].update(attributes)

            # filter by permissions

            public_layers = [
                layer for layer in wfs_resources['layers']
                if layer in permitted_layers
            ]

            # layer attributes
            layers = {}
            for layer, attrs in wfs_resources['layers'].items():
                if layer in permitted_layers:
                    # filter attributes by permissions
                    layers[layer] = [
                        attr for attr in attrs
                        if attr in permitted_layers[layer]
                    ]

            return {
                'service_name': service_name,
                # WFS URL
                'ogc_url': wfs_resources['wfs_url'],
                # custom online resource
                'online_resource': wfs_resources['online_resource'],
                # public layers
                'public_layers': public_layers,
                # layers with permitted attributes
                'layers': layers
            }

        # unsupported OWS type
        return {}

    def get_map_param_prefix(self, params):
        # Deduce map name by looking for param which ends with :EXTENT
        # (Can't look for param ending with :LAYERS as there might be i.e. A:LAYERS for the external layer definition A)
        mapname = ""
        for key, value in params.items():
            if key.endswith(":EXTENT"):
                return key[0:-7]
        return ""
