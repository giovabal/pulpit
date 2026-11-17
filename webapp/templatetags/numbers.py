"""Number formatting for statistics pages: ``pct`` (a share as a percentage), ``thousands`` (an integer
with thousands separators), ``decimal`` (a fixed number of decimals), ``pval`` (a p-value) and
``signed_pct`` (a change). Each renders None as an
em dash, so a figure that cannot be computed reads as missing rather than as zero."""

from django import template

register = template.Library()

_MISSING = "—"


@register.filter
def pct(value: float | None, digits: int = 0) -> str:
    """0.257 → "26%" (``|pct:1`` → "25.7%")."""
    if value is None:
        return _MISSING
    return f"{value * 100:.{int(digits)}f}%"


@register.filter
def thousands(value: int | float | None) -> str:
    """13379 → "13,379"."""
    if value is None:
        return _MISSING
    return f"{round(value):,}"


@register.filter
def decimal(value: float | None, digits: int = 2) -> str:
    """0.6061 → "0.61" (``|decimal:1`` → "0.6")."""
    if value is None:
        return _MISSING
    return f"{value:,.{int(digits)}f}"


@register.filter
def pval(value: float | None) -> str:
    """A p- or q-value: 0.0213 → "0.021", 3e-7 → "<0.001"."""
    if value is None:
        return _MISSING
    return "<0.001" if value < 0.001 else f"{value:.3f}"


@register.filter
def signed_pct(value: float | None, digits: int = 0) -> str:
    """A change as a signed percentage: 0.12 → "+12%", −0.05 → "−5%"."""
    if value is None:
        return _MISSING
    text = f"{abs(value) * 100:.{int(digits)}f}%"
    return ("+" if value > 0 else "−" if value < 0 else "") + text
