def is_geojson_geometry(obj) -> bool:
    return isinstance(obj, dict) and isinstance(obj.get('type'), str) and obj.get('coordinates') is not None
