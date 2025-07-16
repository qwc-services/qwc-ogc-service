from xml.etree import ElementTree
import re
from urllib.parse import urlparse
from collections import OrderedDict

from flask import json, Response
import requests


UNICODE_PAT = re.compile(r'[^\w.\-_]', flags=re.UNICODE)


def wfs_clean_layer_name(layer_name):
    # NOTE: replace special characters in layer/attribute names
    # (WFS capabilities/etc report cleaned names)
    return layer_name.replace(" ", "_").replace(":", "-")


def wfs_clean_attribute_name(attribute_name):
    # NOTE: replace special characters in layer/attribute names
    # (WFS capabilities/etc report cleaned names)
    return UNICODE_PAT.sub('', attribute_name.replace(' ', '_'))


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

        feature_type_list = root.find('wfs:FeatureTypeList', NS_MAP)
        if feature_type_list is not None:

            for feature_type in feature_type_list.findall('wfs:FeatureType', NS_MAP):
                typename = wfs_clean_layer_name(feature_type.find('wfs:Name', NS_MAP).text)
                if typename not in permissions['public_layers']:
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

        complex_type_map = {}
        for element in root.findall('xml:element', NS_MAP):
            typename = wfs_clean_layer_name(element.get('name'))
            complex_typename = element.get('type').removeprefix("qgs:")
            complex_type_map[complex_typename] = typename

            if typename not in permissions['public_layers']:
                # Layer not permitted
                root.remove(element)

        for complex_type in root.findall('xml:complexType', NS_MAP):
            # get layer name
            complex_typename = complex_type.get('name')
            typename = complex_type_map.get(complex_typename, None)
            if not typename:
                # Unknown layer?
                continue

            if typename not in permissions['public_layers']:
                # Layer not permitted
                root.remove(complex_type)
                continue

            # get permitted attributes for layer
            sequence = complex_type.find('.//xml:sequence', NS_MAP)
            for element in sequence.findall('xml:element', NS_MAP):
                attr_name = wfs_clean_attribute_name(element.get('name'))
                permitted_attributes = permissions['layers'].get(typename, [])
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

    for featureMember in root.findall('./gml:featureMember', NS_MAP):
        for feature in list(featureMember):
            typename = wfs_clean_layer_name(feature.tag.removeprefix('{%s}' % NS_MAP['qgs']))

            if typename not in permissions['public_layers']:
                featureMember.remove(feature)
                continue

            # get permitted attributes for layer
            permitted_attributes = permissions['layers'].get(typename, [])

            for attr in feature:
                if attr.tag == "{%s}boundedBy" % NS_MAP['gml']:
                    continue
                attr_name = wfs_clean_attribute_name(attr.tag.removeprefix('{%s}' % NS_MAP['qgs']))
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

    geo_json = json.loads(text, object_pairs_hook=OrderedDict)
    features = geo_json.get('features', [])

    for feature in list(features):
        # get type name from id
        typename = wfs_clean_layer_name('.'.join(feature.get('id', '').split('.')[:-1]))
        if typename not in permissions['public_layers']:
            features.remove(feature)
            continue

        # get permitted attributes for layer
        permitted_attributes = permissions['layers'].get(typename, [])

        properties = feature.get('properties', {})
        for attr_name in dict(properties):
            if wfs_clean_attribute_name(attr_name) not in permitted_attributes:
                # remove not permitted attribute
                properties.pop(attr_name)

    # write GeoJSON to string
    return json.dumps(
        geo_json, ensure_ascii=False,
        sort_keys=False
    )

def wfs_transaction(xml, permissions):
    """Filter WFS transaction body filtered by permissions.

    :param xml string: The transaction post payload
    :param obj permissions: OGC service permission
    """
    register_namespaces()
    root = ElementTree.fromstring(xml)

    permitted_typename_map = wfs_typename_map(permissions['public_layers'])

    # Filter insert
    for insertEl in root.findall('wfs:Insert', NS_MAP):
        for typenameEl in list(insertEl):
            typename = wfs_clean_layer_name(typenameEl.tag.removeprefix('{%s}' % NS_MAP['qgs']))

            if typename not in permissions['public_layers']:
                # Layer not permitted
                insertEl.remove(typenameEl)
                continue

            permitted_attributes = permissions['layers'].get(typename, [])
            for attribEl in list(typenameEl):
                attribname = wfs_clean_attribute_name(attribEl.tag.removeprefix('{%s}' % NS_MAP['qgs']))
                if attribname != "geometry" and attribname not in permitted_attributes:
                    typenameEl.remove(attribEl)

    # Filter update
    for updateEl in root.findall('wfs:Update', NS_MAP):
        typename = wfs_clean_layer_name(updateEl.get('typeName'))
        if typename not in permissions['public_layers']:
            # Layer not permitted
            root.remove(updateEl)
            continue

        permitted_attributes = permissions['layers'].get(typename, [])
        for propertyEl in updateEl.findall('wfs:Property', NS_MAP):
            attribname = wfs_clean_attribute_name(propertyEl.find('wfs:Name', NS_MAP).text)
            if attribname != "geometry" and attribname not in permitted_attributes:
                updateEl.remove(propertyEl)

    # Filter delete
    for deleteEl in root.findall('wfs:Delete', NS_MAP):
        typename = wfs_clean_layer_name(deleteEl.get('typeName'))
        if typename not in permissions['public_layers']:
            # Layer not permitted
            root.remove(deleteEl)
            continue

    return ElementTree.tostring(root, encoding='utf-8', method='xml')
