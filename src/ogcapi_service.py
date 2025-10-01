from flask import jsonify, make_response, Response, url_for
from jinja2 import Environment, FileSystemLoader
import json
import math
import posixpath
import re
import requests
from types import SimpleNamespace
from urllib.parse import quote, unquote, parse_qsl, urlparse, urlencode, urlunparse

from qwc_services_core.auth import get_username
from qwc_services_core.permissions_reader import PermissionsReader
from qwc_services_core.runtime_config import RuntimeConfig

from wfs_handler import wfs_clean_layer_name, wfs_clean_attribute_name



class RecursiveNamespace(SimpleNamespace):

    @staticmethod
    def map_entry(entry):
        if isinstance(entry, dict):
            return RecursiveNamespace(**entry)
        return entry

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for key, val in kwargs.items():
            if type(val) == dict:
                setattr(self, key, RecursiveNamespace(**val))
            elif type(val) == list:
                setattr(self, key, list(map(self.map_entry, val)))

    def __iter__(self):
        return iter(self.__dict__.items())

def parentLink(url, n=1):
    return '/'.join(url.split('/')[:-n])


class OGCAPIService:
    """OGCAPIService class

    Provide OGC API services (Features, Maps) with permission filters.
    Acts as a proxy to a QGIS server.
    """

    def __init__(self, tenant, logger):
        """Constructor

        :param str tenant: Tenant ID
        :param Logger logger: Application logger
        """
        self.tenant = tenant
        self.logger = logger

        config_handler = RuntimeConfig("ogc", logger)
        config = config_handler.tenant_config(tenant)

        self.basic_auth_login_url = config.get('basic_auth_login_url')

        self.oapi_qgis_server_url = config.get(
            'oapi_qgis_server_url', 'http://localhost:8001/wfs3'
        ).rstrip('/')

        self.network_timeout = config.get('network_timeout', 30)

        self.root_qgis_server_url = urlunparse(urlparse(self.oapi_qgis_server_url)._replace(path=''))

        self.qgis_server_url_tenant_suffix = config.get('qgis_server_url_tenant_suffix', '').strip('/')

        self.oapif_max_limit = config.get('oapif_max_limit', 10000)

        if self.qgis_server_url_tenant_suffix:
            self.qgis_server_url_tenant_suffix += '/'

        self.resources = self.load_resources(config)
        self.permissions_handler = PermissionsReader(tenant, logger)

        self.feature_handlers = {
            '^$': {
                "filter_request": self.__getLandingPage_request, "filter_response": self.__getLandingPage_response, "allowed_methods": ["GET"]
            },
            '^/api$': {
                "filter_request": self.__getApiDescription_request, "filter_response": self.__getApiDescription_response, "allowed_methods": ["GET"]
            },
            '^/conformance$': {
                "filter_request": self.__getRequirementClasses_request, "filter_response": self.__getRequirementClasses_response, "allowed_methods": ["GET"]
            },
            '^/collections$': {
                "filter_request": self.__describeCollections_request, "filter_response": self.__describeCollections_response, "allowed_methods": ["GET"]
            },
            '^/collections/([^/]+)$': {
                "filter_request": self.__describeCollection_request, "filter_response": self.__describeCollection_response, "allowed_methods": ["GET"]
            },
            '^/collections/([^/]+)/items$': {
                "filter_request": self.__getFeatures_request, "filter_response": self.__getFeatures_response, "allowed_methods": ["GET", "POST"]
            },
            '^/collections/([^/]+)/items/([^/]+)$': {
                "filter_request": self.__getFeature_request, "filter_response": self.__getFeature_response, "allowed_methods": ["DELETE", "GET", "PATCH", "PUT"]
            }
        }

        # Template utility funcs
        def links_filter(links, attr, value):
            result = []
            if isinstance(links, list):
                for l in links:
                    if getattr(l, attr) == value:
                        result.append(l)
            return result

        def path_chomp(url):
            base, ext = posixpath.splitext(url)
            base = posixpath.dirname(base)
            return base + ext

        def content_type_name(contentType):
            contentTypes = {
                'application/json': 'JSON',
                'application/geo+json': 'GEOJSON',
                'text/html': 'HTML'
            }
            return contentTypes.get(contentType, contentType)

        def nl2br(text):
            return text.replace('\n', '<br>')

        def component_parameter(ref):
            ret = []
            if isinstance(ref, dict):
                try:
                    name = getattr(ref, "$ref").split('/')[-1]
                    ret.append(filtered_json["components"]["parameters"][name])
                except:
                    pass
            return ret

        def if_nullptr_null_str(value):
            return "null" if value is None else value

        def existsIn(obj, attr):
            return hasattr(obj, attr)

        def isArray(obj):
            return isinstance(obj, list)

        def last(array):
            return array[-1]

        self.template_util_funcs = {
            "links_filter": links_filter,
            "path_chomp": path_chomp,
            "content_type_name": content_type_name,
            "nl2br": nl2br,
            "component_parameter": component_parameter,
            "if_nullptr_null_str": if_nullptr_null_str,
            "existsIn": existsIn,
            "isArray": isArray,
            "last": last
        }

    def load_resources(self, config):
        """Load service resources from config.

        :param RuntimeConfig config: Config handler
        """
        wms_services = {}
        wfs_services = {}
        for wms in config.resources().get('wms_services', []):
            if wms.get('hidden_in_landing_page') == True:
                continue
            wms_services[wms['name']] = {
                "title": wms.get("root_layer", {}).get("title"),
                "layers": self.collect_resource_layers(wms.get("root_layer", {}).get("layers", []))
            }
        for wfs in config.resources().get('wfs_services', []):
            if wfs.get('hidden_in_landing_page') == True:
                continue
            wfs_services[wfs['name']] = {
                "title": wfs.get("title"),
                "layers": self.collect_resource_layers(wfs.get("layers", []))
            }

        return {"wms_services": wms_services, "wfs_services": wfs_services}

    def collect_resource_layers(self, layers):
        """Recursively collect layer info for layer subtree from config.

        :param list layers: Layers
        """
        result = {}
        for layer in layers:
            if layer.get('layers'):
                result.update(self.collect_resource_layers(layer['layers']))
            else:
                result.update({layer['name']: layer.get('attributes', {})})
        return result

    def service_permissions(self, identity, service_name, api):
        """Return permissions for a OAPI service.

        :param str identity: User identity
        :param str service_name: OGC service name
        :param str api: OAPI type (maps or features)
        """

        permitted_layers = {}
        if api == 'maps':
            # collect permitted layers with permitted attributes from wms_services as
            # {<layer>: [<attrs>]}
            wms_permissions = self.permissions_handler.resource_permissions(
                'wms_services', identity, service_name
            )
            for permissions in wms_permissions:
                for layer_permission in permissions['layers']:
                    layer_name = layer_permission['name']
                    if layer_name not in permitted_layers:
                        permitted_layers[layer_name] = {
                            'attributes': set(),
                        }
                    permitted_layers[layer_name]['attributes'].update(layer_permission.get('attributes', []))

        elif api == 'features':
            # collect permissions from wfs permissions
            wfs_permissions = self.permissions_handler.resource_permissions(
                "wfs_services", identity, service_name
            )
            for permissions in wfs_permissions:
                for layer_permission in permissions['layers']:
                    layer_name = layer_permission['name']
                    if layer_name not in permitted_layers:
                        permitted_layers[layer_name] = {
                            'attributes': set(),
                        }
                    permitted_layer = permitted_layers[layer_name]
                    permitted_layer['writable'] = permitted_layer.get('writable', False) or layer_permission.get('writable', False)
                    permitted_layer['creatable'] = permitted_layer.get('creatable', False) or layer_permission.get('creatable', False)
                    permitted_layer['readable'] = permitted_layer.get('readable', False) or layer_permission.get('readable', False)
                    permitted_layer['updatable'] = permitted_layer.get('updatable', False) or layer_permission.get('updatable', False)
                    permitted_layer['deletable'] = permitted_layer.get('deletable', False) or layer_permission.get('deletable', False)
                    permitted_layer['attributes'].update(layer_permission.get('attributes', []))

        return permitted_layers

    def index(self, identity, format_ext, auth_path):

        services = {}

        permitted_wms_services = set()
        for entry in self.permissions_handler.resource_permissions('wms_services', identity):
            permitted_wms_services.add(entry['name'])

        permitted_wfs_services = set()
        for entry in self.permissions_handler.resource_permissions('wfs_services', identity):
            permitted_wfs_services.add(entry['name'])

        for name, wms_service in self.resources.get("wms_services", {}).items():
            if not name in permitted_wms_services:
                continue
            if not name in services:
                services[name] = {"title": wms_service['title'] or name, "name": name, "links": []}
            services[name]["links"].append(
                {"href": url_for("ogc", service_name=name, service="WMS", request="GetCapabilities"), "rel": "wms-capabilities", "title": "WMS Capabilities", "type": "text/xml"}
            )

        for name, wfs_service in self.resources.get("wfs_services", {}).items():
            if not name in permitted_wfs_services:
                continue
            if not name in services:
                services[name] = {"title": wfs_service['title'] or name, "name": name, "links": []}
            services[name]["links"].append(
                {"href": url_for("ogc", service_name=name, service="WFS", request="GetCapabilities"), "rel": "wfs-capabilities", "title": "WFS Capabilities", "type": "text/xml"}
            )
            services[name]["links"].append(
                {"href": url_for("oapif", service_name=name, api_path="collections"), "rel": "data", "title": "Feature collections", "type": "application/json"}
            )
            services[name]["links"].append(
                {"href": url_for("oapif", service_name=name, api_path="conformance"), "rel": "conformance", "title": "Conformance classes", "type": "application/json"}
            )
            services[name]["links"].append(
                {"href": url_for("oapif", service_name=name, api_path="api"), "rel": "service-desc", "title": "API description", "type": "application/vnd.oai.openapi+json;version=3.0"}
            )

        links = [
            {
                "href": url_for('index', format_ext='html'),
                "rel": "self",
                "title": "Landing page as HTML",
                "type": "text/html"
            },
            {
                "href": url_for('index', format_ext='json'),
                "rel": "alternate",
                "title": "Landing page as JSON",
                "type": "application/json"
            }
        ]
        if auth_path:
            endpoint = "login" if not identity else "logout"
            title = "Login" if not identity else "Logout " + get_username(identity)
            links.append({
                "href": auth_path + endpoint + "?url=" + quote(url_for("root")),
                "rel": "auth",
                "title": title,
                "type": "text/html"
            })

        if format_ext == "json":
            # NOTE: invert sel/alternate link rels
            for link in links:
                link['rel'] = 'self' if link['rel'] == 'alternate' else 'self'
            return jsonify({"services": services, "links": links})
        else:
            env = Environment(loader=FileSystemLoader('templates/ogcapi'))
            template = env.get_template("getIndex.html")
            metadata = {
                "pageTitle": "Landing page",
                "navigation": []
            }
            return Response(
                template.render(services=[RecursiveNamespace(**service) for service in services.values()],
                                links=[RecursiveNamespace(**link) for link in links],
                                metadata=RecursiveNamespace(**metadata),
                                static=lambda filename: url_for('static', filename=filename),
                                **self.template_util_funcs
                ),
                mimetype="text/html"
            )


    def request(self, identity, method, service_name, api, api_path, format_ext, params, data, auth_path):
        """Check and filter OGC request and forward to QGIS server.

        :param str identity: User identity
        :param str method: Request method 'GET' or 'POST'
        :param str service_name: OGC service name
        :param str api: OGC API name (features, maps)
        :param str api_path: API path
        :param str format_ext: Format specifier extensions
        :param obj params: Request parameters
        :param obj data: Request POST data
        :param str auth_path: Auth service URL
        """

        permissions = self.service_permissions(identity, service_name, api)

        # Check if service is permitted
        if not permissions:
            error = [{"code":"API not found error","description":"Service with given id (%s) was not found" % service_name}]
            return error, 400

        # Sanitize api_path
        api_path = api_path.rstrip('/')
        if api_path and not api_path.startswith('/'):
            api_path = '/' + api_path

        context = {
            'url': url_for(
                'oapif',
                service_name=service_name,
                api_path=api_path.lstrip('/')
            ),
            'service_name': service_name,
            'api': api,
            'api_path': api_path,
            'method': method,
            'params': params,
            'format_ext': format_ext,
            'html_format': format_ext in ['', 'html']
        }


        api_handlers = None
        if api == 'features':
            for pattern, handlers in self.feature_handlers.items():
                if re.match(pattern, api_path):
                    api_handlers = handlers
                    break

        if not api_handlers or not method in api_handlers['allowed_methods']:
            error = [{"code":"Bad request error","description":"Endpoint %s for method %s does not exist" % (api_path, method)}]
            return error, 404

        # Filter request
        params, data, error, status = api_handlers["filter_request"](params, data, context, permissions)

        if error:
            return error, status

        # Forward request to QGIS Server
        self.logger.debug("Service name is %s" % (self.qgis_server_url_tenant_suffix + service_name))
        headers = {'X-QGIS-Project-File': self.qgis_server_url_tenant_suffix + service_name}
        forward_url = self.oapi_qgis_server_url + api_path + ".json"
        self.logger.debug("Forwarding %s request to %s" % (method, forward_url))
        if method == 'GET':
            response = requests.get(forward_url, params=params, headers=headers, timeout=self.network_timeout)
        elif method == 'POST':
            response = requests.post(forward_url, json=data, params=params, headers=headers, timeout=self.network_timeout)
        elif method == 'PUT':
            response = requests.put(forward_url, json=data, params=params, headers=headers, timeout=self.network_timeout)
        elif method == 'PATCH':
            # FIXME QGIS Server not OGC API standards compliant?
            # contentType = {
            #     "Content-Type": "application/merge-patch+json"
            # }
            # response = requests.patch(forward_url, data=json.dumps(data), params=params, headers=headers | contentType)
            response = requests.patch(forward_url, json=data, params=params, headers=headers, timeout=self.network_timeout)
        elif method == 'DELETE':
            response = requests.delete(forward_url, json=data, params=params, headers=headers, timeout=self.network_timeout)

        self.logger.debug("Response code %d" % response.status_code)
        # Handle special response codes
        if response.status_code == 201:
            # FIXME: QGIS Server returns a bogous redirect url? Our fault?
            newid = response.headers['Location'].split("/")[-1]
            response = make_response("", 201)
            response.headers['Location'] = url_for('oapif', service_name=service_name, api_path=api_path.strip("/") + "/" + newid + ".json")
            return response

        if response.status_code == 200 and method == "DELETE":
            # FIXME; QGIS Server should probably return 204 No Content?
            return "", 204

        response_json = response.json()
        self.logger.debug(response_json)

        if response.status_code >= 400:
            return response_json, response.status_code

        # Rewrite links from internal qgis-server to external ogc-service
        self.__rewrite_links(response_json, context)

        if 'paths' in response_json and isinstance(response_json['paths'], dict):
            oapi_root_path = urlparse(self.oapi_qgis_server_url).path
            def rewrite_api_path(kv):
                if kv[0].startswith(oapi_root_path):
                    newkey = url_for('oapif', service_name=context['service_name'], api_path='').rstrip('/') + kv[0][len(oapi_root_path):]
                    return (newkey, kv[1])
                return kv
            response_json['paths'] = dict(map(rewrite_api_path, response_json['paths'].items()))

        # Add login link if not authenticated
        if 'links' in response_json and auth_path:
            endpoint = "login" if not identity else "logout"
            title = "Login" if not identity else "Logout " + get_username(identity)
            response_json['links'].append({
                "href": auth_path + endpoint + "?url=" + quote(url_for("oapif", service_name=service_name, api_path=api_path.strip("/"))),
                "rel": "auth",
                "title": title,
                "type": "text/html"
            })

        # Filter response
        filtered_json, template_name, metadata = api_handlers["filter_response"](response_json, context, permissions)

        # Return json/html response
        if format_ext == "json" or format_ext == "geojson":
            return filtered_json, response.status_code

        else:

            def path_append(name):
                base, ext = posixpath.splitext(context['url'])
                return posixpath.join(base, name) + ext

            env = Environment(loader=FileSystemLoader('templates/ogcapi'))
            template = env.get_template(template_name)
            return Response(
                template.render(**(RecursiveNamespace(**filtered_json).__dict__),
                                metadata=RecursiveNamespace(**metadata),
                                static=lambda filename: url_for('static', filename=filename),
                                path_append=path_append,
                                **self.template_util_funcs
                ),
                mimetype="text/html"
            )

    def __rewrite_links(self, json, context):
        if isinstance(json, list):
            for entry in json:
                self.__rewrite_links(entry, context)
        elif isinstance(json, dict):
            for (key, value) in json.items():
                if key == 'links' and isinstance(value, list):
                    for link in value:
                        # Rewrite internal urls
                        if link['href'].startswith(self.oapi_qgis_server_url):
                            api_path = link['href'][len(self.oapi_qgis_server_url):].lstrip('/')
                            if api_path.endswith('.html'):
                                api_path = api_path[:-5]
                            link['href'] = url_for(
                                'oapif',
                                service_name=context['service_name'],
                                api_path=api_path
                            )
                        elif link['href'].startswith(self.root_qgis_server_url + "/?"):
                            query = dict(parse_qsl(link['href'][len(self.root_qgis_server_url + "/?"):]))
                            link['href'] = url_for('ogc', service_name=context['service_name'], **query)

                        # Avoid double quoting links
                        link['href'] = unquote(link['href'])

                        if context['html_format']:
                            # Swap rel=alternate and rel=self: since we query .json from the QGIS Server,
                            # rel=alternate points to .html, but as we return .html, we want to display the link to the .json
                            if link['rel'] == 'alternate':
                                link['rel'] = 'self'
                            elif link['rel'] == 'self':
                                link['rel'] = 'alternate'
                            # Strip .json or .geojson from navigation links
                            if link['rel'] in ['prev', 'next', 'first', 'last']:
                                parsed_url = urlparse(link['href'])
                                if parsed_url.path.endswith(".json"):
                                    link['href'] = urlunparse(parsed_url._replace(path=parsed_url.path[:-5]))
                                elif parsed_url.path.endswith(".geojson"):
                                    link['href'] = urlunparse(parsed_url._replace(path=parsed_url.path[:-8]))

                elif isinstance(value, list) or isinstance(value, dict):
                    self.__rewrite_links(value, context)


    def __getLandingPage_request(self, params, data, context, permissions):
        return params, data, None, None

    def __getLandingPage_response(self, json, context, permissions):
        metadata = {
            "pageTitle": "Landing page",
            "navigation": []
        }
        return json, 'getLandingPage.html', metadata


    def __getApiDescription_request(self, params, data, context, permissions):
        return params, data, None, None

    def __getApiDescription_response(self, json, context, permissions):
        metadata = {
            "pageTitle": "API description",
            "navigation": [{"title": "Landing page", "href": url_for("root")}]
        }
        return json, 'getApiDescription.html', metadata


    def __getRequirementClasses_request(self, params, data, context, permissions):
        return params, data, None, None

    def __getRequirementClasses_response(self, json, context, permissions):
        metadata = {
            "pageTitle": "WFS 3.0 conformance classes",
            "navigation": [{"title": "Landing page", "href": url_for("root")}]
        }
        return json, 'getRequirementClasses.html', metadata


    def __describeCollections_request(self, params, data, context, permissions):
        return params, data, None, None

    def __describeCollections_response(self, json, context, permissions):
        # Filter permitted collections (=layers)
        json["collections"] = list(filter(
            lambda entry: wfs_clean_layer_name(entry["id"]) in permissions,
            json["collections"]
        ))
        metadata = {
            "pageTitle": context["service_name"],
            "navigation": [{"title": "Landing page", "href": url_for("root")}]
        }
        return json, 'describeCollections.html', metadata


    def __describeCollection_request(self, params, data, context, permissions):
        # Check if collection (=layer) is permitted
        layer_name = wfs_clean_layer_name(context["api_path"].split("/")[2])
        error = None
        status = None
        layer_permissions = permissions.get(layer_name)
        if not layer_permissions or not layer_permissions.get("readable"):
            error = [{"code":"API not found error","description":"Collection with given id (%s) was not found, not permitted, or multiple matches were found" % layer_name}]
            status = 404
        return params, data, error, status

    def __describeCollection_response(self, json, context, permissions):
        metadata = {
            "pageTitle": unquote(context['url'].split("/")[-1]),
            "navigation": [
                {"title": "Landing page", "href": url_for("root")},
                {"title": context["service_name"], "href": parentLink(context['url'])}
            ]
        }
        return json, 'describeCollection.html', metadata


    def __getFeatures_request(self, params, data, context, permissions):
        # Check if collection (=layer) is permitted
        layer_name = wfs_clean_layer_name(context["api_path"].split("/")[2])
        error = None
        status = None
        layer_permissions = permissions.get(layer_name)
        if not layer_permissions or (context['method'] == 'GET' and not layer_permissions.get("readable")):
            error = [{"code":"API not found error","description":"Collection with given id (%s) was not found, not permitted, or multiple matches were found" % layer_name}]
            status = 404

        elif context['method'] == 'POST':

            # Check if writable
            if not layer_permissions.get('writable') or not layer_permissions.get('creatable'):
                error = [{"code":"Forbidden","description":"Features cannot be added to layer '%s'" % layer_name}]
                status = 403
            else:
                # Filter attributes
                # NOTE: QGIS Server expects attribute names, not aliases, on POST
                if "properties" in data:
                    data["properties"] = dict(filter(
                        lambda kv: wfs_clean_attribute_name(kv[0]) in layer_permissions['attributes'],
                        data["properties"].items()
                    ))

        return params, data, error, status

    def __getFeatures_response(self, json, context, permissions):
        layer_name = wfs_clean_layer_name(context["api_path"].split("/")[2])

        # Filter attributes
        attributes = self.resources['wfs_services'][context['service_name']]['layers'][layer_name]

        # NOTE: attribute aliases are used in properties, resolve them to attribute names
        alias_attributes = dict([x[::-1] for x in attributes.items()])

        for feature in json["features"]:
            feature["properties"] = dict(filter(
                lambda kv: alias_attributes.get(kv[0], kv[0]) in permissions[layer_name]['attributes'],
                feature.get("properties", {}).items()
            ))

        parsed_url = urlparse(context["url"])
        filtered_query = [(k, v) for k, v in parse_qsl(parsed_url.query) if k not in ('limit', 'offset')]
        cleanedUrl = urlunparse(parsed_url._replace(query=urlencode(filtered_query)))
        cleanedUrl += '&' if '?' in cleanedUrl else '?'

        # Page size
        pagesize = []
        maxLimit = self.oapif_max_limit
        matchedFeaturesCount = json['numberMatched']
        for count in [1, 10, 20, 50, 100, 1000]:
            if matchedFeaturesCount > count and maxLimit > count:
                pagesize.append({"title": "%d" % count, "href": cleanedUrl + "offset=0&limit=%d" % count})
        maxTitle = "All";
        if maxLimit < matchedFeaturesCount:
            maxTitle = "Maximum"
        pagesize.append({"title": maxTitle, "href": cleanedUrl + "offset=0&limit=%d" % maxLimit })

        # Pagination
        limit = int(context["params"].get("limit", "10"))
        offset = int(context["params"].get("offset", "0"))
        selfLink = list(filter(lambda link: link['rel'] == 'self', json['links']))[0]
        pagination = []

        if limit != 0 and matchedFeaturesCount - limit > 0:
            totalPages = math.ceil(matchedFeaturesCount / limit)
            currentPage = offset // limit + 1
            currentPageLink = selfLink["href"]

            prevPageLink = None
            if offset != 0:
                prevPageLink = cleanedUrl + "offset=%d&limit=%d" % (max(0, offset - limit), limit)

            nextPageLink = None
            if limit + offset < matchedFeaturesCount:
                nextPageLink = cleanedUrl + "offset=%d&limit=%d" % (min(matchedFeaturesCount, offset + limit), limit)

            firstPageLink = cleanedUrl + "offset=0&limit=%d" % limit
            lastPageLink = cleanedUrl + "offset=%d&limit=%d" % (totalPages * limit - limit, limit)

            if currentPage != 1:
                pagination.append({"title": "1", "href": firstPageLink, "class": "page-item"})
            if currentPage > 3:
                pagination.append({"title": "\u2026", "class": "page-item disabled"})
            if currentPage > 2:
                pagination.append({"title": str(currentPage - 1), "href": prevPageLink, "class": "page-item"})
            pagination.append({"title": str(currentPage), "href": currentPageLink, "class": "page-item active"})
            if currentPage < totalPages - 1:
                pagination.append({"title": str(currentPage + 1), "href": nextPageLink, "class": "page-item"})
            if currentPage < totalPages - 2:
                pagination.append({"title": "\u2026", "class": "page-item disabled"})
            if currentPage != totalPages:
                pagination.append({"title": str(totalPages), "href": lastPageLink, "class": "page-item"})

        title = unquote(context['url'].split("/")[-2])
        metadata = {
            "pageTitle": "Features in layer " + title,
            "layerTitle": title,
            "geojsonUrl": context["url"] + ".json",
            "pagesize": pagesize,
            "pagination": pagination,
            "navigation": [
                {"title": "Landing page", "href": url_for("root")},
                {"title": context["service_name"], "href": parentLink(context['url'], 2)},
                {"title": title, "href": parentLink(context['url'], 1)}
            ]
        }
        return json, 'getFeatures.html', metadata


    def __getFeature_request(self, params, data, context, permissions):
        # Check if collection (=layer) is permitted
        layer_name = wfs_clean_layer_name(context["api_path"]).split("/")[2]
        error = None
        status = None
        layer_permissions = permissions.get(layer_name)
        if not layer_permissions or (context['method'] == 'GET' and not layer_permissions.get("readable")):
            error = [{"code":"API not found error","description":"Collection with given id (%s) was not found, not permitted, or multiple matches were found" % layer_name}]
            status = 404

        elif context['method'] == 'PATCH':
            # Check if updatable
            if not layer_permissions.get('writable') or not layer_permissions.get('updatable'):
                error = [{"code":"Forbidden","description":"Features in layer '%s' cannot be changed" % layer_name}]
                status = 403
            else:
                # Filter attributes
                # NOTE: QGIS Server expects attribute names, not aliases, on PUT/PATCH
                if "modify" in data:
                    data["modify"] = dict(filter(
                        lambda kv: wfs_clean_attribute_name(kv[0]) in layer_permissions['attributes'],
                        data["modify"].items()
                    ))

        elif context['method'] == 'PUT':

            # Check if updatable
            if not layer_permissions.get('writable') or not layer_permissions.get('updatable'):
                error = [{"code":"Forbidden","description":"Features in layer '%s' cannot be changed" % layer_name}]
                status = 403
            else:
                # Filter attributes
                # NOTE: QGIS Server expects attribute names, not aliases, on PUT/PATCH
                if "properties" in data:
                    data["properties"] = dict(filter(
                        lambda kv: wfs_clean_attribute_name(kv[0]) in layer_permissions['attributes'],
                        data["properties"].items()
                    ))

        elif context['method'] == 'DELETE':

            # Check if deletable
            if not layer_permissions.get('writable') or not layer_permissions.get('deletable'):
                error = [{"code":"Forbidden","description":"Features in layer '%s' cannot be deleted" % layer_name}]
                status = 403

        return params, data, error, status

    def __getFeature_response(self, json, context, permissions):
        layer_name = wfs_clean_layer_name(context["api_path"].split("/")[2])

        # Filter attributes
        attributes = self.resources['wfs_services'][context['service_name']]['layers'][layer_name]

        # NOTE: attribute aliases are used in properties, resolve them to attribute names
        alias_attributes = dict([x[::-1] for x in attributes.items()])

        json["properties"] = dict(filter(
            lambda kv: alias_attributes.get(kv[0], kv[0]) in permissions[layer_name]['attributes'],
            json.get("properties", {}).items()
        ))

        title = unquote(context['url'].split("/")[-3])
        metadata = {
            "pageTitle": title + " - feature " + json["id"],
            "geojsonUrl": context['url'] + ".json",
            "navigation": [
                {"title": "Landing page", "href": url_for("root")},
                {"title": context["service_name"], "href": parentLink(context['url'], 3)},
                {"title": title, "href": parentLink(context['url'], 2)},
                {"title": "Items of " + title, "href": parentLink(context['url'])}
            ]
        }
        return json, 'getFeature.html', metadata
