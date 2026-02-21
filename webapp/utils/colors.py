from collections.abc import Iterable, Sequence
from typing import Any

import pypalettes

DEFAULT_FALLBACK_COLOR = (204, 204, 204)
COMMUNITY_ALGORITHMS = {"LOUVAIN", "KCORE", "INFOMAP"}
ColorTuple = tuple[int, int, int]


def _normalize_rgb_sequence(value: Sequence[Any]) -> ColorTuple:
    values = [float(part) for part in value[:3]]
    if values and max(values) <= 1:
        return tuple(int(part * 255) for part in values)
    return tuple(int(part) for part in values)


def hex_to_rgb(hex_color: str) -> ColorTuple:
    normalized = hex_color.lstrip("#")
    length = len(normalized)
    if length not in (3, 6):
        raise ValueError("hex_to_rgb expects a 3 or 6 character hex value.")
    step = length // 3
    return tuple(int(normalized[i : i + step], 16) for i in range(0, length, step))


def rgb_to_hex(rgb: Sequence[Any]) -> str:
    if isinstance(rgb, str):
        raise TypeError("rgb_to_hex expects an RGB sequence, not a string.")
    rgb_values = tuple(int(part) for part in rgb[:3])
    return "#%02x%02x%02x" % rgb_values


def rgb_avg(a: Sequence[Any], b: Sequence[Any]) -> ColorTuple:
    return tuple(int((int(a[index]) + int(b[index])) * 0.5) for index in range(3))


def is_color_dark(hex_color: str) -> bool:
    rgb_color = hex_to_rgb(hex_color)
    return 0.2126 * rgb_color[0] + 0.7152 * rgb_color[1] + 0.0722 * rgb_color[2] < 128


def parse_color(value: Any) -> ColorTuple:
    if hasattr(value, "hex"):
        return parse_color(value.hex)
    if hasattr(value, "hex_code"):
        return parse_color(value.hex_code)
    if hasattr(value, "rgb"):
        return parse_color(value.rgb)
    if hasattr(value, "rgba"):
        return parse_color(value.rgba)

    if isinstance(value, dict):
        rgb_keys = (("r", "g", "b"), ("red", "green", "blue"))
        for keys in rgb_keys:
            if all(key in value for key in keys):
                return parse_color([value[key] for key in keys])

    if isinstance(value, (list, tuple)):
        return _normalize_rgb_sequence(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lower().startswith("rgb"):
            channel_values = cleaned[cleaned.find("(") + 1 : cleaned.rfind(")")].split(",")
            parsed = [float(part.strip()) for part in channel_values if part.strip()]
            if not parsed:
                return DEFAULT_FALLBACK_COLOR
            if parsed and max(parsed) <= 1:
                return tuple(int(part * 255) for part in parsed[:3])
            return tuple(int(part) for part in parsed[:3])
        if "," in cleaned:
            return tuple(int(part.strip()) for part in cleaned.split(","))
        if " " in cleaned:
            parts = [part for part in cleaned.split(" ") if part]
            if len(parts) >= 3 and all(part.replace(".", "", 1).isdigit() for part in parts[:3]):
                return _normalize_rgb_sequence(parts)
        if cleaned.lower().startswith("0x"):
            cleaned = cleaned[2:]
        if cleaned.startswith("#"):
            cleaned = cleaned[1:]

        # Accept alpha-enabled hex values from palettes (e.g. RRGGBBAA / RGBBAA style).
        if len(cleaned) in {8, 4} and all(char in "0123456789abcdefABCDEF" for char in cleaned):
            cleaned = cleaned[:-2] if len(cleaned) == 8 else cleaned[:-1]

        try:
            return hex_to_rgb(cleaned)
        except ValueError:
            return DEFAULT_FALLBACK_COLOR

    if isinstance(value, Iterable):
        try:
            return parse_color(list(value))
        except TypeError:
            return DEFAULT_FALLBACK_COLOR
    return DEFAULT_FALLBACK_COLOR


def palette_colors(name: str) -> list[Any]:
    palette = None
    if hasattr(pypalettes, "load_palette"):
        palette = pypalettes.load_palette(name)
    elif hasattr(pypalettes, "get_palette"):
        palette = pypalettes.get_palette(name)
    elif hasattr(pypalettes, "Palette"):
        palette = pypalettes.Palette(name)
    if palette is None:
        raise ValueError(f"Palette '{name}' could not be loaded.")

    colors = None
    for attr in ("hex_colors", "hex", "palette", "colors"):
        if hasattr(palette, attr):
            colors = getattr(palette, attr)
            break
    if colors is None:
        colors = palette
    if not isinstance(colors, (list, tuple)):
        colors = list(colors)
    return colors


def expand_colors(colors: Sequence[Any], count: int) -> list[Any]:
    if not colors:
        return []
    if len(colors) >= count:
        return list(colors[:count])
    repeats = (count + len(colors) - 1) // len(colors)
    return (list(colors) * repeats)[:count]


def average_color(colors: Sequence[Any]) -> ColorTuple:
    if not colors:
        return DEFAULT_FALLBACK_COLOR
    totals = [0, 0, 0]
    for color in colors:
        for index, value in enumerate(parse_color(color)):
            totals[index] += value
    count = len(colors)
    return tuple(int(total / count) for total in totals)
