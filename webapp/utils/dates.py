from typing import Any

# Stable English month abbreviations. strftime("%b") follows the process's C
# locale (LC_TIME), so on a non-English host it leaks localized month names into
# output that the app otherwise keeps in English (LANGUAGE_CODE defaults to
# "en-us"). Formatting from this table keeps month names deterministic.
_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def fmt_month_year(d: Any) -> str:
    """Format a date/datetime as 'Mon YYYY' in stable English, regardless of locale."""
    return f"{_MONTH_ABBR[d.month - 1]} {d.year}"


def fmt_day_month_year(d: Any) -> str:
    """Format a date/datetime as 'Mon D, YYYY' in stable English, regardless of locale."""
    return f"{_MONTH_ABBR[d.month - 1]} {d.day}, {d.year}"


def fmt_date(d: Any) -> str:
    """Format a date/datetime as 'Mon YYYY', or '—' if None."""
    return fmt_month_year(d) if d else "—"


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
