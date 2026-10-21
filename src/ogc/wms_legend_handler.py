import base64
import copy
import os
from io import BytesIO
from typing import override

from flask import send_file
from PIL import Image

from ogc.ogc_service_handler import ServiceException
from ogc.wms_handler import WmsHandler

PIL_Formats = {
    "image/bmp": "BMP",
    "application/postscript": "EPS",
    "image/gif": "GIF",
    "image/jpeg": "JPEG",
    "image/jp2": "JPEG 2000",
    "image/x-pcx": "PCX",
    "image/png": "PNG",
    "image/tiff": "TIFF",
    "image/webp": "WebP"
}

FORMATS_WITH_ALPHA = set([
    "image/png",
    "image/webp"
])

class WmsLegendHandler(WmsHandler):
    """ Handler for GetLegendGraphic requests. """

    def __init__(self, logger, config, qgis_server_url, permission_handler, identity):
        """
        :param obj logger: Application logger
        :param obj config: Service config
        :param obj qgis_server_url: internal QGIS Server URL
        :param obj permission_handler: Permission handler
        :param obj identity: User identity
        """
        super().__init__(logger, config, qgis_server_url, permission_handler, identity)
        self.legend_images_path = config.get('legend_images_path', '/legends/')
        self.legend_default_font_size = config.get("legend_default_font_size")

    @staticmethod
    @override
    def accepts(req):
        """Whether the handler handle the specified request.

        :param OgcRequest req: The OGC request
        """
        return req.service == 'WMS' and req.request == 'GETLEGENDGRAPHIC'

    @override
    def adjust_request_params(self, req, permissions):
        """Check request parameters against permissions and adjust params, returning the adjusted OgcRequest

        :param OgcRequest req: The OGC request
        :param obj permissions: OGC service permissions
        """
        super().adjust_request_params(req, permissions)

        if self.legend_default_font_size:
            if 'layerfontsize' not in req.params:
                req.params['layerfontsize'] = self.legend_default_font_size
            if 'itemfontsize' not in req.params:
                req.params['itemfontsize'] = self.legend_default_font_size

    @override
    def process_request(self, req, permissions, stream):
        """ Process the request.

        :param OgcRequest req: The OGC request
        :param bool stream: Whether the response will be streamed
        :param obj permissions: OGC service permissions
        """

        dpi = req.params.get('dpi', 90)
        type = req.params.get('type', '')
        format_param = req.params.get('format', 'image/png')
        layers = req.params['LAYERS'].split(',')
        styles = req.params['STYLES'].split(',')

        images = []
        for layer, style in zip(layers, styles):
            custom_legend_image = self.get_custom_image(layer, style, type, permissions)
            if custom_legend_image is not None:
                if dpi != '90':
                    try:
                        # scale image to requested DPI
                        img = Image.open(BytesIO(custom_legend_image))
                        scale = float(dpi) / 90.0
                        new_size = (
                            int(img.width * scale), int(img.height * scale)
                        )
                        img = img.resize(new_size, Image.LANCZOS)
                        output = BytesIO()
                        # NOTE: save as PNG to preserve any alpha channel
                        img.save(output, "PNG")
                        images.append({"data": output, "format": None})

                    except Exception as e:
                        self.logger.error(f"Could not resize image for {layer}:\n{e!s}")
                        images.append({"data": BytesIO(custom_legend_image), "format": None})

                else:
                    images.append({"data": BytesIO(custom_legend_image), "format": None})

            else:
                if not images or "data" in images[-1]:
                    images.append({"LAYERS": [], "STYLES": []})
                images[-1]["LAYERS"].append(layer)
                images[-1]["STYLES"].append(style)

            # Forward GetLengend requests
            for idx, entry in enumerate(images):
                if "data" not in entry:
                    fwd_req = copy.copy(req)
                    fwd_req.params['LAYERS'] = ",".join(entry["LAYERS"])
                    fwd_req.params['STYLES'] = ",".join(entry["STYLES"])
                    fwd_req.params.pop('type', None)
                    try:
                        response = super().process_request(fwd_req, permissions, False)
                        buf = BytesIO()
                        buf.write(response.content)
                        images[idx] = {"data": buf, "format": format_param}
                    except ServiceException:
                        # Empty image in case of server error
                        output = BytesIO()
                        Image.new("RGB", (1, 1), (255, 255, 255)).save(
                            output, PIL_Formats[format_param]
                        )
                        images[idx] = {"data": output, "format": format_param}

        if len(images) == 1:
            # If just one image, return it
            if images[0]["format"] != format_param:
                # Convert to requested format if necessary
                output = BytesIO()
                try:
                    images[0]["data"].seek(0)
                    image = Image.open(images[0]["data"])
                    if not self.format_has_alpha(format_param):
                        image = self.convert_img_to_rgb(image)
                    image.save(output, PIL_Formats[format_param])
                except Exception as e:
                    self.logger.error(f"Could not convert image to {format_param}:\n{e!s}")
                    # Empty 1x1 image
                    Image.new("RGB", (1, 1), (255, 255, 255)).save(output, PIL_Formats[format_param])
                images[0]["data"] = output

            images[0]["data"].seek(0)
            return {"data": images[0]["data"], "format": format_param}

        else:
            # Otherwise, compose images
            width = 0
            height = 0
            for entry in images:
                try:
                    entry["image"] = Image.open(entry["data"])
                    if not self.format_has_alpha(format_param):
                        entry["image"] = self.convert_img_to_rgb(entry["image"])
                    width = max(width, entry["image"].width)
                    height += entry["image"].height
                except: #noqa 722
                    entry["image"] = None

            if self.format_has_alpha(format_param):
                image = Image.new("RGBA", (width, height), (255, 255, 255, 255))
            else:
                image = Image.new("RGB", (width, height), (255, 255, 255))

            y = 0
            for entry in images:
                if entry["image"]:
                    image.paste(entry["image"], (0, y))
                    y += entry["image"].height

            data = BytesIO()
            image.save(data, PIL_Formats[format_param])
            data.seek(0)
            return {"data": data, "format": format_param}

    @override
    def build_response(self, req, response, permissions, stream):
        """Build the (possibly filtered) response.

        :param OgcRequest req: The OGC request
        :param obj response: The request response
        :param obj permissions: OGC service permissions
        :param bool stream: Whether to stream the response
        """
        return send_file(response["data"], mimetype=response["format"])

    def get_custom_image(self, layer, style, type, permissions):
        """ Return the custom legend image for the specified layer, if found
            - A filename matching legend_images_path/<service_name>/<layer>_<style>_<suffix>.png
            - A filename matching legend_images_path/<service_name>/<layer>_<suffix>.png
            - A filename matching legend_images_path/<service_name>/default_<suffix>.png
            - A filename matching legend_images_path/<service_name>/<layer>_<style>.png
            - A filename matching legend_images_path/<service_name>/<layer>.png
            - A filename matching legend_images_path/<resource_entry[legend_image]>
            - A filename matching legend_images_path/<service_name>/default.png
            - As base64 in <resource_entry[legend_image_base64]>
        Where _<suffix> may be "_thumbnail" or "_tooltip".

        :param str layer: The layer name
        :param str style: The layer style name
        :param str type: The legend image type
        :param dict permissions: The OGC service permissions
        """
        # Check for image in legend_images_path
        service_name = permissions['service_name']
        layer_permissions = permissions['permitted_layers'][layer]

        filenames = []
        if type == "thumbnail":
            filenames.append(os.path.join(service_name, layer + "_" + style + "_thumbnail.png"))
            filenames.append(os.path.join(service_name, layer + "_thumbnail.png"))
            filenames.append("default_thumbnail.png")
        elif type == "tooltip":
            filenames.append(os.path.join(service_name, layer + "_" + style + "_tooltip.png"))
            filenames.append(os.path.join(service_name, layer + "_tooltip.png"))
            filenames.append("default_tooltip.png")
        filenames.append(os.path.join(service_name, layer + "_" + style + '.png'))
        filenames.append(os.path.join(service_name, layer + '.png'))

        if layer_permissions['legend_image']:
            filenames.append(layer_permissions['legend_image'])

        filenames.append('default.png')

        for filename in filenames:
            image_path = os.path.join(self.legend_images_path, filename)
            self.logger.debug(
                f"Looking for legend image '{image_path}' for layer '{layer}'..."
            )
            try:
                with open(os.path.join(self.legend_images_path, filename), 'rb') as fh:
                    data = fh.read()
            except OSError:
                data = None
            if data:
                self.logger.debug(
                    f"Loading legend image '{image_path}' for layer '{layer}'"
                )
                return data

        # Check for base64 image in resource entry
        if layer_permissions['legend_image_base64']:
            self.logger.debug(f"Decoded base64 custom legend for layer '{layer}'")
            return base64.b64decode(layer_permissions['legend_image_base64'])

        self.logger.debug(f"No custom legend image of type '{type}' found for layer '{layer}'")
        return None

    def format_has_alpha(self, format_param):
        """Return whether image format supports alpha channel.

        :param string format_param: Image format as media type
        """
        return format_param in FORMATS_WITH_ALPHA

    def convert_img_to_rgb(self, image):
        """Return image as RGB, converting from RGBA if necessary.

        :param Image image: Input image
        """
        if image.mode == 'RGBA':
            # remove alpha channel by compositing with white background
            background = Image.new("RGBA", image.size, (255, 255, 255, 255))
            image = Image.alpha_composite(background, image).convert("RGB")

        return image
