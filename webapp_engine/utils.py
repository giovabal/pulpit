def hex_to_rgb(value):
    value = value.lstrip("#")
    lv = len(value)
    return tuple(int(value[i : i + lv // 3], 16) for i in range(0, lv, lv // 3))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % rgb


def rgb_avg(a, b):
    return map(int, [(int(a[0]) + int(b[0])) * 0.5, (int(a[1]) + int(b[1])) * 0.5, (int(a[2]) + int(b[2])) * 0.5])
