from pprint import pprint


def _get_dict(obj):
    if hasattr(obj, "__dict__"):
        return {k: _get_dict(v) for k, v in obj.__dict__.items() if not callable(v) and not k.startswith("_")}
    else:
        return obj


def print_dict(obj):
    pprint(_get_dict(obj))


def hex_to_rgb(hex_color):
    normalized = hex_color.lstrip("#")
    length = len(normalized)
    if length not in (3, 6):
        raise ValueError("hex_to_rgb expects a 3 or 6 character hex value.")
    step = length // 3
    return tuple(int(normalized[i : i + step], 16) for i in range(0, length, step))


def is_color_dark(hex_color):
    rgb_color = hex_to_rgb(hex_color)
    return 0.2126 * rgb_color[0] + 0.7152 * rgb_color[1] + 0.0722 * rgb_color[2] < 128
