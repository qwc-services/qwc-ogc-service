# Sample implementation of a custom layer info module

def layer_info(layer, x, y, crs, params, identity):
    """Query layer and return info result as dict:

        {
            'features': [
                {
                    'id': <feature ID>,  # optional
                    'attributes': [
                        {
                            'name': '<attribute name>',
                            'value': '<attribute value>'
                        }
                    ],
                    'bbox': [<minx>, <miny>, <maxx>, <maxy>],  # optional
                    'geometry': '<WKT geometry>'  # optional
                }
            ]
        }

    :param str layer: Layer name
    :param float x: X coordinate of query
    :param float y: Y coordinate of query
    :param str crs: CRS of query coordinates
    :param obj params: GetFeatureInfo service params
    :param str identity: User name or Identity dict
    """

    attributes = [
        {
            'name': 'title',
            'value': f'Feature for Layer {layer}'
        },
        {
            'name': 'name',
            'value': 'Feature Name'
        }
    ]
    px = round(x)
    py = round(y)

    return {
        'features': [{
            'id': 123,
            'attributes': attributes,
            'bbox': [px - 50, py - 50, px + 50, py + 50],
            'geometry': f"POINT({px} {py})"
        }]
    }
