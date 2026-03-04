from typing import Any, ClassVar

from webapp.utils import hex_to_rgb

import bokeh
from bokeh.colors import RGB


class StatsViewMixin:
    primary_color: ClassVar[str] = RGB(*hex_to_rgb("#A45219")).to_css()
    base_figure_options: ClassVar[dict[str, Any]] = {
        "height": 450,
        "sizing_mode": "stretch_width",
        "tools": "hover",
        "toolbar_location": "above",
    }
    base_line_options: ClassVar[dict[str, Any]] = {"line_width": 4, "color": primary_color}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context_data: dict[str, Any] = super().get_context_data(**kwargs)  # type: ignore[misc]
        context_data.update({"bokeh_version": bokeh.__version__})
        return context_data
