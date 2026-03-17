from typing import Any, ClassVar

from webapp.utils import hex_to_rgb

import bokeh
from bokeh.colors import RGB


class StatsViewMixin:
    primary_color: ClassVar[str] = RGB(*hex_to_rgb("#2563eb")).to_css()
    base_figure_options: ClassVar[dict[str, Any]] = {
        "height": 450,
        "sizing_mode": "stretch_width",
        "tools": "hover",
        "toolbar_location": None,
    }
    base_line_options: ClassVar[dict[str, Any]] = {"line_width": 2, "color": primary_color}

    @staticmethod
    def _style_plot(plot: Any) -> None:
        plot.background_fill_color = "#ffffff"
        plot.border_fill_color = "#ffffff"
        plot.outline_line_color = None
        plot.xgrid.grid_line_color = None
        plot.ygrid.grid_line_color = "#f0f0f0"
        plot.ygrid.grid_line_width = 1
        for axis in (plot.xaxis, plot.yaxis):
            axis.axis_line_color = "#e5e7eb"
            axis.major_tick_line_color = "#e5e7eb"
            axis.minor_tick_line_color = None
            axis.major_label_text_font = "Inter, system-ui, sans-serif"
            axis.major_label_text_font_size = "11px"
            axis.major_label_text_color = "#6b7280"
            axis.axis_label_text_font = "Inter, system-ui, sans-serif"
            axis.axis_label_text_font_size = "11px"
            axis.axis_label_text_color = "#6b7280"
            axis.axis_label_text_font_style = "normal"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context_data: dict[str, Any] = super().get_context_data(**kwargs)  # type: ignore[misc]
        context_data.update({"bokeh_version": bokeh.__version__})
        return context_data
