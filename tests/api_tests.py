import os
import re
import requests
import unittest
import tempfile
import difflib

from flask import Response, json
from flask.testing import FlaskClient
from flask_jwt_extended import JWTManager, create_access_token
from wfs_response_filters import wfs_transaction
from urllib.parse import urlparse, parse_qs, unquote, urlencode
from xml.etree import ElementTree

import server

JWTManager(server.app)


def xmldiff(xml1, xml2):
    def sorted_attrs(elem):
        # Sort attributes and recursively apply to children
        elem.attrib = dict(sorted(elem.attrib.items()))
        for child in elem:
            sorted_attrs(child)
        return elem

    xml1 = ElementTree.tostring(sorted_attrs(ElementTree.fromstring(xml1)), encoding='utf-8', method='xml').decode()
    xml2 = ElementTree.tostring(sorted_attrs(ElementTree.fromstring(xml2)), encoding='utf-8', method='xml').decode()
    lines1 = list(map(lambda line: line.strip(), xml1.splitlines()))
    lines2 = list(map(lambda line: line.strip(), xml2.splitlines()))
    matcher = difflib.SequenceMatcher(None, lines1, lines2)
    result = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'replace':
            old = "\n".join(lines1[i1:i2])
            new = "\n".join(lines2[j1:j2])
            result.append({"op": "replace", "old": old, "new": new})
        elif tag == 'delete':
            result.append({"op": "remove", "old": "\n".join(lines1[i1:i2])})
        elif tag == 'insert':
            result.append({"op": "add", "new": "\n".join(lines1[j1:j2])})
    return result

def jsondiff(json1, json2):
    json1 = json.dumps(json.loads(json1), indent=2, sort_keys=True, ensure_ascii=False)
    json2 = json.dumps(json.loads(json2), indent=2, sort_keys=True, ensure_ascii=False)
    lines1 = list(map(lambda line: line.strip(), json1.splitlines()))
    lines2 = list(map(lambda line: line.strip(), json2.splitlines()))
    matcher = difflib.SequenceMatcher(None, lines1, lines2)
    result = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'replace':
            old = "\n".join(lines1[i1:i2])
            new = "\n".join(lines2[j1:j2])
            result.append({"op": "replace", "old": old, "new": new})
        elif tag == 'delete':
            result.append({"op": "remove", "old": "\n".join(lines1[i1:i2])})
        elif tag == 'insert':
            result.append({"op": "add", "new": "\n".join(lines1[j1:j2])})
    return result

