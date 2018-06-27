QWC OGC Service
===============

Provide OGC services with permission filters as a proxy to a QGIS server.

**Note:** requires a QGIS server running on `$QGIS_SERVER_URL` and a 
QWC Config service running on `$CONFIG_SERVICE_URL`


Usage
-----

Set the `QGIS_SERVER_URL` environment variable to the QGIS server URL
when starting this service. (default: `http://localhost:8001/ows/` on
qwc-qgis-server container)

Set the `CONFIG_SERVICE_URL` environment variable to the QWC config service URL
when starting this service. (default: `http://localhost:5010/` on
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

Start local service:

    QGIS_SERVER_URL=http://localhost:8001/ows/ CONFIG_SERVICE_URL=http://localhost:5010/ python server.py
