import html
import os
import re
import requests
from flask import Response, url_for, request
from urllib.parse import urlparse, parse_qsl, quote, urlencode
from xml.etree import ElementTree



class WmsHandler:

    def __init__(self, logger, qgis_server_url, permission_handler, identity, legend_default_font_size=None):
        """
        :param obj logger: Application logger
        :param obj qgis_server_url: QGIS Server URL
        :param obj permission_handler: Permission handler
        :param obj identity: User identity
        :param int legend_default_font_size: Default legend graphic font size
        """
        self.logger = logger
        self.qgis_server_url = qgis_server_url
        self.permission_handler = permission_handler
        self.identity = identity
        self.legend_default_font_size = legend_default_font_size

    def process_request(self, request, params, permissions, data):
        """Check request parameters against permissions and adjust params.

        :param str request: The OWS request
        :param obj params: Request parameters
        :param obj permissions: OGC service permissions
        :param obj data: POST data, if any
        """

        if not request in [
            'GETCAPABILITIES', 'GETMAP', 'GETFEATUREINFO', 'GETLEGENDGRAPHIC', 'GETSTYLE', 'GETSTYLES',
            'DESCRIBELAYER', 'GETPRINT', 'GETPROJECTSETTINGS', 'GETSCHEMAEXTENSION'
        ]:
            return (
                "OperationNotSupported",
                "Request %s is not supported" % request
            )

        # check layers param
        layer_mandatory_requests = [
            'GETMAP', 'GETFEATUREINFO', 'GETLEGENDGRAPHIC', 'DESCRIBELAYER', 'GETSTYLE', 'GETSTYLES'
        ]

        layers_param = 'LAYERS'
        if request == 'GETPRINT':
            mapname = self.__get_map_param_prefix(params)
            if mapname and (mapname + ":LAYERS") in params:
                layers_param = mapname + ":LAYERS"
        elif request == 'GETLEGENDGRAPHIC' and not 'LAYERS' in params and 'LAYER' in params:
            layers_param = 'LAYER'

        public_layers = list(permissions['public_layers'])
        if (request == 'GETMAP' and params.get('FILENAME')) or request == 'GETPRINT':
            # When doing a raster export (GetMap) or printing (GetPrint),
            # also allow background or external layers
            public_layers += permissions['internal_print_layers']

        if layers := params.get(layers_param):
            for layer in layers.split(','):
                # allow only permitted layers
                if (
                    layer
                    and not layer.startswith('EXTERNAL_WMS:')
                    and layer not in public_layers
                ):
                    return (
                        "LayerNotDefined",
                        'Layer "%s" does not exist or is not permitted' % layer
                    )
        elif request in layer_mandatory_requests:
            # mandatory layers param is missing or blank
            return (
                "MissingParameterValue",
                '%s is mandatory for %s operation' % (layers_param, request)
            )

        if request == 'GETFEATUREINFO':
            if params.get('LAYERS') != params.get('QUERY_LAYERS'):
                return (
                    "InvalidParameterValue",
                    'LAYERS must be identical to QUERY_LAYERS for GETFEATUREINFO operation'
                )
            # check info format
            info_format = params.get('INFO_FORMAT', 'text/plain')
            if not info_format in ['text/plain', 'text/html', 'text/xml']:
                return (
                    "InvalidFormat",
                    "Feature info format '%s' is not supported. "
                    "Possibilities are 'text/plain', 'text/html' or 'text/xml'."
                    % info_format
                )

        elif request == 'GETPRINT':
            # check print templates
            template = params.get('TEMPLATE')
            if template not in permissions['print_templates']:
                return (
                    "Error",
                    "Composer template '%s' not found or not permitted" % template
                )

        # Adjust params

        if request == 'GETMAP':
            expanded = self.__expand_group_layers(params, 'LAYERS', permissions)
            params['LAYERS'] = ",".join([entry['layer'] for entry in expanded])
            params['OPACITIES'] = ",".join([str(entry['opacity']) for entry in expanded])
            params['STYLES'] = ",".join([entry['style'] for entry in expanded])

        elif request == 'GETFEATUREINFO':
            expanded = self.__expand_group_layers(params, 'LAYERS', permissions)

            # filter by queryable layers
            permitted_layers = permissions['permitted_layers']
            expanded = [
                entry for entry in expanded if permitted_layers.get(entry['layer'], {}).get('queryable')
            ]
            params['LAYERS'] = ",".join([entry['layer'] for entry in expanded])
            params['STYLES'] = ",".join([entry['style'] for entry in expanded])
            params['QUERY_LAYERS'] = params['LAYERS']

            # Always request as text/xml, then rebuild text/html or text/plain in response
            self.requested_info_format = params['INFO_FORMAT']
            params['INFO_FORMAT'] = 'text/xml'

        elif request == "GETLEGENDGRAPHIC":
            expanded = self.__expand_group_layers(params, 'LAYERS', permissions)
            params['LAYERS'] = ",".join([entry['layer'] for entry in expanded])
            params['STYLES'] = ",".join([entry['style'] for entry in expanded])

            # Truncate portion after mime-type which qgis server does not support for legend format
            params['FORMAT'] = params.get('FORMAT', '').split(';')[0]
            if self.legend_default_font_size:
                params['LAYERFONTSIZE'] = params.get('LAYERFONTSIZE', self.legend_default_font_size)
                params['ITEMFONTSIZE'] = params.get('ITEMFONTSIZE', self.legend_default_font_size)

        elif request == "DESCRIBELAYER":
            expanded = self.__expand_group_layers(params, 'LAYERS', permissions)
            params['LAYERS'] = ",".join([entry['layer'] for entry in expanded])

        elif request == 'GETPRINT':
            layers_param = self.__get_map_param_prefix(params) + ":LAYERS"
            expanded = self.__expand_group_layers(params, layers_param, permissions)
            params[layers_param] = ",".join([entry['layer'] for entry in expanded])
            params['OPACITIES'] = ",".join([str(entry['opacity']) for entry in expanded])
            params['STYLES'] = ",".join([entry['style'] for entry in expanded])
            # NOTE: also set LAYERS, so that QGIS Server applies OPACITIES correctly
            params['LAYERS'] = params[layers_param]

        return None

    def response_streamable(self, request):
        """ Returns whether the response for the specified request is streamable. """
        return request in ['GETCAPABILITIES', 'GETPROJECTSETTINGS', 'GETFEATUREINFO']

    def filter_response(self, request, response, params, permissions):
        """Filter WMS response by permissions.
        :param request str: The OWS request
        :param requests.Response response: Response object
        :param obj params: Request parameters
        :param obj permissions: OGC service permission
        """
        if request in ['GETCAPABILITIES', 'GETPROJECTSETTINGS']:
            return self.__filter_getcapabilities(response, permissions, params)
        elif request == 'GETFEATUREINFO':
            return self.__filter_getfeatureinfo(response, permissions)
        else:
            return None

    def __get_map_param_prefix(self, params):
        # Deduce map name by looking for param which ends with :EXTENT
        # (Can't look for param ending with :LAYERS as there might be i.e. A:LAYERS for the external layer definition A)
        mapname = ""
        for key, value in params.items():
            if key.endswith(":EXTENT"):
                return key[0:-7]
        return ""

    def __expand_group_layers(self, params, layers_param, permissions):
        """ Replace restricted group layers ("facade layers") with permitted sublayers
            and also return expanded STYLES / OPACITIES
        """

        # replace restricted group layers ("facade layers") with permitted sublayers
        requested_layers = params.get(layers_param, '').split(',')
        requested_opacities = params.get('OPACITIES', '').split(',')
        requested_styles = params.get('STYLES', '').split(',')

        expanded = []
        for i, layer in enumerate(requested_layers):
            try:
                opacity = max(0, min(int(requested_opacities[i]), 255))
            except:
                opacity = 255
            try:
                style = requested_styles[i]
            except:
                style = ''

            if layer.startswith("EXTERNAL_WMS:"):
                self.__rewrite_external_wms_url(layer, params)
                expanded.append({
                    'layer': layer, 'opacity': opacity, 'style': style
                })
            elif sublayers := permissions['restricted_group_layers'].get(layer):
                expanded += self.__expand_restricted_group(sublayers, opacity, permissions)
            else:
                expanded.append({
                    'layer': layer, 'opacity': opacity, 'style': style
                })
        return expanded

    def __expand_restricted_group(self, layers, opacity, permissions):
        """ Recursively expand restricted group layers ("facades")

        :param list(str) layers: The group layers to expand
        :param int opacities_param: Parent group opacity
        :param obj permissions: Service permissions
        """
        result = []
        for layer in layers:
            layer_opacity = round(permissions['permitted_layers'][layer]['opacity'] / 100 * opacity)
            if sublayers := permissions['restricted_group_layers'].get(layer):
                result += self.expand_restricted_group(sublayers, layer_opacity, permissions)
            else:
                result.append({
                    'layer': layer, 'opacity': layer_opacity, 'style': ''
                })
        return result

    def __rewrite_external_wms_url(self, layer, params):
        # Rewrite URLs of EXTERNAL_WMS which point to the ogc service:
        #     <...>?REQUEST=GetPrint&map0:LAYERS=EXTERNAL_WMS:A&A:URL=http://<ogc_service_url>/...
        # and point the URLs directly to the qgis server
        ogc_service_url = url_for("ogc", service_name="service_name", _external=True).removesuffix("service_name")
        layer_ident = layer[13:]
        layer_url = params.get(layer_ident + ":URL")
        if layer_url and layer_url.startswith(ogc_service_url):
            params[layer_ident + ":URL"] = self.qgis_server_url + layer_url.removeprefix(ogc_service_url)
        else:
            # Manually build external URL if request routed through print-service to the internal qwc-ogc-service hostname
            ogc_service_url = request.environ.get('HTTP_ORIGIN', '') + request.environ.get('SCRIPT_NAME', '') + os.environ.get('SERVICE_MOUNTPOINT', '') + "/"
            if layer_url and layer_url.startswith(ogc_service_url):
                params[layer_ident + ":URL"] = self.qgis_server_url + layer_url.removeprefix(ogc_service_url)
            else:
                # No replacement done
                return

        # Filter unpermitted layers
        service_name = layer_url.removeprefix(ogc_service_url)
        wms_permissions = self.permission_handler.resource_permissions(
            'wms_services', self.identity, service_name
        )
        permitted_layers = set()
        for permissions in wms_permissions:
            for layer_permission in permissions['layers']:
                permitted_layers.add(layer_permission['name'])

        ext_layers = params.get(layer_ident + ":LAYERS", "").split(",")
        params[layer_ident + ":LAYERS"] = ",".join(list(filter(
            lambda name: name in permitted_layers, ext_layers
        )))

    def __filter_getcapabilities(self, response, permissions, params):
        """Return WMS GetCapabilities or GetProjectSettings filtered by
        permissions.

        :param requests.Response response: Response object
        :param obj permissions: OGC service permissions
        :param obj params: Request parameters
        """
        xml = response.text
        # Strip control characters
        xml = re.sub("[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", xml)

        if response.status_code == requests.codes.ok:
            # parse capabilities XML
            sldns = 'http://www.opengis.net/sld'
            xlinkns = 'http://www.w3.org/1999/xlink'
            qgsns = 'http://www.qgis.org/wms'
            xsins = 'http://www.w3.org/2001/XMLSchema-instance'
            ElementTree.register_namespace('', 'http://www.opengis.net/wms')
            ElementTree.register_namespace('qgs', qgsns)
            ElementTree.register_namespace('sld', sldns)
            ElementTree.register_namespace('xlink', xlinkns)
            root = ElementTree.fromstring(xml)

            # use default namespace for XML search
            # namespace dict
            ns = {
                'ns': 'http://www.opengis.net/wms',
                'sld': sldns,
                'qgs': qgsns
            }
            # namespace prefix
            np = 'ns:'
            if not root.tag.startswith('{http://'):
                # do not use namespace
                ns = {}
                np = ''

            service_url = permissions['online_resources'].get('service')
            if service_url:
                # override OnlineResources
                online_resources = []
                online_resources += root.findall('.//%sService/%sOnlineResource' % (np, np), ns)
                online_resources += root.findall('.//%sGetCapabilities//%sOnlineResource' % (np, np), ns)
                online_resources += root.findall('.//%sGetMap//%sOnlineResource' % (np, np), ns)
                online_resources += root.findall('.//%sGetFeatureInfo//%sOnlineResource' % (np, np), ns)
                online_resources += root.findall('.//{%s}GetLegendGraphic//%sOnlineResource' % (sldns, np), ns)
                online_resources += root.findall('.//{%s}DescribeLayer//%sOnlineResource' % (sldns, np), ns)
                online_resources += root.findall('.//{%s}GetStyles//%sOnlineResource' % (qgsns, np), ns)
                online_resources += root.findall('.//%sGetPrint//%sOnlineResource' % (np, np), ns)
                online_resources += root.findall('.//%sLegendURL//%sOnlineResource' % (np, np), ns)

                self.__update_online_resources(online_resources, service_url, xlinkns, params)

            info_url = permissions['online_resources'].get('feature_info')
            if info_url:
                # override GetFeatureInfo OnlineResources
                online_resources = root.findall(
                    './/%sGetFeatureInfo//%sOnlineResource' % (np, np), ns
                )
                self.__update_online_resources(online_resources, info_url, xlinkns, params)

            legend_url = permissions['online_resources'].get('legend')
            if legend_url:
                # override GetLegend OnlineResources
                online_resources = root.findall(
                    './/%sLegendURL//%sOnlineResource' % (np, np), ns
                )
                online_resources += root.findall(
                    './/{%s}GetLegendGraphic//%sOnlineResource' % (sldns, np),
                    ns
                )
                self.__update_online_resources(online_resources, legend_url, xlinkns, params)

                # HACK: Inject LegendURL for group layers (which are missing LegendURL)
                # Pending proper upstream QGIS server fix
                # Take first online_resource and tweak the URL
                refUrl = urlparse(online_resources[0].get('{%s}href' % xlinkns))
                refQuery = dict(parse_qsl(refUrl.query))
                refFmt = refQuery.get('FORMAT','image/png')

                layers = root.findall('.//%sLayer' % np, ns)
                for layerEl in layers:
                    styleEl = layerEl.find('%sStyle' % np, ns)
                    if styleEl is None:

                        styleEl = ElementTree.Element('Style')
                        layerEl.append(styleEl)

                        nameEl = ElementTree.Element('Name')
                        nameEl.text = 'default'
                        styleEl.append(nameEl)

                        titleEl = ElementTree.Element('Title')
                        titleEl.text = 'default'
                        styleEl.append(titleEl)

                    legendUrlEl = styleEl.find('%sLegendURL' % np, ns)
                    nameEl = layerEl.find('%sName' % np, ns)
                    if legendUrlEl is None and nameEl is not None:
                        refQuery['LAYER'] = nameEl.text
                        refUrl = refUrl._replace(query = urlencode(refQuery, doseq=True))

                        legendUrlEl = ElementTree.Element('LegendURL')
                        styleEl.append(legendUrlEl)

                        formatEl = ElementTree.Element('Format')
                        formatEl.text = refFmt
                        legendUrlEl.append(formatEl)

                        onlineResourceEl = ElementTree.Element('OnlineResource', {
                            '{%s}href' % xlinkns: refUrl.geturl(),
                            '{%s}type' % xlinkns: 'simple'
                        })
                        legendUrlEl.append(onlineResourceEl)


            root_layer = root.find('%sCapability/%sLayer' % (np, np), ns)
            if root_layer is not None:
                # remove broken info format 'application/vnd.ogc.gml/3.1.1'
                feature_info = root.find('.//%sGetFeatureInfo' % np, ns)
                if feature_info is not None:
                    for format in feature_info.findall('%sFormat' % np, ns):
                        if format.text == 'application/vnd.ogc.gml/3.1.1':
                            feature_info.remove(format)

                # filter and update layers by permissions
                permitted_layers = permissions['public_layers']
                has_queryable_layers = False
                for group in root_layer.findall('.//%sLayer/..' % np, ns):
                    for layer in group.findall('%sLayer' % np, ns):
                        layer_name = layer.find('%sName' % np, ns).text
                        if layer_name not in permitted_layers:
                            # remove not permitted layer
                            group.remove(layer)
                        else:
                            # update queryable
                            if permissions['permitted_layers'][layer_name].get('queryable'):
                                layer.set('queryable', '1')
                                has_queryable_layers = True
                            else:
                                layer.set('queryable', '0')

                        # get permitted attributes for layer
                        permitted_attributes = permissions['permitted_layers'].get(
                            layer_name, {'attributes': {}}
                        )['attributes']

                        # remove layer displayField if attribute not permitted
                        # (for QGIS GetProjectSettings)
                        display_field = layer.get('displayField')
                        if (display_field and
                                display_field not in permitted_attributes.values()):
                            layer.attrib.pop('displayField')

                        # filter layer attributes by permissions
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
                if has_queryable_layers:
                    root_layer.set('queryable', '1')
                else:
                    root_layer.set('queryable', '0')

                # filter LayerDrawingOrder by permissions
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

                # filter ComposerTemplates by permissions
                # (for QGIS GetProjectSettings)
                templates = root.find(
                    '%sCapability/%sComposerTemplates' % (np, np), ns
                )
                if templates is not None:
                    for template in templates.findall(
                        '%sComposerTemplate' % np, ns
                    ):
                        template_name = template.get('name')
                        if template_name not in permissions['print_templates']:
                            # remove not permitted print template
                            templates.remove(template)

                    if templates.find('%sComposerTemplate' % np, ns) is None:
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

    def __update_online_resources(self, elements, new_url, xlinkns, params):
        """Update OnlineResource URLs.

        :param list(Element) elements: List of OnlineResource elements
        :param str new_url: New OnlineResource URL
        :param str xlinkns: XML namespace for OnlineResource href
        :param obj params: Request parameters
        """

        qgis_server_url_parts = urlparse(self.qgis_server_url)
        qgis_server_path = qgis_server_url_parts.path

        for online_resource in elements:
            # update OnlineResource URL
            old_url = online_resource.get('{%s}href' % xlinkns)
            url_parts = urlparse(old_url)
            if not url_parts.scheme.startswith('http'):
                continue

            if new_url.startswith("/"):
                new_url = request.host_url.rstrip("/") + new_url

            # Drop MAP query parameter, it is never useful for services served through qwc-qgis-server
            query = parse_qsl(url_parts.query)
            query = list(filter(lambda kv: kv[0].lower() != "map", query))
            query = list(filter(lambda kv: kv[0].lower() != "requireauth", query))
            if params.get('REQUIREAUTH'):
                query.append(('REQUIREAUTH', params['REQUIREAUTH']))
            # querystring = urlencode(query, doseq=True)
            querystring = "&".join(map(lambda kv: f"{kv[0]}={quote(kv[1], safe=' /')}", query))
            online_resource.set('{%s}href' % xlinkns, new_url.removesuffix("?") + "?" + querystring)


    def __filter_getfeatureinfo(self, response, permissions):
        """Return WMS GetFeatureInfo filtered by permissions.

        :param requests.Response response: Response object
        :param obj permissions: OGC service permissions
        """
        feature_info = response.text
        # Strip control characters
        feature_info = re.sub("[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", feature_info)

        info_format = self.requested_info_format

        # Info always requested as text/xml from server
        ElementTree.register_namespace('', 'http://www.opengis.net/ogc')
        root = ElementTree.fromstring(feature_info)

        for layer in root.findall('./Layer'):
            # get permitted attributes for layer
            permitted_attributes = self.__permitted_info_attributes(
                layer.get('name'), permissions
            )
            if permitted_attributes is None:
                root.remove(layer)
                continue
            layer.set('title', permissions['permitted_layers'][layer.get('name')]['title'])

            for feature in layer.findall('Feature'):
                for attr in feature.findall('Attribute'):
                    if attr.get('name') not in permitted_attributes:
                        # remove not permitted attribute
                        feature.remove(attr)

        if info_format == "text/xml":
            return Response(
                ElementTree.tostring(root, encoding='utf-8', method='xml'),
                content_type="text/xml"
            )

        elif info_format == "text/plain":
            info_text = "GetFeatureInfo results\n\n"
            for layer in root.findall('./Layer'):
                info_text += "Layer '%s'\n" % layer.get('title')

                for feature in layer.findall('Feature'):
                    info_text += "Feature %s\n" % feature.get('id')
                    for attr in feature.findall('Attribute'):
                        info_text += "%s = '%s'\n" % (attr.get('name'), attr.get('value'))
                info_text += "\n"
            return Response(info_text, content_type="text/plain")

        elif info_format == "text/html":

            info_html = '<!DOCTYPE html>\n'
            info_html += '<head>\n'
            info_html += '<title>Information</title>\n'
            info_html += '<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />\n'
            info_html += '<style>\n'
            info_html += '  body { font-family: "Open Sans", "Calluna Sans", "Gill Sans MT", "Calibri", "Trebuchet MS", sans-serif; }\n'
            info_html += '  table, th, td { width: 100%; border: 1px solid black; border-collapse: collapse; text-align: left; padding: 2px; }\n'
            info_html += '  th { width: 25%; font-weight: bold; }\n'
            info_html += '  .layer-title { font-weight: bold; padding: 2px; }\n'
            info_html += '</style>\n'
            info_html += '</head>\n'
            info_html += '<body>\n'
            for layer in root.findall('./Layer'):
                features = layer.findall('Feature')
                if features:
                    info_html += '<div class="layer-title">%s</div>\n' % html.escape(layer.get('title'))
                for feature in features:
                    info_html += '<table>\n'
                    for attr in feature.findall('Attribute'):
                        info_html += '<tr><th>%s</th><td>%s</td></tr>\n' % (html.escape(attr.get('name')), html.escape(attr.get('value')))
                    info_html += '</table>\n'
            info_html += '</body>\n'
            return Response(info_html, content_type="text/html")

    def __permitted_info_attributes(self, info_layer_name, permissions):
        """Get permitted attributes for a feature info result layer.

        :param str info_layer_name: Layer name from feature info result
        :param obj permissions: OGC service permissions
        """
        # get WMS layer name for info result layer

        wms_layer_name = permissions.get('layer_name_from_title', {}) \
            .get(info_layer_name, info_layer_name)

        permitted_layer = permissions['permitted_layers'].get(wms_layer_name)

        if permitted_layer is None:
            # layer is not permitted
            return None

        # return permitted attributes for layer
        attribute_aliases = permitted_layer.get('attributes', {})

        # NOTE: reverse lookup for attribute names from alias, as QGIS Server returns aliases
        alias_attributes = dict([x[::-1] for x in attribute_aliases.items()])
        return alias_attributes
