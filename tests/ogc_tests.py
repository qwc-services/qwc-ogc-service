import difflib
import os
import tempfile
import unittest
from contextlib import contextmanager
from urllib.parse import urlencode
from xml.etree import ElementTree

import jsonschema
import requests
from flask import Response, json
from flask.testing import FlaskClient
from flask_jwt_extended import JWTManager, create_access_token

import server

server.app.config["APPLICATION_ROOT"] = "/ows"
JWTManager(server.app)

xlinkns = 'http://www.w3.org/1999/xlink'

with open('./schemas/qwc-ogc-service.json') as fh:
    QWC_OGC_CONFIG_SCHEMA = json.load(fh)

class OgcTests(unittest.TestCase):
    """Base class for ogc service tests"""

    def setUp(self):
        self.server = server
        self.server.app.testing = True
        self.app = FlaskClient(server.app, Response)

    def tearDown(self):
        pass

    @contextmanager
    def use_config(self, resources, permissions, extra_config = None):
        with tempfile.TemporaryDirectory() as tmpdirpath:
            # Ensure tenant handler cache is empty
            self.server.tenant_handler.handler_cache = {}

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
                        "default_qgis_server_url": qgis_server_url,
                    },
                    "resources": resources
                }
                if extra_config:
                    resources_data["config"].update(extra_config)

                # Validate schema
                jsonschema.validate(instance=resources_data, schema=QWC_OGC_CONFIG_SCHEMA)

                json.dump(resources_data, fh)

            with self.server.app.test_request_context("/", base_url="http://localhost:5000"):
                yield

            os.environ['CONFIG_PATH'] = orig_config_path

    def xmldiff(self, xml1, xml2):
        def sorted_attrs(elem):
            # Sort attributes and recursively apply to children
            elem.attrib = dict(sorted(elem.attrib.items()))
            for child in elem:
                sorted_attrs(child)
            return elem

        xml1 = ElementTree.tostring(sorted_attrs(ElementTree.fromstring(xml1)), encoding='utf-8', method='xml').decode()
        xml2 = ElementTree.tostring(sorted_attrs(ElementTree.fromstring(xml2)), encoding='utf-8', method='xml').decode()
        lines1 = [line.strip() for line in xml1.splitlines()]
        lines2 = [line.strip() for line in xml2.splitlines()]
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

    def jsondiff(self, json1, json2):
        json1 = json.dumps(json.loads(json1), indent=2, sort_keys=True, ensure_ascii=False)
        json2 = json.dumps(json.loads(json2), indent=2, sort_keys=True, ensure_ascii=False)
        lines1 = [line.strip() for line in json1.splitlines()]
        lines2 = [line.strip() for line in json2.splitlines()]
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

    def jwtHeader(self):
        with self.server.app.test_request_context():
            access_token = create_access_token('test')
        return {'Authorization': f'Bearer {access_token}'}

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
        headers = {"X-Qgis-Service-Url": f"http://localhost/ows/{service}"}
        return requests.get(qgis_server_url + "/" + service, params=params, headers=headers)

    def qgs_post(self, service, params, data):
        qgis_server_url = os.getenv('QGIS_SERVER_URL', 'http://localhost:8001/ows/').rstrip('/')
        headers = {"X-Qgis-Service-Url": f"http://localhost/ows/{service}", "Content-Type": data["contentType"]}
        return requests.post(qgis_server_url + "/" + service, params=params, data=data["body"], headers=headers)
