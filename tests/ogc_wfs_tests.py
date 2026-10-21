import re
from copy import deepcopy

from ogc.ogc_service_handler import OgcRequest
from ogc.wfs_handler import WfsHandler, wfs_clean_attribute_name, wfs_clean_layer_name
from tests.ogc_tests import OgcTests


class OgcWfsTests(OgcTests):

    WFS_PERMISSIONS = {
        "wfs_services": [
            {
                "name": "wfs_test",
                "layers": [
                    {
                        "name": wfs_clean_layer_name("ÖV: Linien"),
                        "attributes": [
                            wfs_clean_attribute_name(attr) for attr in ["fid", "id", "nummer", "beschreibung"]
                        ],
                        "creatable": False,
                        "updatable": False,
                        "deletable": False
                    },
                    {
                        "name": wfs_clean_layer_name("ÖV: Haltestellen"),
                        "attributes": [
                            wfs_clean_attribute_name(attr) for attr in ["fid", "id", "name", "eingeführt am", "eigentümer"]
                        ],
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
                        "attributes": [
                            {"name": wfs_clean_attribute_name(attr), "alias": attr}
                            for attr in ["fid", "id", "nummer", "beschreibung"]
                        ]
                    },
                    {
                        "name": wfs_clean_layer_name("ÖV: Haltestellen"),
                        "attributes": [
                            {"name": wfs_clean_attribute_name(attr), "alias": attr}
                            for attr in ["fid", "id", "name", "eingeführt am", "eigentümer"]
                        ]
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
        with self.use_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
            ogc_response = self.ogc_get('wfs_test', params)
        self.assertTrue('Request GETNONEXISTING is not supported' in ogc_response.text)

    ### WFS GetCapabilites ###

    def GETCAPABILITIES_PARAMS(self, version): return {'SERVICE': 'WFS', 'REQUEST': 'GetCapabilities', 'VERSION' : version}

    def test_wfs_capabilities(self):
        ### Check unfiltered GetCapabilities ###
        for version, colon in [("1.0.0", ":"), ("1.1.0", "-")]:
            params = self.GETCAPABILITIES_PARAMS(version)

            with self.use_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = self.xmldiff(qgs_response.text, ogc_response.text)
            self.assertEqual([], diff, f"Unfiltered {version} GetCapabilities contain no changes")

    def test_wfs_capabilities_missing_layer(self):
        ### Check filtered GetCapabilities (missing layer) ###
        for version, colon in [("1.0.0", ":"), ("1.1.0", "-")]:
            params = self.GETCAPABILITIES_PARAMS(version)

            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(
                lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'),
                permissions['wfs_services'][0]['layers']
            ))
            with self.use_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            self.assertTrue(
                f'ÖV{colon}_Haltestellen' in qgs_response.text,
                f'Original {version} GetCapabilities contains ÖV{colon}_Haltestellen'
            )
            self.assertTrue(
                'ÖV: Haltestellen' in qgs_response.text,
                f'Original {version} GetCapabilities contains ÖV: Haltestellen'
            )
            self.assertFalse(
                f'ÖV{colon}_Haltestellen' in ogc_response.text,
                f'Original {version} GetCapabilities contains ÖV{colon}_Haltestellen'
            )
            self.assertFalse(
                'ÖV: Haltestellen' in ogc_response.text,
                f'Filtered {version} GetCapabilities does not contain ÖV: Haltestellen'
            )

    ### WFS DescribeFeatureType ###

    def DESCRIBEFEATURETYPE_PARAMS(self, version): return {
        'SERVICE': 'WFS', 'REQUEST': 'DescribeFeatureType', 'VERSION': version
    }

    def test_wfs_describefeaturetype(self):
        ### Check unfiltered DescribeFeatureType ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.DESCRIBEFEATURETYPE_PARAMS(version)

            with self.use_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = self.xmldiff(qgs_response.text, ogc_response.text)
            self.assertEqual([], diff, "Unfiltered DescribeFeatureType contains no changes")

    def test_wfs_describefeaturetype_restricted_attribute(self):
        ### Check filtered DescribeFeatureType (restricted attribute) ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.DESCRIBEFEATURETYPE_PARAMS(version)

            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['attributes'] = [
                attr for attr in permissions['wfs_services'][0]['layers'][1]['attributes']
                if attr != wfs_clean_attribute_name('eingeführt am')
            ]
            with self.use_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = self.xmldiff(qgs_response.text, ogc_response.text)
            self.assertTrue(
                'eingeführt_am' in qgs_response.text, 'Original DescribeFeatureType contains eingeführt_am'
            )
            self.assertFalse(
                'eingeführt_am' in ogc_response.text, 'Filtered DescribeFeatureType does not contain eingeführt_am'
            )
            self.assertEqual(
                diff, [{'op': 'remove', 'old': '<element name="eingeführt_am" nillable="true" type="date" />'}],
                "Filtered DescribeFeatureType omits the Attribute eingeführt_am"
            )

    def test_wfs_describefeaturetype_restricted_layer(self):
        ### Check filtered DescribeFeatureType (restricted layer) ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.DESCRIBEFEATURETYPE_PARAMS(version)

            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(
                lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'),
                permissions['wfs_services'][0]['layers']
            ))
            with self.use_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = self.xmldiff(qgs_response.text, ogc_response.text)
            self.assertTrue(
                'ÖV-_Haltestellen' in qgs_response.text, 'Original DescribeFeatureType contains ÖV-_Haltestellen'
            )
            self.assertFalse(
                'ÖV-_Haltestellen' in ogc_response.text, 'Filtered DescribeFeatureType does not contain ÖV-_Haltestellen'
            )
            removed_element = (
                '<element name="ÖV-_Haltestellen" substitutionGroup="gml:_Feature" type="qgs:ÖV-_HaltestellenType" />\n'
                '<complexType name="ÖV-_HaltestellenType">\n'
                '<complexContent>\n'
                '<extension base="gml:AbstractFeatureType">\n'
                '<sequence>\n'
                '<element maxOccurs="1" minOccurs="0" name="geometry" type="gml:PointPropertyType" />\n'
                '<element name="fid" type="long" />\n'
                '<element name="id" nillable="true" type="int" />\n'
                '<element alias="Name" name="name" nillable="true" type="string" />\n'
                '<element name="eingeführt_am" nillable="true" type="date" />\n'
                '<element alias="Eigentümer" name="eigentümer" nillable="true" type="string" />\n'
                '</sequence>\n'
                '</extension>\n'
                '</complexContent>\n'
                '</complexType>'
            )
            self.assertEqual(
                diff, [{'op': 'remove', 'old': removed_element}],
                "Filtered DescribeFeatureType omits the FeatureType for ÖV: Haltestellen"
            )

    def test_wfs_describefeaturetype_missing_layer(self):
        ### Check filtered DescribeFeatureType (missing layer in TYPENAME) ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.DESCRIBEFEATURETYPE_PARAMS(version)
            params['TYPENAME'] = wfs_clean_layer_name('ÖV-_Haltestellen')

            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(
                lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'),
                permissions['wfs_services'][0]['layers']
            ))
            with self.use_config(self.WFS_RESOURCES, permissions):
                ogc_response = self.ogc_get('wfs_test', params)
            self.assertTrue(
                "TypeName 'ÖV-_Haltestellen' could not be found or is not permitted" in ogc_response.text,
                'Filtered DescribeFeatureType with non-permitted layer in TYPENAME returns a ServiceExceptionReport'
            )

    ### WFS GetFeature ###

    def GETFEATURE_PARAMS(self, version, outputformat): return {
        'SERVICE': 'WFS',
        'VERSION': version,
        'REQUEST': 'GetFeature',
        'OUTPUTFORMAT': outputformat,
        'TYPENAME': 'ÖV-_Haltestellen,ÖV-_Linien'
    }

    def test_wfs_getfeature_gml(self):
        ### Check unfiltered GML GetFeature ###
        for version, outputformat in [("1.0.0", "GML2"), ("1.1.0", "GML2"), ("1.1.0", "GML3")]:
            params = self.GETFEATURE_PARAMS(version, outputformat)

            with self.use_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = self.xmldiff(qgs_response.text, ogc_response.text)
            self.assertEqual([], diff, f"Unfiltered {version} {outputformat} GetFeature contains no changes")

    def test_wfs_getfeature_gml_restricted_attribute(self):
        ### Check filtered GML GetFeature (restricted attribute) ###
        for version, outputformat in [("1.0.0", "GML2"), ("1.1.0", "GML2"), ("1.1.0", "GML3")]:
            params = self.GETFEATURE_PARAMS(version, outputformat)

            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['attributes'] = [
                attr for attr in permissions['wfs_services'][0]['layers'][1]['attributes']
                if attr != wfs_clean_attribute_name('eingeführt am')
            ]
            with self.use_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            self.assertTrue(
                'eingeführt_am' in qgs_response.text, f'Original {version} {outputformat} GetFeature contains eingeführt_am'
            )
            self.assertFalse(
                'eingeführt_am' in ogc_response.text,
                f'Filtered {version} {outputformat} GetFeature does not contain eingeführt_am'
            )

    def test_wfs_getfeature_gml_restricted_layer(self):
        ### Check filtered GML GetFeature (restricted layer) ###
        for version, outputformat in [("1.0.0", "GML2"), ("1.1.0", "GML2"), ("1.1.0", "GML3")]:
            params = self.GETFEATURE_PARAMS(version, outputformat)

            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(
                lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'),
                permissions['wfs_services'][0]['layers']
            ))
            with self.use_config(self.WFS_RESOURCES, permissions):
                ogc_response = self.ogc_get('wfs_test', params)
            self.assertTrue(
                "TypeName 'ÖV-_Haltestellen' could not be found or is not permitted" in ogc_response.text,
                'Filtered GetFeature with non-permitted layer in TYPENAME returns a ServiceExceptionReport'
            )

    def test_wfs_getfeature_geojson(self):
        ### Check unfiltered GeoJSON GetFeature ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.GETFEATURE_PARAMS(version, 'GEOJSON')

            with self.use_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            diff = self.jsondiff(qgs_response.text, ogc_response.text)
            self.assertEqual([], diff, f"Unfiltered {version} GetFeature contains no changes")

    def test_wfs_getfeature_geojson_restricted_attribute(self):
        ### Check filtered GeoJSON GetFeature (restricted attribute) ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.GETFEATURE_PARAMS(version, 'GEOJSON')

            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['attributes'] = [
                attr for attr in permissions['wfs_services'][0]['layers'][1]['attributes']
                if attr != wfs_clean_attribute_name('eingeführt am')
            ]
            with self.use_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_get('wfs_test', params)
                ogc_response = self.ogc_get('wfs_test', params)
            self.assertTrue(
                'eingeführt am' in qgs_response.text, f'Original {version} GetFeature contains eingeführt am'
            )
            self.assertFalse(
                'eingeführt am' in ogc_response.text, f'Filtered {version} GetFeature does not contain eingeführt am'
            )

    def test_wfs_getfeature_geojson_restricted_layer(self):
        ### Check filtered GeoJSON GetFeature (restricted layer) ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.GETFEATURE_PARAMS(version, 'GEOJSON')

            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(
                filter(lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'),
                permissions['wfs_services'][0]['layers'])
            )
            with self.use_config(self.WFS_RESOURCES, permissions):
                ogc_response = self.ogc_get('wfs_test', params)
            self.assertTrue(
                "TypeName 'ÖV-_Haltestellen' could not be found or is not permitted" in ogc_response.text,
                'Filtered GetFeature with non-permitted layer in TYPENAME returns a ServiceExceptionReport'
            )

    ### WFS Transactions ###

    def TRANSACTION_PARAMS(self, version): return {
        "SERVICE": "WFS", "VERSION": version, "REQUEST": "TRANSACTION"
    }

    def TRANSACTION_INSERT_PAYLOAD(self, version): return {"body":
        """<?xml version="1.0" encoding="UTF-8"?>""" +
        f"""<wfs:Transaction service="WFS" version="{version}"
            xmlns:wfs="http://www.opengis.net/wfs" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xmlns:ogc="http://www.opengis.net/ogc" xmlns="http://www.opengis.net/wfs"
            updateSequence="0" xmlns:xlink="http://www.w3.org/1999/xlink"
            xsi:schemaLocation="http://www.opengis.net/wfs http://schemas.opengis.net/wfs/1.0.0/WFS-capabilities.xsd"
            xmlns:gml="http://www.opengis.net/gml"
            xmlns:ows="http://www.opengis.net/ows" xmlns:qgs="http://www.qgis.org/gml"
        >
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
    """, "contentType": "text/xml"}

    def TRANSACTION_UPDATE_PAYLOAD(self, version, fid): return {"body":
        """<?xml version="1.0" encoding="UTF-8"?>""" +
        f"""<wfs:Transaction service="WFS" version="{version}"
            xmlns:wfs="http://www.opengis.net/wfs" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xmlns:ogc="http://www.opengis.net/ogc" xmlns="http://www.opengis.net/wfs" updateSequence="0"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xsi:schemaLocation="http://www.opengis.net/wfs http://schemas.opengis.net/wfs/1.0.0/WFS-capabilities.xsd"
            xmlns:gml="http://www.opengis.net/gml"  xmlns:ows="http://www.opengis.net/ows"
        >
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
                    <ogc:FeatureId fid="{fid}"/>
                </ogc:Filter>
            </wfs:Update>
        </wfs:Transaction>
    """, "contentType": "text/xml"}

    def TRANSACTION_DELETE_PAYLOAD(self, version, fid): return {"body":
        """<?xml version="1.0" encoding="UTF-8"?>""" +
        f"""<wfs:Transaction service="WFS" version="{version}"
            xmlns:wfs="http://www.opengis.net/wfs" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xmlns:ogc="http://www.opengis.net/ogc" xmlns="http://www.opengis.net/wfs" updateSequence="0"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xsi:schemaLocation="http://www.opengis.net/wfs http://schemas.opengis.net/wfs/1.0.0/WFS-capabilities.xsd"
            xmlns:gml="http://www.opengis.net/gml"  xmlns:ows="http://www.opengis.net/ows"
        >
            <wfs:Delete typeName="ÖV-_Haltestellen">
                <ogc:Filter>
                    <ogc:FeatureId fid="{fid}"/>
                </ogc:Filter>
            </wfs:Delete>
        </wfs:Transaction>
    """, "contentType": "text/xml"}

    def test_wfs_transaction_unpermitted_insert(self):
        ### Check unpermitted insert ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.TRANSACTION_PARAMS(version)
            insert_data = self.TRANSACTION_INSERT_PAYLOAD(version)

            with self.use_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                ogc_response = self.ogc_post('wfs_test', params, insert_data)
            self.assertTrue(
                "No create permissions on typename 'ÖV-_Haltestellen'" in ogc_response.text,
                "Insert fails due to no create permissions"
            )

    def test_wfs_transaction_unpermitted_delete(self):
        ### Check unpermitted delete ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.TRANSACTION_PARAMS(version)
            delete_data = self.TRANSACTION_DELETE_PAYLOAD(version, "0")

            with self.use_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                ogc_response = self.ogc_post('wfs_test', params, delete_data)
            self.assertTrue(
                "No delete permissions on typename 'ÖV-_Haltestellen'" in ogc_response.text,
                "Insert fails due to no delete permissions"
            )

    def test_wfs_transaction_insert_delete(self):
        ### Check unfiltered insert and delete ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.TRANSACTION_PARAMS(version)
            insert_data = self.TRANSACTION_INSERT_PAYLOAD(version)

            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['creatable'] = True
            permissions['wfs_services'][0]['layers'][1]['deletable'] = True
            with self.use_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_post('wfs_test', params, insert_data)
                ogc_response = self.ogc_post('wfs_test', params, insert_data)
            diff = self.xmldiff(qgs_response.text, ogc_response.text)
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in ogc_response.text, f"SUCCESS status with {version} insert document")
            elif version == "1.1.0":
                self.assertTrue(
                    "<totalInserted>1</totalInserted>" in ogc_response.text,
                    f"One feature inserted with {version} insert document"
                )
            self.assertTrue(
                len(diff) == 1 and diff[0]["op"] == "replace" and diff[0]["old"].startswith("<ogc:FeatureId"),
                f"{version} insert transaction result unchanged up to the feature id"
            )
            ins_fid_qgs = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', qgs_response.text).group(1)
            ins_fid_ogc = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', ogc_response.text).group(1)

            delete_data_qgs = self.TRANSACTION_DELETE_PAYLOAD(version, ins_fid_qgs)
            delete_data_ogc = self.TRANSACTION_DELETE_PAYLOAD(version, ins_fid_ogc)
            with self.use_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_post('wfs_test', params, delete_data_qgs)
                ogc_response = self.ogc_post('wfs_test', params, delete_data_ogc)
            diff = self.xmldiff(qgs_response.text, ogc_response.text)
            self.assertEqual([], diff, f"Unfiltered {version} delete contains no changes")
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in ogc_response.text, f"SUCCESS status with {version} delete document")
            elif version == "1.1.0":
                self.assertTrue(
                    "<totalDeleted>1</totalDeleted>" in ogc_response.text,
                    f"One feature deleted with {version} delete document"
                )

    def test_wfs_transaction_insert_restricted_attribute(self):
        ### Check filtered insert (restricted attribute) ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.TRANSACTION_PARAMS(version)
            insert_data = self.TRANSACTION_INSERT_PAYLOAD(version)

            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['attributes'] = [
                attr for attr in permissions['wfs_services'][0]['layers'][1]['attributes']
                if attr != wfs_clean_attribute_name('eigentümer')
            ]
            permissions['wfs_services'][0]['layers'][1]['creatable'] = True
            permissions['wfs_services'][0]['layers'][1]['deletable'] = True
            # Check that transaction body is filtered correctly
            with self.use_config(self.WFS_RESOURCES, permissions):
                ogc_service = self.server.ogc_service_handler()
                ogc_permissions = ogc_service.service_permissions('test', 'wfs_test', 'WFS')
                handler = WfsHandler(self.server.app.logger, ogc_service.config, None, None, None)
            req = OgcRequest("qgis_server_url", "POST", "wfs_test", params, deepcopy(insert_data))
            req = handler.adjust_request_params(req, ogc_permissions)
            diff = self.xmldiff(insert_data['body'], req.data['body'])
            self.assertTrue(
                len(diff) == 1 and diff[0]["op"] == "remove" and "qgs:eigentümer" in diff[0]["old"],
                f"Filtered {version} insert transaction document does not contain attribute eigentümer"
            )

            # Do insert
            with self.use_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_post('wfs_test', params, insert_data)
                ogc_response = self.ogc_post('wfs_test', params, insert_data)
            diff = self.xmldiff(qgs_response.text, ogc_response.text)
            if version == "1.0.0":
                self.assertTrue(
                    "<SUCCESS/>" in qgs_response.text,
                    f"SUCCESS status with {version} insert document directly to qgs-server"
                )
                self.assertTrue(
                    "<SUCCESS/>" in ogc_response.text,
                    f"SUCCESS status with {version} insert document via ogc-service"
                )
            elif version == "1.1.0":
                self.assertTrue(
                    "<totalInserted>1</totalInserted>" in qgs_response.text,
                    f"One feature inserted with {version} insert document directly to qgs-server"
                )
                self.assertTrue(
                    "<totalInserted>1</totalInserted>" in ogc_response.text,
                    f"One feature inserted with {version} insert document via ogc-service"
                )
            self.assertTrue(
                len(diff) == 1 and diff[0]["op"] == "replace" and diff[0]["old"].startswith("<ogc:FeatureId"),
                f"{version} insert transaction result unchanged up to the feature id"
            )
            ins_fid_qgs = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', qgs_response.text).group(1)
            ins_fid_ogc = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', ogc_response.text).group(1)

            # Delete inserted features again
            delete_data_qgs = self.TRANSACTION_DELETE_PAYLOAD(version, ins_fid_qgs)
            delete_data_ogc = self.TRANSACTION_DELETE_PAYLOAD(version, ins_fid_ogc)
            with self.use_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_post('wfs_test', params, delete_data_qgs)
                ogc_response = self.ogc_post('wfs_test', params, delete_data_ogc)


    def test_wfs_transaction_insert_restricted_layer(self):
        ### Check filtered insert (restricted attribute) ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.TRANSACTION_PARAMS(version)
            insert_data = self.TRANSACTION_INSERT_PAYLOAD(version)

            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(
                lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'),
                permissions['wfs_services'][0]['layers']
            ))

            # Check that transaction body is filtered correctly
            with self.use_config(self.WFS_RESOURCES, permissions):
                ogc_service = self.server.ogc_service_handler()
                ogc_permissions = ogc_service.service_permissions('test', 'wfs_test', 'WFS')
                handler = WfsHandler(self.server.app.logger, ogc_service.config, None, None, None)
            req = OgcRequest("qgis_server_url", "POST", "wfs_test", params, deepcopy(insert_data))
            req = handler.adjust_request_params(req, ogc_permissions)
            self.assertTrue(
                "<qgs:ÖV-_Haltestellen>".encode() not in req.data['body'],
                f"Filtered {version} insert transaction document does not contain typename ÖV-_Haltestellen"
            )

            # Do insert
            with self.use_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_post('wfs_test', params, insert_data)
                ogc_response = self.ogc_post('wfs_test', params, insert_data)
            if version == "1.0.0":
                self.assertTrue(
                    "<SUCCESS/>" in qgs_response.text,
                    f"SUCCESS status with {version} insert document directly to qgs-server"
                )
            elif version == "1.1.0":
                self.assertTrue(
                    "<totalInserted>1</totalInserted>" in qgs_response.text,
                    f"One feature inserted with {version} insert document directly to qgs-server"
                )
            self.assertTrue(
                "The server encountered an internal error or misconfiguration" in ogc_response.text,
                f"Filtered {version} insert document returns error via ogc-service"
            )
            ins_fid_qgs = re.search(r'fid="ÖV-_Haltestellen.(\d+)"', qgs_response.text).group(1)

            # Check filtered delete (missing layer)
            delete_data_qgs = self.TRANSACTION_DELETE_PAYLOAD(version, ins_fid_qgs)
            with self.use_config(self.WFS_RESOURCES, permissions):
                ogc_service = self.server.ogc_service_handler()
                ogc_permissions = ogc_service.service_permissions('test', 'wfs_test', 'WFS')
                handler = WfsHandler(self.server.app.logger, ogc_service.config, None, None, None)

            req = OgcRequest("qgis_server_url", "POST", "wfs_test", params, deepcopy(insert_data))
            req = handler.adjust_request_params(req, ogc_permissions)
            self.assertTrue(
                "<wfs:Delete typeName=\"ÖV-_Haltestellen\">".encode() not in req.data['body'],
                f"Filtered {version} delete transaction document does not contain typename ÖV-_Haltestellen"
            )
            self.assertTrue(
                '<ogc:FeatureId fid="ÖV-_Haltestellen.'.encode() not in req.data['body'],
                f"Filtered {version} delete transaction document does not contain typename ÖV-_Haltestellen"
            )

            with self.use_config(self.WFS_RESOURCES, permissions):
                qgs_response = self.qgs_post('wfs_test', params, delete_data_qgs)
                ogc_response = self.ogc_post('wfs_test', params, delete_data_qgs)

            if version == "1.0.0":
                self.assertTrue(
                    "<SUCCESS/>" in qgs_response.text, f"SUCCESS status with {version} delete document"
                )
                self.assertTrue(
                    "The server encountered an internal error" in ogc_response.text,
                    f"SUCCESS status with {version} delete document"
                )
            elif version == "1.1.0":
                self.assertTrue(
                    "<totalDeleted>1</totalDeleted>" in qgs_response.text,
                    f"One feature deleted with {version} delete document directly to qgs-server"
                )
                self.assertTrue(
                    "The server encountered an internal error" in ogc_response.text,
                    f"Zero features deleted with filtered {version} delete document via ogc-service"
                )

            ### Test DELETE via QUERY ###
            # delete_params = {
            #   "VERSION": version,
            #   "REQUEST": "TRANSACTION",
            #   "OPERATION": "DELETE",
            #   "FEATUREID": "ÖV-_Haltestellen." + ins_fid_qgs
            # }
            # qgs_text, ogc_text = self.__wfs_request("wfs_test", delete_params, permitted_layer_attributes)


    def test_wfs_transaction_update_unpermitted(self):
        ### Check unpermitted update ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.TRANSACTION_PARAMS(version)
            update_data = self.TRANSACTION_UPDATE_PAYLOAD(version, "1")

            with self.use_config(self.WFS_RESOURCES, self.WFS_PERMISSIONS):
                ogc_response = self.ogc_post('wfs_test', params, update_data)
            self.assertTrue(
                "No update permissions on typename 'ÖV-_Haltestellen'" in ogc_response.text,
                "Insert fails due to no create permissions"
            )

    def test_wfs_transaction_update(self):
        ### Check unfiltered update ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.TRANSACTION_PARAMS(version)
            update_data = self.TRANSACTION_UPDATE_PAYLOAD(version, "1")

            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['updatable'] = True
            with self.use_config(self.WFS_RESOURCES, permissions):
                ogc_response = self.ogc_post('wfs_test', params, update_data)
                qgs_response = self.qgs_post('wfs_test', params, update_data)
            diff = self.xmldiff(qgs_response.text, ogc_response.text)
            self.assertEqual([], diff, f"Unfiltered {version} update contains no changes")
            if version == "1.0.0":
                self.assertTrue("<SUCCESS/>" in ogc_response.text, f"SUCCESS status with {version} update document")
            elif version == "1.1.0":
                self.assertTrue(
                    "<totalUpdated>1</totalUpdated>" in ogc_response.text,
                    f"One feature updated with {version} update document"
                )

    def test_wfs_transaction_update_restricted_attribute(self):
        ### Check filtered update (restricted attribute) ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.TRANSACTION_PARAMS(version)
            update_data = self.TRANSACTION_UPDATE_PAYLOAD(version, "1")

            permissions = deepcopy(self.WFS_PERMISSIONS)
            self.assertEqual(permissions['wfs_services'][0]['layers'][1]['name'], wfs_clean_layer_name('ÖV: Haltestellen'))
            permissions['wfs_services'][0]['layers'][1]['attributes'] = [
                attr for attr in permissions['wfs_services'][0]['layers'][1]['attributes']
                if attr != wfs_clean_attribute_name('eigentümer')
            ]
            permissions['wfs_services'][0]['layers'][1]['updatable'] = True

            # Check that transaction body is filtered correctly
            with self.use_config(self.WFS_RESOURCES, permissions):
                ogc_service = self.server.ogc_service_handler()
                ogc_permissions = ogc_service.service_permissions('test', 'wfs_test', 'WFS')
                handler = WfsHandler(self.server.app.logger, ogc_service.config, None, None, None)
            req = OgcRequest("qgis_server_url", "POST", "wfs_test", params, deepcopy(update_data))
            req = handler.adjust_request_params(req, ogc_permissions)
            diff = self.xmldiff(update_data["body"], req.data["body"])
            self.assertTrue(
                len(diff) == 1 and diff[0]["op"] == "remove" and "<wfs:Name>eigentümer</wfs:Name>" in diff[0]["old"],
                f"Filtered {version} update transaction document does not contain attribute eigentümer"
            )

            with self.use_config(self.WFS_RESOURCES, permissions):
                ogc_response = self.ogc_post('wfs_test', params, update_data)
                qgs_response = self.qgs_post('wfs_test', params, update_data)
            diff = self.xmldiff(qgs_response.text, ogc_response.text)
            self.assertEqual(diff, [], f"{version} update transaction result unchanged")
            if version == "1.0.0":
                self.assertTrue(
                    "<SUCCESS/>" in qgs_response.text, f"SUCCESS status with {version} update document directly to qgs-server"
                )
                self.assertTrue(
                    "<SUCCESS/>" in qgs_response.text, f"SUCCESS status with {version} update document via ogc-service"
                )
            elif version == "1.1.0":
                self.assertTrue(
                    "<totalUpdated>1</totalUpdated>" in qgs_response.text,
                    f"One feature updated with {version} update document directly to qgs-server")
                self.assertTrue(
                    "<totalUpdated>1</totalUpdated>" in qgs_response.text,
                    f"One feature updated with {version} update document via ogc-service"
                )


    def test_wfs_transaction_update_restricted_layer(self):
        ### Check filtered update (restricted layer) ###
        for version in ["1.0.0", "1.1.0"]:
            params = self.TRANSACTION_PARAMS(version)
            update_data = self.TRANSACTION_UPDATE_PAYLOAD(version, "1")

            permissions = deepcopy(self.WFS_PERMISSIONS)
            permissions['wfs_services'][0]['layers'] = list(filter(
                lambda layer: layer['name'] != wfs_clean_layer_name('ÖV: Haltestellen'),
                permissions['wfs_services'][0]['layers']
            ))

            # Check that transaction body is filtered correctly
            with self.use_config(self.WFS_RESOURCES, permissions):
                ogc_service = self.server.ogc_service_handler()
                ogc_permissions = ogc_service.service_permissions('test', 'wfs_test', 'WFS')
                handler = WfsHandler(self.server.app.logger, ogc_service.config, None, None, None)
            req = OgcRequest("qgis_server_url", "POST", "wfs_test", params, deepcopy(update_data))
            req = handler.adjust_request_params(req, ogc_permissions)
            self.assertTrue(
                '<wfs:Update typeName="ÖV-_Haltestellen">'.encode() not in req.data['body'],
                f"Filtered {version} update transaction document does not contain typename ÖV-_Haltestellen"
            )

            with self.use_config(self.WFS_RESOURCES, permissions):
                ogc_response = self.ogc_post('wfs_test', params, update_data)
                qgs_response = self.qgs_post('wfs_test', params, update_data)
            if version == "1.0.0":
                self.assertTrue(
                    "<SUCCESS/>" in qgs_response.text,
                    f"SUCCESS status with {version} update document directly to qgs-server"
                )
            elif version == "1.1.0":
                self.assertTrue(
                    "<totalUpdated>1</totalUpdated>" in qgs_response.text,
                    f"One feature updated with {version} update document directly to qgs-server"
                )
            self.assertTrue(
                "The server encountered an internal error or misconfiguration" in ogc_response.text,
                f"Filtered {version} update document returns error via ogc-service"
            )
