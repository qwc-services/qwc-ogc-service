import html
import os
import re
from typing import override
from urllib.parse import parse_qsl, quote, urlencode, urlparse
from xml.etree import ElementTree

import psycopg
import requests
from flask import Response, request, url_for
from qwc_services_core.auth import get_username

from ogc.ogc_service_handler import OgcServiceHandler, ServiceException


class WmsHandler(OgcServiceHandler):

    def __init__(self, logger, config, qgis_server_url, permission_handler, identity):
        """
        :param obj logger: Application logger
        :param obj config: Service config
        :param obj qgis_server_url: internal QGIS Server URL
        :param obj permission_handler: Permission handler
        :param obj identity: User identity
        """
        super().__init__(logger, config, qgis_server_url, permission_handler, identity)
        self.qgis_server_url = qgis_server_url
        self.permission_handler = permission_handler
        self.identity = identity
        self.legend_default_font_size = config.get("legend_default_font_size")

        # Marker template and param definitions
        self.marker_template = config.get('marker_template', None)
        self.marker_params = {
            "X": {"type": "number"},
            "Y": {"type": "number"}
        }
        for key, entry in config.get('marker_params', {}).items():
            env_key = "MARKER_" + key.upper()
            value = os.getenv("MARKER_" + key.upper(), entry.get("default", ""))
            self.marker_params[key.upper()] = {
                "value": value,
                "type": entry.get("type", "string")
            }
            if env_key in os.environ:
                logger.info(f"Setting marker param value {key.upper()}={value} from environment")
            else:
                logger.info(f"Setting default marker param value {key.upper()}={value}")

        # GetPrint configuration
        self.print_qgs_postfix = config.get('print_qgs_postfix', '')
        self.print_label_queries = config.get('print_label_queries', [])
        self.print_label_values = config.get('print_label_values', [])

    @staticmethod
    @override
    def accepts(req):
        """Whether the handler handle the specified request.

        :param OgcRequest req: The OGC request
        """
        return req.service == 'WMS'

    @override
    def adjust_request_params(self, req, permissions):
        """Check request parameters against permissions and adjust params, returning the adjusted OgcRequest

        :param OgcRequest req: The OGC request
        :param obj permissions: OGC service permissions
        """

        if req.request not in [
            'GETCAPABILITIES', 'GETMAP', 'GETFEATUREINFO', 'GETLEGENDGRAPHIC', 'GETSTYLE', 'GETSTYLES',
            'DESCRIBELAYER', 'GETPRINT', 'GETPROJECTSETTINGS', 'GETSCHEMAEXTENSION'
        ]:
            raise ServiceException("OperationNotSupported", f"Request {req.request} is not supported")

        # check layers param
        layer_mandatory_requests = [
            'GETMAP', 'GETFEATUREINFO', 'GETLEGENDGRAPHIC', 'DESCRIBELAYER', 'GETSTYLE', 'GETSTYLES'
        ]

        layers_param = 'LAYERS'
        if req.request == 'GETPRINT':
            mapname = self.__get_map_param_prefix(req.params)
            if mapname and (mapname + ":LAYERS") in req.params:
                layers_param = mapname + ":LAYERS"
        elif req.request == 'GETLEGENDGRAPHIC':
            if 'LAYER' in req.params and 'LAYERS' not in req.params:
                req.params['LAYERS'] = req.params['LAYER']
            req.params.pop('LAYER', None)

        public_layers = list(permissions['public_layers'])
        if (req.request == 'GETMAP' and req.params.get('FILENAME')) or req.request == 'GETPRINT':
            # When doing a raster export (GetMap) or printing (GetPrint),
            # also allow background or external layers
            public_layers += permissions['internal_print_layers']

        if layers := req.params.get(layers_param):
            for layer in layers.split(','):
                # allow only permitted layers
                if (
                    layer
                    and not layer.startswith('EXTERNAL_WMS:')
                    and layer not in public_layers
                ):
                    raise ServiceException("LayerNotDefined", f'Layer "{layer}" does not exist or is not permitted')

        elif req.request in layer_mandatory_requests:
            # mandatory layers param is missing or blank
            raise ServiceException("MissingParameterValue", f'{layers_param} is mandatory for {req.request} operation')

        if req.request == 'GETFEATUREINFO':
            if req.params.get('LAYERS') != req.params.get('QUERY_LAYERS'):
                raise ServiceException(
                    "InvalidParameterValue", 'LAYERS must be identical to QUERY_LAYERS for GETFEATUREINFO operation'
                )

            # check info format
            info_format = req.params.get('INFO_FORMAT', 'text/plain')
            if info_format not in ['text/plain', 'text/html', 'text/xml']:
                raise ServiceException(
                    "InvalidFormat",
                    f"Feature info format '{info_format}' is unsupported. Supported are 'text/plain', 'text/html', 'text/xml'."
                )

        elif req.request == 'GETPRINT':
            # check print templates
            template = req.params.get('TEMPLATE')
            if template not in permissions['print_templates']:
                raise ServiceException("Error", f"Composer template '{template}' not found or not permitted")

        # Adjust params

        if req.request == 'GETMAP':
            expanded = self.__expand_group_layers(req.params, 'LAYERS', permissions)
            req.params['LAYERS'] = ",".join([entry['layer'] for entry in expanded])
            req.params['OPACITIES'] = ",".join([str(entry['opacity']) for entry in expanded])
            req.params['STYLES'] = ",".join([entry['style'] for entry in expanded])

        elif req.request == 'GETFEATUREINFO':
            expanded = self.__expand_group_layers(req.params, 'LAYERS', permissions)

            # filter by queryable layers
            permitted_layers = permissions['permitted_layers']
            expanded = [
                entry for entry in expanded if permitted_layers.get(entry['layer'], {}).get('queryable')
            ]
            req.params['LAYERS'] = ",".join([entry['layer'] for entry in expanded])
            req.params['STYLES'] = ",".join([entry['style'] for entry in expanded])
            req.params['QUERY_LAYERS'] = req.params['LAYERS']

            # Always request as text/xml, then rebuild text/html or text/plain in response
            self.requested_info_format = req.params['INFO_FORMAT']
            req.params['INFO_FORMAT'] = 'text/xml'

        elif req.request == "GETLEGENDGRAPHIC":
            expanded = self.__expand_group_layers(req.params, 'LAYERS', permissions)
            req.params['LAYERS'] = ",".join([entry['layer'] for entry in expanded])
            req.params['STYLES'] = ",".join([entry['style'] for entry in expanded])

            # Truncate portion after mime-type which qgis server does not support for legend format
            req.params['FORMAT'] = req.params.get('FORMAT', '').split(';')[0]
            if self.legend_default_font_size:
                req.params['LAYERFONTSIZE'] = req.params.get('LAYERFONTSIZE', self.legend_default_font_size)
                req.params['ITEMFONTSIZE'] = req.params.get('ITEMFONTSIZE', self.legend_default_font_size)

        elif req.request == "DESCRIBELAYER":
            expanded = self.__expand_group_layers(req.params, 'LAYERS', permissions)
            req.params['LAYERS'] = ",".join([entry['layer'] for entry in expanded])

        elif req.request == 'GETPRINT':
            expanded = self.__expand_group_layers(req.params, layers_param, permissions)
            req.params[layers_param] = ",".join([entry['layer'] for entry in expanded])
            req.params['OPACITIES'] = ",".join([str(entry['opacity']) for entry in expanded])
            req.params['STYLES'] = ",".join([entry['style'] for entry in expanded])
            # NOTE: also set LAYERS, so that QGIS Server applies OPACITIES correctly
            req.params['LAYERS'] = req.params[layers_param]
            # Inject custom labels
            username = get_username(self.identity) or ''
            for label in self.print_label_queries:
                sql = label["query"].replace("$username$", f"{username}")
                with psycopg.connect(label["db_url"]) as conn:
                    row = conn.execute(sql).fetchone()
                if row:
                    for idx, param in enumerate(label['params']):
                        req.params[param] = row[idx]

            for label in self.print_label_values:
                req.params[label["field"]] = label["value"].replace("$username$", f"{username}")
            # Honour print suffix
            req.service_name += self.print_qgs_postfix

        # Handle proprietary MARKER extension
        if req.params.get('MARKER') and self.marker_template is not None:
            req.params.update(self.resolve_marker(req.params))
            req.method = 'POST'

        # Use any custom print URL for raster export or printing
        if req.request == 'GETPRINT' or (req.request == 'GETMAP' and req.params.get('FILENAME')):
            req.server_url = permissions['print_url']

        return req

    def resolve_marker(self, params):
        """ Resolve MARKER to HIGHLIGHT_GEOM / HIGHLIGHT_SYMBOL according to the marker_template
        """
        marker_params = dict(map(lambda x: x.split("->"), params['MARKER'].split('|')))
        if 'X' not in marker_params or 'Y' not in marker_params:
            raise ServiceException("InvalidParameterValue", "Both X and Y need to be specified in MARKER param")

        template = self.marker_template
        param_keys = set(marker_params.keys()) | set(self.marker_params.keys())
        for key in param_keys:
            # Validate
            value = str(marker_params.get(key, self.marker_params.get(key, {}).get("value")))
            paramtype = self.marker_params.get(key, {}).get("type")
            if paramtype == "number":
                try:
                    float(value)
                except ValueError:
                    raise ServiceException(
                        "InvalidParameterValue",
                        f"Bad value for MARKER param {key} (value: {value}, expected to be a: {paramtype})"
                    )
            elif paramtype == "color":
                if not re.match(r"^([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$", value):
                    raise ServiceException(
                        "InvalidParameterValue",
                        f"Bad value for MARKER param {key} (value: {value}, expected to be a: {paramtype})"
                    )
                # Prepend hash to hex value
                value = "#" + value
            elif paramtype == "string":
                pass
            else:
                raise ServiceException(
                    "InvalidParameterValue",
                    f"Unknown parameter type {paramtype} in MARKER param {key} configuration"
                )

            template = template.replace(f'${key}$', value)
        marker_geom = f"POINT ({marker_params['X']} {marker_params['Y']})"

        return {
            'HIGHLIGHT_GEOM': ";".join(filter(bool, [params.get('HIGHLIGHT_GEOM', ''), marker_geom])),
            'HIGHLIGHT_SYMBOL': ";".join(filter(bool, [params.get('HIGHLIGHT_SYMBOL', ''), template]))
        }

    @override
    def response_streamable(self, request):
        """ Returns whether the response for the specified request is streamable. """
        return request in ['GETMAP', 'GETPRINT']

    @override
    def build_response(self, req, response, permissions, stream):
        """Build the (possibly filtered) response.

        :param OgcRequest req: The OGC request
        :param obj response: The request response
        :param obj permissions: OGC service permissions
        :param bool stream: Whether to stream the response
        """
        if req.request in ['GETCAPABILITIES', 'GETPROJECTSETTINGS']:
            return self.__filter_getcapabilities(response, permissions, req.params)
        elif req.request == 'GETFEATUREINFO':
            return self.__filter_getfeatureinfo(response, permissions)
        else:
            return super().build_response(req, response, permissions, stream)

    def __get_map_param_prefix(self, params):
        # Deduce map name by looking for param which ends with :EXTENT
        # (Can't look for param ending with :LAYERS as there might be i.e. A:LAYERS for the external layer definition A)
        for key in params:
            if key.endswith(":EXTENT"):
                return key[0:-7]
        return ""

    def __expand_group_layers(self, params, layers_param, permissions):
        """ Replace groups with permitted sublayers and also return expanded STYLES / OPACITIES
        """

        # replace restricted group layers ("facade layers") with permitted sublayers
        requested_layers = params.get(layers_param, '').split(',')
        requested_opacities = params.get('OPACITIES', '').split(',')
        requested_styles = params.get('STYLES', '').split(',')

        expanded = []
        for i, layer in enumerate(requested_layers):
            try:
                opacity = max(0, min(int(requested_opacities[i]), 255))
            except: # noqa E722
                opacity = 255
            try:
                style = requested_styles[i]
            except: #noqa E722
                style = ''

            if layer.startswith("EXTERNAL_WMS:"):
                self.__rewrite_external_wms_url(layer, params)
                expanded.append({
                    'layer': layer, 'opacity': opacity, 'style': style
                })
            elif sublayers := permissions['permitted_layers'][layer]['sublayers']:
                expanded += self.__expand_group(sublayers, opacity, permissions)
            else:
                expanded.append({
                    'layer': layer, 'opacity': opacity, 'style': style
                })
        return expanded

    def __expand_group(self, layers, opacity, permissions):
        """ Recursively expand restricted group layers ("facades")

        :param list(str) layers: The group layers to expand
        :param int opacities_param: Parent group opacity
        :param obj permissions: Service permissions
        """
        result = []
        for layer in layers:
            layer_opacity = round(layer['opacity'] / 100 * opacity)
            if layer['name'] not in permissions['permitted_layers']:
                continue
            elif sublayers := permissions['permitted_layers'][layer['name']]['sublayers']:
                result += self.__expand_group(sublayers, layer_opacity, permissions)
            else:
                result.append({
                    'layer': layer['name'], 'opacity': layer_opacity, 'style': ''
                })
        # NOTE: in WMS, LAYERS is ordered bottom to top (layers appearing later are drawn over layers appearing earlier)
        # A group contains layers in layer-tree-order, i.e. top-to-bottom
        result.reverse()
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
            env = request.environ
            ogc_service_url = env.get('HTTP_ORIGIN', '') + env.get('SCRIPT_NAME', '') + env.get('SERVICE_MOUNTPOINT', '') + "/"
            if layer_url and layer_url.startswith(ogc_service_url):
                params[layer_ident + ":URL"] = self.qgis_server_url + layer_url.removeprefix(ogc_service_url)
            else:
                # No replacement done
                return

        # Filter unpermitted layers
        service_name = layer_url.removeprefix(ogc_service_url).split("?")[0]
        wms_permissions = self.permission_handler.resource_permissions(
            'wms_services', self.identity, service_name
        )
        permitted_layers = set()
        for permissions in wms_permissions:
            for layer_permission in permissions['layers']:
                permitted_layers.add(layer_permission['name'])

        layers = params.get(layer_ident + ":LAYERS", "").split(",")
        styles = params.get(layer_ident + ":STYLES", "").split(",")
        opacities = params.get(layer_ident + ":OPACITIES", "").split(",")
        filtered_layers = []
        filtered_styles = []
        filtered_opacities = []
        for idx, layername in enumerate(layers):
            if layername in permitted_layers:
                filtered_layers.append(layername)
                filtered_styles.append(styles[idx] if idx < len(styles) else '')
                filtered_opacities.append(opacities[idx] if idx < len(opacities) else '255')
        params[layer_ident + ":LAYERS"] = ",".join(filtered_layers)
        params[layer_ident + ":STYLES"] = ",".join(filtered_styles)
        params[layer_ident + ":OPACITIES"] = ",".join(filtered_opacities)

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
            ElementTree.register_namespace('xsi', xsins)
            root = ElementTree.fromstring(xml)

            ogc_request = params.get('REQUEST', '').upper()

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
                online_resources += root.findall(f'.//{np}Service/{np}OnlineResource', ns)
                online_resources += root.findall(f'.//{np}GetCapabilities//{np}OnlineResource', ns)
                online_resources += root.findall(f'.//{np}GetMap//{np}OnlineResource', ns)
                online_resources += root.findall(f'.//{np}GetFeatureInfo//{np}OnlineResource', ns)
                online_resources += root.findall(f'.//{{{sldns}}}GetLegendGraphic//{np}OnlineResource', ns)
                online_resources += root.findall(f'.//{{{sldns}}}DescribeLayer//{np}OnlineResource', ns)
                online_resources += root.findall(f'.//{{{qgsns}}}GetStyles//{np}OnlineResource', ns)
                online_resources += root.findall(f'.//{np}GetPrint//{np}OnlineResource', ns)
                online_resources += root.findall(f'.//{np}LegendURL//{np}OnlineResource', ns)

                self.__update_online_resources(online_resources, service_url, xlinkns, params)

            # remove unsupported info formats
            featureInfoEl = root.find(f'.//{np}GetFeatureInfo', ns)
            for formatEl in featureInfoEl.findall(f'./{np}Format', ns):
                if formatEl.text not in ['text/plain', 'text/xml', 'text/html']:
                    featureInfoEl.remove(formatEl)

            # override GetFeatureInfo OnlineResources
            info_url = permissions['online_resources'].get('feature_info')
            if info_url:
                online_resources = root.findall(
                    f'.//{np}GetFeatureInfo//{np}OnlineResource', ns
                )
                self.__update_online_resources(online_resources, info_url, xlinkns, params)

            # override GetLegend OnlineResources
            legend_url = permissions['online_resources'].get('legend')
            if legend_url:
                online_resources = root.findall(
                    f'.//{np}LegendURL//{np}OnlineResource', ns
                )
                online_resources += root.findall(
                    f'.//{{{sldns}}}GetLegendGraphic//{np}OnlineResource',
                    ns
                )
                self.__update_online_resources(online_resources, legend_url, xlinkns, params)

                # HACK: Inject LegendURL for group layers (which are missing LegendURL)
                # Pending proper upstream QGIS server fix
                # Take first online_resource and tweak the URL
                refUrl = urlparse(online_resources[0].get(f'{{{xlinkns}}}href'))
                refQuery = dict(parse_qsl(refUrl.query))
                refFmt = refQuery.get('FORMAT','image/png')

                layers = root.findall(f'.//{np}Layer', ns)
                for layerEl in layers:
                    styleEl = layerEl.find(f'{np}Style', ns)
                    if styleEl is None:

                        styleEl = ElementTree.Element('Style')
                        layerEl.append(styleEl)

                        nameEl = ElementTree.Element('Name')
                        nameEl.text = 'default'
                        styleEl.append(nameEl)

                        titleEl = ElementTree.Element('Title')
                        titleEl.text = 'default'
                        styleEl.append(titleEl)

                    legendUrlEl = styleEl.find(f'{np}LegendURL', ns)
                    nameEl = layerEl.find(f"{np}Name", ns)
                    if legendUrlEl is None and nameEl is not None:
                        refQuery['LAYER'] = nameEl.text
                        refUrl = refUrl._replace(query = urlencode(refQuery, doseq=True))

                        legendUrlEl = ElementTree.Element('LegendURL')
                        styleEl.append(legendUrlEl)

                        formatEl = ElementTree.Element('Format')
                        formatEl.text = refFmt
                        legendUrlEl.append(formatEl)

                        onlineResourceEl = ElementTree.Element('OnlineResource', {
                            f'{{{xlinkns}}}href': refUrl.geturl(),
                            f'{{{xlinkns}}}type': 'simple'
                        })
                        legendUrlEl.append(onlineResourceEl)

                    # Inject editConfig if layer is editable
                    layer_name = nameEl.text if nameEl is not None else permissions['service_name'].split('/')[-1]
                    if permissions['online_resources'].get('edit_config') and \
                        permissions['permitted_layers'].get(layer_name, {}).get('edit_layers')\
                    :
                        editConfigEl = ElementTree.Element('EditConfig')
                        editConfigEl.set('wms_name', permissions['service_name'])
                        layerEl.append(editConfigEl)
                        edit_layers = ",".join(permissions['permitted_layers'][layer_name]['edit_layers'])
                        edit_config_url = permissions['online_resources']['edit_config'] + "&layers=" + edit_layers
                        if edit_config_url.startswith("/"):
                            edit_config_url = request.host_url.rstrip("/") + edit_config_url
                        onlineResourceEl = ElementTree.Element('OnlineResource', {
                            f'{{{edit_config_url}}}href': edit_config_url,
                            f'{{{xlinkns}}}type': 'simple'
                        })
                        editConfigEl.append(onlineResourceEl)

                    # Inject GetTranslations url
                    if ogc_request == 'GETPROJECTSETTINGS' and permissions['online_resources'].get('service'):
                        translationsEl = ElementTree.Element('Traslations')
                        layerEl.append(translationsEl)
                        ts_url = permissions['online_resources']['service'] + "?SERVICE=GetTranslations&LANG={lang}"
                        if ts_url.startswith("/"):
                            ts_url = request.host_url.rstrip("/") + ts_url
                        onlineResourceEl = ElementTree.Element('OnlineResource', {
                            f'{{{xlinkns}}}href': ts_url,
                            f'{{{xlinkns}}}type': 'simple'
                        })
                        translationsEl.append(onlineResourceEl)

            root_layer = root.find(f'{np}Capability/{np}Layer', ns)
            if root_layer is not None:

                # filter and update layers by permissions
                permitted_layers = permissions['public_layers']
                has_queryable_layers = False
                for group in root_layer.findall(f'.//{np}Layer/..', ns):
                    for layer in group.findall(f'{np}Layer', ns):
                        layer_name = layer.find(f'{np}Name', ns).text.strip()
                        if layer_name not in permitted_layers:
                            # remove not permitted layer
                            group.remove(layer)
                            continue
                        else:
                            # apply queryable permission
                            if not permissions['permitted_layers'][layer_name].get('queryable'):
                                layer.set('queryable', '0')
                            else:
                                has_queryable_layers |= layer.get('queryable') == '1'

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
                        attributes = layer.find(f'{np}Attributes', ns)
                        if attributes is not None:
                            for attr in attributes.findall(
                                f'{np}Attribute', ns
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
                    f'.//{np}LayerDrawingOrder', ns
                )
                if layer_drawing_order is not None:
                    layers = layer_drawing_order.text.split(',')
                    # remove not permitted layers
                    layers = [
                        layer for layer in layers if layer in permitted_layers
                    ]
                    layer_drawing_order.text = ','.join(layers)

                # filter ComposerTemplates by permissions
                # (for QGIS GetProjectSettings)
                templates = root.find(
                    f'{np}Capability/{np}ComposerTemplates', ns
                )
                if templates is not None:
                    for template in templates.findall(
                        f'{np}ComposerTemplate', ns
                    ):
                        template_name = template.get('name')
                        if template_name not in permissions['print_templates']:
                            # remove not permitted print template
                            templates.remove(template)

                    if templates.find(f'{np}ComposerTemplate', ns) is None:
                        # remove ComposerTemplates if empty
                        root.find(f'{np}Capability', ns).remove(templates)

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


        for online_resource in elements:
            # update OnlineResource URL
            old_url = online_resource.get(f'{{{xlinkns}}}href')
            url_parts = urlparse(old_url)
            if not url_parts.scheme.startswith('http'):
                continue

            if new_url.startswith("/"):
                new_url = request.host_url.rstrip("/") + new_url

            # Drop MAP query parameter, it is never useful for services served through qwc-qgis-server
            query = parse_qsl(url_parts.query)
            query = list(filter(lambda kv: kv[0].lower() != "map", query))
            query = list(filter(lambda kv: kv[0].lower() != "requireauth", query))
            if request.values.get('REQUIREAUTH'):
                query.append(('REQUIREAUTH', request.values.get('REQUIREAUTH')))
            # querystring = urlencode(query, doseq=True)
            querystring = "&".join(f"{kv[0]}={quote(kv[1], safe=' /')}" for kv in query)
            online_resource.set(f'{{{xlinkns}}}href', new_url.removesuffix("?") + "?" + querystring)


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
                info_text += f"Layer '{layer.get('title')}'\n"

                for feature in layer.findall('Feature'):
                    info_text += f"Feature {feature.get('id')}\n"
                    for attr in feature.findall('Attribute'):
                        info_text += f"{attr.get('name')} = '{attr.get('value')}'\n"
                info_text += "\n"
            return Response(info_text, content_type="text/plain")

        elif info_format == "text/html":

            info_html = '<!DOCTYPE html>\n'
            info_html += '<head>\n'
            info_html += '<title>Information</title>\n'
            info_html += '<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />\n'
            info_html += '<style>\n'
            info_html += 'body {\n'
            info_html += '  font-family: "Open Sans", "Calluna Sans", "Gill Sans MT", "Calibri", "Trebuchet MS", sans-serif;\n'
            info_html += '}\n'
            info_html += 'table, th, td {\n'
            info_html += '  width: 100%; border: 1px solid black; border-collapse: collapse; text-align: left; padding: 2px;\n'
            info_html += '}\n'
            info_html += 'th { width: 25%; font-weight: bold; }\n'
            info_html += '.layer-title { font-weight: bold; padding: 2px; }\n'
            info_html += '</style>\n'
            info_html += '</head>\n'
            info_html += '<body>\n'
            for layer in root.findall('./Layer'):
                features = layer.findall('Feature')
                if features:
                    info_html += f'<div class="layer-title">{html.escape(layer.get("title"))}</div>\n'
                for feature in features:
                    info_html += '<table>\n'
                    for attr in feature.findall('Attribute'):
                        info_html += '<tr>\n'
                        info_html += f'<th>{html.escape(attr.get("name"))}</th><td>{html.escape(attr.get("value"))}</td>'
                        info_html += '</tr>\n'
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
