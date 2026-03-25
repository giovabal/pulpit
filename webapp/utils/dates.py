from typing import Any


def fmt_date(d: Any) -> str:
    """Format a date/datetime as 'Mon YYYY', or '—' if None."""
    return d.strftime("%b %Y") if d else "—"
