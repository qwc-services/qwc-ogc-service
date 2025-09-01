import os
import re
import requests
import unittest
import tempfile
import difflib

from contextlib import contextmanager
from copy import deepcopy
from flask import Response, json
from flask.testing import FlaskClient
from flask_jwt_extended import JWTManager, create_access_token
from urllib.parse import urlparse, parse_qs, unquote, urlencode
from xml.etree import ElementTree

import server
from wfs_handler import WfsHandler, wfs_clean_layer_name, wfs_clean_attribute_name
from wms_handler import WmsHandler

JWTManager(server.app)

xlinkns = 'http://www.w3.org/1999/xlink'

@contextmanager
def test_config(resources, permissions):
    with tempfile.TemporaryDirectory() as tmpdirpath:
        # Ensure tenant handler cache is empty
        server.tenant_handler.handler_cache = {}

        orig_config_path = os.environ.get('CONFIG_PATH', "")
        os.environ['CONFIG_PATH'] = tmpdirpath
        os.mkdir(os.path.join(tmpdirpath, "default"))
        qgis_server_url = os.getenv('QGIS_SERVER_URL', 'http://localhost:8001/ows/').rstrip('/')

        with open(os.path.join(tmpdirpath, "default", "permissions.json"), "w") as fh:
            permissions_data = {
                "$schema": "https://github.com/qwc-services/qwc-services-core/raw/master/schemas/qwc-services-permissions.json",
                "users": [{"name": "test", "groups": [], "roles": ["test"]}],
                "groups": [],
                "roles": [
                    {
                        "role": "test",
                        "permissions": permissions
                    }
                ]
            }
            json.dump(permissions_data, fh)

        with open(os.path.join(tmpdirpath, "default", "ogcConfig.json"), "w") as fh:
            resources_data = {
                "$schema": "https://github.com/qwc-services/qwc-ogc-service/raw/master/schemas/qwc-ogc-service.json",
                "service": "ogc",
                "config": {
                    "default_qgis_server_url": qgis_server_url
                },
                "resources": resources
            }
            json.dump(resources_data, fh)

        yield

        os.environ['CONFIG_PATH'] = orig_config_path


# Apply the same cleanup (=replace some special characters) to layer and
# attribute names as QGIS Server does in capability documents
# NOTE: the service resources/permissions also contain cleaned names
def wfs_clean_perm(permitted_layer_attributes):
    return dict([
        (wfs_clean_layer_name(kv[0]), {
            "attributes": list(map(wfs_clean_attribute_name, kv[1]["attributes"])),
            "creatable": kv[1].get("creatable", False),
            "updatable": kv[1].get("updatable", False),
            "deletable": kv[1].get("deletable", False)
        })
        for kv in permitted_layer_attributes.items()
    ])

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

