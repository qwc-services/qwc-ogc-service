from xml.etree import ElementTree
import re
from urllib.parse import urlparse
from collections import OrderedDict

from flask import json, Response
import requests


NS_MAP = {
    'gml': 'http://www.opengis.net/gml',
    'ogc': 'http://www.opengis.net/ogc',
    'ows': 'http://www.opengis.net/ows',
    'qgs': 'http://www.qgis.org/gml',
    'wfs': 'http://www.opengis.net/wfs',
    'xlink': 'http://www.w3.org/1999/xlink',
    'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
    'xml': 'http://www.w3.org/2001/XMLSchema'
}
def register_namespaces():
    for key, value in NS_MAP.items():
        ElementTree.register_namespace(key, value)

# Helper methods for WFS responses filtered by permissions

def get_permitted_typename_map(permissions, replaceColons=True):
    # Clean layer names like QGIS does
    if replaceColons:
        return dict(map(
            lambda name: (name.replace(' ', '_').replace(':', '-'), name),
            permissions['public_layers']
        ))
    else:
        return dict(map(
            lambda name: (name.replace(' ', '_'), name),
            permissions['public_layers']
        ))

def get_permitted_attributes(permissions, layer_name, replace_unicode=True):
    # Clean attribute names like QGIS does
    # QRegularExpression sCleanTagNameRegExp( QStringLiteral( "[^\\w\\.-_]" ), QRegularExpression::PatternOption::UseUnicodePropertiesOption );
    # fieldName.replace( ' ', '_' ).replace( sCleanTagNameRegExp, QString() );
    if replace_unicode:
        pat = re.compile(r'[^\w.\-_]', flags=re.UNICODE)
        return list(map(
            lambda field: pat.sub('', field.replace(' ', '_')),
            permissions['layers'].get(layer_name, [])
        ))
    else:
        return list(map(
            lambda field: field.replace(' ', '_'),
            permissions['layers'].get(layer_name, [])
        ))

def get_service_url(permissions, host_url, script_root):
    wfs_url = permissions.get('online_resource')
    if not wfs_url:
        # default OnlineResource from request URL parts
        # e.g. '//example.com/ows/qwc_demo'
        url_parts = urlparse(host_url)
        wfs_url = "%s://%s%s/%s" % (
            url_parts.scheme, url_parts.netloc, script_root, permissions.get('service_name')
        )
    return wfs_url

def wfs_getcapabilities(response, params, permissions, host_url, script_root):
    """Return WFS GetCapabilities filtered by permissions.

    :param requests.Response response: Response object
    :param obj params: Request parameters
    :param obj permissions: OGC service permission
    :param str host_url: host url
    :param str script_root: Request root path
    """
    xml = response.text

    if response.status_code == requests.codes.ok:
        register_namespaces()
        # NOTE: Default namespace for WFS GetCapabilities documents
        ElementTree.register_namespace('', NS_MAP['wfs'])
        # parse capabilities XML
        root = ElementTree.fromstring(xml)

        # override OnlineResources
        service_url = get_service_url(permissions, host_url, script_root)

        if params['VERSION'] == "1.1.0":
            for online_resource in root.findall('.//ows:Get', NS_MAP):
                online_resource.set('{%s}href' % NS_MAP['xlink'], service_url)
            for online_resource in root.findall('.//ows:Post', NS_MAP):
                online_resource.set('{%s}href' % NS_MAP['xlink'], service_url)
        else:
            for online_resource in root.findall('.//wfs:Get', NS_MAP):
                online_resource.set('onlineResource', service_url)
            for online_resource in root.findall('.//wfs:Post', NS_MAP):
                online_resource.set('onlineResource', service_url)

        # remove Transaction capability
        capability_request = root.find(
            './/wfs:Capability//wfs:Request', NS_MAP
        )
        if capability_request is not None:
            for transaction in capability_request.findall(
                'wfs:Transaction', NS_MAP
            ):
                capability_request.remove(transaction)

        feature_type_list = root.find('wfs:FeatureTypeList', NS_MAP)
        if feature_type_list is not None:

            # NOTE: In version 1.0.0 documents, colons are not replaced in Name
            permitted_typename_map = get_permitted_typename_map(permissions, params['VERSION'] == "1.1.0")
            for feature_type in feature_type_list.findall('wfs:FeatureType', NS_MAP):
                typename = feature_type.find('wfs:Name', NS_MAP).text
                if typename not in permitted_typename_map:
                    # remove not permitted layer
                    feature_type_list.remove(feature_type)

        # write XML to string
        xml = ElementTree.tostring(root, encoding='utf-8', method='xml')

    return Response(
        xml,
        content_type=response.headers['content-type'],
        status=response.status_code
    )


