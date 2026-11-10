"""Validate optional SGD amounts shared by listing and browse forms."""
from decimal import Decimal
import re


def parse_amount(value):
    value = (value or '').strip()
    if not value:
        return None
    if not re.fullmatch(r'[0-9]{1,12}(?:[.][0-9]{1,2})?', value):
        raise ValueError('Enter an SGD amount with up to 12 digits and up to two decimal places.')
    return Decimal(value)
