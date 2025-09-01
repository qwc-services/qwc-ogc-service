from flask import jsonify


class GetTranslationsHandler:

    def __init__(self, logger):
        """
        :param obj logger: Application logger
        """
        self.logger = logger

    def process_request(self, request, params, permissions, data):
        """Check request parameters against permissions and adjust params.

        :param str request: The OWS request
        :param obj params: Request parameters
        :param obj permissions: OGC service permissions
        :param obj data: POST data, if any
        """
        return None

    def response_streamable(self, request):
        """ Returns whether the response for the specified request is streamable. """
        return False

    def filter_response(self, request, response, params, permissions):
        """Filter WMS response by permissions.
        :param request str: The OWS request
        :param requests.Response response: Response object
        :param obj params: Request parameters
        :param obj permissions: OGC service permission
        """
        try:
          translations = response.json()
        except:
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
          attribute_aliases = permissions['permitted_layers'].get(layername, {}).get('attributes', {})
          alias_attributes = dict([x[::-1] for x in attribute_aliases.items()])
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
