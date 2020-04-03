from xml.etree import ElementTree
import re
from collections import OrderedDict

from flask import json, Response
import requests


# Helper methods for WFS responses filtered by permissions


def wfs_getcapabilities(response, params, permissions):
    """Return WFS GetCapabilities filtered by permissions.

    :param requests.Response response: Response object
    :param obj params: Request parameters
    :param obj permissions: OGC service permission
    """
    xml = response.text

    if response.status_code == requests.codes.ok:
        # parse capabilities XML
        ElementTree.register_namespace('', 'http://www.opengis.net/wfs')
        ElementTree.register_namespace('ogc', 'http://www.opengis.net/ogc')
        root = ElementTree.fromstring(xml)

        # use default namespace for XML search
        # namespace dict
        ns = {'ns': 'http://www.opengis.net/wfs'}
        # namespace prefix
        np = 'ns:'
        if not root.tag.startswith('{http://'):
            # do not use namespace
            ns = {}
            np = ''

        # override OnlineResources
        wfs_url = permissions.get('online_resource')
        if wfs_url:
            for online_resource in root.findall('.//%sGet' % (np), ns):
                online_resource.set('onlineResource', wfs_url)
            for online_resource in root.findall('.//%sPost' % (np), ns):
                online_resource.set('onlineResource', wfs_url)

        # remove Transaction capability
        capability_request = root.find(
            './/%sCapability//%sRequest' % (np, np), ns
        )
        if capability_request is not None:
            for transaction in capability_request.findall(
                '%sTransaction' % np, ns
            ):
                capability_request.remove(transaction)

        feature_type_list = root.find('%sFeatureTypeList' % (np), ns)
        if feature_type_list is not None:
            # filter and update layers by permission
            permitted_layers = permissions['public_layers']

            for layer in feature_type_list.findall(
                '%sFeatureType' % np, ns
            ):
                layer_name = layer.find('%sName' % np, ns).text
                if layer_name not in permitted_layers:
                    # remove not permitted layer
                    feature_type_list.remove(layer)

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
        # parse capabilities XML
        ElementTree.register_namespace(
            '', 'http://www.w3.org/2001/XMLSchema'
        )
        root = ElementTree.fromstring(xml)

        # use default namespace for XML search
        # namespace dict
        ns = {'ns': 'http://www.w3.org/2001/XMLSchema'}
        # namespace prefix
        np = 'ns:'
        if not root.tag.startswith('{http://'):
            # do not use namespace
            ns = {}
            np = ''

        for complex_type in root.findall('%scomplexType' % np, ns):
            # get layer name
            layer_name = complex_type.get('name', 'Type')[:-4]

            # get permitted attributes for layer
            permitted_attributes = permissions['layers'].get(layer_name, [])

            sequence = complex_type.find('.//%ssequence' % np, ns)
            for element in sequence.findall('%selement' % np, ns):
                attr_name = element.get('name', '')
                if attr_name not in permitted_attributes:
                    # remove not permitted attribute
                    sequence.remove(element)

        # write XML to string
        xml = ElementTree.tostring(root, encoding='utf-8', method='xml')

    return Response(
        xml,
        content_type=response.headers['content-type'],
        status=response.status_code
    )


def wfs_getfeature(response, params, permissions):
    """Return WFS GetFeature filtered by permissions.

    :param requests.Response response: Response object
    :param obj params: Request parameters
    :param obj permissions: OGC service permission
    """
    features = response.text

    if response.status_code == requests.codes.ok:
        output_format = params.get('OUTPUTFORMAT')
        if output_format == 'GeoJSON':
            content_type = 'application/json'
            features = wfs_getfeature_geojson(features, permissions)
        else:
            content_type = response.headers['content-type']
            gml3 = output_format == 'GML3'
            features = wfs_getfeature_gml(features, gml3, permissions)

    return Response(
        features,
        content_type=content_type,
        status=response.status_code
    )


def wfs_getfeature_gml(features, gml3, permissions):
    """Parse features GML and filter feature attributes by permission.

    :param str features: Raw WFS GetFeature response from QGIS server
    :param obj permissions: OGC service permission
    """
    ElementTree.register_namespace('gml', 'http://www.opengis.net/gml')
    ElementTree.register_namespace('qgs', 'http://www.qgis.org/gml')
    ElementTree.register_namespace('wfs', 'http://www.opengis.net/wfs')
    root = ElementTree.fromstring(features)

    # namespace dict
    ns = {
        'gml': 'http://www.opengis.net/gml',
        'qgs': 'http://www.qgis.org/gml'
    }

    qgs_attr_pattern = re.compile("^{%s}(.+)" % ns['qgs'])

    if gml3:
        fid_attr = '{http://www.opengis.net/gml}id'
    else:
        fid_attr = 'fid'

    for feature in root.findall('./gml:featureMember', ns):
        for layer in feature:
            # get layer name from fid, as spaces are removed in tag name
            layer_name = '.'.join(layer.get(fid_attr, '').split('.')[:-1])

            # get permitted attributes for layer
            permitted_attributes = permissions['layers'].get(layer_name, [])

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


def wfs_getfeature_geojson(features, permissions):
    """Parse features GeoJSON and filter feature attributes by permission.

    :param str features: Raw WFS GetFeature response from QGIS server
    :param obj permissions: OGC service permissions
    """
    # parse GeoJSON (preserve order)
    geo_json = json.loads(features, object_pairs_hook=OrderedDict)

    for feature in geo_json.get('features', []):
        # get layer name from id
        layer_name = '.'.join(feature.get('id', '').split('.')[:-1])

        # get permitted attributes for layer
        permitted_attributes = permissions['layers'].get(layer_name, [])

        properties = feature.get('properties', {})
        if properties:
            attributes = list(properties.keys())
            for attr_name in attributes:
                if attr_name not in permitted_attributes:
                    # remove not permitted attribute
                    properties.pop(attr_name)

    # write GeoJSON to string
    return json.dumps(
        geo_json, ensure_ascii=False,
        sort_keys=False
    )
