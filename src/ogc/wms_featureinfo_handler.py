import base64
import copy
import html
import json
import locale
import math
import os
import re
import traceback
from datetime import datetime
from importlib import import_module
from typing import override
from xml.dom.minidom import parseString

import jinja2
import psycopg
from flask import Response, jsonify, request
from geomet import wkt
from psycopg.rows import dict_row

from ogc.ogc_service_handler import ServiceException
from ogc.wms_handler import WmsHandler

DATETIME_CONVERSION_RULES = [
    {"parse": "%Y-%m-%dT%H:%M:%S.%f", "format": "%d.%m.%Y %H:%M:%S"},
    {"parse": "%Y-%m-%dT%H:%M:%S", "format": "%d.%m.%Y %H:%M:%S"},
    {"parse": "%Y-%m-%d", "format": "%d.%m.%Y"}
]

XML_LAYER_TEMPLATE = jinja2.Template("""
  <Layer title="{{ layer_title|e }}" name="{{ layer_name|e }}" layerinfo="{{ (parent_facade or layer_name)|e }}"
    {{- ' featurereport="%s"' | format(feature_report) if feature_report }}
    {{- ' displayfield="%s"' | format(display_field) if display_field }}>
    {%- for feature in features %}
    <Feature id="{{ feature['id'] }}">
      {%- if feature['html_content'] %}
      <HtmlContent inline="1">{{feature['html_content']|e}}</HtmlContent>
      {%- endif %}
      {%- if feature['bbox'] %}
      <BoundingBox CRS="{{ crs }}"
        minx="{{ feature['bbox'][0] }}" miny="{{ feature['bbox'][1] }}"
        maxx="{{ feature['bbox'][2] }}" maxy="{{ feature['bbox'][3] }}"
      />
      {%- endif %}
      {%- if feature['geometry'] %}
      <Attribute name="geometry" value="{{ feature['geometry'] }}" type="derived" />
      {%- endif %}
      {%- for atr in feature['attributes'] %}
      <Attribute name="{{ atr['alias']|e }}" value="{{ render_value(atr['value'], atr)|e }}" attrname="{{ atr['name']|e }}" />
      {%- endfor %}
    </Feature>
    {%- endfor %}
  </Layer>
""")


class InfoFeature(object):
    """ Wrapper around feature passed to HTML templates. """
    def __init__(self, feature):
        self._attributes = feature['attributes']
        for attr in self._attributes:
            setattr(self, attr['name'], attr['value'])


