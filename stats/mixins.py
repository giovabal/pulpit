from webapp.utils import hex_to_rgb

import bokeh
from bokeh.colors import RGB


class StatsViewMixin:
    primary_color = RGB(*hex_to_rgb("#A45219")).to_css()
    secondary_color = RGB(*hex_to_rgb("#4f6181")).to_css()
    template_name = "stats/stats.html"
    base_figure_options = {
        "height": 350,
        "sizing_mode": "stretch_width",
        "tools": "hover",
        "toolbar_location": "above",
    }
    base_vbar_options = {"x": "year", "width": 0.9, "bottom": 0, "top": "amount", "color": primary_color}
    base_line_options = {"line_width": 4, "color": primary_color}

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        context_data.update({"bokeh_version": bokeh.__version__})

        return context_data
