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
            'FORMAT': 'image%2Fpng',
            'TRANSPARENT': 'true',
            'LAYERS': 'test_poly,test_point',
            'STYLES': '',
            'SRS': 'EPSG%3A2056',
            'CRS': 'EPSG%3A2056',
            'TILED': 'false',
            'DPI': '96',
            'OPACITIES': '255,255',
            'WIDTH': '1280',
            'HEIGHT': '556',
            'BBOX': '2606082.333333333%2C1233466.3333333333%2C2633175.666666666%2C1245234.9999999998',
        }
        response = self.app.get('/somap?' + urlencode(params), headers=self.jwtHeader())
        self.assertEqual(200, response.status_code, "Status code is not OK")
        data = json.loads(response.data)
        self.assertEqual('somap', data['path'], 'Print project name mismatch')
        self.assertEqual('GET', data['method'], 'Method mismatch')
        get_params = data['params']
        for param in params.keys():
            self.assertTrue(param in get_params, "Parameter %s missing in response" % param)
            self.assertEqual(get_params[param], str(params[param]), "Parameter %s mismatch" % param)

    def test_wms_post(self):
        params = {
            'SERVICE': 'WMS',
            'VERSION': '1.3.0',
            'REQUEST': 'GetMap',
            'FORMAT': 'image%2Fpng',
            'TRANSPARENT': 'true',
            'LAYERS': 'test_poly,test_point',
            'STYLES': '',
            'SRS': 'EPSG%3A2056',
            'CRS': 'EPSG%3A2056',
            'TILED': 'false',
            'DPI': '96',
            'OPACITIES': '255,255',
            'WIDTH': '1280',
            'HEIGHT': '556',
            'BBOX': '2606082.333333333%2C1233466.3333333333%2C2633175.666666666%2C1245234.9999999998',
        }
        response = self.app.post('/somap', data=params, headers=self.jwtHeader())
        self.assertEqual(200, response.status_code, "Status code is not OK")
        data = json.loads(response.data)
        self.assertEqual('somap', data['path'], 'Print project name mismatch')
        self.assertEqual('POST', data['method'], 'Method mismatch')
        post_params = dict([list(map(unquote, param.split("=", 1))) for param in data['data'].split("&")])
        for param in params.keys():
            self.assertTrue(param in post_params, "Parameter %s missing in response" % param)
            self.assertEqual(post_params[param], str(params[param]), "Parameter %s mismatch" % param)
