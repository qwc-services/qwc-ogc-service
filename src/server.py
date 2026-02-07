from flask import Flask, request, jsonify, json, redirect
from flask_restx import Resource
import urllib.parse
import requests
import os


from qwc_services_core.api import Api
from qwc_services_core.auth import auth_manager, optional_auth, get_identity  # noqa: E402
from qwc_services_core.tenant_handler import TenantHandler, TenantPrefixMiddleware, TenantSessionInterface
from qwc_services_core.runtime_config import RuntimeConfig
from ogc_service import OGCService
from ogcapi_service import OGCAPIService


# Flask application
app = Flask(__name__)

api = Api(app, version='1.0', title='OGC service API',
          description="""API for QWC OGC service.

Provide OGC services with permission filters as a proxy to a QGIS server.
          """,
          default_label='OGC operations', doc='/api/'
)
# disable verbose 404 error message
app.config['ERROR_404_HELP'] = False

auth = auth_manager(app, api)

# create tenant handler
tenant_handler = TenantHandler(app.logger)
app.wsgi_app = TenantPrefixMiddleware(app.wsgi_app)
app.session_interface = TenantSessionInterface()


def ogc_service_handler():
    """Get or create a OGCService instance for a tenant."""
    tenant = tenant_handler.tenant()
    handler = tenant_handler.handler('ogc', 'ogc', tenant)
    if handler is None:
        handler = tenant_handler.register_handler(
            'ogc', tenant, OGCService(tenant, app.logger))
    return handler

def ogcapi_service_handler():
    """Get or create a OGCAPIService instance for a tenant."""
    tenant = tenant_handler.tenant()
    handler = tenant_handler.handler('ogcapi', 'ogcapi', tenant)
    if handler is None:
        handler = tenant_handler.register_handler(
            'ogcapi', tenant, OGCAPIService(tenant, app.logger))
    return handler

def get_identity_or_auth(ogc_service):
    identity = get_identity()
    if not identity and ogc_service.basic_auth_login_url:
        # Check for basic auth
        auth = request.authorization
        if auth:
            headers = {}
            if tenant_handler.tenant_header:
                # forward tenant header
                headers[tenant_handler.tenant_header] = tenant_handler.tenant()
            for login_url in ogc_service.basic_auth_login_url:
                app.logger.debug(f"Checking basic auth via {login_url}")
                data = {'username': auth.username, 'password': auth.password}
                resp = requests.post(login_url, data=data, headers=headers)
                if resp.ok:
                    json_resp = json.loads(resp.text)
                    app.logger.debug(json_resp)
                    return json_resp.get('identity')
    return identity


def auth_path_prefix():
    tenant = tenant_handler.tenant()
    config_handler = RuntimeConfig("ogc", app.logger)
    config = config_handler.tenant_config(tenant)
    auth_path = config.get('auth_service_url', '/auth/')
    return app.session_interface.tenant_path_prefix().rstrip("/") + "/" + auth_path.lstrip("/")


@app.before_request
@optional_auth
def assert_user_is_logged():
    public_endpoints = ['healthz', 'ready']
    if request.endpoint in public_endpoints:
        return

    tenant = tenant_handler.tenant()
    config_handler = RuntimeConfig("ogc", app.logger)
    config = config_handler.tenant_config(tenant)
    public_paths = config.get("public_paths", [])
    if request.path in public_paths:
        return

    if config.get("auth_required", False):
        ogc_service = ogc_service_handler()
        identity = get_identity_or_auth(ogc_service)
        if identity is None:
            app.logger.info("Access denied, authentication required")
            prefix = auth_path_prefix().rstrip('/')
            return redirect(prefix + f"/login?url={urllib.parse.quote(request.url)}")

# routes
@api.route('/', endpoint='root', defaults={'format_ext': ''})
@api.route('/.<string:format_ext>')
class Index(Resource):
    def get(self, format_ext):
        ogcapi_service = ogcapi_service_handler()
        identity = get_identity_or_auth(ogcapi_service)
        return ogcapi_service.index(identity, format_ext, auth_path_prefix())