class OgcTestCase(unittest.TestCase):
    """Test case for OGC server"""

    def setUp(self):
        server.app.testing = True
        self.app = FlaskClient(server.app, Response)

    def tearDown(self):
        pass

    def jwtHeader(self):
        with server.app.test_request_context():
            access_token = create_access_token('test')
        return {'Authorization': 'Bearer {}'.format(access_token)}

    def jwtHeader(self):
        with server.app.test_request_context():
            access_token = create_access_token('test')
        return {'Authorization': 'Bearer {}'.format(access_token)}

    def ogc_get(self, service, params):
        return self.app.get('/' + service + "?" + urlencode(params), headers=self.jwtHeader())

    def ogc_post(self, service, params, data=None):
        if data:
            headers = self.jwtHeader() | {"Content-Type": data["contentType"]}
            return self.app.post('/' + service + "?" + urlencode(params), data=data["body"], headers=headers)
        else:
            return self.app.post('/' + service, data=params, headers=self.jwtHeader())


    def qgs_get(self, service, params):
        qgis_server_url = os.getenv('QGIS_SERVER_URL', 'http://localhost:8001/ows/').rstrip('/')
        headers = {"X-Qgis-Service-Url": f"http://localhost/{service}"}
        return requests.get(qgis_server_url + "/" + service, params=params, headers=headers)

    def qgs_post(self, service, params, data):
        qgis_server_url = os.getenv('QGIS_SERVER_URL', 'http://localhost:8001/ows/').rstrip('/')
        headers = {"X-Qgis-Service-Url": f"http://localhost/{service}", "Content-Type": data["contentType"]}
        return requests.post(qgis_server_url + "/" + service, params=params, data=data["body"], headers=headers)

    ###########
    ### WMS ###
    ###########

    WMS_PERMISSIONS = {
        "wms_services": [
            {
                "name": "wms_test",
                "layers": [
                    {
                        "name": "wms_test",
                        "queryable": True,
                        "info_template": True
                    },
                    {
                        "name": "edit_demo",
                        "queryable": True,
                        "info_template": True
                    },
                    {
                        "name": "edit_points",
                        "queryable": True,
                        "info_template": True,
                        "attributes": [
                            "fid",
                            "id",
                            "point_name",
                            "point_description",
                            "geometry",
                            "maptip"
                        ]
                    },
                    {
                        "name": "edit_lines",
                        "queryable": True,
                        "info_template": True,
                        "attributes": [
                            "fid",
                            "id",
                            "line_name",
                            "line_description",
                            "geometry",
                            "maptip"
                        ]
                    },
                    {
                        "name": "europe",
                        "queryable": True,
                        "info_template": True,
                        "attributes": [
                            "fid",
                            "sovereignt",
                            "name",
                            "name_long",
                            "pop_est",
                            "gdp_md_est",
                            "pop_year",
                            "gdp_year",
                            "continent",
                            "subregion",
                            "geometry",
                            "maptip"
                        ]
                    },
                    {
                        "name": "osm_bg"
                    }
                ],
                "print_templates": ["A4 Landscape"]
            }
        ]
    }
    WMS_RESOURCES = {
        "wms_services": [
            {
                "name": "wms_test",
                "online_resources": {
                    "service": "/wms_test",
                    "feature_info": "/wms_test",
                    "legend": "/wms_test"
                },
                "root_layer": {
                    "name": "wms_test",
                    "title": "Test WMS",
                    "layers": [
                        {
                        "name": "edit_demo",
                        "title": "Edit Demo",
                        "layers": [
                            {
                            "name": "edit_points",
                            "title": "Edit Points",
                            "attributes": {
                                "fid": "fid",
                                "id": "id",
                                "point_name": "Point Name",
                                "point_description": "Point Description",
                                "geometry": "geometry",
                                "maptip": "maptip"
                            },
                            "queryable": True
                            },
                            {
                            "name": "edit_lines",
                            "title": "Edit Lines",
                            "attributes": {
                                "fid": "fid",
                                "id": "id",
                                "line_name": "Line Name",
                                "line_description": "Line Description",
                                "geometry": "geometry",
                                "maptip": "maptip"
                            },
                            "queryable": True
                            }
                        ]
                        },
                        {
                        "name": "europe",
                        "title": "Europe",
                        "attributes": {
                            "fid": "fid",
                            "sovereignt": "sovereignt",
                            "name": "name",
                            "name_long": "Long name",
                            "pop_est": "pop_est",
                            "gdp_md_est": "gdp_md_est",
                            "pop_year": "pop_year",
                            "gdp_year": "gdp_year",
                            "continent": "continent",
                            "subregion": "subregion",
                            "geometry": "geometry",
                            "maptip": "maptip"
                        },
                        "queryable": True
                    }
                ]
                },
                "print_templates": ["A4 Landscape"],
                "internal_print_layers": ["osm_bg"]
            }
        ]
    }

    def test_wms_badrequest(self):
        params = {
            'SERVICE': 'WMS',
            'VERSION': '1.3.0',
            'REQUEST': 'GetNonExisting'
        }
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertTrue('Request GETNONEXISTING is not supported' in ogc_response.text)

    def test_wms_capabilities(self):
        params = {
            'SERVICE': 'WMS',
            'VERSION': '1.3.0',
            'REQUEST': 'GetProjectSettings'
        }

        ### Test unfiltered capabilities ###
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            qgs_response = self.qgs_get('wms_test', params)
            ogc_response = self.ogc_get('wms_test', params)

        self.assertTrue('<Format>application/vnd.ogc.gml/3.1.1</Format>' in qgs_response.text)
        self.assertTrue('<Format>application/vnd.ogc.gml/3.1.1</Format>' not in ogc_response.text)
        self.assertTrue('REQUEST=GetLegendGraphic&amp;LAYER=edit_demo' in ogc_response.text, "GetLegendGraphic OnlineResource added for group Edit Demo")
        self.assertTrue('REQUEST=GetLegendGraphic&amp;LAYER=wms_test' in ogc_response.text, "GetLegendGraphic OnlineResource added for group root layer")
        self.assertTrue('edit_points' in ogc_response.text)
        self.assertTrue('Edit Points' in ogc_response.text)
        self.assertTrue('point_name' in ogc_response.text)
        self.assertTrue('Point Name' in ogc_response.text)
        self.assertTrue('A4 Landscape' in ogc_response.text)
        self.assertTrue('osm_bg' in qgs_response.text, "Original apabilities do not contain internal print layers")
        self.assertTrue('osm_bg' not in ogc_response.text, "Filtered capabilities do not contain internal print layers")


        ### Test online resources ###
        resources = deepcopy(self.WMS_RESOURCES)
        resources['wms_services'][0]['online_resources']['feature_info'] = '/api/v1/feature_info/wms_test'
        with test_config(resources, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params)
        doc = ElementTree.fromstring(ogc_response.text)
        ns = "{http://www.opengis.net/wms}"
        xlinkns = "{http://www.w3.org/1999/xlink}"
        service_onlineres = doc.find(f"./{ns}Service/{ns}OnlineResource")
        featureinfo_onlineres = doc.find(f".//{ns}GetFeatureInfo/{ns}DCPType/{ns}HTTP/{ns}Get/{ns}OnlineResource")
        self.assertEqual(service_onlineres.get(f'{xlinkns}href'), 'http://localhost/wms_test')
        self.assertEqual(featureinfo_onlineres.get(f'{xlinkns}href'), 'http://localhost/api/v1/feature_info/wms_test?')

        ### Test filtered capabilities (layer edit_points unpermitted) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'] = list(filter(lambda layer: layer['name'] != 'edit_points', permissions['wms_services'][0]['layers']))

        with test_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', params)

        self.assertTrue('edit_points' not in ogc_response.text)
        self.assertTrue('Edit Points' not in ogc_response.text)

        ### Test filtered attributes (attribute point_name unpermitted) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'][2]['attributes'] = list(filter(lambda attr: attr != "point_name", permissions['wms_services'][0]['layers'][2]['attributes']))

        with test_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', params)

        self.assertTrue('point_name' not in ogc_response.text)
        self.assertTrue('Point Name' not in ogc_response.text)

        ### Test filtered layouts (layout 'A4 Landscape' not permitted) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['print_templates'] = []

        with test_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', params)

        self.assertTrue('A4 Landscape' not in ogc_response.text)

        ### Test layer marked as not queryable (edit_points permissions with queryable = false) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        self.assertEqual(permissions['wms_services'][0]['layers'][2]['name'], 'edit_points')
        permissions['wms_services'][0]['layers'][2]['queryable'] = False

        with test_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', params)

        doc = ElementTree.fromstring(ogc_response.text)
        ns = "{http://www.opengis.net/wms}"
        xlinkns = "{http://www.w3.org/1999/xlink}"
        for layerEl in doc.findall(f".//{ns}Layer"):
            nameEl = layerEl.find(f'./{ns}Name')
            if nameEl is not None and nameEl.text == "edit_points":
                self.assertEqual(layerEl.get('queryable'), '0')
                break
        else:
            self.assertTrue(False, "Layer edit_points not found")

    def test_wms_getmap(self):
        params = {
            'SERVICE': 'WMS',
            'VERSION': '1.3.0',
            'REQUEST': 'GetMap',
            'FORMAT': 'image/png',
            'TRANSPARENT': 'true',
            'LAYERS': 'edit_points,europe',
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

        ### Test valid GET request ###
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertEqual(200, ogc_response.status_code, "Status code is not OK")
        self.assertEqual(ogc_response.headers['Content-Type'], 'image/png', "Response is not a valid PNG")

        ### Test valid POST request ###
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_post('wms_test', params)
        self.assertEqual(200, ogc_response.status_code, "Status code is not OK")
        self.assertEqual(ogc_response.headers['Content-Type'], 'image/png', "Response is not a valid PNG")

        ### Test request with non-existing layer ###
        params1 = deepcopy(params)
        params1['LAYERS'] = 'edit_points,nonexistent'
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue('Layer "nonexistent" does not exist or is not permitted' in ogc_response.text)

        ### Test request with non-permitted layer (edit_points not permitted) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'] = list(filter(lambda layer: layer['name'] != 'edit_points', permissions['wms_services'][0]['layers']))
        with test_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertTrue('Layer "edit_points" does not exist or is not permitted' in ogc_response.text)

        ### Test request with non-permitted print layer (print layer only permitted for GETMAP+FILENAME) ###
        params1 = deepcopy(params)
        params1['LAYERS'] = 'edit_points,osm_bg'
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue('Layer "osm_bg" does not exist or is not permitted' in ogc_response.text)

        ### Test map export request with print layer and FILENAME ###
        params1 = deepcopy(params)
        params1['LAYERS'] = 'edit_points,osm_bg'
        params1['FILENAME'] = 'export.png'
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertEqual(200, ogc_response.status_code, "Status code is not OK")
        self.assertEqual(ogc_response.headers['Content-Type'], 'image/png', "Response is not a valid PNG")

        ### Test facade layer ###
        resources = deepcopy(self.WMS_RESOURCES)
        self.assertEqual(resources['wms_services'][0]['root_layer']['layers'][0]['name'], 'edit_demo')
        resources['wms_services'][0]['root_layer']['layers'][0]['hide_sublayers'] = True
        self.assertEqual(resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]['name'], 'edit_points')
        resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]['opacity'] = 50
        with test_config(resources, self.WMS_PERMISSIONS):
            ogc_service = server.ogc_service_handler()
            ogc_permissions = ogc_service.service_permissions('test', 'wms_test', 'WMS')
        self.assertTrue('edit_demo' in ogc_permissions['restricted_group_layers'])
        self.assertTrue('edit_points' in ogc_permissions['restricted_group_layers']['edit_demo'])
        self.assertTrue('edit_lines' in ogc_permissions['restricted_group_layers']['edit_demo'])

        qgis_server_url = os.getenv('QGIS_SERVER_URL', 'http://localhost:8001/ows/').rstrip('/')
        handler = WmsHandler(server.app.logger, qgis_server_url)

        params1 = deepcopy(params)
        params1['LAYERS'] = 'edit_demo,europe'
        params1['OPACITIES'] = '127,255'
        handler.process_request('GETMAP', params1, ogc_permissions, None)
        self.assertEqual(params1['LAYERS'], 'edit_points,edit_lines,europe')
        self.assertEqual(params1['OPACITIES'], '64,127,255')
        self.assertEqual(params1['STYLES'], ',,')

    def test_wms_getfeatureinfo(self):
        params = {
            'SERVICE': 'WMS',
            'VERSION': '1.3.0',
            'REQUEST': 'GetFeatureInfo',
            'INFO_FORMAT': 'text/xml',
            'TRANSPARENT': 'true',
            'LAYERS': 'edit_points,europe',
            'QUERY_LAYERS': 'edit_points,europe',
            'STYLES': '',
            'SRS': 'EPSG:3857',
            'CRS': 'EPSG:3857',
            'WIDTH': '101',
            'HEIGHT': '101',
            'FEATURE_COUNT': 10,
            'BBOX': '626276.0416666667,5639505.208333335,1294348.9583333333,6307578.125000001',
            'X': 51,
            'Y': 51,
            'I': 51,
            'J': 51,
            'FI_LINE_TOLERANCE': 8,
            'FI_POINT_TOLERANCE': 16,
            'FI_POLYGON_TOLERANCE': 4
        }

        ### Test unrestricted query ###
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertTrue('GetFeatureInfoResponse' in ogc_response.text)
        self.assertTrue(
            ('<Layer title="Edit Points" name="edit_points">' in ogc_response.text) or
            ('<Layer name="edit_points" title="Edit Points">' in ogc_response.text)
        )
        self.assertTrue(
            ('<Attribute name="Point Name" value="point" />' in ogc_response.text) or
            ('<Attribute value="point" name="Point Name" />' in ogc_response.text)
        )
        self.assertTrue(
            ('<Layer title="Europe" name="europe">' in ogc_response.text) or
            ('<Layer name="europe" title="Europe">' in ogc_response.text)
        )

        ### Test text/plain query ###
        params1 = deepcopy(params)
        params1['INFO_FORMAT'] = 'text/plain'
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue("Layer 'Edit Points'" in ogc_response.text)
        self.assertTrue("Point Name = 'point'" in ogc_response.text)
        self.assertTrue("Layer 'Europe'" in ogc_response.text)

        ### Test text/html query ###
        params1 = deepcopy(params)
        params1['INFO_FORMAT'] = 'text/html'
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue('<div class="layer-title">Edit Points</div>' in ogc_response.text)
        self.assertTrue("<th>Point Name</th>" in ogc_response.text)
        self.assertTrue('<div class="layer-title">Europe</div>' in ogc_response.text)

        ### Test with query_layers not equal layers ###
        params1 = deepcopy(params)
        params1['QUERY_LAYERS'] = 'edit_lines,europe'
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue('LAYERS must be identical to QUERY_LAYERS for GETFEATUREINFO operation' in ogc_response.text)

        ### Test with unsupported/invalid info format ###
        params1 = deepcopy(params)
        params1['INFO_FORMAT'] = 'application/pdf'
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue("Feature info format 'application/pdf' is not supported" in ogc_response.text)

        ### Test query with edit_points marked as not queryable ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        self.assertEqual(permissions['wms_services'][0]['layers'][2]['name'], 'edit_points')
        permissions['wms_services'][0]['layers'][2]['queryable'] = False
        with test_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertTrue('GetFeatureInfoResponse' in ogc_response.text)
        self.assertTrue('name="edit_points"' not in ogc_response.text)
        self.assertTrue(
            ('<Layer title="Europe" name="europe">' in ogc_response.text) or
            ('<Layer name="europe" title="Europe">' in ogc_response.text)
        )

        ### Test query with edit_points not permitted ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'] = list(filter(lambda layer: layer['name'] != 'edit_points', permissions['wms_services'][0]['layers']))
        with test_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertTrue('Layer "edit_points" does not exist or is not permitted' in ogc_response.text)

        ### Test query with not permitted point_name attribute ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        self.assertEqual(permissions['wms_services'][0]['layers'][2]['name'], 'edit_points')
        permissions['wms_services'][0]['layers'][2]['attributes'] = [attr for attr in permissions['wms_services'][0]['layers'][2]['attributes'] if attr != 'point_name']
        with test_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertTrue('GetFeatureInfoResponse' in ogc_response.text)
        self.assertTrue(
            ('<Layer title="Edit Points" name="edit_points">' in ogc_response.text) or
            ('<Layer name="edit_points" title="Edit Points">' in ogc_response.text)
        )
        self.assertTrue('name="Point Name"' not in ogc_response.text)

        ### Test facade layer ###
        resources = deepcopy(self.WMS_RESOURCES)
        self.assertEqual(resources['wms_services'][0]['root_layer']['layers'][0]['name'], 'edit_demo')
        resources['wms_services'][0]['root_layer']['layers'][0]['hide_sublayers'] = True
        params1 = deepcopy(params)
        params1['LAYERS'] = 'edit_demo,europe'
        params1['QUERY_LAYERS'] = 'edit_demo,europe'
        with test_config(resources, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue(
            ('<Layer title="Edit Points" name="edit_points">' in ogc_response.text) or
            ('<Layer name="edit_points" title="Edit Points">' in ogc_response.text)
        )
        self.assertTrue(
            ('<Layer title="Edit Lines" name="edit_lines">' in ogc_response.text) or
            ('<Layer name="edit_lines" title="Edit Lines">' in ogc_response.text)
        )

    def test_wms_getlegendgraphic(self):
        params = {
            'SERVICE': 'WMS',
            'VERSION': '1.3.0',
            'REQUEST': 'GetLegendGraphic',
            'FORMAT': 'image/png',
            'LAYER': 'europe',
            'STYLES': '',
            'SRS': 'EPSG:3857',
            'CRS': 'EPSG:3857',
            'WIDTH': 200,
            'HEIGHT': 200
        }

        ### Test valid GET request ###
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertEqual(200, ogc_response.status_code, "Status code is not OK")
        self.assertEqual(ogc_response.headers['Content-Type'], 'image/png', "Response is not a valid PNG")

        ### Test request with non-existing layer ###
        params1 = deepcopy(params)
        params1['LAYER'] = 'edit_points,nonexistent'
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue('Layer "nonexistent" does not exist or is not permitted' in ogc_response.text)

    def test_wms_getprint(self):
        params = {
            'SERVICE': 'WMS',
            'VERSION': '1.3.0',
            'REQUEST': 'GetPrint',
            'TEMPLATE': 'A4 Landscape',
            'FORMAT': 'application/pdf',
            'map0%3Ascale': '12500000',
            'DPI': '300',
            'SRS': 'EPSG:3857',
            'LAYERS': 'edit_points,europe',
            'OPACITIES': '255,255',
            'STYLES': '',
            'map0:LAYERS': 'edit_points,europe',
            'map0:STYLES': '',
            'map0:rotation': '0.0',
            'map0:extent': '-375000,4812500,2375000,7187500'
        }
        ### Test valid request ###
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertEqual(200, ogc_response.status_code, "Status code is not OK")
        self.assertEqual(ogc_response.headers['Content-Type'], 'application/pdf', "Response is not a valid PDF")

        ### Test invalid request (non-existing layout) ###
        params1 = deepcopy(params)
        params1['TEMPLATE'] = 'A4 Portrait'
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue("Composer template 'A4 Portrait' not found or not permitted" in ogc_response.text)

        ### Test invalid request (restricted layout) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['print_templates'] = []
        with test_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertTrue("Composer template 'A4 Landscape' not found or not permitted" in ogc_response.text)

        ### Test request with non-existing layer in LAYERS - should succeed, as map0 LAYERS is honoured ###
        params1 = deepcopy(params)
        params1['LAYERS'] = 'edit_points,nonexistent'
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertEqual(200, ogc_response.status_code, "Status code is not OK")
        self.assertEqual(ogc_response.headers['Content-Type'], 'application/pdf', "Response is not a valid PDF")

        ### Test request with non-existing layer in map0:LAYERS - should fail ###
        params1 = deepcopy(params)
        params1['map0:LAYERS'] = 'edit_points,nonexistent'
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue('Layer "nonexistent" does not exist or is not permitted' in ogc_response.text)

    def test_wms_getstyle(self):
        params = {
            'SERVICE': 'WMS',
            'VERSION': '1.3.0',
            'REQUEST': 'GetStyle',
            'LAYERS': 'edit_points,europe'
        }
        ### Test valid request ###
        with test_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertTrue('<se:Name>edit_points</se:Name>' in ogc_response.text)

        ### Test filtered request (layer edit_points unpermitted) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'] = list(filter(lambda layer: layer['name'] != 'edit_points', permissions['wms_services'][0]['layers']))

        with test_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', params)

        self.assertTrue('<se:Name>edit_points</se:Name>' not in ogc_response.text)


    ###########
    ### WFS ###
    ###########
    WFS_PERMISSIONS = {
        "wfs_services": [
            {
                "name": "wfs_test",
                "layers": [
                    {
                        "name": wfs_clean_layer_name("ÖV: Linien"),
                        "attributes": list(map(wfs_clean_attribute_name, ["fid", "id", "nummer", "beschreibung"])),
                        "creatable": False,
                        "updatable": False,
                        "deletable": False
                    },
                    {
                        "name": wfs_clean_layer_name("ÖV: Haltestellen"),
                        "attributes": list(map(wfs_clean_attribute_name, ["fid", "id", "name", "eingeführt am", "eigentümer"])),
                        "creatable": False,
                        "updatable": False,
                        "deletable": False
                    }
                ]
            }
        ]
    }
    WFS_RESOURCES = {
        "wfs_services": [
            {
                "name": "wfs_test",
                "layers": [
                    {
                        "name": wfs_clean_layer_name("ÖV: Linien"),
                        "attributes": list(map(wfs_clean_attribute_name, ["fid", "id", "nummer", "beschreibung"]))
                    },
                    {
                        "name": wfs_clean_layer_name("ÖV: Haltestellen"),
                        "attributes": list(map(wfs_clean_attribute_name, ["fid", "id", "name", "eingeführt am", "eigentümer"]))
                    }
                ]
            }
        ]
    }

    def test_wfs_badrequest(self):
        params = {
            'SERVICE': 'WFS',
            'VERSION': '1.0.0',
            'REQUEST': 'GetNonExisting'
        }
        with test_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
            ogc_response = self.ogc_get('wfs_test', params)
        self.assertTrue('Request GETNONEXISTING is not supported' in ogc_response.text)

    def test_wfs_capabilities(self):
        for version, colon in [("1.0.0", ":"), ("1.1.0", "-")]:
            params = {'SERVICE': 'WFS', 'VERSION': version, 'REQUEST': 'GetCapabilities'}

            ### Check unfiltered GetCapabilities ###
            with test_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = xmldiff(qgs_response.text, ogc_response.text)
            self.assertEqual([], diff, "Unfiltered %s GetCapabilities contain no changes" % version)

            ### Check filtered GetCapabilities (missing layer) ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'), permissions['wfs_services'][0]['layers']))
            with test_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = xmldiff(qgs_response.text, ogc_response.text)
            self.assertTrue('ÖV%s_Haltestellen' % colon in qgs_response.text, 'Original %s GetCapabilities contains ÖV%s_Haltestellen' % (version, colon))
            self.assertTrue('ÖV: Haltestellen' in qgs_response.text, 'Original %s GetCapabilities contains ÖV: Haltestellen' % version)
            self.assertFalse('ÖV%s_Haltestellen' % colon in ogc_response.text, 'Original %s GetCapabilities contains ÖV%s_Haltestellen' % (version, colon))
            self.assertFalse('ÖV: Haltestellen' in ogc_response.text, 'Filtered %s GetCapabilities does not contain ÖV: Haltestellen' % version)

    def test_wfs_describefeaturetype(self):
        for version in ["1.0.0", "1.1.0"]:
            params = {'SERVICE': 'WFS', 'VERSION': version, 'REQUEST': 'DescribeFeatureType'}

            ### Check unfiltered DescribeFeatureType ###
            with test_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = xmldiff(qgs_response.text, ogc_response.text)
            self.assertEqual([], diff, "Unfiltered DescribeFeatureType contains no changes")

            ### Check filtered DescribeFeatureType (restricted attribute) ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['attributes'] = [
                attr for attr in permissions['wfs_services'][0]['layers'][1]['attributes'] if not attr == wfs_clean_attribute_name('eingeführt am')
            ]
            with test_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = xmldiff(qgs_response.text, ogc_response.text)
            self.assertTrue('eingeführt_am' in qgs_response.text, 'Original DescribeFeatureType contains eingeführt_am')
            self.assertFalse('eingeführt_am' in ogc_response.text, 'Filtered DescribeFeatureType does not contain eingeführt_am')
            self.assertEqual(diff, [{'op': 'remove', 'old': '<element name="eingeführt_am" nillable="true" type="date" />'}], "Filtered DescribeFeatureType omits the Attribute eingeführt_am")

            ### Check filtered DescribeFeatureType (restricted layer) ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'), permissions['wfs_services'][0]['layers']))
            with test_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = xmldiff(qgs_response.text, ogc_response.text)
            self.assertTrue('ÖV-_Haltestellen' in qgs_response.text, 'Original DescribeFeatureType contains ÖV-_Haltestellen')
            self.assertFalse('ÖV-_Haltestellen' in ogc_response.text, 'Filtered DescribeFeatureType does not contain ÖV-_Haltestellen')
            self.assertEqual(diff, [{'op': 'remove', 'old': '<element name="ÖV-_Haltestellen" substitutionGroup="gml:_Feature" type="qgs:ÖV-_HaltestellenType" />\n<complexType name="ÖV-_HaltestellenType">\n<complexContent>\n<extension base="gml:AbstractFeatureType">\n<sequence>\n<element maxOccurs="1" minOccurs="0" name="geometry" type="gml:PointPropertyType" />\n<element name="fid" type="long" />\n<element name="id" nillable="true" type="int" />\n<element alias="Name" name="name" nillable="true" type="string" />\n<element name="eingeführt_am" nillable="true" type="date" />\n<element alias="Eigentümer" name="eigentümer" nillable="true" type="string" />\n</sequence>\n</extension>\n</complexContent>\n</complexType>'}], "Filtered DescribeFeatureType omits the FeatureType for ÖV: Haltestellen")


            ### Check filtered DescribeFeatureType (missing layer in TYPENAME) ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'), permissions['wfs_services'][0]['layers']))
            params1 = deepcopy(params)
            params1['TYPENAME'] = wfs_clean_layer_name('ÖV-_Haltestellen')
            with test_config(self.WFS_RESOURCES, permissions):
                ogc_response = self.ogc_get('wfs_test', params1)
            self.assertTrue("TypeName 'ÖV-_Haltestellen' could not be found or is not permitted" in ogc_response.text, 'Filtered DescribeFeatureType with non-permitted layer in TYPENAME returns a ServiceExceptionReport')

    def test_wfs_getfeature_gml(self):
        for version, outputformat in [("1.0.0", "GML2"), ("1.1.0", "GML2"), ("1.1.0", "GML3")]:
            params = {'SERVICE': 'WFS', 'VERSION': version, 'REQUEST': 'GetFeature', 'OUTPUTFORMAT': outputformat, 'TYPENAME': 'ÖV-_Haltestellen,ÖV-_Linien'}

            ### Check unfiltered GetFeature ###
            with test_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = xmldiff(qgs_response.text, ogc_response.text)
            self.assertEqual([], diff, "Unfiltered %s %s GetFeature contains no changes" % (version, outputformat))

            ### Check filtered GetFeature (missing attribute) ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['attributes'] = [
                attr for attr in permissions['wfs_services'][0]['layers'][1]['attributes'] if not attr == wfs_clean_attribute_name('eingeführt am')
            ]
            with test_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            self.assertTrue('eingeführt_am' in qgs_response.text, 'Original %s %s GetFeature contains eingeführt_am' % (version, outputformat))
            self.assertFalse('eingeführt_am' in ogc_response.text, 'Filtered %s %s GetFeature does not contain eingeführt_am' % (version, outputformat))

            ### Check filtered GetFeature (restricted layer) ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'), permissions['wfs_services'][0]['layers']))
            with test_config(self.WFS_RESOURCES, permissions):
                ogc_response = self.ogc_get('wfs_test', params)
            self.assertTrue("TypeName 'ÖV-_Haltestellen' could not be found or is not permitted" in ogc_response.text, 'Filtered GetFeature with non-permitted layer in TYPENAME returns a ServiceExceptionReport')

    def test_wfs_getfeature_geojson(self):
        for version in ["1.0.0", "1.1.0"]:
            params = {'SERVICE': 'WFS', 'VERSION': version, 'REQUEST': 'GetFeature', 'TYPENAME': 'ÖV-_Haltestellen,ÖV-_Linien', 'OUTPUTFORMAT': 'GEOJSON'}

            ### Check unfiltered GetFeature ###
            with test_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = jsondiff(qgs_response.text, ogc_response.text)
            self.assertEqual([], diff, "Unfiltered %s GetFeature contains no changes" % version)

            # Check filtered GetFeature (missing attribute)
            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['attributes'] = [
                attr for attr in permissions['wfs_services'][0]['layers'][1]['attributes'] if not attr == wfs_clean_attribute_name('eingeführt am')
            ]
            with test_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            self.assertTrue('eingeführt am' in qgs_response.text, 'Original %s GetFeature contains eingeführt am' % version)
            self.assertFalse('eingeführt am' in ogc_response.text, 'Filtered %s GetFeature does not contain eingeführt am' % version)

            ### Check filtered GetFeature (restricted layer) ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'), permissions['wfs_services'][0]['layers']))
            with test_config(self.WFS_RESOURCES, permissions):
                ogc_response = self.ogc_get('wfs_test', params)
            self.assertTrue("TypeName 'ÖV-_Haltestellen' could not be found or is not permitted" in ogc_response.text, 'Filtered GetFeature with non-permitted layer in TYPENAME returns a ServiceExceptionReport')

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
            params = {"SERVICE": "WFS", "VERSION": version, "REQUEST": "TRANSACTION"}
            insert_data = {"body": insert_payload, "contentType": "text/xml"}

            ### Check unpermitted insert ###
            with test_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                ogc_response = self.ogc_post('wfs_test', params, insert_data)
            self.assertTrue("No create permissions on typename 'ÖV-_Haltestellen'" in ogc_response.text, "Insert fails due to no create permissions")


            ### Check unpermitted delete ###
            delete_data = {"body": delete_payload.replace("@FID@", "0"), "contentType": "text/xml"}
            with test_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                ogc_response = self.ogc_post('wfs_test', params, delete_data)
            self.assertTrue("No delete permissions on typename 'ÖV-_Haltestellen'" in ogc_response.text, "Insert fails due to no delete permissions")


            ### Check unfiltered insert and delete ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['creatable'] = True
            permissions['wfs_services'][0]['layers'][1]['deletable'] = True
            with test_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_post('wfs_test', params, insert_data)
                ogc_response = self.ogc_post('wfs_test', params, insert_data)
            diff = xmldiff(qgs_response.text, ogc_response.text)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in ogc_response.text, "SUCCESS status with %s insert document" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalInserted>1</totalInserted>" in ogc_response.text, "One feature inserted with %s insert document" % version)
            self.assertTrue(len(diff) == 1 and diff[0]["op"] == "replace" and diff[0]["old"].startswith("<ogc:FeatureId"), "%s insert transaction result unchanged up to the feature id" % version)
            ins_fid_qgs = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', qgs_response.text).group(1)
            ins_fid_ogc = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', ogc_response.text).group(1)

            delete_payload_qgs = delete_payload.replace("@FID@", ins_fid_qgs)
            delete_payload_ogc = delete_payload.replace("@FID@", ins_fid_ogc)
            delete_data_qgs = {"body": delete_payload_qgs, "contentType": "text/xml"}
            delete_data_ogc = {"body": delete_payload_ogc, "contentType": "text/xml"}
            with test_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_post('wfs_test', params, delete_data_qgs)
                ogc_response = self.ogc_post('wfs_test', params, delete_data_ogc)
            diff = xmldiff(qgs_response.text, ogc_response.text)
            self.assertEqual([], diff, "Unfiltered %s delete contains no changes" % version)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in ogc_response.text, "SUCCESS status with %s delete document" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalDeleted>1</totalDeleted>" in ogc_response.text, "One feature deleted with %s delete document" % version)


            ### Check filtered insert (missing attribute) ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['attributes'] = [
                attr for attr in permissions['wfs_services'][0]['layers'][1]['attributes'] if not attr == wfs_clean_attribute_name('eigentümer')
            ]
            permissions['wfs_services'][0]['layers'][1]['creatable'] = True
            permissions['wfs_services'][0]['layers'][1]['deletable'] = True
            # Check that transaction body is filtered correctly
            with test_config(self.WFS_RESOURCES, permissions):
                ogc_service = server.ogc_service_handler()
                ogc_permissions = ogc_service.service_permissions('test', 'wfs_test', 'WFS')
            req_data = {'body': insert_payload}
            error = WfsHandler(server.app.logger).process_request('TRANSACTION', params, ogc_permissions, req_data)
            self.assertEqual(error, None)
            diff = xmldiff(insert_payload, req_data['body'])
            self.assertTrue(len(diff) == 1 and diff[0]["op"] == "remove" and "qgs:eigentümer" in diff[0]["old"], "Filtered %s insert transaction document does not contain attribute eigentümer" % version)

            # Do insert
            with test_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_post('wfs_test', params, insert_data)
                ogc_response = self.ogc_post('wfs_test', params, insert_data)
            diff = xmldiff(qgs_response.text, ogc_response.text)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in qgs_response.text, "SUCCESS status with %s insert document directly to qgs-server" % version)
                self.assertTrue("<SUCCESS/>" in ogc_response.text, "SUCCESS status with %s insert document via ogc-service" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalInserted>1</totalInserted>" in qgs_response.text, "One feature inserted with %s insert document directly to qgs-server" % version)
                self.assertTrue("<totalInserted>1</totalInserted>" in ogc_response.text, "One feature inserted with %s insert document via ogc-service" % version)
            self.assertTrue(len(diff) == 1 and diff[0]["op"] == "replace" and diff[0]["old"].startswith("<ogc:FeatureId"), "%s insert transaction result unchanged up to the feature id" % version)
            ins_fid_qgs = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', qgs_response.text).group(1)
            ins_fid_ogc = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', ogc_response.text).group(1)

            # Delete inserted features again
            delete_payload_qgs = delete_payload.replace("@FID@", ins_fid_qgs)
            delete_payload_ogc = delete_payload.replace("@FID@", ins_fid_ogc)
            delete_data_qgs = {"body": delete_payload_qgs, "contentType": "text/xml"}
            delete_data_ogc = {"body": delete_payload_ogc, "contentType": "text/xml"}
            with test_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_post('wfs_test', params, delete_data_qgs)
                ogc_response = self.ogc_post('wfs_test', params, delete_data_ogc)


            ### Check filtered insert and delete (missing layer) ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'), permissions['wfs_services'][0]['layers']))

            # Check that transaction body is filtered correctly
            with test_config(self.WFS_RESOURCES, permissions):
                ogc_service = server.ogc_service_handler()
                ogc_permissions = ogc_service.service_permissions('test', 'wfs_test', 'WFS')
            req_data = {'body': insert_payload}
            error = WfsHandler(server.app.logger).process_request('TRANSACTION', params, ogc_permissions, req_data)
            self.assertEqual(error, None)
            self.assertTrue("<qgs:ÖV-_Haltestellen>".encode('utf-8') not in req_data['body'], "Filtered %s insert transaction document does not contain typename ÖV-_Haltestellen" % version)

            # Do insert
            with test_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_post('wfs_test', params, insert_data)
                ogc_response = self.ogc_post('wfs_test', params, insert_data)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in qgs_response.text, "SUCCESS status with %s insert document directly to qgs-server" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalInserted>1</totalInserted>" in qgs_response.text, "One feature inserted with %s insert document directly to qgs-server" % version)
            self.assertTrue("The server encountered an internal error or misconfiguration and was unable to complete your request" in ogc_response.text, "Filtered %s insert document returns error via ogc-service" % version)
            ins_fid_qgs = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', qgs_response.text).group(1)

            # Check filtered delete (missing layer)
            delete_payload_qgs = delete_payload.replace("@FID@", ins_fid_qgs)
            delete_data_qgs = {"body": delete_payload_qgs, "contentType": "text/xml"}

            req_data = {'body': delete_payload_qgs}
            WfsHandler(server.app.logger).process_request('TRANSACTION', params, ogc_permissions, req_data)
            self.assertTrue("<wfs:Delete typeName=\"ÖV-_Haltestellen\">".encode('utf-8') not in req_data['body'], "Filtered %s delete transaction document does not contain typename ÖV-_Haltestellen" % version)
            self.assertTrue('<ogc:FeatureId fid="ÖV-_Haltestellen.'.encode('utf-8') not in req_data['body'], "Filtered %s delete transaction document does not contain typename ÖV-_Haltestellen" % version)

            with test_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_post('wfs_test', params, delete_data_qgs)
                ogc_response = self.ogc_post('wfs_test', params, delete_data_qgs)

            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in qgs_response.text, "SUCCESS status with %s delete document" % version)
                self.assertTrue("The server encountered an internal error" in ogc_response.text, "SUCCESS status with %s delete document" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalDeleted>1</totalDeleted>" in qgs_response.text, "One feature deleted with %s delete document directly to qgs-server" % version)
                self.assertTrue("The server encountered an internal error" in ogc_response.text, "Zero features deleted with filtered %s delete document via ogc-service" % version)

            ### Test DELETE via QUERY ###
            # delete_params = {"VERSION": version, "REQUEST": "TRANSACTION", "OPERATION": "DELETE", "FEATUREID": "ÖV-_Haltestellen." + ins_fid_qgs}
            # qgs_text, ogc_text = self.__wfs_request("wfs_test", delete_params, permitted_layer_attributes)


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
            params = {"SERVICE": "WFS", "VERSION": version, "REQUEST": "TRANSACTION"}
            update_data = {"body": update_payload, "contentType": "text/xml"}

            ### Check unpermitted update ###
            with test_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                ogc_response = self.ogc_post('wfs_test', params, update_data)
            self.assertTrue("No update permissions on typename 'ÖV-_Haltestellen'" in ogc_response.text, "Insert fails due to no create permissions")


            ### Check unfiltered update ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['updatable'] = True
            with test_config(self.WFS_RESOURCES, permissions):
                ogc_response = self.ogc_post('wfs_test', params, update_data)
                qgs_response = self.qgs_post('wfs_test', params, update_data)
            diff = xmldiff(qgs_response.text, ogc_response.text)
            self.assertEqual([], diff, "Unfiltered %s update contains no changes" % version)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in ogc_response.text, "SUCCESS status with %s update document" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalUpdated>1</totalUpdated>" in ogc_response.text, "One feature updated with %s update document" % version)


            ### Check filtered update (missing attribute) ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['attributes'] = [
                attr for attr in permissions['wfs_services'][0]['layers'][1]['attributes'] if not attr == wfs_clean_attribute_name('eigentümer')
            ]
            permissions['wfs_services'][0]['layers'][1]['updatable'] = True

            # Check that transaction body is filtered correctly
            with test_config(self.WFS_RESOURCES, permissions):
                ogc_service = server.ogc_service_handler()
                ogc_permissions = ogc_service.service_permissions('test', 'wfs_test', 'WFS')
            req_data = {'body': update_payload}
            error = WfsHandler(server.app.logger).process_request('TRANSACTION', params, ogc_permissions, req_data)
            self.assertEqual(error, None)
            diff = xmldiff(update_payload, req_data["body"])
            self.assertTrue(len(diff) == 1 and diff[0]["op"] == "remove" and "<wfs:Name>eigentümer</wfs:Name>" in diff[0]["old"], "Filtered %s update transaction document does not contain attribute eigentümer" % version)

            with test_config(self.WFS_RESOURCES, permissions):
                ogc_response = self.ogc_post('wfs_test', params, update_data)
                qgs_response = self.qgs_post('wfs_test', params, update_data)
            diff = xmldiff(qgs_response.text, ogc_response.text)
            self.assertEqual(diff, [], "%s update transaction result unchanged" % version)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in qgs_response.text, "SUCCESS status with %s update document directly to qgs-server" % version)
                self.assertTrue("<SUCCESS/>" in qgs_response.text, "SUCCESS status with %s update document via ogc-service" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalUpdated>1</totalUpdated>" in qgs_response.text, "One feature updated with %s update document directly to qgs-server" % version)
                self.assertTrue("<totalUpdated>1</totalUpdated>" in qgs_response.text, "One feature updated with %s update document via ogc-service" % version)


            ### Check filtered insert (missing layer) ###
            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'), permissions['wfs_services'][0]['layers']))

            # Check that transaction body is filtered correctly
            with test_config(self.WFS_RESOURCES, permissions):
                ogc_service = server.ogc_service_handler()
                ogc_permissions = ogc_service.service_permissions('test', 'wfs_test', 'WFS')
            req_data = {'body': update_payload}
            error = WfsHandler(server.app.logger).process_request('TRANSACTION', params, ogc_permissions, req_data)
            self.assertEqual(error, None)
            self.assertTrue('<wfs:Update typeName="ÖV-_Haltestellen">'.encode('utf-8') not in req_data['body'], "Filtered %s update transaction document does not contain typename ÖV-_Haltestellen" % version)

            with test_config(self.WFS_RESOURCES, permissions):
                ogc_response = self.ogc_post('wfs_test', params, update_data)
                qgs_response = self.qgs_post('wfs_test', params, update_data)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in qgs_response.text, "SUCCESS status with %s update document directly to qgs-server" % version)
            elif version == "1.1.0":
                self.assertTrue("<totalUpdated>1</totalUpdated>" in qgs_response.text, "One feature updated with %s update document directly to qgs-server" % version)
            self.assertTrue("The server encountered an internal error or misconfiguration and was unable to complete your request" in ogc_response.text, "Filtered %s update document returns error via ogc-service" % version)
