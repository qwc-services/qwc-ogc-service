import os
import unittest
from urllib.parse import urlparse, parse_qs, unquote, urlencode

from flask import Response, json
from flask.testing import FlaskClient
from flask_jwt_extended import JWTManager, create_access_token

import server


class ApiTestCase(unittest.TestCase):
    """Test case for server API"""

    def setUp(self):
        server.app.testing = True
        self.app = FlaskClient(server.app, Response)
        JWTManager(server.app)

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
