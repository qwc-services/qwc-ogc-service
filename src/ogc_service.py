import json
from xml.sax.saxutils import escape as xml_escape

from flask import (
    Response,
    current_app,
    make_response,
    request,
    stream_with_context,
)
from gettranslations_handler import GetTranslationsHandler
from ogc_service_handler import OgcRequest, ServiceException
from qwc_services_core.auth import get_username
from qwc_services_core.permissions_reader import PermissionsReader
from qwc_services_core.runtime_config import RuntimeConfig
from wfs_handler import WfsHandler
from wms_handler import WmsHandler


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
        self.config = config_handler.tenant_config(tenant)

        self.enabled_handlers = [
            WmsHandler,
            WfsHandler,
            GetTranslationsHandler
        ]

        # get internal QGIS server URL from config
        # (default: local qgis-server container)
        self.default_qgis_server_url = self.config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'

        qgis_server_url_tenant_suffix = self.config.get('qgis_server_url_tenant_suffix', '').strip('/')
        if qgis_server_url_tenant_suffix:
            self.default_qgis_server_url += qgis_server_url_tenant_suffix + '/'

        self.basic_auth_login_url = self.config.get('basic_auth_login_url')
        self.qgis_server_identity_parameter = self.config.get("qgis_server_identity_parameter", "QWC_USERNAME")

        self.resources = self.load_resources(self.config)
        self.permissions_handler = PermissionsReader(tenant, logger)

    def process_request(self, identity, method, service_name, params, data):
        """Check and filter OGC request and forward to QGIS server.

        :param str identity: User identity
        :param str method: Request method 'GET' or 'POST'
        :param str service_name: OGC service name
        :param obj params: Request parameters
        :param obj data: Request POST data
        """
        # normalize parameter keys to upper case
        params = {k.upper(): v for k, v in params.items()}

        # Check if basic auth challenge should be sent
        require_auth = params.get('REQUIREAUTH', '').lower() in ["1", "true"]
        if not identity and require_auth:
            # Return WWW-Authenticate header, e.g. for browser password prompt
            response = make_response("Unauthorized", 401)
            response.headers["WWW-Authenticate"] = 'Basic realm="Login Required"'
            return response
        params.pop('REQUIREAUTH', None)

        # Inject identity parameter if configured
        if self.qgis_server_identity_parameter is not None:
            parameter_name = self.qgis_server_identity_parameter.upper()
            if identity:
                params[parameter_name] = get_username(identity)
            elif parameter_name in params:
                del params[parameter_name]

        service = params.get('SERVICE', '').upper()
        permissions = self.service_permissions(identity, service_name, service)

        if not permissions:
            # service unknown or not permitted
            return self.service_exception(
                "ServiceNotSupported",
                "Service unknown or not permitted"
            )

        req = OgcRequest(permissions['ogc_url'], method, service_name, params, data)
        for handlerClass in self.enabled_handlers:
            if handlerClass.accepts(req):
                break
        else:
            handlerClass = None
        if not handlerClass:
            return self.service_exception(
                "ServiceNotSupported", "Service unknown or not permitted"
            )

        handler = handlerClass(
            self.logger, self.config, self.default_qgis_server_url, self.permissions_handler, identity
        )

        # check and adjust request params
        try:
            handler.adjust_request_params(req, permissions)
        except ServiceException as e:
            return self.service_exception(e.code, e.message)

        # forward request and return filtered response
        # NOTE: do not stream filtered responses
        stream = not current_app.testing and handler.response_streamable(req)

        # forward to QGIS server
        try:
            response = handler.forward_request(req, stream)
        except ServiceException as e:
            return self.service_exception(e.code, e.message)

        filtered_response = handler.filter_response(req, response, permissions)

        if filtered_response:
            return filtered_response
        elif stream:
            return Response(
                stream_with_context(response.iter_content(chunk_size=16*1024)),
                content_type=response.headers['content-type'],
                status=response.status_code
            )
        else:
            return Response(
                response.content,
                content_type=response.headers['content-type'],
                status=response.status_code
            )

    def service_exception(self, code, message):
        """Create ServiceExceptionReport XML

        :param str code: ServiceException code
        :param str message: ServiceException text
        """
        response_body = (
            '<ServiceExceptionReport version="1.3.0">\n'
            f' <ServiceException code="{code}">{xml_escape(message)}</ServiceException>\n'
            '</ServiceExceptionReport>'
        )
        return Response(
            response_body,
            content_type='text/xml; charset=utf-8',
            status=200
        )

    def load_resources(self, config):
        """Load service resources from config.

        :param RuntimeConfig config: Config handler
        """
        wms_services = {}
        wfs_services = {}
        for wms in config.resources().get('wms_services', []):
            ogc_url = wms.get('wms_url', self.default_qgis_server_url + wms['name'])
            online_resources = wms.get('online_resources', {})
            for key in online_resources:
                if online_resources[key].startswith('/'):
                    online_resources[key] = request.host_url.rstrip('/') + online_resources[key]
            wms_services[wms['name']] = {
                'layers': self.collect_resource_layers(wms["root_layer"]),
                'ogc_url': ogc_url,
                'print_url': wms.get('print_url', ogc_url),
                'online_resources': online_resources,
                'print_templates': wms.get('print_templates', []),
                'internal_print_layers': wms.get('internal_print_layers', [])
            }
            for layer_name in wms.get('internal_print_layers', []):
                wms_services[wms['name']]['layers'][layer_name] = {
                    'title': layer_name,
                    'opacity': 100,
                    'attributes': {}
                }

        for wfs in config.resources().get('wfs_services', []):
            online_resource = wfs.get('online_resource')
            if online_resource and online_resource.startswith('/'):
                online_resource = request.host_url.rstrip('/') + online_resource
            wfs_services[wfs['name']] = {
                'ogc_url': wfs.get('wfs_url', self.default_qgis_server_url + wfs['name']),
                'online_resource': online_resource,
                'layers': self.collect_resource_layers(wfs)
            }

        return {"wms_services": wms_services, "wfs_services": wfs_services}

    def collect_resource_layers(self, layer, result=None, hidden=False):
        """Recursively collect layer info for layer subtree from config.

        :param list layers: Layers
        """
        if result is None:
            result = {}

        for sublayer in layer.get('layers', []):
            self.collect_resource_layers(sublayer, result, hidden or layer.get('hide_sublayers', False))

        # Convert from legacy format (without attribute aliases)
        attributes = layer.get('attributes', {})
        if isinstance(attributes, list):
            attributes = {attr: attr for attr in attributes}

        # group is queryable if any sub layer is queryable
        queryable_sublayers = next(filter(lambda x: x.get('queryable'), result.values()), None) is not None
        layer_sublayers = [
            {'name': sublayer['name'], 'opacity': sublayer.get('opacity', 100)} for sublayer in layer.get('layers', [])
        ]

        # With facade layers, a layer may appear multiple times in the WMS layer tree
        prev_result = result.get(layer['name'], {})


        if (
            prev_result and (layer_sublayers or prev_result.get('sublayers')) and
            json.dumps(layer_sublayers) != json.dumps(prev_result.get('sublayers'))
        ):
                self.logger.warning(f"The group layer '{layer['name']}' appears multiple times with different sublayers")

        result[layer['name']] = {
            'title': layer.get('title', layer['name']),
            'attributes': attributes,
            # Mark a layer as queryable if any occurence in the WMS tree is queryable
            'queryable': prev_result.get('queryable', False) or layer.get('queryable', False) or queryable_sublayers,
            'opacity': layer.get('opacity', 100),
            # Only mark the layer as hidden if all it's occurences in the WMS tree are hidden
            'hidden': prev_result.get('hidden', True) and hidden,
            'hide_sublayers': layer.get('hide_sublayers', False),
            'sublayers': layer_sublayers,
            'edit_layers': layer.get('edit_layers', [])
        }
        return result

    def service_permissions(self, identity, service_name, ows_type):
        """Return permissions for a OGC service.

        :param str identity: User identity
        :param str service_name: OGC service name
        :param str ows_type: OWS service type
        """
        self.logger.debug("Getting permissions for identity %s", identity)

        if ows_type == 'WMS' or ows_type == "GETTRANSLATIONS":
            wms_resource = self.resources['wms_services'].get(service_name)
            if not wms_resource:
                # WMS service unknown
                return {}

            wms_permissions = self.permissions_handler.resource_permissions(
                'wms_services', identity, service_name
            )
            if not wms_permissions:
                # WMS not permitted
                return {}

            # collect permissions
            permitted_layers = {}
            layer_name_from_title = {}
            permitted_print_templates = set()
            for permissions in wms_permissions:
                for layer_permission in permissions['layers']:
                    layer_name = layer_permission['name']
                    layer_resource = wms_resource['layers'].get(layer_name)
                    if not layer_resource:
                        continue
                    if layer_name not in permitted_layers:
                        # add permitted layer
                        permitted_layers[layer_name] = {
                            'title': layer_resource['title'],
                            'attributes': {},
                            'queryable': False,
                            'opacity': layer_resource['opacity'],
                            'edit_layers': layer_resource.get('edit_layers')
                        }
                        layer_name_from_title[layer_resource.get('title', layer_name)] = layer_name
                    permitted_layer = permitted_layers[layer_name]
                    # queryable
                    if layer_resource.get('queryable', False):
                        permitted_layer['queryable'] |= layer_permission.get('queryable', False)
                    # add permitted attributes
                    for attr in layer_permission.get('attributes', []):
                        if attr in layer_resource['attributes']:
                            permitted_layer['attributes'][attr] = layer_resource['attributes'][attr]

                # collect permitted print templates
                permitted_print_templates.update(permissions.get('print_templates', []))

            # filter resources by permissions
            public_layers = [
                layername for layername, layer in wms_resource['layers'].items()
                if layername in permitted_layers and not layer.get('hidden')
                and layername not in wms_resource['internal_print_layers']
            ]

            restricted_group_layers = {}
            for layername, layer in wms_resource['layers'].items():
                if layername in permitted_layers and layer.get('hide_sublayers'):
                    restricted_group_layers[layername] = [
                        sublayer for sublayer in layer.get('sublayers', [])
                        if sublayer['name'] in permitted_layers
                    ]

            internal_print_layers = [
                layer for layer in wms_resource['internal_print_layers']
                if layer in permitted_layers
            ]

            print_templates = [
                template for template in wms_resource['print_templates']
                if template in permitted_print_templates
            ]

            return {
                'service_name': service_name,
                # WMS URL
                'ogc_url': wms_resource['ogc_url'],
                # print URL
                'print_url': wms_resource['print_url'],
                # custom online resource
                'online_resources': wms_resource['online_resources'],
                # all permitted layers layers with permitted attributes
                'permitted_layers': permitted_layers,
                # permitted layers which are not hidden sublayers
                'public_layers': public_layers,
                # group layers with hidden sublayers (=facade layers)
                'restricted_group_layers': restricted_group_layers,
                # permitted print templates
                'print_templates': print_templates,
                # permitted internal print layers
                'internal_print_layers': internal_print_layers,
                # lookup layer names from layer titles (used to filter feature info)
                'layer_name_from_title': layer_name_from_title,
            }
        elif ows_type == 'WFS':
            wfs_resource = self.resources['wfs_services'].get(service_name)
            if not wfs_resource:
                # WFS service unknown
                return {}

            wfs_permissions = self.permissions_handler.resource_permissions(
                'wfs_services', identity, service_name
            )
            if not wfs_permissions:
                # WFS not permitted
                return {}

            # Collect layers
            permitted_layers = {}
            for permissions in wfs_permissions:
                for layer_permission in permissions['layers']:
                    layer_name = layer_permission['name']
                    if layer_name not in permitted_layers:
                        permitted_layers[layer_name] = {
                            'attributes': set(),
                            'writable': False,
                            'creatable': False,
                            'readable': False,
                            'updatable': False,
                            'deletable': False
                        }
                    permitted_layer = permitted_layers[layer_name]
                    permitted_layer['writable'] |= layer_permission.get('writable', False)
                    permitted_layer['creatable'] |= layer_permission.get('creatable', False)
                    permitted_layer['readable'] |= layer_permission.get('readable', True)
                    permitted_layer['updatable'] |= layer_permission.get('updatable', False)
                    permitted_layer['deletable'] |= layer_permission.get('deletable', False)
                    permitted_layer['attributes'].update(layer_permission.get('attributes', []))

            return {
                'service_name': service_name,
                # WFS URL
                'ogc_url': wfs_resource['ogc_url'],
                # custom online resource
                'online_resource': wfs_resource['online_resource'],
                # permitted layers and attributes
                'permitted_layers': permitted_layers
            }

        # unsupported OWS type
        return {}
