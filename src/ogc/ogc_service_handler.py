from abc import ABC, abstractmethod

import requests
from flask import url_for


class OgcRequest:
    """ Collection of parameters which describe a OGC request. """
    def __init__(self, server_url, method, service_name, params, data):
        self.server_url = server_url
        self.method = method
        self.service_name = service_name
        self.params = params
        self.data = data
        self.service = params.get('SERVICE', '').upper()
        self.request = params.get('REQUEST', '').upper()

    def __copy__(self):
        return OgcRequest(
            self.server_url, self.method, self.service_name, dict(self.params), dict(self.data) if self.data else None
        )


class ServiceException(Exception):
    """ Exception for errors while processing a OGC request. """
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


class OgcServiceHandler(ABC):
    def __init__(self, logger, config, qgis_server_url, permission_handler, identity):
        """
        :param obj logger: Application logger
        :param obj config: Service config
        :param obj qgis_server_url: internal QGIS Server URL
        :param obj permission_handler: Permission handler
        :param obj identity: User identity
        """
        self.logger = logger
        self.network_timeout = config.get('network_timeout', 30)

    @staticmethod
    @abstractmethod
    def accepts(req):
        """Whether the handler handle the specified request.

        :param OgcRequest req: The OGC request
        """

    @abstractmethod
    def adjust_request_params(self, req, permissions):
        """Check request parameters against permissions and adjust params, returning the adjusted OgcRequest

        :param OgcRequest req: The OGC request
        :param obj permissions: OGC service permissions
        """

    def forward_request(self, req, permissions, stream):
        """ Forwards the specified request to the internal QGIS Server.

        :param OgcRequest req: The OGC request
        :param bool stream: Whether the response will be streamed
        :param obj permissions: OGC service permissions
        """
        headers = {
            "X-Qgis-Service-Url": url_for("ogc", service_name=req.service_name, _external=True)
        }
        try:
            self.logger.info(f"Forward {req.method} request to {req.server_url}")
            self.logger.info("\n".join(
                (f"  {k} = {v}" for k, v, in req.params.items()))
            )
            if req.method == 'POST':
                response = requests.post(
                    req.server_url, data=req.data["body"] if req.data else req.params,
                    params=req.params if req.data else None,
                    headers=headers | {"Content-Type": req.data["contentType"]} if req.data else {},
                    stream=stream, timeout=self.network_timeout
                )
            else:
                response = requests.get(
                    req.server_url, params=req.params, stream=stream, timeout=self.network_timeout, headers=headers
                )
        except Exception as e: # noqa BLE001
            self.logger.error(f"Failed to forward request: {e!s}")
            raise ServiceException(
                "UnknownError",
                "The server encountered an internal error or misconfiguration and was unable to complete your request."
            )

        if response.status_code != requests.codes.ok:
            # handle internal server error
            self.logger.error(f"Internal Server Error:\n\n{response.text}")
            raise ServiceException(
                "UnknownError",
                "The server encountered an internal error or misconfiguration and was unable to complete your request."
            )
        return response

    def response_streamable(self, req):
        """ Returns whether the response for the specified request is streamable.

        :param OgcRequest req: The OGC request
        """
        return False

    @abstractmethod
    def filter_response(self, req, response, permissions):
        """Check request parameters against permissions and adjust params.

        :param OgcRequest req: The OGC request
        :param obj response: The network response
        :param obj permissions: OGC service permissions
        """
