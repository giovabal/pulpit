from typing import Any


def fmt_date(d: Any) -> str:
    """Format a date/datetime as 'Mon YYYY', or '—' if None."""
    return d.strftime("%b %Y") if d else "—"


def fmt_ttl(seconds: int) -> str:
    """Convert a Telegram message TTL (seconds) to a human-readable string."""
    if seconds <= 0:
        return ""
    known = {
        86400: "1 day",
        604800: "1 week",
        2592000: "1 month",
        31536000: "1 year",
    }
    if seconds in known:
        return known[seconds]
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''}"