class ApiTestCase(unittest.TestCase):
    """Test case for server API"""

    def setUp(self):
        server.app.testing = True
        self.app = FlaskClient(server.app, Response)

    def tearDown(self):
        pass

    def jwtHeader(self):
        with server.app.test_request_context():
            access_token = create_access_token('test')
        return {'Authorization': 'Bearer {}'.format(access_token)}

    # submit query
    def test_wms_get(self):
        params = {
            'SERVICE': 'WMS',
            'VERSION': '1.3.0',
            'REQUEST': 'GetMap',
            'FORMAT': 'image/png',
            'TRANSPARENT': 'true',
            'LAYERS': 'edit_points',
            'STYLES': '',
            'SRS': 'EPSG:3857',
            'CRS': 'EPSG:3857',
            'TILED': 'false',
            'DPI': '96',
            'OPACITIES': '255,255',
            'WIDTH': '101',
            'HEIGHT': '101',
            'BBOX': '671639,5694018,1244689,6267068',
        }
        response = self.app.get('/qwc_demo?' + urlencode(params), headers=self.jwtHeader())
        self.assertEqual(200, response.status_code, "Status code is not OK")
        self.assertTrue(isinstance(response.data, bytes), "Response is not a valid PNG")

    def test_wms_post(self):
        params = {
            'SERVICE': 'WMS',
            'VERSION': '1.3.0',
            'REQUEST': 'GetMap',
            'FORMAT': 'image/png',
            'TRANSPARENT': 'true',
            'LAYERS': 'edit_points',
            'STYLES': '',
            'SRS': 'EPSG:3857',
            'CRS': 'EPSG:3857',
            'TILED': 'false',
            'DPI': '96',
            'OPACITIES': '255,255',
            'WIDTH': '101',
            'HEIGHT': '101',
            'BBOX': '671639,5694018,1244689,6267068',
        }
        response = self.app.post('/qwc_demo', data=params, headers=self.jwtHeader())
        self.assertEqual(200, response.status_code, "Status code is not OK")
        self.assertTrue(isinstance(response.data, bytes), "Response is not a valid PNG")


    # WFS
    WFS_TEST_LAYER_ATTRIBUTES = {
        "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"],
        "ÖV: Haltestellen": ["fid", "id", "name", "eingeführt am", "eigentümer"]
    }

    def __wfs_request(self, service, params, all_layer_attributes, permitted_layer_attributes, data=None, data2=None):
        with tempfile.TemporaryDirectory() as tmpdirpath:
            orig_config_path = os.environ.get('CONFIG_PATH', "")
            os.environ['CONFIG_PATH'] = tmpdirpath
            os.mkdir(os.path.join(tmpdirpath, "default"))
            qgis_server_url = os.getenv('QGIS_SERVER_URL', 'http://localhost:8001/ows/').rstrip('/')

            with open(os.path.join(tmpdirpath, "default", "permissions.json"), "w") as fh:
                json.dump({
                    "$schema": "https://github.com/qwc-services/qwc-services-core/raw/master/schemas/qwc-services-permissions.json",
                    "users": [{"name": "test", "groups": [], "roles": ["test"]}],
                    "groups": [],
                    "roles": [
                        {
                            "role": "test",
                            "permissions": {
                                "wfs_services": [
                                    {
                                        "name": service,
                                        "layers": list(map(lambda kv: {
                                            "name": kv[0],
                                            "attributes": kv[1]
                                        }, permitted_layer_attributes.items()))
                                    }
                                ]
                            }
                        }
                    ]
                }, fh)

            with open(os.path.join(tmpdirpath, "default", "ogcConfig.json"), "w") as fh:
                json.dump({
                    "$schema": "https://github.com/qwc-services/qwc-ogc-service/raw/master/schemas/qwc-ogc-service.json",
                    "service": "ogc",
                    "config": {
                        "default_qgis_server_url": qgis_server_url
                    },
                    "resources": {
                        "wfs_services": [
                            {
                                "name": service,
                                "layers": list(map(lambda kv: {
                                    "name": kv[0],
                                    "attributes": kv[1]
                                }, all_layer_attributes.items()))
                            }
                        ]
                    }
                }, fh)
            req_params = {
                'SERVICE': 'WFS'
            } | params

            if data:
                headers = {"Content-Type": data["contentType"]}
                qgs_response = requests.post(qgis_server_url + "/" + service, params=req_params, data=data["body"], headers=headers)
                headers2 = {"Content-Type": data2["contentType"] if data2 else data["contentType"]}
                ogc_response = self.app.post('/' + service + "?" + urlencode(req_params), data=data2["body"] if data2 else data["body"], headers=self.jwtHeader() | headers2)
            else:
                qgs_response = requests.get(qgis_server_url + "/" + service, params=req_params)
                ogc_response = self.app.get('/' + service + "?" + urlencode(req_params), headers=self.jwtHeader())

            # Revert CONFIG_PATH change
            os.environ['CONFIG_PATH'] = orig_config_path

            # NOTE: Rewrite server url like ogc service does
            qgs_text = qgs_response.text.replace(qgis_server_url + "/" + service, "http://localhost/" + service)
            return qgs_text, ogc_response.text


    def test_wfs_capabilities(self):
        for version, colon in [("1.0.0", ":"), ("1.1.0", "-")]:
            params = {'VERSION': version, 'REQUEST': 'GetCapabilities'}

            # Check unfiltered GetCapabilities
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES)
            diff = xmldiff(qgs_text, ogc_text)
            self.assertEqual([], diff, "Unfiltered %s GetCapabilities contain no changes" % version)

            # Check filtered GetCapabilities (missing layer)
            permitted_layer_attributes = {
                "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"]
            }
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
            diff = xmldiff(qgs_text, ogc_text)
            self.assertTrue('ÖV%s_Haltestellen' % colon in qgs_text, 'Original %s GetCapabilities contains ÖV%s_Haltestellen' % (version, colon))
            self.assertTrue('ÖV: Haltestellen' in qgs_text, 'Original %s GetCapabilities contains ÖV: Haltestellen' % version)
            self.assertFalse('ÖV%s_Haltestellen' % colon in ogc_text, 'Original %s GetCapabilities contains ÖV%s_Haltestellen' % (version, colon))
            self.assertFalse('ÖV: Haltestellen' in ogc_text, 'Filtered %s GetCapabilities does not contain ÖV: Haltestellen' % version)

    def test_wfs_describefeaturetype(self):
        for version in ["1.0.0", "1.1.0"]:
            params = {'VERSION': version, 'REQUEST': 'DescribeFeatureType'}

            # Check unfiltered DescribeFeatureType
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES)
            diff = xmldiff(qgs_text, ogc_text)
            self.assertEqual([], diff, "Unfiltered DescribeFeatureType contains no changes")

            # Check filtered DescribeFeatureType (restricted attribute)
            permitted_layer_attributes = {
                "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"],
                "ÖV: Haltestellen": ["fid", "id", "name", "eigentümer"]
            }
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
            diff = xmldiff(qgs_text, ogc_text)
            self.assertTrue('eingeführt_am' in qgs_text, 'Original DescribeFeatureType contains eingeführt_am')
            self.assertFalse('eingeführt_am' in ogc_text, 'Filtered DescribeFeatureType does not contain eingeführt_am')
            self.assertEqual(diff, [{'op': 'remove', 'old': '<element name="eingeführt_am" nillable="true" type="date" />'}], "Filtered DescribeFeatureType omits the Attribute eingeführt_am")

            # Check filtered DescribeFeatureType (restricted layer)
            permitted_layer_attributes = {
                "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"]
            }
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
            diff = xmldiff(qgs_text, ogc_text)
            self.assertTrue('ÖV-_Haltestellen' in qgs_text, 'Original DescribeFeatureType contains ÖV-_Haltestellen')
            self.assertFalse('ÖV-_Haltestellen' in ogc_text, 'Filtered DescribeFeatureType does not contain ÖV-_Haltestellen')
            self.assertEqual(diff, [{'op': 'remove', 'old': '<element name="ÖV-_Haltestellen" substitutionGroup="gml:_Feature" type="qgs:ÖV-_HaltestellenType" />\n<complexType name="ÖV-_HaltestellenType">\n<complexContent>\n<extension base="gml:AbstractFeatureType">\n<sequence>\n<element maxOccurs="1" minOccurs="0" name="geometry" type="gml:PointPropertyType" />\n<element name="fid" type="long" />\n<element name="id" nillable="true" type="int" />\n<element alias="Name" name="name" nillable="true" type="string" />\n<element name="eingeführt_am" nillable="true" type="date" />\n<element alias="Eigentümer" name="eigentümer" nillable="true" type="string" />\n</sequence>\n</extension>\n</complexContent>\n</complexType>'}], "Filtered DescribeFeatureType omits the FeatureType for ÖV: Haltestellen")


            # Check filtered DescribeFeatureType (missing layer in TYPENAME)
            permitted_layer_attributes = {
                "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"]
            }
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params | {'TYPENAME': 'ÖV-_Haltestellen'}, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
            self.assertEqual(ogc_text, '<ServiceExceptionReport version="1.3.0">\n <ServiceException code="LayerNotDefined">No permitted or existing layers specified in TYPENAME</ServiceException>\n</ServiceExceptionReport>', 'Filtered DescribeFeatureType with non-permitted layer in TYPENAME returns a ServiceExceptionReport')

    def test_wfs_getfeature_gml(self):
        for version, outputformat in [("1.0.0", "GML2"), ("1.1.0", "GML2"), ("1.1.0", "GML3")]:
            params = {'VERSION': version, 'REQUEST': 'GetFeature', 'OUTPUTFORMAT': outputformat, 'TYPENAME': 'ÖV-_Haltestellen,ÖV-_Linien'}

            # Check unfiltered GetFeature
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES)
            diff = xmldiff(qgs_text, ogc_text)
            self.assertEqual([], diff, "Unfiltered %s %s GetFeature contains no changes" % (version, outputformat))

            # Check filtered GetFeature (missing attribute)
            permitted_layer_attributes = {
                "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"],
                "ÖV: Haltestellen": ["fid", "id", "name", "eigentümer"]
            }
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
            diff = xmldiff(qgs_text, ogc_text)
            self.assertTrue('eingeführt_am' in qgs_text, 'Original %s %s GetFeature contains eingeführt_am' % (version, outputformat))
            self.assertFalse('eingeführt_am' in ogc_text, 'Filtered %s %s GetFeature does not contain eingeführt_am' % (version, outputformat))
            self.assertEqual([{'op': 'remove', 'old': '<qgs:eingeführt_am>2024-09-12</qgs:eingeführt_am>'}, {'op': 'remove', 'old': '<qgs:eingeführt_am>2004-05-01</qgs:eingeführt_am>'}], diff, "Filtered GetFeature does not contain eingeführt_am")

            # Check filtered GetFeature (missing layer)
            permitted_layer_attributes = {
                "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"],
            }
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params | {'TYPENAME': 'ÖV-_Haltestellen'}, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
            self.assertEqual(ogc_text, '<ServiceExceptionReport version="1.3.0">\n <ServiceException code="LayerNotDefined">No permitted or existing layers specified in TYPENAME</ServiceException>\n</ServiceExceptionReport>', 'Filtered GetFeature with non-permitted layer in TYPENAME returns a ServiceExceptionReport')

    def test_wfs_getfeature_geojson(self):
        for version in ["1.0.0", "1.1.0"]:
            params = {'VERSION': version, 'REQUEST': 'GetFeature', 'TYPENAME': 'ÖV-_Haltestellen,ÖV-_Linien', 'OUTPUTFORMAT': 'GEOJSON'}

            # Check unfiltered GetFeature
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES)
            diff = jsondiff(qgs_text, ogc_text)
            self.assertEqual([], diff, "Unfiltered %s GetFeature contains no changes" % version)

            # Check filtered GetFeature (missing attribute)
            permitted_layer_attributes = {
                "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"],
                "ÖV: Haltestellen": ["fid", "id", "name", "eigentümer"]
            }
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
            diff = jsondiff(qgs_text, ogc_text)
            self.assertTrue('eingeführt am' in qgs_text, 'Original %s GetFeature contains eingeführt am' % version)
            self.assertFalse('eingeführt am' in ogc_text, 'Filtered %s GetFeature does not contain eingeführt am' % version)
            self.assertEqual([{'op': 'remove', 'old': '"eingeführt am": "2024-09-12",'}, {'op': 'remove', 'old': '"eingeführt am": "2004-05-01",'}], diff, "Filtered GetFeature does not contain eingeführt_am")

            # Check filtered GetFeature (missing layer)
            permitted_layer_attributes = {
                "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"],
            }
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params | {'TYPENAME': 'ÖV-_Haltestellen'}, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
            self.assertEqual(ogc_text, '<ServiceExceptionReport version="1.3.0">\n <ServiceException code="LayerNotDefined">No permitted or existing layers specified in TYPENAME</ServiceException>\n</ServiceExceptionReport>', 'Filtered %s GetFeature with non-permitted layer in TYPENAME returns a ServiceExceptionReport' % version)

    def test_wfs_transaction_insert_delete(self):
        for version in ["1.0.0", "1.1.0"]:
            insert_payload = """<?xml version="1.0" encoding="UTF-8"?>
                <wfs:Transaction service="WFS" version="%s" xmlns:wfs="http://www.opengis.net/wfs" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:ogc="http://www.opengis.net/ogc" xmlns="http://www.opengis.net/wfs" updateSequence="0" xmlns:xlink="http://www.w3.org/1999/xlink" xsi:schemaLocation="http://www.opengis.net/wfs http://schemas.opengis.net/wfs/1.0.0/WFS-capabilities.xsd" xmlns:gml="http://www.opengis.net/gml"  xmlns:ows="http://www.opengis.net/ows" xmlns:qgs="http://www.qgis.org/gml">
                    <wfs:Insert idgen="GenerateNew">
                        <qgs:ÖV-_Haltestellen>
                            <qgs:geometry>
                                <gml:Point srsDimension="2" srsName="http://www.opengis.net/def/crs/EPSG/0/2056">
                                    <gml:coordinates decimal="." cs="," ts=" ">1903072,-8658180</gml:coordinates>
                                </gml:Point>
                            </qgs:geometry>
                            <qgs:name>TEST</qgs:name>
                            <qgs:eigentümer>TEST</qgs:eigentümer>
                        </qgs:ÖV-_Haltestellen>
                    </wfs:Insert>
                </wfs:Transaction>
            """ % version
            delete_payload = """<?xml version="1.0" encoding="UTF-8"?>
                <wfs:Transaction service="WFS" version="%s" xmlns:wfs="http://www.opengis.net/wfs" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:ogc="http://www.opengis.net/ogc" xmlns="http://www.opengis.net/wfs" updateSequence="0" xmlns:xlink="http://www.w3.org/1999/xlink" xsi:schemaLocation="http://www.opengis.net/wfs http://schemas.opengis.net/wfs/1.0.0/WFS-capabilities.xsd" xmlns:gml="http://www.opengis.net/gml"  xmlns:ows="http://www.opengis.net/ows">
                    <wfs:Delete typeName="ÖV-_Haltestellen">
                        <ogc:Filter>
                            <ogc:FeatureId fid="@FID@"/>
                        </ogc:Filter>
                    </wfs:Delete>
                </wfs:Transaction>
            """ % version
            params = {"VERSION": version, "REQUEST": "TRANSACTION"}
            insert_data = {"body": insert_payload, "contentType": "text/xml"}

            # Check unfiltered insert
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES, insert_data)
            diff = xmldiff(qgs_text, ogc_text)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in ogc_text, "SUCCESS status with %s insert document" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalInserted>1</totalInserted>" in ogc_text, "One feature inserted with %s insert document" % version)
            self.assertTrue(len(diff) == 1 and diff[0]["op"] == "replace" and diff[0]["old"].startswith("<ogc:FeatureId"), "%s insert transaction result unchanged up to the feature id" % version)
            ins_fid_0 = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', qgs_text).group(1)
            ins_fid_1 = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', ogc_text).group(1)

            # Check unfiltered delete
            delete_payload_0 = delete_payload.replace("@FID@", ins_fid_0)
            delete_payload_1 = delete_payload.replace("@FID@", ins_fid_1)
            delete_data_0 = {"body": delete_payload_0, "contentType": "text/xml"}
            delete_data_1 = {"body": delete_payload_1, "contentType": "text/xml"}
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES, delete_data_0, delete_data_1)
            diff = xmldiff(qgs_text, ogc_text)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in ogc_text, "SUCCESS status with %s delete document" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalDeleted>1</totalDeleted>" in ogc_text, "One feature deleted with %s delete document" % version)

            # Check filtered insert (missing attribute)
            permitted_layer_attributes = {
                "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"],
                "ÖV: Haltestellen": ["fid", "id", "name", "eingeführt am"]
            }

            filtered_insert_payload = wfs_transaction(insert_payload, {"layers": permitted_layer_attributes, "public_layers": permitted_layer_attributes})
            diff = xmldiff(insert_payload, filtered_insert_payload)
            self.assertTrue(len(diff) == 1 and diff[0]["op"] == "remove" and "qgs:eigentümer" in diff[0]["old"], "Filtered %s insert transaction document does not contain attribute eigentümer" % version)

            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes, insert_data)
            diff = xmldiff(qgs_text, ogc_text)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in qgs_text, "SUCCESS status with %s insert document directly to qgs-server" % version)
                self.assertTrue("<SUCCESS/>" in ogc_text, "SUCCESS status with %s insert document via ogc-service" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalInserted>1</totalInserted>" in qgs_text, "One feature inserted with %s insert document directly to qgs-server" % version)
                self.assertTrue("<totalInserted>1</totalInserted>" in ogc_text, "One feature inserted with %s insert document via ogc-service" % version)
            self.assertTrue(len(diff) == 1 and diff[0]["op"] == "replace" and diff[0]["old"].startswith("<ogc:FeatureId"), "%s insert transaction result unchanged up to the feature id" % version)
            ins_fid_0 = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', qgs_text).group(1)
            ins_fid_1 = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', ogc_text).group(1)

            # -> Delete inserted features again
            delete_payload_0 = delete_payload.replace("@FID@", ins_fid_0)
            delete_payload_1 = delete_payload.replace("@FID@", ins_fid_1)
            delete_data_0 = {"body": delete_payload_0, "contentType": "text/xml"}
            delete_data_1 = {"body": delete_payload_1, "contentType": "text/xml"}
            self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES, delete_data_0, delete_data_1)

            # Check filtered insert (missing layer)
            permitted_layer_attributes = {
                "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"]
            }

            filtered_insert_payload = wfs_transaction(insert_payload, {"layers": permitted_layer_attributes, "public_layers": permitted_layer_attributes})
            self.assertTrue("<qgs:ÖV-_Haltestellen>".encode('utf-8') not in filtered_insert_payload, "Filtered %s insert transaction document does not contain typename ÖV-_Haltestellen" % version)

            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes, insert_data)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in qgs_text, "SUCCESS status with %s insert document directly to qgs-server" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalInserted>1</totalInserted>" in qgs_text, "One feature inserted with %s insert document directly to qgs-server" % version)
            self.assertTrue("The server encountered an internal error or misconfiguration and was unable to complete your request" in ogc_text, "Filtered %s insert document returns error via ogc-service" % version)
            ins_fid_0 = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', qgs_text).group(1)

            # Check filtered delete (missing layer)
            delete_payload_0 = delete_payload.replace("@FID@", ins_fid_0)
            delete_data_0 = {"body": delete_payload_0, "contentType": "text/xml"}

            filtered_delete_payload = wfs_transaction(delete_payload_0, {"layers": permitted_layer_attributes, "public_layers": permitted_layer_attributes})
            self.assertTrue("<wfs:Delete typeName=\"ÖV-_Haltestellen\">".encode('utf-8') not in filtered_delete_payload, "Filtered %s delete transaction document does not contain typename ÖV-_Haltestellen" % version)
            self.assertTrue('<ogc:FeatureId fid="ÖV-_Haltestellen.'.encode('utf-8') not in filtered_delete_payload, "Filtered %s delete transaction document does not contain typename ÖV-_Haltestellen" % version)

            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES, delete_data_0)
            diff = xmldiff(qgs_text, ogc_text)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in qgs_text, "SUCCESS status with %s delete document" % version)
                self.assertTrue("<SUCCESS/>" in ogc_text, "SUCCESS status with %s delete document" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalDeleted>1</totalDeleted>" in qgs_text, "One feature deleted with %s delete document directly to qgs-server" % version)
                self.assertTrue("<totalDeleted>0</totalDeleted>" in ogc_text, "Zero features deleted with filtered %s delete document via ogc-service" % version)

            # Test DELETE via QUERY
            # FIXME: https://github.com/qgis/QGIS/pull/62245
            # delete_params = {"VERSION": version, "REQUEST": "TRANSACTION", "OPERATION": "DELETE", "FEATUREID": "ÖV-_Haltestellen." + ins_fid_0}
            # qgs_text, ogc_text = self.__wfs_request("wfs_test", delete_params, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)


    def test_wfs_transaction_update(self):
        for version in ["1.0.0", "1.1.0"]:
            update_payload = """<?xml version="1.0" encoding="UTF-8"?>
                <wfs:Transaction service="WFS" version="%s" xmlns:wfs="http://www.opengis.net/wfs" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:ogc="http://www.opengis.net/ogc" xmlns="http://www.opengis.net/wfs" updateSequence="0" xmlns:xlink="http://www.w3.org/1999/xlink" xsi:schemaLocation="http://www.opengis.net/wfs http://schemas.opengis.net/wfs/1.0.0/WFS-capabilities.xsd" xmlns:gml="http://www.opengis.net/gml"  xmlns:ows="http://www.opengis.net/ows">
                    <wfs:Update typeName="ÖV-_Haltestellen">
                        <wfs:Property>
                            <wfs:Name>name</wfs:Name>
                            <wfs:Value>TEST</wfs:Value>
                        </wfs:Property>
                        <wfs:Property>
                            <wfs:Name>eigentümer</wfs:Name>
                            <wfs:Value>TEST</wfs:Value>
                        </wfs:Property>
                        <ogc:Filter>
                            <ogc:FeatureId fid="1"/>
                        </ogc:Filter>
                    </wfs:Update>
                </wfs:Transaction>
            """ % version
            params = {"VERSION": version, "REQUEST": "TRANSACTION"}
            data = {"body": update_payload, "contentType": "text/xml"}

            # Check unfiltered update
            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES, data)
            diff = xmldiff(qgs_text, ogc_text)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in ogc_text, "SUCCESS status with %s update document" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalUpdated>1</totalUpdated>" in ogc_text, "One feature updated with %s update document" % version)
            self.assertEqual(diff, [], "%s update transaction result unchanged" % version)

            # Check filtered update (missing attribute)
            permitted_layer_attributes = {
                "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"],
                "ÖV: Haltestellen": ["fid", "id", "name", "eingeführt am"]
            }

            filtered_update_payload = wfs_transaction(update_payload, {"layers": permitted_layer_attributes, "public_layers": permitted_layer_attributes})
            diff = xmldiff(update_payload, filtered_update_payload)
            self.assertTrue(len(diff) == 1 and diff[0]["op"] == "remove" and "<wfs:Name>eigentümer</wfs:Name>" in diff[0]["old"], "Filtered %s update transaction document does not contain attribute eigentümer" % version)

            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes, data)
            diff = xmldiff(qgs_text, ogc_text)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in qgs_text, "SUCCESS status with %s update document directly to qgs-server" % version)
                self.assertTrue("<SUCCESS/>" in ogc_text, "SUCCESS status with %s update document via ogc-service" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalUpdated>1</totalUpdated>" in qgs_text, "One feature updated with %s update document directly to qgs-server" % version)
                self.assertTrue("<totalUpdated>1</totalUpdated>" in ogc_text, "One feature updated with %s update document via ogc-service" % version)
            self.assertEqual(diff, [], "%s update transaction result unchanged" % version)

            # Check filtered insert (missing layer)
            permitted_layer_attributes = {
                "ÖV: Linien": ["fid", "id", "nummer", "beschreibung"]
            }

            filtered_update_payload = wfs_transaction(update_payload, {"layers": permitted_layer_attributes, "public_layers": permitted_layer_attributes})
            self.assertTrue('<wfs:Update typeName="ÖV-_Haltestellen">'.encode('utf-8') not in filtered_update_payload, "Filtered %s update transaction document does not contain typename ÖV-_Haltestellen" % version)

            qgs_text, ogc_text = self.__wfs_request("wfs_test", params, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes, data)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in qgs_text, "SUCCESS status with %s update document directly to qgs-server" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalUpdated>1</totalUpdated>" in qgs_text, "One feature updated with %s update document directly to qgs-server" % version)
            self.assertTrue("The server encountered an internal error or misconfiguration and was unable to complete your request" in ogc_text, "Filtered %s update document returns error via ogc-service" % version)
