"""Preserve employee IDs as text, fixing Excel numeric cells like 12999.0."""
from decimal import Decimal, InvalidOperation


def username(value):
    if value is None:
        return ''
    value = str(value).strip().lower()
    # Only strip the trailing decimal from integral numeric IDs; retain leading zeros.
    if value.endswith('.0') and value[:-2].isdigit():
        return value[:-2]
    return value
