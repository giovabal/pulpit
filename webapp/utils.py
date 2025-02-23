from pprint import pprint


def _get_dict(obj):
    if hasattr(obj, "__dict__"):
        return {k: _get_dict(v) for k, v in obj.__dict__.items() if not callable(v) and not k.startswith("_")}
    else:
        return obj


def print_dict(obj):
    pprint(_get_dict(obj))


def hex_to_rgb(hex_color):
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def is_color_dark(hex_color):
    rgb_color = hex_to_rgb(hex_color)
    return 0.2126 * rgb_color[0] + 0.7152 * rgb_color[1] + 0.0722 * rgb_color[2] < 128
