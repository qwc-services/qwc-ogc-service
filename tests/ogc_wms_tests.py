import html
import json
import os
from copy import deepcopy
from io import BytesIO
from urllib.parse import urlencode
from xml.etree import ElementTree

from PIL import Image
from qwc_services_core.permissions_reader import PermissionsReader

from ogc.ogc_service_handler import OgcRequest
from ogc.wms_handler import WmsHandler
from tests.ogc_tests import OgcTests


class OgcWmsTests(OgcTests):

    WMS_PERMISSIONS = {  # noqa: RUF012
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
    WMS_RESOURCES = {  # noqa: RUF012
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
                                "attributes": [
                                    {
                                        "name": "fid",
                                        "alias": "fid"
                                    },
                                    {
                                        "name": "id",
                                        "alias": "id"
                                    },
                                    {
                                        "name": "point_name",
                                        "alias": "Point Name"
                                    },
                                    {
                                        "name": "point_description",
                                        "alias": "Point Description"
                                    },
                                    {
                                        "name": "geometry",
                                        "alias": "geometry"
                                    },
                                    {
                                        "name": "maptip",
                                        "alias": "maptip"
                                    }
                                ],
                                "queryable": True,
                                "display_field": "Point Name"
                            },
                            {
                                "name": "edit_lines",
                                "title": "Edit Lines",
                                "attributes": [
                                    {
                                        "name": "fid",
                                        "alias": "fid"
                                    },
                                    {
                                        "name": "id",
                                        "alias": "id"
                                    },
                                    {
                                        "name": "line_name",
                                        "alias": "Line Name"
                                    },
                                    {
                                        "name": "line_description",
                                        "alias": "Line Description"
                                    },
                                    {
                                        "name": "geometry",
                                        "alias": "geometry"
                                    },
                                    {
                                        "name": "maptip",
                                        "alias": "maptip"
                                    }
                                ],
                                "queryable": True,
                                "display_field": "Line Name"
                            }
                        ]
                        },
                        {
                            "name": "europe",
                            "title": "Europe",
                            "attributes": [
                                {
                                    "name": "fid",
                                    "alias": "fid"
                                },
                                {
                                    "name": "sovereignt",
                                    "alias": "sovereignt"
                                },
                                {
                                    "name": "name",
                                    "alias": "name"
                                },
                                {
                                    "name": "name_long",
                                    "alias": "Long name"
                                },
                                {
                                    "name": "pop_est",
                                    "alias": "pop_est"
                                },
                                {
                                    "name": "gdp_md_est",
                                    "alias": "gdp_md_est"
                                },
                                {
                                    "name": "pop_year",
                                    "alias": "pop_year"
                                },
                                {
                                    "name": "gdp_year",
                                    "alias": "gdp_year"
                                },
                                {
                                    "name": "continent",
                                    "alias": "continent"
                                },
                                {
                                    "name": "subregion",
                                    "alias": "subregion"
                                },
                                {
                                    "name": "geometry",
                                    "alias": "geometry"
                                },
                                {
                                    "name": "maptip",
                                    "alias": "maptip"
                                }
                            ],
                            "queryable": True,
                            "display_field": "Long Name",
                            "feature_report": "countries_report"
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
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertTrue('Request GETNONEXISTING is not supported' in ogc_response.text)

    def test_wms_requireauth(self):
        params = {
            'SERVICE': 'WMS',
            'VERSION': '1.3.0',
            'REQUEST': 'GetProjectSettings',
            'REQUIREAUTH': '1'
        }
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.app.get('/wms_test?' + urlencode(params))
        self.assertTrue('Unauthorized' in ogc_response.text)
        self.assertEqual(401, ogc_response.status_code)

        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params)
        self.assertTrue('REQUIREAUTH=1' in ogc_response.text)

    ### WMS GetProjectSettings ###

    GETPROJECTSETTINGS_PARAMS = {  # noqa: RUF012
        'SERVICE': 'WMS',
        'VERSION': '1.3.0',
        'REQUEST': 'GetProjectSettings'
    }
    def test_wms_capabilities_unfiltered(self):
        ### Test unfiltered capabilities ###
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            qgs_response = self.qgs_get('wms_test', self.GETPROJECTSETTINGS_PARAMS)
            ogc_response = self.ogc_get('wms_test', self.GETPROJECTSETTINGS_PARAMS)

        self.assertTrue('<Format>application/vnd.ogc.gml/3.1.1</Format>' in qgs_response.text)
        self.assertTrue('<Format>application/vnd.ogc.gml/3.1.1</Format>' not in ogc_response.text)
        self.assertTrue(
            'REQUEST=GetLegendGraphic&amp;LAYER=edit_demo' in ogc_response.text,
            "GetLegendGraphic OnlineResource added for group Edit Demo"
        )
        self.assertTrue(
            'REQUEST=GetLegendGraphic&amp;LAYER=wms_test' in ogc_response.text,
            "GetLegendGraphic OnlineResource added for group root layer"
        )
        self.assertTrue('edit_points' in ogc_response.text)
        self.assertTrue('Edit Points' in ogc_response.text)
        self.assertTrue('point_name' in ogc_response.text)
        self.assertTrue('Point Name' in ogc_response.text)
        self.assertTrue('A4 Landscape' in ogc_response.text)
        self.assertTrue('osm_bg' in qgs_response.text, "Original apabilities do not contain internal print layers")
        self.assertTrue('osm_bg' not in ogc_response.text, "Filtered capabilities do not contain internal print layers")

    def test_wms_capabilities_onlineresources(self):
        ### Test online resources ###
        resources = deepcopy(self.WMS_RESOURCES)
        resources['wms_services'][0]['online_resources']['feature_info'] = '/api/v1/feature_info/wms_test'
        with self.use_config(resources, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', self.GETPROJECTSETTINGS_PARAMS)
        doc = ElementTree.fromstring(ogc_response.text)
        ns = "{http://www.opengis.net/wms}"
        xlinkns = "{http://www.w3.org/1999/xlink}"
        service_onlineres = doc.find(f"./{ns}Service/{ns}OnlineResource")
        featureinfo_onlineres = doc.find(f".//{ns}GetFeatureInfo/{ns}DCPType/{ns}HTTP/{ns}Get/{ns}OnlineResource")
        self.assertEqual(service_onlineres.get(f'{xlinkns}href'), 'http://localhost/wms_test?')
        self.assertEqual(featureinfo_onlineres.get(f'{xlinkns}href'), 'http://localhost/api/v1/feature_info/wms_test?')

    def test_wms_capabilities_filter_layer(self):
        ### Test filtered capabilities (layer edit_points unpermitted) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'] = list(
            filter(lambda layer: layer['name'] != 'edit_points', permissions['wms_services'][0]['layers']
        ))

        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', self.GETPROJECTSETTINGS_PARAMS)

        self.assertTrue('edit_points' not in ogc_response.text)
        self.assertTrue('Edit Points' not in ogc_response.text)

    def test_wms_capabilities_filter_attribute(self):
        ### Test filtered attributes (attribute point_name unpermitted) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'][2]['attributes'] = list(
            filter(lambda attr: attr != "point_name", permissions['wms_services'][0]['layers'][2]['attributes'])
        )

        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', self.GETPROJECTSETTINGS_PARAMS)

        self.assertTrue('point_name' not in ogc_response.text)
        self.assertTrue('Point Name' not in ogc_response.text)

    def test_wms_capabilities_filter_layout(self):
        ### Test filtered layouts (layout 'A4 Landscape' not permitted) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['print_templates'] = []

        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', self.GETPROJECTSETTINGS_PARAMS)

        self.assertTrue('A4 Landscape' not in ogc_response.text)

    def test_wms_capabilities_nonqueryable(self):
        ### Test layer marked as not queryable (edit_points permissions with queryable = false) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        self.assertEqual(permissions['wms_services'][0]['layers'][2]['name'], 'edit_points')
        permissions['wms_services'][0]['layers'][2]['queryable'] = False

        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', self.GETPROJECTSETTINGS_PARAMS)

        doc = ElementTree.fromstring(ogc_response.text)
        ns = "{http://www.opengis.net/wms}"
        for layerEl in doc.findall(f".//{ns}Layer"):
            nameEl = layerEl.find(f'./{ns}Name')
            if nameEl is not None and nameEl.text == "edit_points":
                self.assertEqual(layerEl.get('queryable'), '0')
                break
        else:
            self.assertTrue(False, "Layer edit_points not found")

    def test_wms_capabilities_facade_sublayers(self):
        ### Test that facade group sublayers are filtered from capabilities
        resources = deepcopy(self.WMS_RESOURCES)
        self.assertEqual(resources['wms_services'][0]['root_layer']['layers'][0]['name'], 'edit_demo')
        resources['wms_services'][0]['root_layer']['layers'][0]['hide_sublayers'] = True
        with self.use_config(resources, self.WMS_PERMISSIONS):
            qgs_response = self.qgs_get('wms_test', self.GETPROJECTSETTINGS_PARAMS)
            ogc_response = self.ogc_get('wms_test', self.GETPROJECTSETTINGS_PARAMS)

        self.assertTrue('edit_points' not in ogc_response.text)
        self.assertTrue('Edit Points' not in ogc_response.text)
        self.assertTrue('edit_points' in qgs_response.text)
        self.assertTrue('Edit Points' in qgs_response.text)
        self.assertTrue('edit_lines' not in ogc_response.text)
        self.assertTrue('Edit Lines' not in ogc_response.text)
        self.assertTrue('edit_lines' in qgs_response.text)
        self.assertTrue('Edit Lines' in qgs_response.text)

    def test_wms_capabilities_facade_standalone(self):
        ### Test that a layer which appears both standalone and inside a facade group is not filtered from capabilities
        resources = deepcopy(self.WMS_RESOURCES)
        self.assertEqual(resources['wms_services'][0]['root_layer']['layers'][0]['name'], 'edit_demo')
        resources['wms_services'][0]['root_layer']['layers'][0]['hide_sublayers'] = True
        resources['wms_services'][0]['root_layer']['layers'].insert(1, {
            "name": "edit_points",
            "title": "Edit Points",
            "attributes": [
                {
                    "name": "fid",
                    "alias": "fid"
                },
                {
                    "name": "id",
                    "alias": "id"
                },
                {
                    "name": "point_name",
                    "alias": "Point Name"
                },
                {
                    "name": "point_description",
                    "alias": "Point Description"
                },
                {
                    "name": "geometry",
                    "alias": "geometry"
                },
                {
                    "name": "maptip",
                    "alias": "maptip"
                }
            ],
            "queryable": True
        })
        with self.use_config(resources, self.WMS_PERMISSIONS):
            qgs_response = self.qgs_get('wms_test', self.GETPROJECTSETTINGS_PARAMS)
            ogc_response = self.ogc_get('wms_test', self.GETPROJECTSETTINGS_PARAMS)

        self.assertTrue('edit_points' in ogc_response.text)
        self.assertTrue('Edit Points' in ogc_response.text)
        self.assertTrue('edit_points' in qgs_response.text)
        self.assertTrue('Edit Points' in qgs_response.text)
        self.assertTrue('edit_lines' not in ogc_response.text)
        self.assertTrue('Edit Lines' not in ogc_response.text)
        self.assertTrue('edit_lines' in qgs_response.text)
        self.assertTrue('Edit Lines' in qgs_response.text)

    ### WMS GetMap ###

    GETMAP_PARAMS = {  # noqa: RUF012
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
    def test_wms_getmap_get(self):
        ### Test valid GET request ###
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', self.GETMAP_PARAMS)
        self.assertEqual(200, ogc_response.status_code, "Status code is not OK")
        self.assertEqual(ogc_response.headers['Content-Type'], 'image/png', "Response is not a valid PNG")

    def test_wms_getmap_post(self):
        ### Test valid POST request ###
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_post('wms_test', self.GETMAP_PARAMS)
        self.assertEqual(200, ogc_response.status_code, "Status code is not OK")
        self.assertEqual(ogc_response.headers['Content-Type'], 'image/png', "Response is not a valid PNG")

    def test_wms_getmap_invalid_layer(self):
        ### Test request with non-existing layer ###
        params1 = deepcopy(self.GETMAP_PARAMS)
        params1['LAYERS'] = 'edit_points,nonexistent'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue('Layer "nonexistent" does not exist or is not permitted' in ogc_response.text)

    def test_wms_getmap_restricted_layer(self):
        ### Test request with non-permitted layer (edit_points not permitted) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'] = list(
            filter(lambda layer: layer['name'] != 'edit_points', permissions['wms_services'][0]['layers'])
        )
        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', self.GETMAP_PARAMS)
        self.assertTrue('Layer "edit_points" does not exist or is not permitted' in ogc_response.text)

    def test_wms_getmap_restricted_sublayer(self):
        ### Test querying group with non-permitted sublayer (edit_points not permitted) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'] = list(
            filter(lambda layer: layer['name'] != 'edit_points', permissions['wms_services'][0]['layers'])
        )
        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_service = self.server.ogc_service_handler()
            ogc_permissions = ogc_service.service_permissions('test', 'wms_test', 'WMS')
            qgis_server_url = os.getenv('QGIS_SERVER_URL', 'http://localhost:8001/ows/').rstrip('/') + "/"
            handler = WmsHandler(self.server.app.logger, ogc_service.config, qgis_server_url, None, None)
        params1 = deepcopy(self.GETMAP_PARAMS)
        params1['LAYERS'] = 'edit_demo'
        params1['OPACITIES'] = '127'
        req = OgcRequest(qgis_server_url, "GET", "wms_test", params1, None)
        req = handler.adjust_request_params(req, ogc_permissions)
        self.assertEqual('edit_lines', req.params['LAYERS'])
        self.assertEqual('127', req.params['OPACITIES'])

    def test_wms_getmap_restricted_printlayer(self):
        ### Test request with non-permitted print layer (print layer only permitted for GETMAP+FILENAME) ###
        params1 = deepcopy(self.GETMAP_PARAMS)
        params1['LAYERS'] = 'edit_points,osm_bg'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue('Layer "osm_bg" does not exist or is not permitted' in ogc_response.text)

    def test_wms_getmap_printlayer(self):
        ### Test map export request with print layer and FILENAME ###
        params1 = deepcopy(self.GETMAP_PARAMS)
        params1['LAYERS'] = 'edit_points,osm_bg'
        params1['FILENAME'] = 'export.png'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertEqual(200, ogc_response.status_code, "Status code is not OK")
        self.assertEqual(ogc_response.headers['Content-Type'], 'image/png', "Response is not a valid PNG")

    def test_wms_getmap_facade(self):
        ### Test facade layer ###
        resources = deepcopy(self.WMS_RESOURCES)
        self.assertEqual(resources['wms_services'][0]['root_layer']['layers'][0]['name'], 'edit_demo')
        resources['wms_services'][0]['root_layer']['layers'][0]['hide_sublayers'] = True
        self.assertEqual(resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]['name'], 'edit_points')
        resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]['opacity'] = 50
        with self.use_config(resources, self.WMS_PERMISSIONS):
            ogc_service = self.server.ogc_service_handler()
            ogc_permissions = ogc_service.service_permissions('test', 'wms_test', 'WMS')
            qgis_server_url = os.getenv('QGIS_SERVER_URL', 'http://localhost:8001/ows/').rstrip('/') + "/"
            handler = WmsHandler(self.server.app.logger, ogc_service.config, qgis_server_url, None, None)
        self.assertTrue('edit_demo' in ogc_permissions['public_layers'])
        self.assertTrue('edit_points' not in ogc_permissions['public_layers'])
        self.assertTrue('edit_lines' not in ogc_permissions['public_layers'])

        params1 = deepcopy(self.GETMAP_PARAMS)
        params1['LAYERS'] = 'edit_demo,europe'
        params1['OPACITIES'] = '127,255'
        req = OgcRequest(qgis_server_url, "GET", "wms_test", params1, None)
        req = handler.adjust_request_params(req, ogc_permissions)
        self.assertEqual(req.params['LAYERS'], 'edit_lines,edit_points,europe')
        self.assertEqual(req.params['OPACITIES'], '127,64,255')
        self.assertEqual(req.params['STYLES'], ',,')

    def test_wms_getmap_restricted_externalwms(self):
        ### Test EXTERNAL_WMS, with edit_points not permitted ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'] = list(
            filter(lambda layer: layer['name'] != 'edit_points', permissions['wms_services'][0]['layers'])
        )
        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_service = self.server.ogc_service_handler()
            ogc_permissions = ogc_service.service_permissions('test', 'wms_test', 'WMS')
            qgis_server_url = os.getenv('QGIS_SERVER_URL', 'http://localhost:8001/ows/').rstrip('/') + "/"
            permission_reader = PermissionsReader('default', self.server.app.logger)
            handler = WmsHandler(self.server.app.logger, ogc_service.config, qgis_server_url, permission_reader, "test")
        params1 = deepcopy(self.GETMAP_PARAMS)
        params1['LAYERS'] = 'EXTERNAL_WMS:A'
        params1['OPACITIES'] = '255'
        params1['A:LAYERS'] = 'edit_points,edit_lines'
        params1['A:STYLES'] = 'default,default'
        params1['A:OPACITIES'] = '255,255'
        params1['A:URL'] = 'http://localhost/ows/wms_test'
        with self.server.app.test_request_context():
            req = OgcRequest(qgis_server_url, "GET", "wms_test", params1, None)
            req = handler.adjust_request_params(req, ogc_permissions)
        self.assertEqual(req.params['LAYERS'], 'EXTERNAL_WMS:A')
        self.assertEqual(req.params['OPACITIES'], '255')
        self.assertEqual(req.params['A:LAYERS'], 'edit_lines')
        self.assertEqual(req.params['A:STYLES'], 'default')
        self.assertEqual(req.params['A:OPACITIES'], '255')
        self.assertEqual(req.params['A:URL'], 'http://localhost:8001/ows/wms_test')

    ### WMS GetFeatureInfo ###

    GETFEATUREINFO_PARAMS = {  # noqa: RUF012
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
        'FI_POLYGON_TOLERANCE': 4,
        'WITH_GEOMETRY': 1,
        'WITH_HTMLCONTENT': 1
    }

    def test_wms_getfeatureinfo(self):
        ### Test unrestricted query ###
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.tag, "GetFeatureInfoResponse")
        layerEls = doc.findall("./Layer")
        self.assertEqual(len(layerEls), 2)
        self.assertEqual(layerEls[0].get('name'), "edit_points")
        self.assertEqual(layerEls[0].get('title'), "Edit Points")
        self.assertEqual(layerEls[0].get('displayfield'), "Point Name")
        self.assertEqual(layerEls[1].get('name'), "europe")
        self.assertEqual(layerEls[1].get('title'), "Europe")
        self.assertEqual(layerEls[1].get('displayfield'), "Long Name")
        self.assertEqual(layerEls[1].get('featurereport'), "countries_report")
        layer1FeatureEls = layerEls[0].findall("./Feature")
        self.assertEqual(len(layer1FeatureEls), 1)
        self.assertTrue(layer1FeatureEls[0].find("./Attribute[@name='Point Name']") is not None)
        self.assertEqual(layer1FeatureEls[0].find("./Attribute[@name='Point Name']").get("value"), "point")
        self.assertEqual(layer1FeatureEls[0].find("./Attribute[@name='Point Name']").get("attrname"), "point_name")
        layer2FeatureEls = layerEls[1].findall("./Feature")
        self.assertEqual(len(layer2FeatureEls), 1)
        self.assertTrue(layer2FeatureEls[0].find("./Attribute[@name='name']") is not None)
        self.assertEqual(layer2FeatureEls[0].find("./Attribute[@name='name']").get("value"), "Switzerland")
        self.assertEqual(layer2FeatureEls[0].find("./Attribute[@name='name']").get("attrname"), "name")

    def test_wms_getfeatureinfo_text(self):
        ### Test text/plain query ###
        params1 = deepcopy(self.GETFEATUREINFO_PARAMS)
        params1['INFO_FORMAT'] = 'text/plain'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue("Layer 'Edit Points'" in ogc_response.text)
        self.assertTrue("Point Name = 'point'" in ogc_response.text)
        self.assertTrue("Layer 'Europe'" in ogc_response.text)

    def test_wms_getfeatureinfo_html(self):
        ### Test text/html query ###
        params1 = deepcopy(self.GETFEATUREINFO_PARAMS)
        params1['INFO_FORMAT'] = 'text/html'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue('<div class="layer-title">Edit Points</div>' in ogc_response.text)
        self.assertTrue("<th>Point Name</th>" in ogc_response.text)
        self.assertTrue('<div class="layer-title">Europe</div>' in ogc_response.text)

    def test_wms_getfeatureinfo_json(self):
        ### Test application/json query ###
        params1 = deepcopy(self.GETFEATUREINFO_PARAMS)
        params1['INFO_FORMAT'] = 'application/json'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        info_json = json.loads(ogc_response.text)
        edit_point_features = list(filter(lambda feature: feature['layerName'] == 'Edit Points', info_json['features']))
        self.assertEqual(len(edit_point_features), 1)
        self.assertEqual(edit_point_features[0]['properties']['Point Name'], 'point')
        self.assertEqual(edit_point_features[0]['geometry']['type'], 'Point')
        europe_features = list(filter(lambda feature: feature['layerName'] == 'Europe', info_json['features']))
        self.assertEqual(len(europe_features), 1)
        self.assertEqual(europe_features[0]['properties']['name'], 'Switzerland')
        self.assertEqual(europe_features[0]['geometry']['type'], 'MultiPolygon')

    def test_wms_getfeatureinfo_json_nogeometry(self):
        ### Test application/json query without geometry ###
        params1 = deepcopy(self.GETFEATUREINFO_PARAMS)
        params1['INFO_FORMAT'] = 'application/json'
        params1['WITH_GEOMETRY'] = '0'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        info_json = json.loads(ogc_response.text)
        edit_point_features = list(filter(lambda feature: feature['layerName'] == 'Edit Points', info_json['features']))
        self.assertEqual(len(edit_point_features), 1)
        self.assertEqual(edit_point_features[0]['properties']['Point Name'], 'point')
        self.assertEqual(edit_point_features[0]['geometry'], None)

    def test_wms_getfeatureinfo_param_mismatch(self):
        ### Test with query_layers not equal layers ###
        params1 = deepcopy(self.GETFEATUREINFO_PARAMS)
        params1['QUERY_LAYERS'] = 'edit_lines,europe'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue('LAYERS must be identical to QUERY_LAYERS for GETFEATUREINFO operation' in ogc_response.text)

    def test_wms_getfeatureinfo_invalid_format(self):
        ### Test with unsupported/invalid info format ###
        params1 = deepcopy(self.GETFEATUREINFO_PARAMS)
        params1['INFO_FORMAT'] = 'application/pdf'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue("Feature info format 'application/pdf' is unsupported" in ogc_response.text)

    def test_wms_getfeatureinfo_non_queryable(self):
        ### Test query with edit_points marked as not queryable ###
        # At resource level
        resources = deepcopy(self.WMS_RESOURCES)
        self.assertEqual(resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]['name'], 'edit_points')
        resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]['queryable'] = False
        with self.use_config(resources, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)

        # At permission level
        permissions = deepcopy(self.WMS_PERMISSIONS)
        self.assertEqual(permissions['wms_services'][0]['layers'][2]['name'], 'edit_points')
        permissions['wms_services'][0]['layers'][2]['queryable'] = False
        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)

        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.tag, "GetFeatureInfoResponse")
        self.assertTrue(doc.find("./Layer[@name='edit_points']") is None)
        self.assertTrue(doc.find("./Layer[@name='europe']") is not None)

    def test_wms_getfeatureinfo_restricted_layer(self):
        ### Test query with edit_points not permitted ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'] = list(
            filter(lambda layer: layer['name'] != 'edit_points', permissions['wms_services'][0]['layers'])
        )
        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
        self.assertTrue('Layer "edit_points" does not exist or is not permitted' in ogc_response.text)

    def test_wms_getfeatureinfo_restricted_attribute(self):
        ### Test query with not permitted point_name attribute ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        self.assertEqual(permissions['wms_services'][0]['layers'][2]['name'], 'edit_points')
        permissions['wms_services'][0]['layers'][2]['attributes'] = [
            attr for attr in permissions['wms_services'][0]['layers'][2]['attributes'] if attr != 'point_name'
        ]
        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.tag, "GetFeatureInfoResponse")
        self.assertTrue(doc.find("./Layer[@name='edit_points']") is not None)
        self.assertTrue(doc.find("./Layer[@name='edit_points']/Feature/Attribute[@attrname='point_description']") is not None)
        self.assertTrue(doc.find("./Layer[@name='edit_points']/Feature/Attribute[@attrname='point_name']") is None)

    def test_wms_getfeatureinfo_facade(self):
        ### Test facade layer ###
        resources = deepcopy(self.WMS_RESOURCES)
        self.assertEqual(resources['wms_services'][0]['root_layer']['layers'][0]['name'], 'edit_demo')
        resources['wms_services'][0]['root_layer']['layers'][0]['hide_sublayers'] = True
        params1 = deepcopy(self.GETFEATUREINFO_PARAMS)
        params1['LAYERS'] = 'edit_demo,europe'
        params1['QUERY_LAYERS'] = 'edit_demo,europe'
        with self.use_config(resources, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.tag, "GetFeatureInfoResponse")
        self.assertTrue(doc.find("./Layer[@name='edit_points']") is not None)
        self.assertEqual(doc.find("./Layer[@name='edit_points']").get("layerinfo"), "edit_demo")
        self.assertTrue(doc.find("./Layer[@name='edit_lines']") is not None)
        self.assertEqual(doc.find("./Layer[@name='edit_lines']").get("layerinfo"), "edit_demo")

    def test_wms_getfeatureinfo_no_htmlcontent(self):
        ### No template => no HtmlContent
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.tag, "GetFeatureInfoResponse")
        self.assertTrue(doc.find("./Layer[@name='edit_points']/Feature/HtmlContent") is None)

    def test_wms_getfeatureinfo_wms_template(self):
        ### WMS info template
        resources = deepcopy(self.WMS_RESOURCES)
        edit_points_resource = resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]
        self.assertEqual(edit_points_resource['name'], 'edit_points')
        template_configs = [
            {"template": 'Point {{ feature.point_name }} ({{ feature["point_description"] }})'},
            {"template_base64": 'UG9pbnQge3sgZmVhdHVyZS5wb2ludF9uYW1lIH19ICh7eyBmZWF0dXJlWyJwb2ludF9kZXNjcmlwdGlvbiJdIH19KQ=='},
            {"template_path": './tests/testdata/info_template.html'}
        ]
        for template_config in template_configs:
            edit_points_resource['info_template'] = {"type": "wms"} | template_config
            with self.use_config(resources, self.WMS_PERMISSIONS):
                ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
            doc = ElementTree.fromstring(ogc_response.text)
            self.assertTrue(
                doc.find("./Layer[@name='edit_points']/Feature/HtmlContent") is not None,
                "Has HtmlContent with " + str(template_config)
            )
            self.assertEqual(doc.find("./Layer[@name='edit_points']/Feature/HtmlContent").get('inline'), "1")
            self.assertEqual(
                doc.find("./Layer/Feature/HtmlContent").text, 'Point point (Example Point)',
                "Has correct HtmlContent with " + str(template_config)
            )

    def test_wms_getfeatureinfo_wms_template_html_output(self):
        ### WMS info template in text/html output
        params = deepcopy(self.GETFEATUREINFO_PARAMS)
        params['INFO_FORMAT'] = 'text/html'
        resources = deepcopy(self.WMS_RESOURCES)
        edit_points_resource = resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]
        self.assertEqual(edit_points_resource['name'], 'edit_points')
        template_configs = [
            {"template": 'Point {{ feature.point_name }} ({{ feature["point_description"] }})'},
            {"template_base64": 'UG9pbnQge3sgZmVhdHVyZS5wb2ludF9uYW1lIH19ICh7eyBmZWF0dXJlWyJwb2ludF9kZXNjcmlwdGlvbiJdIH19KQ=='},
            {"template_path": './tests/testdata/info_template.html'}
        ]
        for template_config in template_configs:
            edit_points_resource['info_template'] = {"type": "wms"} | template_config
            with self.use_config(resources, self.WMS_PERMISSIONS):
                ogc_response = self.ogc_get('wms_test', params)
            self.assertTrue('Point point (Example Point)' in ogc_response.text)

    def test_wms_getfeatureinfo_wms_auto_template(self):
        ### Autodetected WMS template / default templates
        extra_configs = [
            ({"info_templates_path": "./tests/testdata"}, 'Point point (Example Point)'),
            ({"default_info_template": 'Default template'}, 'Default template'),
            ({"default_info_template_path": './tests/testdata/default_template.html'}, 'Default template')
        ]
        for extra_config, expected_value in extra_configs:
            with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS, extra_config):
                ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
            doc = ElementTree.fromstring(ogc_response.text)
            self.assertEqual(doc.tag, "GetFeatureInfoResponse")
            self.assertTrue(
                doc.find("./Layer[@name='edit_points']/Feature/HtmlContent") is not None,
                "Has HtmlContent with " + str(extra_config)
            )
            self.assertEqual(
                doc.find("./Layer/Feature/HtmlContent").text, expected_value,
                "Has correct HtmlContent with " + str(extra_config)
            )

    def test_wms_getfeatureinfo_wms_template_nohtmlcontent(self):
        ### WMS template, without WITH_HTMLCONTENT = 1
        resources = deepcopy(self.WMS_RESOURCES)
        edit_points_resource = resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]
        self.assertEqual(edit_points_resource['name'], 'edit_points')
        edit_points_resource['info_template'] = {
            "type": "wms", "template": 'Point {{ feature.point_name }} ({{ feature["point_description"] }})'
        }
        params1 = deepcopy(self.GETFEATUREINFO_PARAMS)
        del params1['WITH_HTMLCONTENT']
        with self.use_config(resources, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.tag, "GetFeatureInfoResponse")
        self.assertTrue(doc.find("./Layer/Feature[@name='edit_points']/HtmlContent") is None)

    def test_wms_getfeatureinfo_sql(self):
        ### SQL info module
        resources = deepcopy(self.WMS_RESOURCES)
        europe_resource = resources['wms_services'][0]['root_layer']['layers'][1]
        self.assertEqual(europe_resource['name'], 'europe')
        europe_resource['info_template'] = {
            "type": "sql",
            "db_url": "postgresql:///?service=qwc_geodb",
            "sql": """
                SELECT
                    ogc_fid AS _fid_, 'testvalue' AS name, pop_est,
                    ST_AsText(wkb_geometry) AS wkt_geom, Box2D(wkb_geometry) AS bbox
                FROM qwc_geodb.ne_10m_admin_0_countries
                WHERE ST_Intersects(wkb_geometry, ST_GeomFromText(:geom, :srid))
                LIMIT :feature_count;
            """
        }
        with self.use_config(resources, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.find("./Layer[@name='europe']/Feature/Attribute[@name='name']").get('value'), 'testvalue')
        self.assertTrue(doc.find("./Layer[@name='europe']/Feature/BoundingBox") is not None)

    def test_wms_getfeatureinfo_custom_module(self):
        ### Custom info module
        resources = deepcopy(self.WMS_RESOURCES)
        europe_resource = resources['wms_services'][0]['root_layer']['layers'][1]
        self.assertEqual(europe_resource['name'], 'europe')
        europe_resource['info_template'] = {
            "type": "module",
            "module": "example"
        }
        with self.use_config(resources, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
        doc = ElementTree.fromstring(ogc_response.text)
        featureEl = doc.find("./Layer[@name='europe']/Feature[@id='123']")
        self.assertEqual(featureEl.find("./Attribute[@name='name']").get('value'), 'Feature Name')
        self.assertEqual(featureEl.find("./Attribute[@name='geometry']").get('value'), 'POINT(960312 5973542)')

    def test_wms_getfeatureinfo_skip_empty_attributes(self):
        ### skip_empty_attributes
        resources = deepcopy(self.WMS_RESOURCES)
        europe_resource = resources['wms_services'][0]['root_layer']['layers'][1]
        self.assertEqual(europe_resource['name'], 'europe')
        europe_resource['info_template'] = {
            "type": "sql",
            "db_url": "postgresql:///?service=qwc_geodb",
            "sql": """
                SELECT ogc_fid AS _fid_, '' AS name, pop_est, ST_AsText(wkb_geometry) AS wkt_geom
                FROM qwc_geodb.ne_10m_admin_0_countries
                WHERE ST_Intersects(wkb_geometry, ST_GeomFromText(:geom, :srid));
            """
        }
        with self.use_config(resources, self.WMS_PERMISSIONS, {"skip_empty_attributes": False}):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.find("./Layer[@name='europe']/Feature/Attribute[@name='name']").get("value"), '')
        with self.use_config(resources, self.WMS_PERMISSIONS, {"skip_empty_attributes": True}):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertTrue(doc.find("./Layer[@name='europe']/Feature/Attribute[@name='name']") is None)

    def test_wms_getfeatureinfo_attrib_order(self):
        ### use_resource_attribute_order / attributes resource config
        resources = deepcopy(self.WMS_RESOURCES)
        edit_points_resource = resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]
        self.assertEqual(edit_points_resource['name'], 'edit_points')
        edit_points_resource['attributes'] = [
            {"name": "point_name", "alias": "Point Name"},
            {"name": "point_description", "alias": "Point Description"},
            {"name": "id", "alias": "ID"}
        ]
        with self.use_config(resources, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.tag, "GetFeatureInfoResponse")
        attributeEls = doc.findall("./Layer[@name='edit_points']/Feature/Attribute")
        self.assertEqual(len(attributeEls), 3)
        self.assertEqual(attributeEls[0].get('name'), 'ID')
        self.assertEqual(attributeEls[1].get('name'), 'Point Name')
        self.assertEqual(attributeEls[2].get('name'), 'Point Description')

        with self.use_config(resources, self.WMS_PERMISSIONS, {"use_resource_attribute_order": True}):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.tag, "GetFeatureInfoResponse")
        attributeEls = doc.findall("./Layer[@name='edit_points']/Feature/Attribute")
        self.assertEqual(len(attributeEls), 3)
        self.assertEqual(attributeEls[0].get('name'), 'Point Name')
        self.assertEqual(attributeEls[1].get('name'), 'Point Description')
        self.assertEqual(attributeEls[2].get('name'), 'ID')

    def test_wms_getfeatureinfo_attrib_format(self):
        ### Attribute format / JSON attributes
        permissions = deepcopy(self.WMS_PERMISSIONS)
        self.assertEqual(permissions['wms_services'][0]['layers'][2]['name'], 'edit_points')
        permissions['wms_services'][0]['layers'][2]['attributes'].append('attachment')
        permissions['wms_services'][0]['layers'][2]['attributes'].append('num')
        permissions['wms_services'][0]['layers'][2]['attributes'].append('bool')
        permissions['wms_services'][0]['layers'][2]['attributes'].append('date')
        permissions['wms_services'][0]['layers'][2]['attributes'].append('link')
        permissions['wms_services'][0]['layers'][2]['attributes'].append('jsonflatlist')
        permissions['wms_services'][0]['layers'][2]['attributes'].append('jsondictlist')
        permissions['wms_services'][0]['layers'][2]['attributes'].append('jsondict')

        resources = deepcopy(self.WMS_RESOURCES)
        edit_points_resource = resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]
        self.assertEqual(edit_points_resource['name'], 'edit_points')
        edit_points_resource["attributes"].append({"name": "attachment", "alias": "Attachment"})
        edit_points_resource["attributes"].append({"name": "num", "alias": "Number", "format": " >+10.3f"})
        edit_points_resource["attributes"].append({"name": "bool", "alias": "Boolean", "format": '{"0": "False", "1": "True"}'})
        edit_points_resource["attributes"].append({"name": "date", "alias": "Date"})
        edit_points_resource["attributes"].append({"name": "link", "alias": "Link"})
        edit_points_resource["attributes"].append({"name": "jsonflatlist", "alias": "JSON Flat List"})
        edit_points_resource["attributes"].append({
            "name": "jsondictlist",
            "alias": "JSON Dict List",
            "json_attributes": [
                {"name": "key1", "alias": "Key 1"},
                {"name": "key3", "alias": "Key 3"},
            ]
        })
        edit_points_resource["attributes"].append({
            "name": "jsondict",
            "alias": "JSON Dict",
            "json_attributes": [
                {"name": "key1", "alias": "Key 1"},
                {"name": "key3", "alias": "Key 3"},
            ]
        })
        edit_points_resource['info_template'] = {
            "type": "sql",
            "db_url": "postgresql:///?service=qwc_geodb",
            "sql": """
                SELECT id AS _fid_, name, description, num,
                  '0' AS bool, 'attachment://foo' AS attachment, '2026-10-21T19:02:34' AS date,
                  'https://example.com' AS link,
                  '["Item 1", "Item 2"]' AS jsonflatlist,
                  '[{"key3": "Item 3", "key1": "Item 1"}, {"key3": "Item 3", "key2": "Item 2"}]' as jsondictlist,
                  '{"key2": "Item 2", "key1": "Item 1", "key3": "Item 3"}' as jsondict
                FROM qwc_geodb.edit_points WHERE id = 1
            """
        }
        with self.use_config(resources, permissions, {"info_link_text": "\\1"}):
            ogc_response = self.ogc_get('wms_test', self.GETFEATUREINFO_PARAMS)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.tag, "GetFeatureInfoResponse")

        # Test attachment URL rewriting
        self.assertEqual(
            doc.find("./Layer[@name='edit_points']/Feature/Attribute[@name='Attachment']").get("value"),
            '/api/v1/data/wms_test.edit_points/attachment?file=foo'
        )

        # Test date formatting
        self.assertEqual(
            doc.find("./Layer[@name='edit_points']/Feature/Attribute[@name='Date']").get("value"),
            '21.10.2026 19:02:34'
        )

        # Test attribute format strings
        self.assertEqual(
            doc.find("./Layer[@name='edit_points']/Feature/Attribute[@name='Number']").get("value"),
            '  +123.000'
        )

        # Test attribute dict formatting
        self.assertEqual(
            doc.find("./Layer[@name='edit_points']/Feature/Attribute[@name='Boolean']").get("value"),
            'False'
        )

        # JSON flat list formatting
        self.assertEqual(
            '<table class="identify-attr-subtable"><tbody>'
            '<tr><td class="identify-attr-value identify-attr-single-value wrap" colspan="2">Item 1</td></tr>'
            '<tr><td class="identify-attr-spacer" colspan="2"></td></tr>'
            '<tr><td class="identify-attr-value identify-attr-single-value wrap" colspan="2">Item 2</td></tr>'
            '<tr><td class="identify-attr-spacer" colspan="2"></td></tr>'
            '</tbody></table>',
            html.unescape(doc.find("./Layer[@name='edit_points']/Feature/Attribute[@name='JSON Flat List']").get("value"))
        )

        # JSON dict list formatting
        self.assertEqual(
            '<table class="identify-attr-subtable"><tbody>'
            '<tr><td class="identify-attr-title-wrap"><i>Key 1</i></td><td class="identify-attr-value wrap">Item 1</td></tr>'
            '<tr><td class="identify-attr-title-wrap"><i>Key 3</i></td><td class="identify-attr-value wrap">Item 3</td></tr>'
            '<tr><td class="identify-attr-spacer" colspan="2"></td></tr>'
            '<tr><td class="identify-attr-title-wrap"><i>Key 3</i></td><td class="identify-attr-value wrap">Item 3</td></tr>'
            '<tr><td class="identify-attr-spacer" colspan="2"></td></tr>'
            '</tbody></table>',
            html.unescape(doc.find("./Layer[@name='edit_points']/Feature/Attribute[@name='JSON Dict List']").get("value"))
        )

        # JSON dict formatting
        self.assertEqual(
            '<table class="identify-attr-subtable"><tbody>'
            '<tr><td class="identify-attr-title-wrap"><i>Key 1</i></td><td class="identify-attr-value wrap">Item 1</td></tr>'
            '<tr><td class="identify-attr-title-wrap"><i>Key 3</i></td><td class="identify-attr-value wrap">Item 3</td></tr>'
            '</tbody></table>',
            html.unescape(doc.find("./Layer[@name='edit_points']/Feature/Attribute[@name='JSON Dict']").get("value"))
        )

        # Link formatting
        self.assertEqual(
            '<a href="https://example.com" target="_blank">https://example.com</a>',
            html.unescape(doc.find("./Layer[@name='edit_points']/Feature/Attribute[@name='Link']").get("value"))
        )

    def test_wms_getfeatureinfo_geomcentroid(self):
        """ Test GEOMCENTROID """
        params1 = deepcopy(self.GETFEATUREINFO_PARAMS)
        params1['GEOMCENTROID'] = '1'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.tag, "GetFeatureInfoResponse")
        self.assertTrue(doc.find("./Layer[@name='edit_points']/Feature/Attribute[@name='geometry']").get("value").startswith('POINT'))
        self.assertTrue(doc.find("./Layer[@name='europe']/Feature/Attribute[@name='geometry']").get("value").startswith('POINT'))

    def test_wms_getfeatureinfo_filter(self):
        """ Test FILTER request """
        params1 = deepcopy(self.GETFEATUREINFO_PARAMS)
        del params1['BBOX']
        params1['LAYERS'] = params1['QUERY_LAYERS'] = 'europe'
        params1['FILTER'] = 'europe:"fid" = 93'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        doc = ElementTree.fromstring(ogc_response.text)
        self.assertEqual(doc.tag, "GetFeatureInfoResponse")
        self.assertEqual(len(doc.findall("./Layer[@name='europe']/Feature")), 1)
        self.assertEqual(doc.find("./Layer[@name='europe']/Feature/Attribute[@name='fid']").get("value"), "93")

    ### WMS GetLegendGraphic ###

    GETLEGENDGRAPHIC_PARAMS = {  # noqa: RUF012
        'SERVICE': 'WMS',
        'VERSION': '1.3.0',
        'REQUEST': 'GetLegendGraphic',
        'FORMAT': 'image/png',
        'LAYER': 'edit_points',
        'STYLES': '',
        'SRS': 'EPSG:3857',
        'CRS': 'EPSG:3857',
        'WIDTH': 200,
        'HEIGHT': 200
    }

    def test_wms_getlegendgraphic(self):
        ### Test valid GET request ###
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', self.GETLEGENDGRAPHIC_PARAMS)
        self.assertEqual(200, ogc_response.status_code, "Status code is not OK")
        self.assertEqual(ogc_response.headers['Content-Type'], 'image/png', "Response is not a valid PNG")

    def test_wms_getlegendgraphic_restrictedlayer(self):
        ### Test request with non-existing layer ###
        params1 = deepcopy(self.GETLEGENDGRAPHIC_PARAMS)
        params1['LAYER'] = 'edit_points,nonexistent'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue('Layer "nonexistent" does not exist or is not permitted' in ogc_response.text)

    def test_wms_getlegendgraphic_custom_image_filename(self):
        ### Test custom image matched by filename (image exists at expected location, see .github/workflows/main.yml)
        params1 = deepcopy(self.GETLEGENDGRAPHIC_PARAMS)
        params1['LAYER'] = 'europe'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        img = Image.open(BytesIO(ogc_response.data))
        self.assertEqual(img.width, 32)
        self.assertEqual(img.height, 64)

    def test_wms_getlegendgraphic_custom_image_reosurce(self):
        ### Test custom image matched by resource config (image exists at expected location, see .github/workflows/main.yml)
        # NOTE: filename matching takes precedence over resource config!
        params1 = deepcopy(self.GETLEGENDGRAPHIC_PARAMS)
        params1['LAYER'] = 'europe'
        resources = deepcopy(self.WMS_RESOURCES)
        self.assertEqual(resources['wms_services'][0]['root_layer']['layers'][1]['name'], 'europe')
        resources['wms_services'][0]['root_layer']['layers'][1]['legend_image'] = 'custom_legend_image.png'

        with self.use_config(resources, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        img = Image.open(BytesIO(ogc_response.data))
        self.assertEqual(img.width, 64)
        self.assertEqual(img.height, 32)

    def test_wms_getlegendgraphic_custom_image_resource(self):
        ### Test custom image matched by resource config (image exists at expected location, see .github/workflows/main.yml)
        params1 = deepcopy(self.GETLEGENDGRAPHIC_PARAMS)
        params1['LAYER'] = 'edit_points'
        resources = deepcopy(self.WMS_RESOURCES)
        self.assertEqual(resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]['name'], 'edit_points')
        resources['wms_services'][0]['root_layer']['layers'][0]['layers'][0]['legend_image'] = 'custom_legend_image.png'

        with self.use_config(resources, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        img = Image.open(BytesIO(ogc_response.data))
        self.assertEqual(img.width, 64)
        self.assertEqual(img.height, 32)

    def test_wms_getlegendgraphic_group_layers(self):
        ### Test that group layers are resolved
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_service = self.server.ogc_service_handler()
            ogc_permissions = ogc_service.service_permissions('test', 'wms_test', 'WMS')
            qgis_server_url = os.getenv('QGIS_SERVER_URL', 'http://localhost:8001/ows/').rstrip('/') + "/"
            permission_reader = PermissionsReader('default', self.server.app.logger)
            handler = WmsHandler(self.server.app.logger, ogc_service.config, qgis_server_url, permission_reader, "test")
        params1 = deepcopy(self.GETLEGENDGRAPHIC_PARAMS)
        params1['LAYERS'] = 'edit_demo'
        with self.server.app.test_request_context():
            req = OgcRequest(qgis_server_url, "GET", "wms_test", params1, None)
            req = handler.adjust_request_params(req, ogc_permissions)
        self.assertEqual(req.params['LAYERS'], 'edit_lines,edit_points')

    ### WMS GetPrint ###

    GETPRINT_PARAMS = {  # noqa: RUF012
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

    def test_wms_getprint(self):
        ### Test valid request ###
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', self.GETPRINT_PARAMS)
        self.assertEqual(200, ogc_response.status_code, "Status code is not OK")
        self.assertEqual(ogc_response.headers['Content-Type'], 'application/pdf', "Response is not a valid PDF")

    def test_wms_getprint_missing_layout(self):
        ### Test invalid request (non-existing layout) ###
        params1 = deepcopy(self.GETPRINT_PARAMS)
        params1['TEMPLATE'] = 'A4 Portrait'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue("Composer template 'A4 Portrait' not found or not permitted" in ogc_response.text)

    def test_wms_getprint_restricted_layout(self):
        ### Test invalid request (restricted layout) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['print_templates'] = []
        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', self.GETPRINT_PARAMS)
        self.assertTrue("Composer template 'A4 Landscape' not found or not permitted" in ogc_response.text)

    def test_wms_getprint_bad_layers_param(self):
        ### Test request with non-existing layer in LAYERS - should succeed, as map0 LAYERS is honoured ###
        params1 = deepcopy(self.GETPRINT_PARAMS)
        params1['LAYERS'] = 'edit_points,nonexistent'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertEqual(200, ogc_response.status_code, "Status code is not OK")
        self.assertEqual(ogc_response.headers['Content-Type'], 'application/pdf', "Response is not a valid PDF")

    def test_wms_getprint_bad_map_layers_param(self):
        ### Test request with non-existing layer in map0:LAYERS - should fail ###
        params1 = deepcopy(self.GETPRINT_PARAMS)
        params1['map0:LAYERS'] = 'edit_points,nonexistent'
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', params1)
        self.assertTrue('Layer "nonexistent" does not exist or is not permitted' in ogc_response.text)

    def test_wms_getprint_custom_labels(self):
        ### Test custom labels and qgs suffix
        extra_config = {
            "print_label_queries": [
                {
                    "db_url": "postgresql:///?service=qwc_configdb",
                    "query": "SELECT description FROM qwc_config.users WHERE name = 'admin'",
                    "params": [
                        "USER_DESC"
                    ]
                }
            ],
            "print_label_values": [
                {
                    "field": "USERNAME",
                    "value": "$username$"
                }
            ],
            "print_qgs_postfix": "_print"
        }
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS, extra_config):
            ogc_service = self.server.ogc_service_handler()
            ogc_permissions = ogc_service.service_permissions('test', 'wms_test', 'WMS')
            qgis_server_url = os.getenv('QGIS_SERVER_URL', 'http://localhost:8001/ows/').rstrip('/') + "/"
            handler = WmsHandler(self.server.app.logger, ogc_service.config, qgis_server_url, None, "testuser")
        req = OgcRequest(qgis_server_url, "GET", "wms_test", self.GETPRINT_PARAMS, None)
        req = handler.adjust_request_params(req, ogc_permissions)
        self.assertEqual(req.params.get('USERNAME'), "testuser")
        self.assertEqual(req.params.get('USER_DESC'), "Default admin user")
        self.assertEqual(req.service_name, "wms_test_print")

    ### WMS GetStyle ###

    GETSTYLE_PARAMS = {  # noqa: RUF012
        'SERVICE': 'WMS',
        'VERSION': '1.3.0',
        'REQUEST': 'GetStyle',
        'LAYERS': 'edit_points,europe'
    }

    def test_wms_getstyle(self):
        ### Test valid request ###
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', self.GETSTYLE_PARAMS)
        self.assertTrue('<se:Name>edit_points</se:Name>' in ogc_response.text)

    def test_wms_getstyle_restricted_layer(self):
        ### Test filtered request (layer edit_points unpermitted) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'] = list(
            filter(lambda layer: layer['name'] != 'edit_points', permissions['wms_services'][0]['layers'])
        )

        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', self.GETSTYLE_PARAMS)

        self.assertTrue('<se:Name>edit_points</se:Name>' not in ogc_response.text)

    ### GetTranslatons ###

    GETTRANSLATIONS_PARAM = {  # noqa: RUF012
        'SERVICE': 'GetTranslations',
        'LANG': 'de-CH'
    }

    def test_gettranslations(self):
        ### Test valid request ###
        with self.use_config(self.WMS_RESOURCES, self.WMS_PERMISSIONS):
            ogc_response = self.ogc_get('wms_test', self.GETTRANSLATIONS_PARAM)
        translations = json.loads(ogc_response.text)
        self.assertEqual(translations["layertree"]["europe"], "Europa")

    def test_gettranslations_restricted_layer(self):
        ### Test filtered translations (layer europe unpermitted) ###
        permissions = deepcopy(self.WMS_PERMISSIONS)
        permissions['wms_services'][0]['layers'] = list(
            filter(lambda layer: layer['name'] != 'europe', permissions['wms_services'][0]['layers'])
        )
        with self.use_config(self.WMS_RESOURCES, permissions):
            ogc_response = self.ogc_get('wms_test', self.GETTRANSLATIONS_PARAM)
        translations = json.loads(ogc_response.text)
        self.assertTrue("europe" not in translations["layertree"])