@api.route('/<path:service_name>', endpoint='ogc')
@api.param('service_name', 'OGC service name', default='qwc_demo')
class OGC(Resource):
    @api.doc('ogc_get')
    @api.param('SERVICE', 'Service', default='WMS')
    @api.param('REQUEST', 'Request', default='GetCapabilities')
    @api.param('VERSION', 'Version', default='1.1.1')
    @api.param('filename', 'Output file name')
    @api.param('REQUIREAUTH', 'Whether to send a 401 Unauthorized response if not authenticated')
    @optional_auth
    def get(self, service_name):
        """OGC service request

        GET request for an OGC service (WMS, WFS).
        """
        ogc_service = ogc_service_handler()
        identity = get_identity_or_auth(ogc_service)
        headers = request.headers
        response = ogc_service.request(
            identity, 'GET', service_name, request.args, None)

        filename = request.args.get('filename')
        if filename:
            response.headers['content-disposition'] = 'attachment; filename=' + filename

        return response

    @api.doc('ogc_post')
    @api.param('SERVICE', 'Service', _in='formData', default='WMS')
    @api.param('REQUEST', 'Request', _in='formData', default='GetCapabilities')
    @api.param('VERSION', 'Version', _in='formData', default='1.1.1')
    @api.param('REQUIREAUTH', 'Whether to send a 401 Unauthorized response if not authenticated')
    @api.param('filename', 'Output file name')
    @optional_auth
    def post(self, service_name):
        """OGC service request

        POST request for an OGC service (WMS, WFS).
        """
        # NOTE: use combined parameters from request args and form
        ogc_service = ogc_service_handler()
        identity = get_identity_or_auth(ogc_service)
        headers = request.headers
        if request.data:
            data = {"body": request.data, "contentType": headers.get("Content-Type", "text/plain")}
        else:
            data = None
        response = ogc_service.request(
                identity, 'POST', service_name, request.values, data)

        filename = request.values.get('filename')
        if filename:
            response.headers['content-disposition'] = 'attachment; filename=' + filename

        return response


@api.route('/<path:service_name>/features', defaults={'api_path': '', 'format_ext': ''})
@api.route('/<path:service_name>/features.<string:format_ext>', defaults={'api_path': ''})
@api.route('/<path:service_name>/features/', defaults={'api_path': '', 'format_ext': ''})
@api.route('/<path:service_name>/features/.<string:format_ext>', defaults={'api_path': ''})
@api.route('/<path:service_name>/features/<path:api_path>', defaults={'format_ext': ''}, endpoint='oapif')
@api.route('/<path:service_name>/features/<path:api_path>.<string:format_ext>')

@api.param('service_name', 'OGC service name', default='qwc_demo')
@api.param('api_path', 'API path', default='')
@api.param('format_ext', 'Format specifier extensions (.json, .html)', default='')
class OGCAPIFeatures(Resource):
    def get(self, service_name, api_path, format_ext):
        ogcapi_service = ogcapi_service_handler()
        identity = get_identity_or_auth(ogcapi_service)
        return ogcapi_service.request(
            identity, 'GET', service_name, 'features', api_path, format_ext, request.args, None, auth_path_prefix()
        )

    def post(self, service_name, api_path, format_ext):
        ogcapi_service = ogcapi_service_handler()
        identity = get_identity_or_auth(ogcapi_service)
        return ogcapi_service.request(
            identity, 'POST', service_name, 'features', api_path, format_ext, request.args, request.get_json(), None
        )

    def patch(self, service_name, api_path, format_ext):
        ogcapi_service = ogcapi_service_handler()
        identity = get_identity_or_auth(ogcapi_service)
        return ogcapi_service.request(
            identity, 'PATCH', service_name, 'features', api_path, format_ext, request.args, request.get_json(), None
        )

    def put(self, service_name, api_path, format_ext):
        ogcapi_service = ogcapi_service_handler()
        identity = get_identity_or_auth(ogcapi_service)
        return ogcapi_service.request(
            identity, 'PUT', service_name, 'features', api_path, format_ext, request.args, request.get_json(), None
        )

    def delete(self, service_name, api_path, format_ext):
        ogcapi_service = ogcapi_service_handler()
        identity = get_identity_or_auth(ogcapi_service)
        return ogcapi_service.request(
            identity, 'DELETE', service_name, 'features', api_path, format_ext, request.args, None, None
        )


""" readyness probe endpoint """
@app.route("/ready", methods=['GET'])
def ready():
    return jsonify({"status": "OK"})


""" liveness probe endpoint """
@app.route("/healthz", methods=['GET'])
def healthz():
    return jsonify({"status": "OK"})


# local webserver
if __name__ == '__main__':
    print("Starting OGC service...")
    from flask_cors import CORS
    CORS(app)
    app.run(host='localhost', port=os.environ.get("FLASK_RUN_PORT", 5000), debug=True)
