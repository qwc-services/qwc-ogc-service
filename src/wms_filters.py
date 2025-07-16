import html
import re
from urllib.parse import urlparse, parse_qs, parse_qsl, urlencode
from xml.etree import ElementTree

from flask import Response
import requests


# Helper methods for WMS responses filtered by permissions


def wms_getcapabilities(response, host_url, params, script_root, permissions):
    """Return WMS GetCapabilities or GetProjectSettings filtered by
    permissions.

    :param requests.Response response: Response object
    :param str host_url: host url
    :param obj params: Request parameters
    :param str script_root: Request root path
    :param obj permissions: OGC service permissions
    """
    xml = response.text

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
        if not service_url:
            # default OnlineResource from request URL parts
            # e.g. '//example.com/ows/qwc_demo'
            service_url = "//%s%s/%s" % (
                urlparse(host_url).netloc, script_root, permissions.get('service_name')
            )

        # override GetSchemaExtension URL in xsi:schemaLocation
        update_schema_location(root, service_url, xsins)

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

        update_online_resources(
            online_resources, service_url, xlinkns, host_url
        )

        info_url = permissions['online_resources'].get('feature_info')
        if info_url:
            # override GetFeatureInfo OnlineResources
            online_resources = root.findall(
                './/%sGetFeatureInfo//%sOnlineResource' % (np, np), ns
            )
            update_online_resources(
                online_resources, info_url, xlinkns, host_url
            )

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
            update_online_resources(
                online_resources, legend_url, xlinkns, host_url
            )

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
            queryable_layers = permissions['queryable_layers']
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
                    permitted_attributes = permissions['layers'].get(
                        layer_name, {}
                    )

                    # remove layer displayField if attribute not permitted
                    # (for QGIS GetProjectSettings)
                    display_field = layer.get('displayField')
                    if (display_field and
                            display_field not in permitted_attributes):
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
            if queryable_layers:
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
                permitted_templates = permissions.get('print_templates', [])
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


def update_schema_location(capabilities, new_url, xsins):
    """Update GetSchemaExtension URL in WMS_Capabilities xsi:schemaLocation.

    :param Element capabilities: WMS_Capabilities element
    :param str new_url: New OnlineResource URL
    :param str xsins: XML namespace for WMS_Capabilities schemaLocation
    """
    # get URL parts
    url = urlparse(new_url)
    scheme = url.scheme
    netloc = url.netloc
    path = url.path.rstrip('/')

    schema_location = capabilities.get('{%s}schemaLocation' % xsins)
    if schema_location:
        # extract GetSchemaExtension URL
        # e.g. http://...?SERVICE=WMS&REQUEST=GetSchemaExtension
        match = re.search(
            r'(https?:\/\/[^\s]*REQUEST=GetSchemaExtension[^\s]*)',
            schema_location,
            re.IGNORECASE
        )
        if match:
            schema_extension_url = match.group(1)

            # update GetSchemaExtension URL
            url = urlparse(schema_extension_url)
            if scheme:
                url = url._replace(scheme=scheme)
            url = url._replace(netloc=netloc)
            url = url._replace(path=path)

            capabilities.set(
                '{%s}schemaLocation' % xsins,
                schema_location.replace(schema_extension_url, url.geturl())
            )


def update_online_resources(elements, new_url, xlinkns, host_url):
    """Update OnlineResource URLs.

    :param list(Element) elements: List of OnlineResource elements
    :param str new_url: New OnlineResource URL
    :param str xlinkns: XML namespace for OnlineResource href
    :param str host_url: host url
    """

    host_url_parts = urlparse(host_url)

    # get URL parts
    url = urlparse(new_url)
    scheme = url.scheme if url.scheme else host_url_parts.scheme
    netloc = url.netloc if url.netloc else host_url_parts.netloc
    path = url.path

    for online_resource in elements:
        # update OnlineResource URL
        url = urlparse(online_resource.get('{%s}href' % xlinkns))
        if not url.scheme.startswith('http'):
            continue
        url = url._replace(scheme=scheme)
        url = url._replace(netloc=netloc)
        url = url._replace(path=path)

        # Drop MAP query parameter, it is never useful for services served through qwc-qgis-server
        query = parse_qs(url.query)
        query_keys = list(query.keys())
        for key in query_keys:
            if key.lower() == "map":
                del query[key]

        url = url._replace(query = urlencode(query, doseq=True))

        online_resource.set('{%s}href' % xlinkns, url.geturl())


def wms_getfeatureinfo(response, params, permissions, original_params):
    """Return WMS GetFeatureInfo filtered by permissions.

    :param requests.Response response: Response object
    :param obj params: Request parameters
    :param obj permissions: OGC service permissions
    :param obj original_params: Original request params
    """
    feature_info = response.text

    info_format = original_params.get('INFO_FORMAT', 'text/plain')

    # Info always requested as text/xml from server
    ElementTree.register_namespace('', 'http://www.opengis.net/ogc')
    root = ElementTree.fromstring(feature_info)

    for layer in root.findall('./Layer'):
        # get permitted attributes for layer
        permitted_attributes = permitted_info_attributes(
            layer.get('name'), permissions
        )

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
            info_text += "Layer '%s'\n" % layer.get('name')

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
                info_html += '<div class="layer-title">%s</div>\n' % html.escape(layer.get('name'))
            for feature in features:
                info_html += '<table>\n'
                for attr in feature.findall('Attribute'):
                    info_html += '<tr><th>%s</th><td>%s</td></tr>\n' % (html.escape(attr.get('name')), html.escape(attr.get('value')))
                info_html += '</table>\n'
        info_html += '</body>\n'
        return Response(info_html, content_type="text/html")
    else:
        service_exception = (
            '<ServiceExceptionReport version="1.3.0">\n'
            ' <ServiceException code="InvalidFormat">Unsupported info_format</ServiceException>\n'
            '</ServiceExceptionReport>'
        )
        return Response(
            service_exception,
            content_type='text/xml; charset=utf-8',
            status=200
        )

def permitted_info_attributes(info_layer_name, permissions):
    """Get permitted attributes for a feature info result layer.

    :param str info_layer_name: Layer name from feature info result
    :param obj permissions: OGC service permissions
    """
    # get WMS layer name for info result layer
    wms_layer_name = permissions.get('feature_info_aliases', {}) \
        .get(info_layer_name, info_layer_name)

    # return permitted attributes for layer
    attribute_aliases = permissions['layers'].get(wms_layer_name, {})

    # NOTE: reverse lookup for attribute names from alias, as QGIS Server returns aliases
    alias_attributes = dict([x[::-1] for x in attribute_aliases.items()])
    return alias_attributes
