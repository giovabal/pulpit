def hex_to_rgb(value):
    value = value.lstrip("#")
    lv = len(value)
    return tuple(int(value[i : i + lv // 3], 16) for i in range(0, lv, lv // 3))


def rgb_to_hex(rgb):
    if isinstance(rgb, str):
        raise TypeError("rgb_to_hex expects an RGB sequence, not a string.")
    rgb_values = tuple(int(part) for part in rgb[:3])
    return "#%02x%02x%02x" % rgb_values


def rgb_avg(a, b):
    return tuple(int((int(a[index]) + int(b[index])) * 0.5) for index in range(3))
