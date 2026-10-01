"""
Shared output formatting helpers.

These exist so that the same value renders identically wherever it is shown —
in a template, in a PDF, or in the body of a client-facing email. Format money
through these rather than inline (e.g. ``f"{invoice.total:.2f}"``) so the sign,
symbol and separators never diverge between surfaces.
"""

from decimal import Decimal


def format_currency(value: Decimal | float | int, symbol: str = "$") -> str:
    """Format a number as US currency.

    Comma thousands separator, period decimal separator, symbol in front and
    the minus sign ahead of the symbol.

    Example: ``Decimal("11064.03")`` -> ``"$11,064.03"``; ``-5`` -> ``"-$5.00"``
    """
    amount = float(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}{symbol}{abs(amount):,.2f}"


def format_currency_rounded(value: Decimal | float | int, symbol: str = "$") -> str:
    """Format a number as US currency rounded to whole dollars: ``"$11,065"``."""
    amount = round(float(value))
    sign = "-" if amount < 0 else ""
    return f"{sign}{symbol}{abs(amount):,}"