def wfs_describefeaturetype(response, params, permissions):
    """Return WFS DescribeFeatureType filtered by permissions.

    :param requests.Response response: Response object
    :param obj params: Request parameters
    :param obj permissions: OGC service permission
    """
    xml = response.text

    if response.status_code == requests.codes.ok:
        register_namespaces()
        # NOTE: Default namespace for WFS DescribeFeatureType documents
        ElementTree.register_namespace('', NS_MAP['xml'])
        # parse capabilities XML
        root = ElementTree.fromstring(xml)

        # Manually register namespaces which appear in attribute values
        root.set("xmlns:qgs", 'http://www.qgis.org/gml')
        root.set("xmlns:gml", 'http://www.opengis.net/gml')

        permitted_typename_map = get_permitted_typename_map(permissions)
        complex_type_map = {}
        for element in root.findall('xml:element', NS_MAP):
            typename = element.get('name')
            complex_typename = element.get('type').removeprefix("qgs:")
            complex_type_map[complex_typename] = typename

            if not typename in permitted_typename_map:
                # Layer not permitted
                root.remove(element)

        for complex_type in root.findall('xml:complexType', NS_MAP):
            # get layer name
            complex_typename = complex_type.get('name')
            typename = complex_type_map.get(complex_typename, None)
            if not typename:
                # Unknown layer?
                continue

            if not typename in permitted_typename_map:
                # Layer not permitted
                root.remove(complex_type)
                continue

            # get permitted attributes for layer
            layer_name = permitted_typename_map[typename]

            sequence = complex_type.find('.//xml:sequence', NS_MAP)
            for element in sequence.findall('xml:element', NS_MAP):
                attr_name = element.get('name')
                # NOTE: the element name attribute contains the non-utf-cleaned attribute name
                permitted_attributes = get_permitted_attributes(permissions, layer_name, False)
                # NOTE: keep geometry attribute
                if attr_name != "geometry" and attr_name not in permitted_attributes:
                    # remove not permitted attribute
                    sequence.remove(element)

        # write XML to string
        xml = ElementTree.tostring(root, encoding='utf-8', method='xml')

    return Response(
        xml,
        content_type=response.headers['content-type'],
        status=response.status_code
    )


def wfs_getfeature(response, params, permissions, host_url, script_root):
    """Return WFS GetFeature filtered by permissions.

    :param requests.Response response: Response object
    :param obj params: Request parameters
    :param obj permissions: OGC service permission
    :param str host_url: host url
    :param str script_root: Request root path
    """
    features = response.text

    if response.status_code == requests.codes.ok:
        output_format = params.get('OUTPUTFORMAT', 'gml3').lower()
        content_type = response.headers['content-type']
        if output_format == 'geojson':
            features = wfs_getfeature_geojson(response, permissions)
        else:
            features = wfs_getfeature_gml(response, permissions, host_url, script_root)

    return Response(
        features,
        content_type=content_type,
        status=response.status_code
    )


def wfs_getfeature_gml(response, permissions, host_url, script_root):
    """Parse features GML and filter feature attributes by permission.

    :param requests.Response response: Response object
    :param obj permissions: OGC service permission
    :param str host_url: host url
    :param str script_root: Request root path
    """
    register_namespaces()
    root = ElementTree.fromstring(response.text)

    # NOTE: Rewrite internal URL in schema location
    internal_url = response.request.url.split("?")[0]
    service_url = get_service_url(permissions, host_url, script_root)
    schemaLocation = "{%s}schemaLocation" % NS_MAP['xsi']
    root.attrib[schemaLocation] = root.attrib[schemaLocation].replace(internal_url, service_url)

    permitted_typename_map = get_permitted_typename_map(permissions)

    for featureMember in root.findall('./gml:featureMember', NS_MAP):
        for feature in list(featureMember):
            typename = feature.tag.removeprefix('{%s}' % NS_MAP['qgs'])

            if not typename in permitted_typename_map:
                featureMember.remove(feature)
                continue

            layer_name = permitted_typename_map[typename]

            # get permitted attributes for layer
            # NOTE: the element name attribute contains the non-utf-cleaned attribute name
            permitted_attributes = get_permitted_attributes(permissions, layer_name, False)

            for attr in feature:
                if attr.tag == "{%s}boundedBy" % NS_MAP['gml']:
                    continue
                attr_name = attr.tag.removeprefix('{%s}' % NS_MAP['qgs'])
                # NOTE: keep geometry attribute
                if attr_name != "geometry" and attr_name not in permitted_attributes:
                    # remove not permitted attribute
                    feature.remove(attr)

    # write XML to string
    return ElementTree.tostring(
        root, encoding='utf-8', method='xml', short_empty_elements=False
    )


def wfs_getfeature_geojson(response, permissions):
    """Parse features GeoJSON and filter feature attributes by permission.

    :param requests.Response response: Response object
    :param obj permissions: OGC service permissions
    """
    # parse GeoJSON (preserve order)
    geo_json = json.loads(response.text, object_pairs_hook=OrderedDict)
    features = geo_json.get('features', [])

    permitted_typename_map = get_permitted_typename_map(permissions)

    for feature in list(features):
        # get type name from id
        typename = '.'.join(feature.get('id', '').split('.')[:-1])
        if not typename in permitted_typename_map:
            features.remove(feature)
            continue

        layer_name = permitted_typename_map[typename]

        # get permitted attributes for layer
        # NOTE: the properties contain the non-cleaned attribute name
        permitted_attributes = permissions['layers'].get(layer_name, [])

        properties = feature.get('properties', {})
        for attr_name in dict(properties):
            if attr_name not in permitted_attributes:
                # remove not permitted attribute
                properties.pop(attr_name)

    # write GeoJSON to string
    return json.dumps(
        geo_json, ensure_ascii=False,
        sort_keys=False
    )
