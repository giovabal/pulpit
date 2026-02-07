def hex_to_rgb(hex_color):
    normalized = hex_color.lstrip("#")
    length = len(normalized)
    if length not in (3, 6):
        raise ValueError("hex_to_rgb expects a 3 or 6 character hex value.")
    step = length // 3
    return tuple(int(normalized[i : i + step], 16) for i in range(0, length, step))


def rgb_to_hex(rgb):
    if isinstance(rgb, str):
        raise TypeError("rgb_to_hex expects an RGB sequence, not a string.")
    rgb_values = tuple(int(part) for part in rgb[:3])
    return "#%02x%02x%02x" % rgb_values


def rgb_avg(a, b):
    return tuple(int((int(a[index]) + int(b[index])) * 0.5) for index in range(3))


def is_color_dark(hex_color):
    rgb_color = hex_to_rgb(hex_color)
    return 0.2126 * rgb_color[0] + 0.7152 * rgb_color[1] + 0.0722 * rgb_color[2] < 128
