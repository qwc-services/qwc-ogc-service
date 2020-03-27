QWC OGC Service v2
==================

Provide OGC services with permission filters as a proxy to a QGIS server.

**v2** (WIP): add support for multitenancy and replace QWC Config service with static config and permission files.

**Note:** requires a QGIS server running on `default_ogc_service_url`.


Configuration
-------------

The static config and permission files are stored as JSON files in `$CONFIG_PATH` with subdirectories for each tenant,
e.g. `$CONFIG_PATH/default/*.json`. The default tenant name is `default`.


### Data Service config

* File location: `$CONFIG_PATH/<tenant>/ogcConfig.json`

Example:
```json
{
  "service": "ogc",
  "config": {
    "default_ogc_service_url": "http://localhost:8001/ows/"
  },
  "resources": {
    "wms_services": [
      {
        "name": "qwc_demo",
        "wms_url": "http://localhost:8001/ows/qwc_demo",
        "online_resource": "http://localhost:5013/qwc_demo",
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
                    "id", "name", "description", "num", "value", "type", "amount", "validated", "datetime", "geometry", "maptip"
                  ],
                  "queryable": true
                },
                {
                  "name": "edit_lines",
                  "title": "Edit Lines",
                  "attributes": [
                    "id", "name", "description", "num", "value", "type", "amount", "validated", "datetime", "geometry", "maptip"
                  ],
                  "queryable": true
                },
                {
                  "name": "edit_polygons",
                  "title": "Edit Polygons",
                  "attributes": [
                    "id", "name", "description", "num", "value", "type", "amount", "validated", "datetime", "geometry", "maptip"
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
                "name", "formal_en", "pop_est", "subregion", "geometry"
              ],
              "queryable": true
            }
          ]
        },
        "print_templates": ["A4 Landscape"],
        "internal_print_layers": ["bluemarble_bg", "osm_bg"]
      }
    ]
  }
}
```


Usage
-----

Set the `CONFIG_PATH` environment variable to the path containing the service config and permission files when starting this service (default: `config`).

Set the `QGIS_SERVER_URL` environment variable to the QGIS server URL
when starting this service. (default: `http://localhost:8001/ows/` on
qwc-qgis-server container)

Base URL:

    http://localhost:5013/

Service API:

    http://localhost:5013/api/

Sample requests:

    curl 'http://localhost:5013/qwc_demo?VERSION=1.1.1&SERVICE=WMS&REQUEST=GetCapabilities'


Development
-----------

Create a virtual environment:

    virtualenv --python=/usr/bin/python3 --system-site-packages .venv

Without system packages:

    virtualenv --python=/usr/bin/python3 .venv

Activate virtual environment:

    source .venv/bin/activate

Install requirements:

    pip install -r requirements.txt
    pip install flask_cors

Start local service:

    CONFIG_PATH=/PATH/TO/CONFIGS/ QGIS_SERVER_URL=http://localhost:8001/ows/ CONFIG_SERVICE_URL=http://localhost:5010/ python server.py
