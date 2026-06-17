"""colorcet palette sampling for the Labels page "Recolor" picker."""

from __future__ import annotations

from typing import Any

from webapp.utils import colors as color_utils

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

_MAX_COUNT = 1000


@api_view(["GET"])
def palette_colors(request: Any, name: str) -> Response:
    """Return ``count`` hex colours sampled from colorcet palette ``name``.

    ``GET /manage/api/palettes/<name>/colors/?count=N`` → ``{name, count, colors}``.
    The sampling strategy (ordered for glasbey, evenly-spaced for gradients) is
    inferred server-side from the palette identity.
    """
    try:
        count = int(request.GET.get("count", "0"))
    except (TypeError, ValueError):
        return Response({"error": "count must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
    if not 0 <= count <= _MAX_COUNT:
        return Response({"error": f"count must be between 0 and {_MAX_COUNT}"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        colors = color_utils.colorcet_colors(name, count)
    except KeyError:
        return Response({"error": f"unknown palette '{name}'"}, status=status.HTTP_404_NOT_FOUND)
    return Response({"name": name, "count": count, "colors": colors})
