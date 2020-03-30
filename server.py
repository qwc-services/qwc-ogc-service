from flask import Flask, request
from flask_jwt_extended import JWTManager, jwt_optional, get_jwt_identity
from flask_restplus import Api, Resource

from qwc_services_core.jwt import jwt_manager
from qwc_services_core.tenant_handler import TenantHandler
from ogc_service import OGCService


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

# Setup the Flask-JWT-Extended extension
jwt = jwt_manager(app, api)

# create tenant handler
tenant_handler = TenantHandler(app.logger)


def ogc_service_handler(identity):
    """Get or create a OGCService instance for a tenant.

    :param str identity: User identity
    """
    tenant = tenant_handler.tenant(identity)
    handler = tenant_handler.handler('ogc', 'ogc', tenant)
    if handler is None:
        handler = tenant_handler.register_handler(
            'ogc', tenant, OGCService(tenant, app.logger))
    return handler


# routes
@api.route('/<path:service_name>')
@api.param('service_name', 'OGC service name', default='qwc_demo')
class OGC(Resource):
    @api.doc('ogc_get')
    @api.param('SERVICE', 'Service', default='WMS')
    @api.param('REQUEST', 'Request', default='GetCapabilities')
    @api.param('VERSION', 'Version', default='1.1.1')
    @api.param('filename', 'Output file name')
    @jwt_optional
    def get(self, service_name):
        """OGC service request

        GET request for an OGC service (WMS, WFS).
        """
        ogc_service = ogc_service_handler(get_jwt_identity())
        response = ogc_service.get(
            get_jwt_identity(), service_name,
            request.host, request.args, request.script_root)

        filename = request.values.get('filename')
        if filename:
            response.headers['content-disposition'] = 'attachment; filename=' + filename

        return response

    @api.doc('ogc_post')
    @api.param('SERVICE', 'Service', _in='formData', default='WMS')
    @api.param('REQUEST', 'Request', _in='formData', default='GetCapabilities')
    @api.param('VERSION', 'Version', _in='formData', default='1.1.1')
    @api.param('filename', 'Output file name')
    @jwt_optional
    def post(self, service_name):
        """OGC service request

        POST request for an OGC service (WMS, WFS).
        """
        # NOTE: use combined parameters from request args and form
        ogc_service = ogc_service_handler(get_jwt_identity())
        response = ogc_service.post(
            get_jwt_identity(), service_name,
            request.host, request.values, request.script_root)

        filename = request.values.get('filename')
        if filename:
            response.headers['content-disposition'] = 'attachment; filename=' + filename

        return response


# local webserver
if __name__ == '__main__':
    print("Starting OGC service...")
    from flask_cors import CORS
    CORS(app)
    app.run(host='localhost', port=5013, debug=True)
