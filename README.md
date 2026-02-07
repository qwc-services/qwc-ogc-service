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
    "oapi_qgis_server_url": "http://localhost:8001/wfs3/"
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
                  "attributes": {
                    "id": "id", "name": "Name", "description": "Description", "num": "Number", "value": "value", "type": "Type", "amount": "amount", "validated": "Validated", "datetime": "Date", "geometry": "geometry", "maptip": "maptip"
                  },
                  "queryable": true
                },
                {
                  "name": "edit_lines",
                  "title": "Edit Lines",
                  "attributes": {
                    "id": "id", "name": "Name", "description": "Description", "num": "Number", "value": "value", "type": "Type", "amount": "amount", "validated": "Validated", "datetime": "Date", "geometry": "geometry", "maptip": "maptip"
                  },
                  "queryable": true
                },
                {
                  "name": "edit_polygons",
                  "title": "Edit Polygons",
                  "attributes": {
                    "id": "id", "name": "Name", "description": "Description", "num": "Number", "value": "value", "type": "Type", "amount": "amount", "validated": "Validated", "datetime": "Date", "geometry": "geometry", "maptip": "maptip"
                  },
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
              "attributes": {
                "name": "name", "formal_en": "formal_en", "pop_est": "pop_est", "subregion": "subregion", "geometry": "geometry"
              },
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
            "attributes": {
              "id": "id", "name": "Name", "description": "Description", "num": "Number", "value": "value", "type": "Type", "amount": "amount", "validated": "Validated", "datetime": "Date", "geometry": "geometry"
            }
          },
          {
            "name": "edit_lines",
            "attributes": {
              "id": "id", "name": "Name", "description": "Description", "num": "Number", "value": "value", "type": "Type", "amount": "amount", "validated": "Validated", "datetime": "Date", "geometry": "geometry"
            }
          }
        ]
      }
    ]
  }
}
```

**Note**: `wfs_services` example for a separate QGIS project `qwc_demo_wfs` with WFS enabled.

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

