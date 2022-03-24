import re
from urllib.parse import urlparse, parse_qs, urlencode
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
        xsins = 'http://www.w3.org/2001/XMLSchema-instance'
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
        online_resources = root.findall('.//%sOnlineResource' % np, ns)
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


def wms_getfeatureinfo(response, params, permissions):
    """Return WMS GetFeatureInfo filtered by permissions.

    :param requests.Response response: Response object
    :param obj params: Request parameters
    :param obj permissions: OGC service permissions
    """
    feature_info = response.text

    if response.status_code == requests.codes.ok:
        info_format = params.get('INFO_FORMAT', 'text/plain')
        if info_format == 'text/plain':
            feature_info = wms_getfeatureinfo_plain(
                feature_info, permissions
            )
        elif info_format == 'text/html':
            feature_info = wms_getfeatureinfo_html(
                feature_info, permissions
            )
        elif info_format == 'text/xml':
            feature_info = wms_getfeatureinfo_xml(
                feature_info, permissions
            )
        elif info_format == 'application/vnd.ogc.gml':
            feature_info = wms_getfeatureinfo_gml(
                feature_info, permissions
            )

        # NOTE: application/vnd.ogc.gml/3.1.1 is broken in QGIS server

    return Response(
        feature_info,
        content_type=response.headers['content-type'],
        status=response.status_code
    )


def wms_getfeatureinfo_plain(feature_info, permissions):
    """Parse feature info text and filter feature attributes by permissions.

    :param str feature_info: Raw feature info response from QGIS server
    :param obj permissions: OGC service permissions
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

        # filter feature attributes by permissions
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
                    permitted_attributes = permitted_info_attributes(
                        current_layer, permissions
                    )

            # keep line
            lines.append(line)

        # join filtered lines
        feature_info = '\n'.join(lines)

    return feature_info


def wms_getfeatureinfo_html(feature_info, permissions):
    """Parse feature info HTML and filter feature attributes by permissions.

    :param str feature_info: Raw feature info response from QGIS server
    :param obj permissions: OGC service permissions
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
                    permitted_attributes = permitted_info_attributes(
                        current_layer, permissions
                    )

            # keep line
            lines.append(line)

        # join filtered lines
        feature_info = '\n'.join(lines)

    return feature_info


def wms_getfeatureinfo_xml(feature_info, permissions):
    """Parse feature info XML and filter feature attributes by permissions.

    :param str feature_info: Raw feature info response from QGIS server
    :param obj permissions: OGC service permissions
    """
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

    # write XML to string
    return ElementTree.tostring(root, encoding='utf-8', method='xml')


def wms_getfeatureinfo_gml(feature_info, permissions):
    """Parse feature info GML and filter feature attributes by permissions.

    :param str feature_info: Raw feature info response from QGIS server
    :param obj permissions: OGC service permissions
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
            permitted_attributes = permitted_info_attributes(
                layer_name, permissions
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


def permitted_info_attributes(info_layer_name, permissions):
    """Get permitted attributes for a feature info result layer.

    :param str info_layer_name: Layer name from feature info result
    :param obj permissions: OGC service permissions
    """
    # get WMS layer name for info result layer
    wms_layer_name = permissions.get('feature_info_aliases', {}) \
        .get(info_layer_name, info_layer_name)

    # return permitted attributes for layer
    return permissions['layers'].get(wms_layer_name, {})
