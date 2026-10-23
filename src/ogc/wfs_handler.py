import re
from typing import override
from xml.etree import ElementTree

import requests
from flask import Response, json, url_for

from ogc.ogc_service_handler import OgcServiceHandler, ServiceException

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

class WfsHandler(OgcServiceHandler):

    def __init__(self, logger, config, qgis_server_url, permission_handler, identity):
        """
        :param obj logger: Application logger
        :param obj config: Service config
        :param obj qgis_server_url: internal QGIS Server URL
        :param obj permission_handler: Permission handler
        :param obj identity: User identity
        """
        super().__init__(logger, config, qgis_server_url, permission_handler, identity)
        self.allow_outputformat_unfiltered = config.get('allow_outputformat_unfiltered',{})

    @staticmethod
    @override
    def accepts(req):
        """Whether the handler handle the specified request.

        :param OgcRequest req: The OGC request
        """
        return req.service == 'WFS'

    @override
    def adjust_request_params(self, req, permissions):
        """Check request parameters against permissions and adjust params, returning the adjusted OgcRequest

        :param OgcRequest req: The OGC request
        :param obj permissions: OGC service permissions
        """

        if req.request not in [
            'GETCAPABILITIES', 'GETFEATURE', 'DESCRIBEFEATURETYPE', 'TRANSACTION'
        ]:
            raise ServiceException("OperationNotSupported", f"Request {req.request} is not supported")

        # check TYPENAME param
        for typename in req.params.get('TYPENAME', "").split(","):
            # allow only permitted layers
            if (
                typename
                and wfs_clean_layer_name(typename) not in permissions['permitted_layers']
            ):
                raise ServiceException(
                    "RequestNotWellFormed", f"TypeName '{typename}' could not be found or is not permitted"
                )

        # check FEATUREID param
        for featureid in req.params.get('FEATUREID', "").split(","):
            # allow only permitted layers
            if (
                featureid
                and wfs_clean_layer_name(featureid.split(".")[0]) not in permissions['permitted_layers']
            ):
                raise ServiceException(
                    "RequestNotWellFormed", f"TypeName '{featureid.split('.')[0]}' could not be found or is not permitted"
                )

        # Adjust params

        if req.params.get('VERSION') not in ['1.0.0', '1.1.0']:
            self.logger.warning("Falling back to WFS 1.1.0")
            req.params['VERSION'] = '1.1.0'

        if req.request == 'GETFEATURE':
            # Map info outputformat
            format_map = {
                "gml2": "gml2",
                "text/xml; subtype=gml/2.1.2": "gml2",
                "gml3": "gml3",
                "text/xml; subtype=gml/3.1.1": "gml3",
                "geojson": "geojson",
                "application/vnd.geo+json": "geojson",
                "application/vnd.geo json": "geojson",
                "application/geo+json": "geojson",
                "application/geo json": "geojson",
                "application/json": "geojson"
            }
            if self.allow_outputformat_unfiltered:
                format_map.update(self.allow_outputformat_unfiltered)
            req.params['OUTPUTFORMAT'] = format_map.get(
                req.params.get('OUTPUTFORMAT', "").lower(),
                'gml3' if req.params['VERSION'] == '1.1.0' else 'gml2'
            )
        elif req.request == 'TRANSACTION' and req.data:
            # Filter WFS Transaction data
            self.__check_transaction(req.data, permissions)

        return req

    @override
    def build_response(self, req, response, permissions, stream):
        """Build the (possibly filtered) response.

        :param OgcRequest req: The OGC request
        :param obj response: The request response
        :param obj permissions: OGC service permissions
        :param bool stream: Whether to stream the response
        """
        if req.request == 'GETCAPABILITIES':
            return self.__filter_getcapabilities(response, req.params, permissions)
        elif req.request == 'DESCRIBEFEATURETYPE':
            return self.__filter_describefeaturetype(response, req.params, permissions)
        elif req.request == 'GETFEATURE':
            return self.__filter_getfeature(response, req.params, permissions)
        else:
            return super().build_response(req, response, permissions, stream)

    def __register_namespaces(self):
        for key, value in NS_MAP.items():
            ElementTree.register_namespace(key, value)

    def __check_transaction(self, data, permissions):
        """Filter WFS transaction body filtered by permissions.

        :param data obj: The POST payload
        :param obj permissions: OGC service permission
        """
        self.__register_namespaces()
        root = ElementTree.fromstring(data['body'])

        # Filter insert
        for insertEl in root.findall('wfs:Insert', NS_MAP):
            for typenameEl in list(insertEl):
                typename = wfs_clean_layer_name(typenameEl.tag.removeprefix('{%s}' % NS_MAP['qgs'])) # noqa: UP031

                permission = permissions['permitted_layers'].get(typename)
                if not permission:
                    # Layer not permitted
                    insertEl.remove(typenameEl)
                    continue

                if not permission['creatable']:
                    raise ServiceException("Forbidden", f"No create permissions on typename '{typename}'")

                permitted_attributes = permissions['permitted_layers'][typename]['attributes']
                for attribEl in list(typenameEl):
                    attribname = wfs_clean_attribute_name(attribEl.tag.removeprefix('{%s}' % NS_MAP['qgs'])) # noqa: UP031
                    if attribname != "geometry" and attribname not in permitted_attributes:
                        typenameEl.remove(attribEl)

        # Filter update
        for updateEl in root.findall('wfs:Update', NS_MAP):
            typename = wfs_clean_layer_name(updateEl.get('typeName'))

            permission = permissions['permitted_layers'].get(typename)
            if not permission:
                # Layer not permitted
                root.remove(updateEl)
                continue

            if not permission['updatable']:
                raise ServiceException("Forbidden", f"No update permissions on typename '{typename}'")

            permitted_attributes = permissions['permitted_layers'][typename]['attributes']
            for propertyEl in updateEl.findall('wfs:Property', NS_MAP):
                attribname = wfs_clean_attribute_name(propertyEl.find('wfs:Name', NS_MAP).text)
                if attribname != "geometry" and attribname not in permitted_attributes:
                    updateEl.remove(propertyEl)

        # Filter delete
        for deleteEl in root.findall('wfs:Delete', NS_MAP):
            typename = wfs_clean_layer_name(deleteEl.get('typeName'))

            permission = permissions['permitted_layers'].get(typename)
            if not permission:
                # Layer not permitted
                root.remove(deleteEl)
                continue

            if not permission['deletable']:
                raise ServiceException("Forbidden", f"No delete permissions on typename '{typename}'")

        data['body'] = ElementTree.tostring(root, encoding='utf-8', method='xml')

    def __filter_getcapabilities(self, response, params, permissions):
        """Return WFS GetCapabilities filtered by permissions.

        :param requests.Response response: Response object
        :param obj params: Request parameters
        :param obj permissions: OGC service permission
        """
        xml = response.text
        # Strip control characters
        xml = re.sub("[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", xml)

        if response.status_code == requests.codes.ok:
            self.__register_namespaces()
            # NOTE: Default namespace for WFS GetCapabilities documents
            ElementTree.register_namespace('', NS_MAP['wfs'])
            # parse capabilities XML
            root = ElementTree.fromstring(xml)

            # override OnlineResources
            service_url = permissions.get('online_resource') or url_for(
                'ogc', service_name=permissions['service_name'], _external=True
            )

            if params['VERSION'] == "1.1.0":
                for online_resource in root.findall('.//ows:Get', NS_MAP):
                    online_resource.set('{%s}href' % NS_MAP['xlink'], service_url) # noqa: UP031
                for online_resource in root.findall('.//ows:Post', NS_MAP):
                    online_resource.set('{%s}href' % NS_MAP['xlink'], service_url) # noqa: UP031
            else:
                for online_resource in root.findall('.//wfs:Get', NS_MAP):
                    online_resource.set('onlineResource', service_url)
                for online_resource in root.findall('.//wfs:Post', NS_MAP):
                    online_resource.set('onlineResource', service_url)

            feature_type_list = root.find('wfs:FeatureTypeList', NS_MAP)
            if feature_type_list is not None:

                for feature_type in feature_type_list.findall('wfs:FeatureType', NS_MAP):
                    typename = wfs_clean_layer_name(feature_type.find('wfs:Name', NS_MAP).text)
                    if typename not in permissions['permitted_layers']:
                        # remove not permitted layer
                        feature_type_list.remove(feature_type)

            # write XML to string
            xml = ElementTree.tostring(root, encoding='utf-8', method='xml')

        return Response(
            xml,
            content_type=response.headers['content-type'],
            status=response.status_code
        )

    def __filter_describefeaturetype(self, response, params, permissions):
        """Return WFS DescribeFeatureType filtered by permissions.

        :param requests.Response response: Response object
        :param obj params: Request parameters
        :param obj permissions: OGC service permission
        """
        xml = response.text
        # Strip control characters
        xml = re.sub("[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", xml)

        if response.status_code == requests.codes.ok:
            self.__register_namespaces()
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

                if typename not in permissions['permitted_layers']:
                    # Layer not permitted
                    root.remove(element)

            for complex_type in root.findall('xml:complexType', NS_MAP):
                # get layer name
                complex_typename = complex_type.get('name')
                typename = complex_type_map.get(complex_typename)
                if not typename:
                    # Unknown layer?
                    continue

                if typename not in permissions['permitted_layers']:
                    # Layer not permitted
                    root.remove(complex_type)
                    continue

                # get permitted attributes for layer
                permitted_attributes = permissions['permitted_layers'][typename]['attributes']
                sequence = complex_type.find('.//xml:sequence', NS_MAP)
                for element in sequence.findall('xml:element', NS_MAP):
                    attr_name = wfs_clean_attribute_name(element.get('name'))
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

    def __filter_getfeature(self, response, params, permissions):
        """Return WFS GetFeature filtered by permissions.

        :param requests.Response response: Response object
        :param obj params: Request parameters
        :param obj permissions: OGC service permission
        """
        features = response.text
        if response.status_code == requests.codes.ok:
            output_format = params.get('OUTPUTFORMAT', 'gml3').lower()
            content_type = response.headers['content-type']
            if output_format == 'geojson':
                features = self.__filter_getfeature_geojson(response, permissions)
            elif output_format in ('gml2', 'gml3'):
                features = self.__filter_getfeature_gml(response, permissions)
            else:
                # there is formats in self.allow_outputformat_unfiltered
                # so it is an other output_format and there is no filter to apply
                return Response(
                    response.content,
                    content_type=response.headers['content-type'],
                    headers={
                        "content-disposition": response.headers['content-disposition']
                    },
                    status=response.status_code
                )
        return Response(
            features,
            content_type=content_type,
            status=response.status_code
        )

    def __filter_getfeature_gml(self, response, permissions):
        """Parse features GML and filter feature attributes by permission.

        :param requests.Response response: Response object
        :param obj permissions: OGC service permission
        """
        self.__register_namespaces()
        xml = response.text
        # Strip control characters
        xml = re.sub("[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", xml)

        root = ElementTree.fromstring(xml)

        # NOTE: Rewrite internal URL in schema location
        internal_url = response.request.url.split("?")[0]
        service_url = permissions.get('online_resource') or url_for(
            'ogc', service_name=permissions['service_name'], _external=True
        )
        schemaLocation = "{%s}schemaLocation" % NS_MAP['xsi'] # noqa: UP031
        root.attrib[schemaLocation] = root.attrib[schemaLocation].replace(internal_url, service_url)

        for featureMember in root.findall('./gml:featureMember', NS_MAP):
            for feature in list(featureMember):
                typename = wfs_clean_layer_name(feature.tag.removeprefix('{%s}' % NS_MAP['qgs'])) # noqa: UP031

                if typename not in permissions['permitted_layers']:
                    featureMember.remove(feature)
                    continue

                # get permitted attributes for layer
                permitted_attributes = permissions['permitted_layers'][typename]['attributes']
                for attr in feature:
                    if attr.tag == "{%s}boundedBy" % NS_MAP['gml']: # noqa: UP031
                        continue
                    attr_name = wfs_clean_attribute_name(attr.tag.removeprefix('{%s}' % NS_MAP['qgs'])) # noqa: UP031
                    # NOTE: keep geometry attribute
                    if attr_name != "geometry" and attr_name not in permitted_attributes:
                        # remove not permitted attribute
                        feature.remove(attr)

        # write XML to string
        return ElementTree.tostring(
            root, encoding='utf-8', method='xml', short_empty_elements=False
        )

    def __filter_getfeature_geojson(self, response, permissions):
        """Parse features GeoJSON and filter feature attributes by permission.

        :param requests.Response response: Response object
        :param obj permissions: OGC service permissions
        """
        # parse GeoJSON (preserve order)
        text = response.text
        # Strip control characters
        text = re.sub("[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)

        geo_json = json.loads(text)
        features = geo_json.get('features', [])

        for feature in list(features):
            # get type name from id
            typename = wfs_clean_layer_name('.'.join(feature.get('id', '').split('.')[:-1]))
            if typename not in permissions['permitted_layers']:
                features.remove(feature)
                continue

            # get permitted attributes for layer
            permitted_attributes = permissions['permitted_layers'][typename]['attributes']

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
