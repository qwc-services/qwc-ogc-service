import os
import re
import requests
import unittest
import tempfile
import difflib

from flask import Response, json
from flask.testing import FlaskClient
from flask_jwt_extended import JWTManager, create_access_token
from urllib.parse import urlparse, parse_qs, unquote, urlencode

import server
from wfs_handler import wfs_clean_layer_name, wfs_clean_attribute_name

JWTManager(server.app)


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

class OgcApiTestCase(unittest.TestCase):
    """Test case for OGC API server"""

    def setUp(self):
        server.app.testing = True
        self.app = FlaskClient(server.app, Response)

    def tearDown(self):
        pass

    def jwtHeader(self):
        with server.app.test_request_context():
            access_token = create_access_token('test')
        return {'Authorization': 'Bearer {}'.format(access_token)}

    # OAPI/Features
    WFS_TEST_LAYER_ATTRIBUTES = {
        "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}, "readable": True},
        "ÖV: Haltestellen": {"attributes": {"fid": "fid", "id": "id", "name": "Name", "eingeführt am": "eingeführt am", "eigentümer": "Eigentümer"}, "readable": True}
    }

    def __oapi_request(self, method, service, api_path, all_layer_attributes, permitted_layer_attributes, data=None):
        with tempfile.TemporaryDirectory() as tmpdirpath:
            # Ensure tenant handler cache is empty
            server.tenant_handler.handler_cache = {}

            orig_config_path = os.environ.get('CONFIG_PATH', "")
            os.environ['CONFIG_PATH'] = tmpdirpath
            os.mkdir(os.path.join(tmpdirpath, "default"))
            default_qgis_server_url = os.getenv('DEFAULT_QGIS_SERVER_URL', 'http://localhost:8001/ows/')
            oapi_qgis_server_url = os.getenv('OAPI_QGIS_SERVER_URL', 'http://localhost:8001/wfs3/')
            qgis_server_url_tenant_suffix = os.getenv('QGIS_SERVER_URL_TENANT_SUFFIX', '')

            with open(os.path.join(tmpdirpath, "default", "permissions.json"), "w") as fh:
                permissions = {
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
                                            "name": wfs_clean_layer_name(kv[0]),
                                            "readable": kv[1].get("readable", True),
                                            "writable": kv[1].get("writable", False),
                                            "creatable": kv[1].get("creatable", False),
                                            "updatable": kv[1].get("updatable", False),
                                            "deletable": kv[1].get("deletable", False),
                                            "attributes": [
                                                wfs_clean_attribute_name(attr) for attr in kv[1]["attributes"]
                                            ]
                                        }, permitted_layer_attributes.items()))
                                    }
                                ]
                            }
                        }
                    ]
                }
                json.dump(permissions, fh)

            with open(os.path.join(tmpdirpath, "default", "ogcConfig.json"), "w") as fh:
                ogcConfig = {
                    "$schema": "https://github.com/qwc-services/qwc-ogc-service/raw/master/schemas/qwc-ogc-service.json",
                    "service": "ogc",
                    "config": {
                        "default_qgis_server_url": default_qgis_server_url,
                        "oapi_qgis_server_url": oapi_qgis_server_url,
                        "qgis_server_url_tenant_suffix": qgis_server_url_tenant_suffix
                    },
                    "resources": {
                        "wfs_services": [
                            {
                                "name": service,
                                "layers": list(map(lambda kv: {
                                    "name": wfs_clean_layer_name(kv[0]),
                                    "attributes": dict([
                                        (wfs_clean_attribute_name(aa[0]), aa[1])
                                        for aa in kv[1]["attributes"].items()
                                    ])
                                }, permitted_layer_attributes.items()))
                            }
                        ]
                    }
                }
                json.dump(ogcConfig, fh)

            if method == "GET":
                response = self.app.get('/' + service + api_path, headers=self.jwtHeader())
            elif method == "POST":
                response = self.app.post('/' + service + api_path, json=data, headers=self.jwtHeader())
            elif method == "PUT":
                response = self.app.put('/' + service + api_path, json=data, headers=self.jwtHeader())
            elif method == "PATCH":
                response = self.app.patch('/' + service + api_path, json=data, headers=self.jwtHeader())
            elif method == "DELETE":
                response = self.app.delete('/' + service + api_path, json=data, headers=self.jwtHeader())

            # Revert CONFIG_PATH change
            os.environ['CONFIG_PATH'] = orig_config_path

            return response


    def test_collections(self):
        response = self.__oapi_request("GET", "wfs_test", "/features/collections.json", self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES)
        json = response.json
        self.assertTrue(len(list(filter(lambda c: c['id'] == 'ÖV: Linien', json.get('collections', [])))) == 1, "'wfs_test/features/collections' contains 'ÖV: Linien'")
        self.assertTrue(len(list(filter(lambda c: c['id'] == 'ÖV: Haltestellen', json.get('collections', [])))) == 1, "'wfs_test/features/collections contains 'ÖV: Haltestellen'")

    def test_unpermitted_collections(self):
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}},
        }
        response = self.__oapi_request("GET", "wfs_test", "/features/collections.json", self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
        json = response.json
        self.assertTrue(len(list(filter(lambda c: c['id'] == 'ÖV: Linien', json.get('collections', [])))) == 1, "'wfs_test/features/collections' contains 'ÖV: Linien'")
        self.assertTrue(len(list(filter(lambda c: c['id'] == 'ÖV: Haltestellen', json.get('collections', [])))) == 0, "'wfs_test/features/collections' does not contain 'ÖV: Haltestellen'")

    def test_collection(self):
        response = self.__oapi_request("GET", "wfs_test", "/features/collections/ÖV: Haltestellen.json", self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES)
        json = response.json
        self.assertEqual(json["id"], "ÖV: Haltestellen", "'wfs_test/features/collections/ÖV: Haltestellen collection' id is 'ÖV: Haltestellen'")

    def test_unpermitted_collection(self):
        # Not permitted (no permission entry)
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}},
        }
        response = self.__oapi_request("GET", "wfs_test", "/features/collections/ÖV: Haltestellen.json", self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json[0]["code"], "API not found error")

        # Not permitted (readable=false)
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}, "readable": True},
            "ÖV: Haltestellen": {"attributes": {"fid": "fid", "id": "id", "name": "Name", "eingeführt am": "eingeführt am"}, "readable": False}
        }
        response = self.__oapi_request("GET", "wfs_test", "/features/collections/ÖV: Haltestellen.json", self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json[0]["code"], "API not found error")

    def test_getfeatures(self):
        response = self.__oapi_request("GET", "wfs_test", "/features/collections/ÖV: Haltestellen/items.json", self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES)
        json = response.json
        self.assertTrue(len(json.get('features', [])) > 0, "'wfs_test/features/collections/ÖV: Haltestellen/items' contains features")
        for attr, alias in self.WFS_TEST_LAYER_ATTRIBUTES['ÖV: Haltestellen']['attributes'].items():
            self.assertTrue(alias in json['features'][0].get('properties', {}), "'wfs_test/features/collections/ÖV: Haltestellen/items' feature properties contains '%s'" % alias)

    def test_getfeatures_filter(self):
        response = self.__oapi_request("GET", "wfs_test", "/features/collections/ÖV: Haltestellen/items.json?name=Bächlistrasse", self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES)
        json = response.json
        self.assertTrue(len(json.get('features', [])) == 1, "'wfs_test/features/collections/ÖV: Haltestellen/items' contains one feature")

    def test_unpermitted_layer_getfeatures(self):
        # Not permitted (no permission entry)
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}, "readable": True},
        }
        response = self.__oapi_request("GET", "wfs_test", "/features/collections/ÖV: Haltestellen/items.json", self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json[0]["code"], "API not found error")
        # Not permitted (readable=false)
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}, "readable": True},
            "ÖV: Haltestellen": {"attributes": {"fid": "fid", "id": "id", "name": "Name", "eingeführt am": "eingeführt am"}, "readable": False}
        }
        response = self.__oapi_request("GET", "wfs_test", "/features/collections/ÖV: Haltestellen/items.json", self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json[0]["code"], "API not found error")

    def test_unpermitted_attrib_getfeatures(self):
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}, "readable": True},
            "ÖV: Haltestellen": {"attributes": {"fid": "fid", "id": "id", "name": "Name", "eingeführt am": "eingeführt am"}, "readable": True}
        }
        response = self.__oapi_request("GET", "wfs_test", "/features/collections/ÖV: Haltestellen/items.json", self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
        json = response.json
        self.assertTrue(len(json.get('features', [])) > 0, "'wfs_test/features/collections/ÖV: Haltestellen/items' contains features")
        for attr, alias in permitted_layer_attributes['ÖV: Haltestellen']['attributes'].items():
            self.assertTrue(alias in json['features'][0].get('properties', {}), "'wfs_test/features/collections/ÖV: Haltestellen/items' feature properties contains '%s'" % alias)
        self.assertTrue("Eigentümer" not in json['features'][0].get('properties', {}), "'wfs_test/features/collections/ÖV: Haltestellen/items' feature properties does not contain 'eigentümer'")

    def test_getfeature(self):
        response = self.__oapi_request("GET", "wfs_test", "/features/collections/ÖV: Haltestellen/items/1.json", self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES)
        json = response.json
        self.assertTrue(json['id'] == '1', "'wfs_test/features/collections/ÖV: Haltestellen/items/1' id is '1'")
        for attr, alias in self.WFS_TEST_LAYER_ATTRIBUTES['ÖV: Haltestellen']['attributes'].items():
            self.assertTrue(alias in json.get('properties', {}), "'wfs_test/features/collections/ÖV: Haltestellen/items/1' feature properties contains '%s'" % alias)

    def test_unpermitted_layer_getfeature(self):
        # Not permitted (no permission entry)
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}, "readable": True},
        }
        response = self.__oapi_request("GET", "wfs_test", "/features/collections/ÖV: Haltestellen/items/1.json", self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json[0]["code"], "API not found error")

        # Not permitted (readable=false)
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}, "readable": True},
            "ÖV: Haltestellen": {"attributes": {"fid": "fid", "id": "id", "name": "Name", "eingeführt am": "eingeführt am"}, "readable": False}
        }
        response = self.__oapi_request("GET", "wfs_test", "/features/collections/ÖV: Haltestellen/items/1.json", self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json[0]["code"], "API not found error")

    def test_unpermitted_attrib_getfeature(self):
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}, "readable": True},
            "ÖV: Haltestellen": {"attributes": {"fid": "fid", "id": "id", "name": "Name", "eingeführt am": "eingeführt am"}, "readable": True}
        }
        response = self.__oapi_request("GET", "wfs_test", "/features/collections/ÖV: Haltestellen/items/1.json", self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
        json = response.json
        self.assertTrue(json['id'] == '1', "'wfs_test/features/collections/ÖV: Haltestellen/items/1' id is '1'")
        for attr, alias in permitted_layer_attributes['ÖV: Haltestellen']['attributes'].items():
            self.assertTrue(alias in json.get('properties', {}), "'wfs_test/features/collections/ÖV: Haltestellen/items/1' feature properties contains '%s'" % alias)
        self.assertTrue("Eigentümer" not in json.get('properties', {}), "'wfs_test/features/collections/ÖV: Haltestellen/items/1' feature properties does not contain 'eigentümer'")

    def test_post_put_patch_delete_features(self):
        data = {
            "type": "Feature",
            "id": "3",
            "properties": {
                "name": "Bahnhofstrasse",
                "eigentümer": "Test",
                "eingeführt am": "2025-07-17"
            },
            "geometry": {
                "type": "Point",
                "coordinates": [0, 0]
            }
        }
        data_2 = {
            "type": "Feature",
            "id": "3",
            "properties": {
                "name": "Seestrasse",
                "eigentümer": "Test2",
                "eingeführt am": "2025-07-18"
            },
            "geometry": {
                "type": "Point",
                "coordinates": [0, 0]
            }
        }
        data_patch = {
            "modify": {
                "eigentümer": "Patchtest"
            }
        }

        # POST: Not permitted (no permission entry)
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}},
        }
        response = self.__oapi_request("POST", "wfs_test", "/features/collections/ÖV: Haltestellen/items", self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes, data)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json[0]["code"], "API not found error")

        # POST: Not permitted (only "readable")
        response = self.__oapi_request("POST", "wfs_test", "/features/collections/ÖV: Haltestellen/items", self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES, data)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json[0]["code"], "Forbidden")

        # POST: Permitted (creatable=true), but with non permitted eigentümer attribute
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}},
            "ÖV: Haltestellen": {"attributes": {"fid": "fid", "id": "id", "name": "Name", "eingeführt am": "eingeführt am"}, "writable": True, "creatable": True}
        }
        response = self.__oapi_request("POST", "wfs_test", "/features/collections/ÖV: Haltestellen/items", self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes, data)
        self.assertEqual(response.status_code, 201)
        location = unquote(response.headers.get('Location', ''))
        self.assertTrue(location.startswith("/wfs_test/features/collections/ÖV: Haltestellen/items/"), "Check location header")
        inserted_id = location.split("/")[-1]
        self.assertTrue(inserted_id != "")

        # Check inserted feature
        item_path = "/" + "/".join(location.split("/")[2:])
        response = self.__oapi_request("GET", "wfs_test", item_path, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES)
        json = response.json
        attr_aliases = self.WFS_TEST_LAYER_ATTRIBUTES["ÖV: Haltestellen"]["attributes"]
        for attr, value in data["properties"].items():
            if attr != "eigentümer":
                self.assertEqual(json.get("properties", {}).get(attr_aliases[attr]), value, "Inserted feature contains %s = %s" % (attr, value))
        self.assertEqual(json.get("properties", {}).get(attr_aliases["eigentümer"]), None, "Filtered attribute is empty")

        # PUT: Not permitted (no permission entry)
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}},
        }
        response = self.__oapi_request("PUT", "wfs_test", item_path, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes, data)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json[0]["code"], "API not found error")

        # PUT: Not permitted (updatable=false)
        response = self.__oapi_request("PUT", "wfs_test", item_path, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES, data_patch)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json[0]["code"], "Forbidden")

        # PUT: Permitted (updatable=true), but with non permitted eigentümer attribute
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}},
            "ÖV: Haltestellen": {"attributes": {"fid": "fid", "id": "id", "name": "Name", "eingeführt am": "eingeführt am"}, "writable": True, "updatable": True}
        }
        response = self.__oapi_request("PUT", "wfs_test", item_path, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes, data_2)
        json = response.json
        self.assertEqual(response.status_code, 200)
        for attr, value in data_2["properties"].items():
            if attr != "eigentümer":
                self.assertEqual(json.get("properties", {}).get(attr_aliases[attr]), value, "Inserted feature contains %s = %s" % (attr, value))
        self.assertEqual(json.get("properties", {}).get(attr_aliases["eigentümer"]), None, "Filtered attribute is empty")

        # PATCH: Not permitted (no permission entry)
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}},
        }
        response = self.__oapi_request("PATCH", "wfs_test", item_path, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes, data_patch)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json[0]["code"], "API not found error")

        # PATCH: Not permitted (updatable=false)
        response = self.__oapi_request("PATCH", "wfs_test", item_path, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES, data_patch)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json[0]["code"], "Forbidden")

        # PATCH: no-change (eigentümer not permitted)
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}},
            "ÖV: Haltestellen": {"attributes": {"fid": "fid", "id": "id", "name": "Name", "eingeführt am": "eingeführt am"}, "writable": True, "updatable": True}
        }
        response = self.__oapi_request("PATCH", "wfs_test", item_path, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes, data_patch)
        self.assertEqual(response.status_code, 200)
        self.assertTrue("Eigentümer" not in response.json["properties"])
        # Check patch performed no changes
        response = self.__oapi_request("GET", "wfs_test", item_path, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES)
        self.assertEqual(response.json["properties"]["Eigentümer"], None)


        # PATCH: Permitted (eigentümer not permitted)
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}},
            "ÖV: Haltestellen": {"attributes": {"fid": "fid", "id": "id", "name": "Name", "eingeführt am": "eingeführt am", "eigentümer": "Eigentümer"}, "writable": True, "updatable": True}
        }
        response = self.__oapi_request("PATCH", "wfs_test", item_path, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes, data_patch)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["properties"]["Eigentümer"], "Patchtest")

        # DELETE: Not permitted (not deleteable)
        response = self.__oapi_request("DELETE", "wfs_test", item_path, self.WFS_TEST_LAYER_ATTRIBUTES, self.WFS_TEST_LAYER_ATTRIBUTES)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json[0]["code"], "Forbidden")

        # DELETE: Permitted
        permitted_layer_attributes = {
            "ÖV: Linien": {"attributes": {"fid": "fid", "id": "id", "nummer": "Nummer", "beschreibung": "beschreibung"}},
            "ÖV: Haltestellen": {"attributes": {"fid": "fid", "id": "id", "name": "Name", "eingeführt am": "eingeführt am", "eigentümer": "Eigentümer"}, "writable": True, "deletable": True}
        }
        response = self.__oapi_request("DELETE", "wfs_test", item_path, self.WFS_TEST_LAYER_ATTRIBUTES, permitted_layer_attributes)
        self.assertEqual(response.status_code, 204)
