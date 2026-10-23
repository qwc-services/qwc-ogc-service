[![](https://github.com/qwc-services/qwc-ogc-service/workflows/build/badge.svg)](https://github.com/qwc-services/qwc-ogc-service/actions)
[![docker](https://img.shields.io/docker/v/sourcepole/qwc-ogc-service?label=Docker%20image&sort=semver)](https://hub.docker.com/r/sourcepole/qwc-ogc-service)

QWC OGC Service
===============

Provide OGC services with permission filters as a proxy to a QGIS server.

It suppports proxying WMS, WFS, WFS-T and OGC API Features.

Configuration
-------------

The static config and permission files are stored as JSON files in `$CONFIG_PATH` with subdirectories for each tenant,
e.g. `$CONFIG_PATH/default/*.json`. The default tenant name is `default`.


### Service config

* [JSON schema](schemas/qwc-ogc-service.json)
* File location: `$CONFIG_PATH/<tenant>/ogcConfig.json`

Example:
```json
{
  "$schema": "https://raw.githubusercontent.com/qwc-services/qwc-ogc-service/v2/schemas/qwc-ogc-service.json",
  "service": "ogc",
  "config": {
    "default_qgis_server_url": "http://localhost:8001/ows/",
    "oapi_qgis_server_url": "http://localhost:8001/wfs3/",
    "legend_images_path": "/legends",
    "print_label_queries": [
      {
        "db_url": "postgresql:///?service=fachdaten",
        "query": "SELECT 'Bearbeiter/in: ' ||  vorname || ' ' || nachname FROM benutzer WHERE username = $username$",
        "params": [
          "NAME"
        ]
      }
    ],
    "print_label_values": [
      {
        "field": "USERNAME",
        "value": "$username$"
      }
    ]
  },
  "resources": {
    "wms_services": [
      {
        "name": "qwc_demo",
        "wms_url": "http://localhost:8001/ows/qwc_demo",
        "online_resources": {
          "service": "http://localhost:5013/qwc_demo",
          "feature_info": "http://localhost:5013/qwc_demo",
          "legend": "http://localhost:5013/qwc_demo"
        },
        "root_layer": {
          "name": "qwc_demo",
          "layers": [
            {
              "name": "edit_demo",
              "layers": [
                {
                  "name": "edit_points",
                  "title": "Edit Points",
                  "attributes": [
                    {"name":"id", "alias":"id"},
                    {"name":"name", "alias":"Name"},
                    {"name":"description", "alias":"Description"},
                    {"name":"num", "alias":"Number"},
                    {"name":"value", "alias":"value"},
                    {"name":"type", "alias":"Type"},
                    {"name":"amount", "alias":"amount"},
                    {"name":"validated", "alias":"Validated"},
                    {"name":"datetime", "alias":"Date"},
                    {"name":"geometry", "alias":"geometry"},
                    {"name":"maptip", "alias":"maptip"}
                  ],
                  "queryable": true,
                  "legend_image": "edit_points.png",
                },
                {
                  "name": "edit_lines",
                  "title": "Edit Lines",
                  "attributes": [
                    {"name":"id", "alias":"id"},
                    {"name":"name", "alias":"Name"},
                    {"name":"description", "alias":"Description"},
                    {"name":"num", "alias":"Number"},
                    {"name":"value", "alias":"value"},
                    {"name":"type", "alias":"Type"},
                    {"name":"amount", "alias":"amount"},
                    {"name":"validated", "alias":"Validated"},
                    {"name":"datetime", "alias":"Date"},
                    {"name":"geometry", "alias":"geometry"},
                    {"name":"maptip", "alias":"maptip"}
                  ],
                  "queryable": true,
                  "legend_image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAHUlEQVQI12NgwAEYGRgY/tdjiDYyMOHSQQ8JnAAAUUoCDCaibn8AAAAASUVORK5CYII="
                },
                {
                  "name": "edit_polygons",
                  "title": "Edit Polygons",
                  "attributes": [
                    {"name":"id", "alias":"id"},
                    {"name":"name", "alias":"Name"},
                    {"name":"description", "alias":"Description"},
                    {"name":"num", "alias":"Number"},
                    {"name":"value", "alias":"value"},
                    {"name":"type", "alias":"Type"},
                    {"name":"amount", "alias":"amount"},
                    {"name":"validated", "alias":"Validated"},
                    {"name":"datetime", "alias":"Date"},
                    {"name":"geometry", "alias":"geometry"},
                    {"name":"maptip", "alias":"maptip"}
                  ],
                  "queryable": true
                }
              ]
            },
            {
              "name": "geographic_lines"
            },
            {
              "name": "country_names"
            },
            {
              "name": "states_provinces"
            },
            {
              "name": "countries",
              "title": "Countries",
              "attributes": [
                {"name":"name", "alias":"name"},
                {"name":"formal_en", "alias":"formal_en"},
                {"name":"pop_est", "alias":"pop_est"},
                {"name":"subregion", "alias":"subregion"},
                {"name":"geometry", "alias":"geometry"}
              ],
              "queryable": true
            }
          ]
        },
        "print_url": "http://localhost:5013/qwc_demo",
        "print_templates": ["A4 Landscape"],
        "internal_print_layers": ["bluemarble_bg", "osm_bg"]
      }
    ],
    "wfs_services": [
      {
        "name": "qwc_demo",
        "wfs_url": "http://localhost:8001/ows/qwc_demo_wfs",
        "online_resource": "http://localhost:5013/qwc_demo",
        "layers": [
          {
            "name": "edit_points",
            "attributes": [
              {"name":"id", "alias":"id"},
              {"name":"name", "alias":"Name"},
              {"name":"description", "alias":"Description"},
              {"name":"num", "alias":"Number"},
              {"name":"value", "alias":"value"},
              {"name":"type", "alias":"Type"},
              {"name":"amount", "alias":"amount"},
              {"name":"validated", "alias":"Validated"},
              {"name":"datetime", "alias":"Date"},
              {"name":"geometry","alias":"geometry"}
            ]
          },
          {
            "name": "edit_lines",
            "attributes": [
              {"name":"id", "alias":"id"},
              {"name":"name", "alias":"Name"},
              {"name":"description", "alias":"Description"},
              {"name":"num", "alias":"Number"},
              {"name":"value", "alias":"value"},
              {"name":"type", "alias":"Type"},
              {"name":"amount", "alias":"amount"},
              {"name":"validated", "alias":"Validated"},
              {"name":"datetime", "alias":"Date"},
              {"name":"geometry", "alias":"geometry"}
            ]
          }
        ]
      }
    ]
  }
}
```

### Environment variables

Config options in the config file can be overridden by equivalent uppercase environment variables.

### Permissions

* [JSON schema](https://github.com/qwc-services/qwc-services-core/blob/master/schemas/qwc-services-permissions.json)
* File location: `$CONFIG_PATH/<tenant>/permissions.json`

Example:
```json
{
  "$schema": "https://raw.githubusercontent.com/qwc-services/qwc-services-core/master/schemas/qwc-services-permissions.json",
  "users": [
    {
      "name": "demo",
      "groups": ["demo"],
      "roles": []
    }
  ],
  "groups": [
    {
      "name": "demo",
      "roles": ["demo"]
    }
  ],
  "roles": [
    {
      "role": "public",
      "permissions": {
        "wms_services": [
          {
            "name": "qwc_demo",
            "layers": [
              {
                "name": "qwc_demo"
              },
              {
                "name": "edit_demo"
              },
              {
                "name": "edit_points",
                "attributes": [
                  "id", "name", "description", "num", "value", "type", "amount", "validated", "datetime", "geometry", "maptip"
                ]
              },
              {
                "name": "edit_lines",
                "attributes": [
                  "id", "name", "description", "num", "value", "type", "amount", "validated", "datetime", "geometry", "maptip"
                ]
              },
              {
                "name": "edit_polygons",
                "attributes": [
                  "id", "name", "description", "num", "value", "type", "amount", "validated", "datetime", "geometry", "maptip"
                ]
              },
              {
                "name": "geographic_lines"
              },
              {
                "name": "country_names"
              },
              {
                "name": "states_provinces"
              },
              {
                "name": "countries",
                "attributes": [
                  "name", "formal_en", "pop_est", "subregion", "geometry"
                ]
              },
              {
                "name": "bluemarble_bg"
              },
              {
                "name": "osm_bg"
              }
            ],
            "print_templates": ["A4 Landscape"]
          }
        ]
      },
      "wfs_services": [
        {
          "name": "qwc_demo",
          "layers": [
            {
              "name": "edit_points",
              "attributes": [
                "id", "name", "description", "num", "value", "type", "amount", "validated", "datetime", "geometry"
              ]
            },
            {
              "name": "edit_lines",
              "attributes": [
                "id", "name", "description", "num", "value", "type", "amount", "validated", "datetime", "geometry"
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

**Note**: `layers` in `wms_services` is a flat list of all permitted layers, group layers and internal print layers.

### Supported services and landing page

The OGC Service supports:

- WMS

      http://<ogc-service-url>/<service_name>?SERVICE=WMS&VERSION=1.3.0&REQUEST=...

- WFS (version 1.0.0 and 1.1.0), including WFS-T

      http://<ogc-service-url>/<service_name>?SERVICE=WFS&VERSION=1.1.0&REQUEST=...

- OGC API features

      http://<ogc-service-url>/<service_name>/<features>

A landing page will be returned when requesting the service root endpoint (i.e. `http://<ogc-service-url>/`). It displays an overview of all available services/datasets.

The landing page is rendered from templates which are located at [src/templates/ogcapi](src/templates/ogcapi).
You can customize the landing page by modifying these templates, resp. if using Docker by mounting the modified templates to `/srv/qwc_service/templates/ogcapi/`.

### Basic Auth

The OGC service be configured to accept password authentication using Basic authentication.

Example:

```json
  "config": {
    "basic_auth_login_url": ["http://qwc-auth-service:9090/verify_login"]
  },
```

To force the `qwc-ogc-service` to return a `401 Unauthorized` response if not authenticated, pass `REQUIREAUTH=1` to the `WMS` or `WFS` request args, example:
```
http://<ogc-service-url>/<service_nae>?SERVICE=WMS&REQUEST=GetCapabilities&REQUIREAUTH=1
```

### Feature info

A range of option to customize the feature info responses are available.

**HTML Templates**

You can provide custom HTML templates for rendering the info results. These will be used for `text/html` as well as `text/xml` responses, in the latter case the FeatureInfo XML reponse will contain a `HtmlContent` element with the HTML output which QWC viewer will display.

A template can be specified as follows (in order of precedence):

- Via `template`, `template_base64` or `template_path` in the WMS layer resource configuration, i.e.
    ```json
    {
      "name": "edit_points",
      "attributes": [...],
      "info_template": {
        "template": "<Jinja2 template string>",
        "template_base64": "<base64 encoded Jinja2 template string>",
        "template_path": "<path to a html file containing a Jinja2 template>"
      }
    },
    ```
- Placing a `.html` file below `<info_templates_path>/<map_name>/<layer_name>.html`. This is usually the easier approach.


A template specified via resource configuration takes precedence over templates matched by filename below `info_templates_path`, as set in the service configuration.

*Note*: When running `qwc-ogc-service` in Docker, mount the info templates folder into the `qwc-ogc-service` container, i.e.:
```yml
  qwc-ogc-service:
    image: sourcepole/qwc-ogc-service:vYYYY.MM.DD
    volumes:
      ...
      - ./volumes/info_templates:/info_templates
```
and set `info_templates_path` to `/info_templates` in the service configuration. 

A template must only contain the body content (without `head`, `script`, `body`). The HTML can be styled using inline CSS, otherwise the CSS from the QWC viewer is used.

A template can contain attribute value placeholders, in the form `{{ feature.attr }}` which are replaced with the respective values when the template is rendered (using [Jinja2](http://jinja.pocoo.org/)).

The following values are available in the template:

* `x`, `y`, `crs`: Coordinates and CRS of info query
* `feature`: Feature with attributes from info result as properties, e.g. `feature.name`, as well as an `_attributes` array, see below.
* `fid`: Feature ID (if present)
* `bbox`: Feature bounding box as `[<minx>, <miny>, <maxx>, <maxy>]` (if present)
* `geometry`: Feature geometry as WKT (if present)
* `layer`: Layer name
* `render_value`: Function which detects special value formats and renders them accordingly
* `locale`: The [Locale module](https://docs.python.org/3/library/locale.html), allows i.e. locale aware number formatting
* `request`: The original request, useful for extracting i.e. request origin etc.

In particular:

- The `feature` object provides a list of its attributes:
    ```
    feature._attributes = [{
      'name': <attribute name>,
      'value': <attribute value>,
      'alias': <attribute alias>,
      'type': <attribute value data type as string>,
      'json_aliases': <JSON attribute aliases as {'json_key': 'value'}>
    }]
    ```
- The `render_value` function will transform:
  * Attribute values which match an image URL to an image if `transform_image_urls` is set to `true` in the service config.
  * Attribute values which match an URL to a clickable hyperlink, with the link text configurable via `info_link_text` in the service config.
  * Attribute values which match an email to a cllickable `mailto:` hyperlink.
  * Structured JSON attributes to subtables, as described below

- When the `qwc-ogc-service` Docker container, you can set the locale used by `locale` by setting the `LANG` environment variable. Since the `qwc-ogc-service` Docker image is based on Alpine and only contains minimal locale support, you may need to provide your own [locale convention](https://docs.python.org/3/library/locale.html?locale.localeconv) overrides, especially for number formatting, via the `LOCALECONV_OVERRIDES` environment variable. For example:
    ```yml
    environment:
      LANG: 'de_DE.UTF-8'
      LOCALECONV_OVERRIDES: '{"decimal_point": ",", "thousands_sep": "\'", "grouping": [3, 0]}'
    ```
    In a template, you can then use i.e. `{{ locale.format("%.3f", feature.number, grouping=True) }}`.

Example:

```xml
    <div>Result at coordinates {{ x }}, {{ y }}</div>
    <table>
        <tr>
            <td>Name:</td>
            <td>{{ feature.name }}</td>
        </tr>
        <tr>
            <td>Description:</td>
            <td>{{ feature.description }}</td>
        </tr>
        <tr>
            <td>Link:</td>
            <td>{{ render_value(feature.link) }}</td>
        </tr>
    </table>
```

When using [localized themes](https://docs.qwc.app/master/topics/Translations#translated-themes), you can make the QWC viewer translate the attribute names by enclosing these in `translate()`, i.e. `translate(Description)`.

**Structured JSON attribute values**

Attribute values which parse as JSON lists or dicts will be rendered as sub-tables in HTML templates if rendered via `render_value`.

The following formats are supported:

- Flat list, i.e. `["Value 1", "Value 2", ...]`
- Dictionaries, i.e. `{"key1: "Value 1", "key2": "Value 2", ...}`
- List of dictionaries, i.e. `[{"key1: "Value 1", "key2": "Value 2", ...}, {"key1: "Value 1", "key2": "Value 2", ...}]`

Keys can be mapped to aliases via `json_attributes`, i.e.
```json
{
  "name": "jsonfield",
  "alias": "JSON Field",
  "json_attributes": [
    {"name": "key1", "alias": "Key 1"},
    {"name": "key2", "alias": "Key 2"},
]}
```

**WMS, SQL and custom module info queries**

By default, WMS `GetFeatureInfo` are forwarded to the internal QGIS Server. You can instead query another server, or query a DB via SQL,
or implement a custom module which queries the feature from an arbitrary source.

*WMS query*:

Example configuration:
```json
"info_template": {
  "type": "wms",  
  "wms_url": "<Custom WMS URL if different from `default_qgis_server_url`>"
}
```

*DB query*:

Example configuration:
```json
"info_template": {
  "type": "sql",
  "db_url": "postgresql:///?service=qwc_geodb",
  "sql": "SELECT ogc_fid AS _fid_, name, formal_en, pop_est, subregion, ST_AsText(wkb_geometry) AS wkt_geom, Box2D(wkb_geometry) AS bbox FROM qwc_geodb.ne_10m_admin_0_countries WHERE ST_Intersects(wkb_geometry, ST_GeomFromText(:geom, :srid)) LIMIT :feature_count;"
}
```
In a DB query the following values are replaced in the SQL:

* `:x`: X coordinate of query
* `:y`: Y coordinate of query
* `:srid`: SRID of query coordinates
* `:resolution`: Resolution in map units per pixel
* `:FI_POINT_TOLERANCE`: Tolerance for picking points, in pixels (default=16)
* `:FI_LINE_TOLERANCE`: Tolerance for picking lines, in pixels (default=8)
* `:FI_POLYGON_TOLERANCE`: Tolerance for picking polygons, in pixels (default=4)
* `:i`: X ordinate of query point on map, in pixels
* `:j`: Y ordinate of query point on map, in pixels
* `:height`: Height of map output, in pixels
* `:width`: Width of map output, in pixels
* `:bbox`: 'Bounding box for map extent as minx,miny,maxx,maxy'
* `:crs`: 'CRS for map extent'
* `:feature_count`: Max feature count
* `:with_geometry`: Whether to return geometries in response (default=1)
* `:with_maptip`: Whether to return maptip in response (default=1)
* `:geom`: The `filter_geom` passed to the `GetFeatureInfo` request, if any, otherwise `POINT(x y)`

The query should return the feature ID as `_fid_`, the WKT geometry as `wkt_geom` and the BBOX as `bbox`. All other selected columns are used as feature attributes.

*Custom module*:

Example configuration:
```json
"info_template": {
  "type": "module",
  "module": "<module_name>"
}
```
Custom info modules must be placed in `./ogc/custom_info_modules/<module name>` and must provide the following method:

```python
def layer_info(layer, x, y, crs, params, identity)
```

See [the example module](src/ogc/custom_info_modules/example.py).

**Attribute formats**

You can apply some basic attribute formatting without having to use templates. This formatting will be applied for all `INFO_FORMAT`s.

- *Date conversion rules*: There are the following built-in conversion rules which format datetime strings
    ```
    "%Y-%m-%dT%H:%M:%S.%f" => "%d.%m.%Y %H:%M:%S"
    "%Y-%m-%dT%H:%M:%S" => "%d.%m.%Y %H:%M:%S"
    "%Y-%m-%d" => "%d.%m.%Y"
    ```
  You can override these in the service config by setting `date_conversion_rules`.
- You can format a number value specifing an attribute format according to the [Python format language](https://docs.python.org/3/library/string.html#format-specification-mini-language), for example
    ```json
    "attributes": [
      {"name": "num", "alias": "Number", "format": " >+10.3f"}
      ...
    ]
    ```
- You can transform attribute values with a fixed lookup dictionary, for example
    ```json
    "attributes": [
      {"name": "bool", "alias": "Boolean", "format": '{"0": "False", "1": "True"}'}
      ...
    ]
    ```
- Attachments URLs (as written into the feature attributes by the `qwc-data-service` when uploading files) will be automatically resolved to absolute URLs relative to the `data_service_url`, as configured in the OGC service configuration (defaults to `/api/v1/data`).

### Marker params

The OGC service supports specifying marker parameters to insert a SLD styled marker into GetMap requests via QGIS Server `HIGHLIGHT_SYMBOL` and `HIGHLIGHT_GEOM`. To use this feature, provide a SLD template and parameter definitions in the ogc service config, for example:

    "marker_template": "<StyledLayerDescriptor><UserStyle><se:Name>Marker</se:Name><se:FeatureTypeStyle><se:Rule><se:Name>Single symbol</se:Name><se:PointSymbolizer><se:Graphic><se:Mark><se:WellKnownName>circle</se:WellKnownName><se:Fill><se:SvgParameter name=\"fill\">$FILL$</se:SvgParameter></se:Fill><se:Stroke><se:SvgParameter name=\"stroke\">$STROKE$</se:SvgParameter><se:SvgParameter name=\"stroke-width\">$STROKE_WIDTH$</se:SvgParameter></se:Stroke></se:Mark><se:Size>$SIZE$</se:Size></se:Graphic></se:PointSymbolizer></se:Rule></se:FeatureTypeStyle></UserStyle></StyledLayerDescriptor>",
    "marker_params": {
      "size": {
        "default": 10,
        "type": "number"
      },
      "fill": {
        "default": "FFFFFF",
        "type": "color"
      },
      "stroke": {
        "default": "FF0000",
        "type": "color"
      },
      "stroke_width": {
        "default": 5,
        "type": "number"
      }

Note:

* Use `$<PARAM_NAME>$` as parameter placeholders in the SLD template.
* You can selectively override the default values via environment variables by setting `MARKER_<PARAM_NAME>` (i.e. `MARKER_SIZE`) to the desired values.

You can then specify the `MARKER` URL query parameter in `GetMap` requests to inject a marker as follows:

    ...?SERVICE=WMS&REQUEST=GetMap&...&MARKER=X->123456|Y->123456|STROKE->000FFA...

`X` and `Y` are compulsory and specify the marker position in map CRS, any other additional parameters are optional and will override the default values if provided. All parameters have to written in uppercase.

### Custom legend graphics

The OGC service supports custom layer legend images, which will be matched in this order (the first one found is used):

- As base64, as set in `<layer_resource_config>[legend_image_base64]`
- A filename as set in `<layer_resource_config>[legend_image]`
- A filename matching `<legend_images_path>/<service_name>/<layername>_<style>_<suffix>.png`
- A filename matching `<legend_images_path>/<service_name>/<layername>_<suffix>.png`
- A filename matching `<legend_images_path>/<service_name>/default_<suffix>.png`
- A filename matching `<legend_images_path>/<service_name>/<layername>_<style>.png`
- A filename matching `<legend_images_path>/<service_name>/<layername>.png`
- A filename matching `<legend_images_path>/<resource_entry[legend_image]>`
- A filename matching `<legend_images_path>/<service_name>/default.png`

Where

* `legend_images_path` is the directory containing custom legend images, configured in the service configuration.
* `service_name` is the name of the WMS service
* `layername` is the WMS layer name
* `suffix`: empty, or one of `_thumbnail`, `_tooltip`. The suffix is passed by QWC to the legend service depending on the requested image type
* `resource_entry[legend_image]` and `resource_entry[legend_image_base64]` are the `legend_image` resp. `legend_image_base64` settings of a layer as configured in the service resource configuration, for example:
```json
{
  "name": "ogc",
  "config": ...,
  "resources": {
    "wms_services": [
      {
        "name": "<service name>",
        "root_layer": {
          "name": "<root_layer_name>",
          "layers": [
            {
              "name": "<layer_name>",
              "legend_image": "/path/to/legend_image.png"
            }
          ]
        }
      }
    ]
  }
}
```

*Note*: When running `qwc-ogc-service` in Docker, mount the legend templates folder into the `qwc-ogc-service` container, i.e.:
```yml
  qwc-ogc-service:
    image: sourcepole/qwc-ogc-service:vYYYY.MM.DD
    volumes:
      ...
      - ./volumes/legends:/legends
```
and set `legend_images_path` to `/legends` in the service configuration. 

### Injected GetPrint labels and print project suffix

Specifying `print_label_queries` in the service config allows configuring additional parameters to inject into the WMS `GetPrint` request, which will be computed from a DB query.

The format is as follows:

    "print_label_queries": [
      {
        "db_url": "<db_url>",
        "query": "<query>",
        "params": ["<ParamName1>", ...]
      },{
        ...
      }
    ]

where:

* `query` is an arbitrary query, returning exactly one row. The `$username$` placeholder can be used to inject the current username.
* `params` is an array of parameter names to inject. The same number of parameters as number of returned values by the query must be specified.

Similarly, `print_label_values` allows configuring additional static parameters to inject into the WMS `GetPrint` request.
The format is as follows:

    "print_label_values": [
      {
        "field": "<ParamName1>",
        "value": "<value>"
      },{
        ...
      }
    ]

Finally, you can specify a suffix for the print projects if you want to use a separate project for printing by setting `print_qgs_postfix`.

### Extra WFS output formats

You can choose extra formats to allow to OUTPUTFORMAT parameter of WFS GetFeature request.
**Please note that the returned data will be unfiltered.**

Example:

```json
  "config": {
    "allow_outputformat_unfiltered": {
    	  "shp": "shp",
          "application/x-zipped-shp": "shp",
          "tab": "tab",
          "application/x-zipped-tab": "tab",
          "mif": "mif",
          "application/x-zipped-mif": "mif",
          "kml": "kml",
          "application/vnd.google-earth.kml+xml": "kml",
          "gpkg": "gpkg",
          "application/geopackage+vnd.sqlite3": "gpkg",
          "gpx": "gpx",
          "application/gpx+xml": "gpx",
          "ods": "ods",
          "application/vnd.oasis.opendocument.spreadsheet": "ods",
          "xlsx": "xlsx",
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
          "csv": "csv",
          "text/csv": "csv",
          "fgb": "fgb",
          "application/x-fgb": "fgb"
       }
  },
```

Adding these formats is particularly useful when using the QGIS Server plugin `qgis-wfsOutputExtension` (https://github.com/3liz/qgis-wfsOutputExtension/tree/master).

Run locally
-----------

Install dependencies and run:

    export CONFIG_PATH=<CONFIG_PATH>
    uv run src/server.py

To use configs from a `qwc-docker` setup, set `CONFIG_PATH=<...>/qwc-docker/volumes/config`.

Set `FLASK_DEBUG=1` for additional debug output.

Set `FLASK_RUN_PORT=<port>` to change the default port (default: `5000`).

API documentation:

    http://localhost:$FLASK_RUN_PORT/api/

Docker usage
------------

The Docker image is published on [Dockerhub](https://hub.docker.com/r/sourcepole/qwc-ogc-service).

See sample [docker-compose.yml](https://github.com/qwc-services/qwc-docker/blob/master/docker-compose-example.yml) of [qwc-docker](https://github.com/qwc-services/qwc-docker).

