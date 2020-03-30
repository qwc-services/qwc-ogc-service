import os
import re
from urllib.parse import urljoin, urlencode, urlparse
from xml.etree import ElementTree

from flask import Response, stream_with_context
import requests

from qwc_services_core.permission import PermissionClient


class OGCService:
    """OGCService class

    Provide OGC services (WMS, WFS) with permission filters.
    Acts as a proxy to a QGIS server.
    """

    def __init__(self, logger):
        """Constructor

        :param Logger logger: Application logger
        """
        self.logger = logger
        self.permission = PermissionClient()

        # get internal QGIS server URL from ENV
        # (default: local qgis-server container)
        self.qgis_server_url = os.environ.get('QGIS_SERVER_URL',
                                              'http://localhost/wms/').rstrip('/') + '/'

    def get(self, identity, service_name, hostname, params, script_root):
        """Check and filter OGC GET request and forward to QGIS server.

        :param str identity: User identity
        :param str service_name: OGC service name
        :param str hostname: host name
        :param obj params: Request parameters
        :param str script_root: script root
        """
        return self.request(identity, 'GET', service_name, hostname, params, script_root)

    def post(self, identity, service_name, hostname, params, script_root):
        """Check and filter OGC POST request and forward to QGIS server.

        :param str identity: User identity
        :param str service_name: OGC service name
        :param str hostname: host name
        :param obj params: Request parameters
        :param str script_root: script root
        """
        return self.request(identity, 'POST', service_name, hostname, params, script_root)

    def request(self, identity, method, service_name, hostname, params, script_root):
        """Check and filter OGC request and forward to QGIS server.

        :param str identity: User identity
        :param str method: Request method 'GET' or 'POST'
        :param str service_name: OGC service name
        :param str hostname: host name
        :param obj params: Request parameters
        :param str script_root: script root
        """
        # normalize parameter keys to upper case
        params = {k.upper(): v for k, v in params.items()}

        # get permission
        permission = self.service_permission(
            identity, service_name, params.get('SERVICE')
        )

        # check request
        exception = self.check_request(params, permission)
        if exception:
            return Response(
                self.service_exception(exception['code'], exception['message']),
                content_type='text/xml; charset=utf-8',
                status=200
            )

        # adjust request parameters
        self.adjust_params(params, permission)

        # forward request and return filtered response
        return self.forward_request(method, hostname, params, permission, script_root)

    def service_permission(self, identity, service_name, ows_type):
        """Return permissions for a OGC service.

        :param str identity: User identity
        :param str service_name: OGC service name
        :param str ows_type: OWS type (WMS or WFS)
        """
        self.logger.debug("Getting permissions for identity %s", identity)
        print("[ogc_service] service_permission: Getting permissions for identity: %s" % identity)

        permission = {}
        if ows_type:
            permission = self.permission.ogc_permissions(
                service_name, ows_type, identity
            )

        return permission

    def check_request(self, params, permission):
        """Check request parameters and permissions.

        :param obj params: Request parameters
        :param obj permission: OGC service permission
        """
        exception = {}

        if permission.get('qgs_project') is None:
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
                # find map layers param for GetPrint (usually 'map0:LAYERS')
                for key, value in params.items():
                    if key.endswith(":LAYERS"):
                        layer_params = [key, None]
                        break

            if layer_params:
                permitted_layers = permission['public_layers']
                filename = params.get('FILENAME', '')
                if (service == 'WMS' and (
                    (request == 'GETMAP' and filename) or request == 'GETPRINT'
                )):
                    # When doing a raster export (GetMap with FILENAME)
                    # or printing (GetPrint), also allow background layers
                    permitted_layers += permission['background_layers']
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

        requested_layers = params.get(layer_param)
        if requested_layers:
            requested_layers = requested_layers.split(',')
            for layer in requested_layers:
                # allow only permitted layers
                if layer and not layer.startswith('EXTERNAL_WMS:') and layer not in permitted_layers:
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

    def adjust_params(self, params, permission):
        """Adjust parameters depending on request and permissions.

        :param obj params: Request parameters
        :param obj permission: OGC service permission
        """
        ogc_service = params.get('SERVICE', '')
        ogc_request = params.get('REQUEST', '').upper()

        if ogc_service == 'WMS' and ogc_request == 'GETMAP':
            requested_layers = params.get('LAYERS')
            if requested_layers:
                # replace restricted group layers with permitted sublayers
                requested_layers = requested_layers.split(',')
                restricted_group_layers = permission['restricted_group_layers']
                permitted_layers = self.expand_group_layers(
                    requested_layers, restricted_group_layers
                )

                params['LAYERS'] = ",".join(permitted_layers)

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
            # find map layers param for GetPrint (usually 'map0:LAYERS')
            map_layers_param = None
            for key, value in params.items():
                if key.endswith(":LAYERS"):
                    map_layers_param = key
                    break

            requested_layers = params.get(map_layers_param)
            if requested_layers:
                # replace restricted group layers with permitted sublayers
                requested_layers = requested_layers.split(',')
                restricted_group_layers = permission['restricted_group_layers']
                permitted_layers = self.expand_group_layers(
                    requested_layers, restricted_group_layers
                )

                params[map_layers_param] = ",".join(permitted_layers)

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
                # expand sublayers
                sublayers = restricted_group_layers.get(layer)
                permitted_layers += self.expand_group_layers(
                    sublayers, restricted_group_layers
                )
            else:
                # leaf layer or permitted group layer
                permitted_layers.append(layer)

        return permitted_layers

    def forward_request(self, method, hostname, params, permission, script_root):
        """Forward request to QGIS server and return filtered response.

        :param str method: Request method 'GET' or 'POST'
        :param str hostname: host name
        :param obj params: Request parameters
        :param obj permission: OGC service permission
        :param str script_root: script root
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
        project_name = permission['qgs_project']
        url = urljoin(self.qgis_server_url, project_name)
        if method == 'POST':
            # log forward URL and params
            self.logger.info("Forward POST request to %s" % url)
            self.logger.info("  %s" % ("\n  ").join(
                ("%s = %s" % (k, v) for k, v, in params.items()))
            )

            response = requests.post(url, headers={'host': hostname},
                                     data=params, stream=stream)
        else:
            # log forward URL and params
            self.logger.info("Forward GET request to %s?%s" %
                             (url, urlencode(params)))

            response = requests.get(url, headers={'host': hostname},
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
                self.service_exception(exception['code'], exception['message']),
                content_type='text/xml; charset=utf-8',
                status=200
            )
        # return filtered response
        elif ogc_service == 'WMS' and ogc_request in [
            'GETCAPABILITIES', 'GETPROJECTSETTINGS'
        ]:
            return self.wms_getcapabilities(response, params, permission, hostname, script_root)
        elif ogc_service == 'WMS' and ogc_request == 'GETFEATUREINFO':
            return self.wms_getfeatureinfo(response, params, permission)
        # TODO: filter DescribeFeatureInfo
        else:
            # unfiltered streamed response
            return Response(
                stream_with_context(response.iter_content(chunk_size=16*1024)),
                content_type=response.headers['content-type'],
                status=response.status_code
            )

    def wms_getcapabilities(self, response, params, permission, hostname, script_root):
        """Return WMS GetCapabilities or GetProjectSettings filtered by permissions.

        :param requests.Response response: Response object
        :param obj params: Request parameters
        :param obj permission: OGC service permission
        """
        xml = response.text

        if response.status_code == requests.codes.ok:
            # parse capabilities XML
            xlinkns = 'http://www.w3.org/1999/xlink'
            sldns = 'http://www.opengis.net/sld'
            ElementTree.register_namespace('', 'http://www.opengis.net/wms')
            ElementTree.register_namespace('qgs', 'http://www.qgis.org/wms')
            ElementTree.register_namespace('sld', sldns)
            ElementTree.register_namespace('xlink', xlinkns)
            root = ElementTree.fromstring(xml)

            # use default namespace for XML search
            # namespace dict
            ns = {'ns': 'http://www.opengis.net/wms'}
            # namespace prefix
            np = 'ns:'
            if not root.tag.startswith('{http://'):
                # do not use namespace
                ns = {}
                np = ''

            # Ensure correct OnlineResource for service
            online_resources = root.findall('.//%sOnlineResource' % np, ns)
            for online_resource in online_resources:
                url = urlparse(online_resource.get('{%s}href' % xlinkns))
                if url.path.endswith(permission['qgs_project']):
                    url = url._replace(netloc=hostname)
                    url = url._replace(path=script_root + "/" + permission['qgs_project'])
                    online_resource.set('{%s}href' % xlinkns, url.geturl())

            # If necessary, alter legend urls
            legend_service_url = os.environ.get('LEGEND_SERVICE_URL', '')
            if legend_service_url:
                legend_url = urlparse(legend_service_url)
                legend_online_resources = root.findall('.//%sLegendURL//%sOnlineResource' % (np,np), ns)
                legend_online_resources += root.findall('.//{%s}GetLegendGraphic//%sOnlineResource' % (sldns,np), ns)
                for online_resource in legend_online_resources:
                    url = urlparse(online_resource.get('{%s}href' % xlinkns))
                    if url.path.endswith(permission['qgs_project']):
                        url = url._replace(netloc=legend_url.netloc or hostname)
                        url = url._replace(path=legend_url.path + "/" + permission['qgs_project'])
                        online_resource.set('{%s}href' % xlinkns, url.geturl())

            # If necessary, alter featureinfo urls
            info_service_url = os.environ.get('INFO_SERVICE_URL', '')
            if info_service_url:
                info_url = urlparse(info_service_url)
                featureinfo_online_resources = root.findall('.//%sGetFeatureInfo//%sOnlineResource' % (np,np), ns)
                for online_resource in featureinfo_online_resources:
                    url = urlparse(online_resource.get('{%s}href' % xlinkns))
                    if url.path.endswith(permission['qgs_project'] or hostname):
                        url = url._replace(netloc=info_url.netloc)
                        url = url._replace(path=info_url.path + "/" + permission['qgs_project'])
                        online_resource.set('{%s}href' % xlinkns, url.geturl())


            root_layer = root.find('%sCapability/%sLayer' % (np, np), ns)
            if root_layer is not None:
                # remove broken info format 'application/vnd.ogc.gml/3.1.1'
                feature_info = root.find('.//%sGetFeatureInfo' % np, ns)
                if feature_info is not None:
                    for format in feature_info.findall('%sFormat' % np, ns):
                        if format.text == 'application/vnd.ogc.gml/3.1.1':
                            feature_info.remove(format)

                # filter and update layers by permission
                permitted_layers = permission['public_layers']
                queryable_layers = permission['queryable_layers']
                for group in root_layer.findall('.//%sLayer/..' % np, ns):
                    for layer in group.findall('%sLayer' % np, ns):
                        layer_name = layer.find('%sName' % np, ns).text
                        if layer_name not in permitted_layers:
                            # remove not permitted layer
                            group.remove(layer)
                        else:
                            # update queryable
                            if layer_name in queryable_layers:
                                layer.set('queryable', '1')
                            else:
                                layer.set('queryable', '0')

                        # get permitted attributes for layer
                        permitted_attributes = permission['layers'].get(
                            layer_name, {}
                        )

                        # remove layer displayField if attribute not permitted
                        # (for QGIS GetProjectSettings)
                        display_field = layer.get('displayField')
                        if (display_field and
                                display_field not in permitted_attributes):
                            layer.attrib.pop('displayField')

                        # filter layer attributes by permission
                        # (for QGIS GetProjectSettings)
                        attributes = layer.find('%sAttributes' % np, ns)
                        if attributes is not None:
                            for attr in attributes.findall(
                                '%sAttribute' % np, ns
                            ):
                                if attr.get('name') not in permitted_attributes:
                                    # remove not permitted attribute
                                    attributes.remove(attr)

                # update queryable for root layer
                if queryable_layers:
                    root_layer.set('queryable', '1')
                else:
                    root_layer.set('queryable', '0')

                # filter LayerDrawingOrder by permission
                # (for QGIS GetProjectSettings)
                layer_drawing_order = root.find(
                    './/%sLayerDrawingOrder' % np, ns
                )
                if layer_drawing_order is not None:
                    layers = layer_drawing_order.text.split(',')
                    # remove not permitted layers
                    layers = [
                        l for l in layers if l in permitted_layers
                    ]
                    layer_drawing_order.text = ','.join(layers)

                # filter ComposerTemplates by permission
                # (for QGIS GetProjectSettings)
                templates = root.find(
                    '%sCapability/%sComposerTemplates' % (np, np), ns
                )
                if templates is not None:
                    permitted_templates = permission.get('print_templates', [])
                    for template in templates.findall(
                        '%sComposerTemplate' % np, ns
                    ):
                        template_name = template.get('name')
                        if template_name not in permitted_templates:
                            # remove not permitted print template
                            templates.remove(template)

                    if not templates.find('%sComposerTemplate' % np, ns):
                        # remove ComposerTemplates if empty
                        root.find('%sCapability' % np, ns).remove(templates)

                # write XML to string
                xml = ElementTree.tostring(
                    root, encoding='utf-8', method='xml'
                )

        return Response(
            xml,
            content_type=response.headers['content-type'],
            status=response.status_code
        )

    def wms_getfeatureinfo(self, response, params, permission):
        """Return WMS GetFeatureInfo filtered by permissions.

        :param requests.Response response: Response object
        :param obj params: Request parameters
        :param obj permission: OGC service permission
        """
        feature_info = response.text

        if response.status_code == requests.codes.ok:
            info_format = params.get('INFO_FORMAT', 'text/plain')
            if info_format == 'text/plain':
                feature_info = self.wms_getfeatureinfo_plain(
                    feature_info, permission
                )
            elif info_format == 'text/html':
                feature_info = self.wms_getfeatureinfo_html(
                    feature_info, permission
                )
            elif info_format == 'text/xml':
                feature_info = self.wms_getfeatureinfo_xml(
                    feature_info, permission
                )
            elif info_format == 'application/vnd.ogc.gml':
                feature_info = self.wms_getfeatureinfo_gml(
                    feature_info, permission
                )

            # NOTE: application/vnd.ogc.gml/3.1.1 is broken in QGIS server

        return Response(
            feature_info,
            content_type=response.headers['content-type'],
            status=response.status_code
        )

    def wms_getfeatureinfo_plain(self, feature_info, permission):
        """Parse feature info text and filter feature attributes by permission.

        :param str feature_info: Raw feature info response from QGIS server
        :param obj permission: OGC service permission
        """
        """
        GetFeatureInfo results

        Layer 'Grundstuecke'
        Feature 1
        t_id = '1234'
        nbident = 'SO0123456789'
        nummer = '1234'
        ...
        """
        if feature_info.startswith('GetFeatureInfo'):
            lines = []

            layer_pattern = re.compile("^Layer '(.+)'$")
            attr_pattern = re.compile("^(.+) = .+$")
            permitted_attributes = {}

            # filter feature attributes by permission
            for line in feature_info.splitlines():
                m = attr_pattern.match(line)
                if m is not None:
                    # attribute line
                    # check if layer attribute is permitted
                    attr = m.group(1)
                    if attr not in permitted_attributes:
                        # skip not permitted attribute
                        continue
                else:
                    m = layer_pattern.match(line)
                    if m is not None:
                        # layer line
                        # get permitted attributes for layer
                        current_layer = m.group(1)
                        permitted_attributes = self.permitted_info_attributes(
                            current_layer, permission
                        )

                # keep line
                lines.append(line)

            # join filtered lines
            feature_info = '\n'.join(lines)

        return feature_info

    def wms_getfeatureinfo_html(self, feature_info, permission):
        """Parse feature info HTML and filter feature attributes by permission.

        :param str feature_info: Raw feature info response from QGIS server
        :param obj permission: OGC service permission
        """
        # NOTE: info content is not valid XML, parse as text
        if feature_info.startswith('<HEAD>'):
            lines = []

            layer_pattern = re.compile(
                "^<TR>.+>Layer<\/TH><TD>(.+)<\/TD><\/TR>$"
            )
            table_pattern = re.compile("^.*<TABLE")
            attr_pattern = re.compile("^<TR><TH>(.+)<\/TH><TD>.+</TD><\/TR>$")
            next_tr_is_feature = False
            permitted_attributes = {}

            for line in feature_info.splitlines():
                m = attr_pattern.match(line)
                if m is not None:
                    # attribute line
                    # check if layer attribute is permitted
                    attr = m.group(1)
                    if next_tr_is_feature:
                        # keep 'Feature', filter subsequent attributes
                        next_tr_is_feature = False
                    elif attr not in permitted_attributes:
                        # skip not permitted attribute
                        continue
                elif table_pattern.match(line):
                    # mark next tr as 'Feature'
                    next_tr_is_feature = True
                else:
                    m = layer_pattern.match(line)
                    if m is not None:
                        # layer line
                        # get permitted attributes for layer
                        current_layer = m.group(1)
                        permitted_attributes = self.permitted_info_attributes(
                            current_layer, permission
                        )

                # keep line
                lines.append(line)

            # join filtered lines
            feature_info = '\n'.join(lines)

        return feature_info

    def wms_getfeatureinfo_xml(self, feature_info, permission):
        """Parse feature info XML and filter feature attributes by permission.

        :param str feature_info: Raw feature info response from QGIS server
        :param obj permission: OGC service permission
        """
        ElementTree.register_namespace('', 'http://www.opengis.net/ogc')
        root = ElementTree.fromstring(feature_info)

        for layer in root.findall('./Layer'):
            # get permitted attributes for layer
            permitted_attributes = self.permitted_info_attributes(
                layer.get('name'), permission
            )

            for feature in layer.findall('Feature'):
                for attr in feature.findall('Attribute'):
                    if attr.get('name') not in permitted_attributes:
                        # remove not permitted attribute
                        feature.remove(attr)

        # write XML to string
        return ElementTree.tostring(root, encoding='utf-8', method='xml')

    def wms_getfeatureinfo_gml(self, feature_info, permission):
        """Parse feature info GML and filter feature attributes by permission.

        :param str feature_info: Raw feature info response from QGIS server
        :param obj permission: OGC service permission
        """
        ElementTree.register_namespace('gml', 'http://www.opengis.net/gml')
        ElementTree.register_namespace('qgs', 'http://qgis.org/gml')
        ElementTree.register_namespace('wfs', 'http://www.opengis.net/wfs')
        root = ElementTree.fromstring(feature_info)

        # namespace dict
        ns = {
            'gml': 'http://www.opengis.net/gml',
            'qgs': 'http://qgis.org/gml'
        }

        qgs_attr_pattern = re.compile("^{%s}(.+)" % ns['qgs'])

        for feature in root.findall('./gml:featureMember', ns):
            for layer in feature:
                # get layer name from fid, as spaces are removed in tag name
                layer_name = '.'.join(layer.get('fid', '').split('.')[:-1])

                # get permitted attributes for layer
                permitted_attributes = self.permitted_info_attributes(
                    layer_name, permission
                )

                for attr in layer.findall('*'):
                    m = qgs_attr_pattern.match(attr.tag)
                    if m is not None:
                        # attribute tag
                        attr_name = m.group(1)
                        if attr_name not in permitted_attributes:
                            # remove not permitted attribute
                            layer.remove(attr)

        # write XML to string
        return ElementTree.tostring(
            root, encoding='utf-8', method='xml', short_empty_elements=False
        )

    def permitted_info_attributes(self, info_layer_name, permission):
        """Get permitted attributes for a feature info result layer.

        :param str info_layer_name: Layer name from feature info result
        :param obj permission: OGC service permission
        """
        # get WMS layer name for info result layer
        wms_layer_name = permission.get('feature_info_aliases', {}) \
            .get(info_layer_name, info_layer_name)

        # return permitted attributes for layer
        return permission['layers'].get(wms_layer_name, {})
