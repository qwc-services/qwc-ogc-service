from typing import override

from flask import jsonify

from ogc.ogc_service_handler import OgcServiceHandler


class GetTranslationsHandler(OgcServiceHandler):
    """ Handler for GetTranslations requests. """

    def __init__(self, logger, config, qgis_server_url, permission_handler, identity):
        """
        :param obj logger: Application logger
        :param obj config: Service config
        :param obj qgis_server_url: internal QGIS Server URL
        :param obj permission_handler: Permission handler
        :param obj identity: User identity
        """
        super().__init__(logger, config, qgis_server_url, permission_handler, identity)

    @staticmethod
    @override
    def accepts(req):
        """Whether the handler handle the specified request.

        :param OgcRequest req: The OGC request
        """
        return req.service == 'GETTRANSLATIONS'

    @override
    def adjust_request_params(self, req, permissions):
        """Check request parameters against permissions and adjust params, returning the adjusted OgcRequest

        :param OgcRequest req: The OGC request
        :param obj permissions: OGC service permissions
        """
        return req

    @override
    def build_response(self, req, response, permissions, stream):
        """Build the (possibly filtered) response.

        :param OgcRequest req: The OGC request
        :param obj response: The request response
        :param obj permissions: OGC service permissions
        :param bool stream: Whether to stream the response
        """
        try:
          translations = response.json()
        except: # noqa: E722
          self.logger.warning("Failed to parse translations, is the get_translations QGIS server plugin enabled?")
          return jsonify({})

        # Filter layertree
        translations['layertree'] = dict([
          entry for entry in translations.get('layertree', {}).items()
          if entry[0] in permissions['permitted_layers']
        ])

        # Filter layers
        translations['layers'] = dict([
          entry for entry in translations.get('layers', {}).items()
          if entry[0] in permissions['permitted_layers']
        ])

        # Filter attributes
        for layername, entry in translations['layers'].items():
          attributes = permissions['permitted_layers'].get(layername, {}).get('attributes', {})
          alias_attributes = {attr['alias']: attr['name'] for attr in attributes.values()}
          entry['fields'] = dict([
            fieldentry for fieldentry in entry.get('fields', {}).items()
            if fieldentry[0] in alias_attributes
          ])

          # Filter layouts
          translations['layouts'] = dict([
              entry for entry in translations['layouts'].items()
              if entry[0] in permissions['print_templates']
          ])

        return jsonify(translations)