class WmsFeatureInfoHandler(WmsHandler):
    """ Handler for GetFeatureInfo requests. """

    def __init__(self, logger, config, qgis_server_url, permission_handler, identity):
        """
        :param obj logger: Application logger
        :param obj config: Service config
        :param obj qgis_server_url: internal QGIS Server URL
        :param obj permission_handler: Permission handler
        :param obj identity: User identity
        """
        super().__init__(logger, config, qgis_server_url, permission_handler, identity)

        self.default_info_template = None
        self.default_info_template_dir = None
        if config.get('default_info_template'):
            self.default_info_template = config.get('default_info_template')
        elif config.get('default_info_template_path'):
            try:
                with open(config.get('default_info_template_path'), 'r') as fh:
                    self.default_info_template = fh.read()
                self.default_info_template_dir = os.path.dirname(config.get('default_info_template_path'))
            except OSError:
                self.logger.warning(
                    f"Failed to read default template from path {config.get('default_info_template_path')}"
                )
        elif config.get('default_info_template_base64'):
            self.default_info_template = base64.b64decode(
                config.get('default_info_template_base64')
            ).decode('utf-8')

        self.transform_image_urls = config.get('transform_image_urls', True)
        self.skip_empty_attributes = config.get('skip_empty_attributes', False)
        self.use_resource_attribute_order = config.get('use_resource_attribute_order', False)
        self.info_templates_path = config.get('info_templates_path', '/info_templates/')
        self.data_service_url = config.get('data_service_url', '/api/v1/data/').rstrip('/')
        self.date_conversion_rules = config.get('date_conversion_rules', DATETIME_CONVERSION_RULES)
        self.link_text = config.get('info_link_text', '\\1')

        if not self.data_service_url.startswith('http'):
            origin = request.origin or ""
            headers = request.headers
            if not origin and headers.get("Host") and headers.get("X-Forwarded-Proto"):
                origin = headers.get("X-Forwarded-Proto") + "://" + headers.get("Host")
            self.data_service_url = origin + self.data_service_url

    @staticmethod
    @override
    def accepts(req):
        """Whether the handler handle the specified request.

        :param OgcRequest req: The OGC request
        """
        return req.service == 'WMS' and req.request == 'GETFEATUREINFO'

    @override
    def adjust_request_params(self, req, permissions):
        """Check request parameters against permissions and adjust params, returning the adjusted OgcRequest

        :param OgcRequest req: The OGC request
        :param obj permissions: OGC service permissions
        """
        super().adjust_request_params(req, permissions)

        # Calculate query coordinates and resolutions
        try:
            bbox = list(map(float, req.params["BBOX"].split(",")))
            req.aux_params['x'] = 0.5 * (bbox[0] + bbox[2])
            req.aux_params['y'] = 0.5 * (bbox[1] + bbox[3])
            xres = (bbox[2] - bbox[0]) / float(req.params['WIDTH'])
            yres = (bbox[3] - bbox[1]) / float(req.params['HEIGHT'])
            req.aux_params['resolution'] = max(xres, yres)
        except Exception:
            raise ServiceException('InvalidParameterValue', "The parameters 'BBOX', 'WIDTH', 'HEIGHT' are missing or invalid.")

    @override
    def process_request(self, req, permissions, stream):
        """ Process the request.

        :param OgcRequest req: The OGC request
        :param bool stream: Whether the response will be streamed
        :param obj permissions: OGC service permissions
        """
        layers = req.params['LAYERS'].split(',')
        styles = req.params['STYLES'].split(',')

        layer_infos = []
        for layer, style in zip(layers, styles):
            layer_permissions = permissions['permitted_layers'][layer]
            if not layer_permissions.get('queryable'):
                continue

            features = []
            error = False
            info_template = self.resolve_template(req.service_name, layer, layer_permissions['info_template'])
            info_type = info_template.get('type')
            self.logger.debug(f"Info type for layer {layer} is {info_type}")
            if info_type == 'wms':
                features = self.wms_layer_info(layer, style, req, info_template, permissions)
            elif info_type == 'sql':
                try:
                    features = self.sql_layer_info(layer, style, req, info_template)
                except Exception as e:
                    self.logger.debug(traceback.format_exc())
                    self.logger.error(f"Failed to execute SQL layer info query for layer {layer}: {e!s}")
                    error = True
            elif info_type == 'module':
                # custom module
                try:
                    # import custom layer info method
                    module_name = info_template.get('module')
                    custom_module = import_module(f'ogc.custom_info_modules.{module_name}')
                    layer_info = getattr(custom_module, 'layer_info')

                    features = layer_info(
                        layer, req.aux_params['x'], req.aux_params['y'], req.params['CRS'], req.params, self.identity
                    )['features']
                    for f in features:
                        f["attributes"] = {attr["name"]: attr["value"] for attr in f["attributes"]}
                except ImportError as e:
                    self.logger.error(f"Failed to import custom info module {module_name} for layer {layer}: {e!s}")
                    error = True
                except AttributeError as e:
                    self.logger.error(f"Failed to call custom info module {module_name} for layer {layer}: {e!s}")
                    error = True
                except Exception:
                    self.logger.error(
                        f"Exception in custom info module '{module_name}' for layer {layer}: {traceback.format_exc()}"
                    )
                    error = True
            else:
                self.logger.debug("Skipping layer with unknown info type")
                continue

            if not error:
                layer_infos.append({
                    "layer_name": layer,
                    "layer_title": layer_permissions["title"],
                    "features": features,
                    "info_template": info_template,
                    'display_field': layer_permissions["display_field"],
                    'feature_report': layer_permissions["feature_report"],
                    'parent_facade': layer_permissions["parent_facade"]
                })

        return layer_infos

    def wms_layer_info(self, layer, style, req, info_template, permissions):
        """ Query the layer info by forwarding the request to the QGIS Server. """
        local_req = copy.copy(req)
        local_req.params = {
            'SERVICE': 'WMS',
            'VERSION': '1.3.0',
            'REQUEST': 'GetFeatureInfo',
            'INFO_FORMAT': 'text/xml',
            'LAYERS': layer,
            'STYLES': style,
            'QUERY_LAYERS': layer
        }
        if info_template.get('wms_url'):
            # Use layer specific WMS
            local_req.server_url = info_template['wms_url']

        # Additional supported params as per QGIS Server documentation
        local_req.params.update({k: req.params.get(k) for k in [
            'CRS', 'BBOX', 'WIDTH', 'HEIGHT', 'FEATURE_COUNT', 'I', 'J', 'WMS_PRECISION', 'FILTER', 'FILTER_GEOM',
            'FI_POINT_TOLERANCE', 'FI_LINE_TOLERANCE', 'FI_POLYGON_TOLERANCE',
            'WITH_DISPLAY_NAME', 'WITH_MAPTIP', 'WITH_GEOMETRY'
        ]})

        # Forward to QGIS Server
        response = super().process_request(local_req, permissions, False)

        # NOTE: reverse lookup for attribute names from alias, as QGIS Server returns aliases
        permitted_attributes = permissions['permitted_layers'][layer]['attributes']
        alias_attributes = {attr['alias']: attr['name'] for attr in permitted_attributes.values()}

        # Build response object
        features = []
        document = parseString(response.content.decode())
        for layerEl in document.getElementsByTagName('Layer'):
            featureEls = layerEl.getElementsByTagName('Feature')
            for featureEl in featureEls:
                # Vector layer
                feature_id = featureEl.getAttribute('id')
                attributes = {}
                bbox = None
                geometry = None
                for attrEl in featureEl.getElementsByTagName('Attribute'):
                    info_name = attrEl.getAttribute('name')
                    name = alias_attributes.get(info_name, info_name)
                    value = attrEl.getAttribute('value')
                    if name == 'geometry' and attrEl.getAttribute('type') == 'derived':
                        geometry = value
                    else:
                        attributes[name] = value

                # Parse bbox
                for bboxEl in featureEl.getElementsByTagName('BoundingBox'):
                    bbox = [
                        float(bboxEl.getAttribute('minx')),
                        float(bboxEl.getAttribute('miny')),
                        float(bboxEl.getAttribute('maxx')),
                        float(bboxEl.getAttribute('maxy'))
                    ]
                features.append({
                    'id': feature_id,
                    'attributes': attributes,
                    'bbox': bbox,
                    'geometry': geometry
                })
            if not featureEls:
                # No features => raster layer
                attributes = {}
                for attrEl in layerEl.getElementsByTagName('Attribute'):
                    name = attrEl.getAttribute('name')
                    value = attrEl.getAttribute('value')
                    attributes[name] = value
                if attributes:
                    features.append({
                        'attributes': attributes
                    })
        return features

    def sql_layer_info(self, layer, style, req, info_template):
        """ Query the layer info via SQL query. """
        database = info_template['db_url']
        if info_template.get('sql_base64'):
            sql = base64.b64decode(info_template.get('sql_base64')).decode('utf-8')
        else:
            sql = info_template['sql']
        fid_column = info_template.get('fid_column', '_fid_')
        geom_column = info_template.get('geom_column', 'wkt_geom')
        bbox_column = info_template.get('bbox_column', 'bbox')
        x = req.aux_params['x']
        y = req.aux_params['y']

        sql_params = {}
        sql_params['X'] = x
        sql_params['Y'] = y
        sql_params['SRID'] = int(req.params['CRS'].split(':')[-1])
        sql_params['RESOLUTION'] = req.aux_params['resolution']
        sql_params['GEOM'] = req.params.get('FILTER_GEOM', f'POINT({x} {y})')
        for param in [
            'I', 'J', 'HEIGHT', 'WIDTH', 'BBOX', 'CRS', 'FEATURE_COUNT', 'WITH_GEOMETRY', 'WITH_MAPTIP',
            'FI_POINT_TOLERANCE', 'FI_LINE_TOLERANCE', 'FI_POLYGON_TOLERANCE'
        ]:
            sql_params[param] = req.params.get(param)
        # NOTE: provide also lower case keys
        sql_params.update({k.lower(): v for k, v in sql_params.items()})

        features = []
        adj_sql = re.sub(r"(?<!:):([A-Za-z_]\w*)", r"%(\1)s", sql)
        if adj_sql != sql:
            self.logger.warning(
                f"Replaced SQLAlchemy-style placeholders with psycopg-style placeholders in SQL query for layer '{layer}'. "
                "Please adjust the queries to use '%(<placeholder>)s' instead of ':<placeholder>'"
            )
            sql = adj_sql
        self.logger.debug(sql)
        self.logger.debug(sql_params)
        with psycopg.connect(database, row_factory=dict_row) as conn:
            for row in conn.execute(sql, sql_params):
                fid = row.pop(fid_column, None)
                geom = row.pop(geom_column, None)
                bbox = row.pop(bbox_column, None)
                if isinstance(bbox, str):
                    try:
                        bbox = [float(x) for x in re.split('[ ,]+', re.match(r"^BOX\(([^)]+)\)", bbox).group(1))]
                    except Exception:
                        bbox = None
                features.append({
                    'id': fid,
                    'attributes': dict(row),
                    'bbox': bbox,
                    'geometry': geom
                })
        return features

    @override
    def build_response(self, req, response, permissions, stream):
        """Build the (possibly filtered) response.

        :param OgcRequest req: The OGC request
        :param obj response: The request response
        :param obj permissions: OGC service permissions
        :param bool stream: Whether to stream the response
        """
        info_format = req.params.get('INFO_FORMAT').lower()
        geomcentroid = req.params.get('GEOMCENTROID', "false").lower() in ["true", "1"]
        with_bbox = req.params.get('WITH_BBOX', "true").lower() in ["true", "1"]
        with_geometry = req.params.get('WITH_GEOMETRY', "false").lower() in ["true", "1"]
        layerattribs = json.loads(req.params.get('LAYERATTRIBS', '[]'))

        # Format and filter attributes
        for layer_info in response:
            permitted_attributes = permissions['permitted_layers'][layer_info['layer_name']]['attributes']
            dataset_name = f"{req.service_name}.{layer_info['layer_name']}"
            if layerattribs:
                permitted_attributes = {
                    attrName: attr for attrName, attr in permitted_attributes.items() if attrName in layerattribs
                }

            for feature in layer_info['features']:
                if self.use_resource_attribute_order:
                    feature['attributes'] = [
                        {
                            'name': name,
                            'value': (v1 := self.format_attribute_value(
                                feature['attributes'][name], permitted_attributes[name], dataset_name
                            )),
                            'alias': permitted_attributes[name]['alias'],
                            'type': type(v1).__name__,
                            'json_aliases': {
                                entry["name"]: entry["alias"]
                                for entry in permitted_attributes[name].get('json_attributes', [])
                            }
                        }
                        for name in permitted_attributes if name in feature['attributes']
                    ]
                else:
                    feature['attributes'] = [
                        {
                            'name': name,
                            'value': (v2 := self.format_attribute_value(
                                value, permitted_attributes.get(name), dataset_name
                            )),
                            'alias': permitted_attributes[name]['alias'],
                            'type': type(v2).__name__,
                            'json_aliases': {
                                entry["name"]: entry["alias"]
                                for entry in permitted_attributes[name].get('json_attributes', [])
                            }
                        }
                        for name, value in feature['attributes'].items() if name in permitted_attributes
                    ]
                if self.skip_empty_attributes:
                    feature['attributes'] = list(filter(lambda attr: attr['value'], feature['attributes']))

                # Honour with_geometry, geomcentroid, with_bbox
                if not with_geometry or "geometry" not in permitted_attributes:
                    feature['geometry'] = None
                    feature['bbox'] = None
                elif geomcentroid and feature['geometry']:
                    gj = wkt.loads(feature['geometry'].upper().replace('Z',''))
                    feature['geometry'] = wkt.dumps({
                        "type": "Point",
                        "coordinates": self.geom_center(gj["type"], gj["coordinates"])[0:2]
                    })
                    feature['bbox'] = None
                elif not with_bbox:
                    feature['bbox'] = None

        if info_format == 'text/html':
            return self.build_response_html(response, req)
        elif info_format == 'text/plain':
            return self.build_response_text(response)
        elif info_format == 'application/json':
            return self.build_response_json(response, req)
        elif info_format == 'text/xml':
            return self.build_response_xml(response, req)
        else:
            raise ServiceException(
                "InvalidFormat",
                f"Feature info format '{info_format}' is unsupported. " +
                "Supported are 'text/plain', 'text/html', 'application/json', 'text/xml'."
            )

    def build_response_html(self, response, req):
        """ Build a text/html GetFeatureInfo response. """

        info_response = (
            '<!DOCTYPE html>\n'
            '<html>\n'
            '<head>\n'
            '<title>Information</title>\n'
            '<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />\n'
            '<style>\n'
            'body {\n'
            '  font-family: "Open Sans", "Calluna Sans", "Gill Sans MT", "Calibri", "Trebuchet MS", sans-serif;\n'
            '}\n'
            'table, th, td {\n'
            '  width: 100%; border: 1px solid black; border-collapse: collapse; text-align: left; padding: 2px;\n'
            '}\n'
            'th { width: 25%; font-weight: bold; }\n'
            '.layer-title { font-weight: bold; padding: 2px; }\n'
            '</style>\n'
            '</head>\n'
            '<body>\n'
        )
        for layer_info in response:
            info_response += f'<div class="layer-title">{html.escape(layer_info["layer_title"])}</div>\n'
            for feature in layer_info["features"]:
                template = layer_info['info_template'].get('template')
                if template:
                    info_template = layer_info['info_template']
                    info_response += '<div>\n'
                    info_response += self.render_template(info_template, layer_info["layer_name"], feature, req) + '\n'
                    info_response += '</div>\n'
                else:
                    info_response += '<table>\n'
                    for attr in feature['attributes']:
                        info_response += '<tr>\n'
                        info_response += f'<th>{html.escape(attr["alias"])}</th><td>{html.escape(attr["value"])}</td>'
                        info_response += '</tr>\n'
                    info_response += '</table>\n'
        info_response += '</body>\n'
        return Response(info_response, content_type="text/html")

    def build_response_text(self, response):
        """ Build a text/plain GetFeatureInfo response. """
        info_response = ''
        for layer_info in response:
            info_response += f'Layer \'{layer_info["layer_title"]}\'\n\n'
            for feature in layer_info["features"]:
                info_response += '\n'.join((f"{attr['alias']} = \'{attr['value']}\'" for attr in feature['attributes']))
                info_response += '\n\n'
            info_response + '\n'
        return Response(info_response, content_type="text/plain")

    def build_response_json(self, response, req):
        """ Build a application/json GetFeatureInfo response. """
        features = []
        collection_bbox = None
        has_geometry = False
        for layer_info in response:
            for feature in layer_info['features']:
                if bb := feature.get('bbox'):
                    collection_bbox = [
                        min(bb[0], collection_bbox[0]), min(bb[1], collection_bbox[1]),
                        max(bb[2], collection_bbox[2]), max(bb[3], collection_bbox[3])
                    ] if collection_bbox else bb
                feature_json = {
                    "type": "Feature",
                    "layerName": layer_info["layer_title"],
                    "id": feature['id'],
                    "geometry": wkt.loads(feature['geometry'].upper().replace('Z','')) if feature['geometry'] else None,
                    "properties": {attr["alias"]: attr["value"] for attr in feature['attributes']}
                }
                has_geometry |= feature_json["geometry"] is not None
                if feature['bbox']:
                    feature_json["bbox"] = feature['bbox']
                features.append(feature_json)
        collection_json = {
            "type": "FeatureCollection",
            "features": features
        }
        if has_geometry:
            collection_json["crs"] = {
                "type": "name",
                "properties": {
                    "name": f"urn:ogc:def:crs:{req.params['CRS'].replace(':', '::')}"
                }
            },
        if collection_bbox:
            collection_json["bbox"] = collection_bbox
        return jsonify(collection_json)

    def build_response_xml(self, response, req):
        """ Build a text/xml GetFeatureInfo response. """
        with_htmlcontent = req.params.get('WITH_HTMLCONTENT', "true").lower() in ["true", "1"]

        info_response = '<GetFeatureInfoResponse>'

        for layer_info in response:
            for feature in layer_info['features']:

                template = layer_info['info_template'].get('template')
                if with_htmlcontent and template:
                    info_template = layer_info['info_template']
                    feature['html_content'] = self.render_template(info_template, layer_info["layer_name"], feature, req)
                else:
                    feature['html_content'] = None

            info_response += XML_LAYER_TEMPLATE.render(
                layer_name=layer_info["layer_name"],
                layer_title=layer_info['layer_title'],
                features=layer_info['features'],
                display_field=layer_info['display_field'],
                feature_report=layer_info['feature_report'],
                parent_facade=layer_info['parent_facade'],
                crs=req.params['CRS'],
                render_value=self.render_template_value
            )

        info_response += "\n</GetFeatureInfoResponse>"
        return Response(info_response, content_type="text/xml")

    def resolve_template(self, service_name, layer, info_template):
        """ Resolves the HTML info template for the specified layer. """

        # Resolve template
        # - "template", as specified in resource config
        # - "template_base64", as specified in resource config
        # - "template_path", as specified in resource config
        # - Autodetect in self.info_templates_path
        # - Default template if all this fails

        info_template = info_template or {}
        info_template['type'] = info_template.get('type', 'wms')

        if not info_template.get('template'):
            if info_template.get('template_base64'):
                info_template['template'] = base64.b64decode(info_template.get('template_base64')).decode('utf-8')
                info_template['template_dir'] = self.default_info_template_dir
            elif info_template.get('template_path'):
                try:
                    with open(info_template['template_path'], 'r') as fh:
                        info_template['template'] = fh.read()
                    info_template['template_dir'] = os.path.dirname(info_template['template_path'])
                except Exception:
                    self.logger.warning(f"Failed to read template from '{info_template['template_path']}'")
            else:
                # Autodetect info template
                template_path = os.path.join(self.info_templates_path, service_name, layer + '.html')
                self.logger.debug(f"Looking for info template '{template_path}' for layer '{layer}'...")
                try:
                    with open(template_path, 'r') as fh:
                        info_template['template'] = fh.read()
                        info_template['template_dir'] = os.path.dirname(template_path)
                    self.logger.debug(f"Found info template '{template_path}' for layer '{layer}'...")
                except Exception:
                    pass
        if not info_template.get('template'):
            info_template['template'] = self.default_info_template
            info_template['template_dir'] = self.default_info_template_dir

        return info_template

    def format_attribute_value(self, value, permitted_attribute, dataset_name):
        """ Formats an attribute value (independently of the GetFeatureInfo output format). """
        # Empty string instead of NULL
        if value == "NULL":
            return ''

        # Handle datetime formats
        if isinstance(value, str):
            for rule in self.date_conversion_rules:
                try:
                    return format(datetime.strptime(value, rule["parse"]), rule["format"])
                except Exception:
                    pass

        if permitted_attribute.get('format'):
            formatstr = permitted_attribute['format']
            # Format according to formatstr
            if formatstr.startswith('{'):
                # JSON dict as lookup table
                return json.loads(formatstr).get(value, value)
            else:
                # Format value according to type spec in format
                # https://docs.python.org/3/library/string.html#format-specification-mini-language
                try:
                    typechar = formatstr[-1]
                    if typechar in 'bcdoxXn':
                        value = int(value)
                    elif typechar in 'eEfFgGn%':
                        value = float(value)
                    return format(value, formatstr)
                except Exception as e:
                    self.logger.warn(f"Error formatting attribute value '{value}' with format '{formatstr}': {e!s}")
                    return value
        elif not isinstance(value, str):
            return value
        elif (value.startswith('{') and value.endswith('}')) or (value.startswith('[') and value.endswith(']')):
            # Handle JSON attributes
            try:
                json_value = json.loads(value)
            except Exception as e:
                self.logger.warn(f"Error parsing attribute value '{value}' as JSON: {e!s}")
                return value
            json_aliases = {entry["name"]: entry["alias"] for entry in permitted_attribute.get('json_attributes', {})}
            if isinstance(json_value, list) and json_aliases:
                # Reorder item keys according to JSON aliases
                # NOTE: skip any keys not in JSON aliases
                json_value = [
                    {json_aliases[key]: item[key] for key in json_aliases if key in item}
                    for item in json_value
                ]
            elif isinstance(json_value, dict) and json_aliases:
                json_value = {json_aliases[key]: json_value[key] for key in json_aliases if key in json_value}
            return json_value

        elif value.startswith("attachment://"):
            return f"{self.data_service_url}/{dataset_name}/attachment?file={value[13:]}"
        return value

    def render_template(self, info_template, layer_name, feature, req):
        # Render the template
        template_loader = None
        template = info_template['template']
        template_dir = info_template.get('template_dir')
        if template_dir:
            template_loader = jinja2.FileSystemLoader(searchpath=template_dir)
        templateEnv = jinja2.Environment(loader=template_loader, autoescape=True)
        feature_template = templateEnv.from_string(template)
        return feature_template.render(
            feature=InfoFeature(feature),
            fid=feature['id'],
            bbox=feature['bbox'],
            geometry=feature['geometry'],
            layer=layer_name,
            x=req.aux_params['x'], y=req.aux_params['y'],
            crs=req.params['CRS'],
            render_value=self.render_template_value,
            locale=locale, request=request
        )

    def render_template_value(self, value, attr=None):
        """Renders a value inside a HTML info template, applying transformation rules as necessary. """
        if isinstance(value, str):
            # If value is already html (i.e. begins with a valid HTML tag), return it as is
            if bool(re.match(r'\s*<[a-z][^>]*>', value, re.I)):
                return value

            value = value.replace("\n", "<br />")
            rules = []

            if self.transform_image_urls:
                # Images
                rules.append((
                    r'^(https?:\/\/.*\.(jpg|jpeg|png|bmp|svg))$',
                    lambda m: m.expand(r'<a href="\1" target="_blank"><img src="\1" /></a>')
                ))

            # HTML links
            rules.append((
                r'^(https?:\/\/.*)$',
                lambda m: m.expand(r'<a href="\1" target="_blank">{link_text}</a>'.format(link_text=self.link_text))
            ))
            # E-Mails
            rules.append((
                r'^(mailto:)?([\w\-\.]+@([\w-]+\.)+[\w-]{2,63})$',
                lambda m: m.expand(r'<a href="mailto:\2">\2</a>')
            ))

            for rule in rules:
                match = re.match(rule[0], value, re.IGNORECASE)
                if match:
                    value = rule[1](match)
                    break

            return value

        elif isinstance(value, list):
            result = '<table class="identify-attr-subtable"><tbody>'
            for item in value:
                if isinstance(item, dict):
                    for key in item:
                        alias = attr['json_aliases'].get(key, key)
                        result += '<tr>' + \
                            f'<td class="identify-attr-title-wrap"><i>{html.escape(alias)}</i></td>' + \
                            f'<td class="identify-attr-value wrap">{self.render_template_value(item[key])}</td>' + \
                            '</tr>'
                else:
                    result += '<tr>' + \
                        '<td class="identify-attr-value identify-attr-single-value wrap" colspan="2">' + \
                        self.render_template_value(item) + \
                        '</td>' + \
                        '</tr>'
                result += '<tr><td class="identify-attr-spacer" colspan="2"></td></tr>'

            result += '</tbody></table>'
            return result

        elif isinstance(value, dict):
            result = '<table class="identify-attr-subtable"><tbody>'
            for key in value:
                alias = attr['json_aliases'].get(key, key)
                result += '<tr>' + \
                    f'<td class="identify-attr-title-wrap"><i>{html.escape(alias)}</i></td>' + \
                    f'<td class="identify-attr-value wrap">{self.render_template_value(value[key])}</td>' + \
                    '</tr>'
            result += '</tbody></table>'
            return result
        else:
            return value

    def geom_center(self, geomtype, coordinates):
        """ Computes the center of a GeoJSON geometry. """
        if geomtype.startswith("Multi"):
            return self.geom_center(geomtype[5:], coordinates[0])
        elif geomtype == "Point":
            return coordinates
        elif geomtype == "LineString":
            cumlengths = [0]
            for i in range(1, len(coordinates)):
                dx = coordinates[i][0] - coordinates[i - 1][0]
                dy = coordinates[i][1] - coordinates[i - 1][1]
                cumlengths.append(cumlengths[i - 1] + math.sqrt(dx * dx + dy * dy))
            halflen = 0.5 * cumlengths[-1]
            for i in range(1, len(cumlengths)):
                if cumlengths[i] > halflen:
                    mu = (halflen - cumlengths[i - 1]) / (cumlengths[i] - cumlengths[i - 1])
                    return [
                        coordinates[i - 1][0] + mu * (coordinates[i][0] - coordinates[i - 1][0]),
                        coordinates[i - 1][1] + mu * (coordinates[i][1] - coordinates[i - 1][1])
                    ]
        elif geomtype == "Polygon":
            ring = coordinates[0]
            area = 0
            cx = cy = 0
            for i in range(0, len(ring) - 1):
                t = ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
                area += t
                cx += (ring[i][0] + ring[i + 1][0]) * t
                cy += (ring[i][1] + ring[i + 1][1]) * t

            return [cx / (3 * area), cy / (3 * area)]
