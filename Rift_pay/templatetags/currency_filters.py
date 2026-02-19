from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def fcfa(value):
    if value is None:
        amount = Decimal('0.00')
    else:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            amount = Decimal('0.00')

    formatted = f"{amount:,.2f}"
    formatted = formatted.replace(',', ' ').replace('.', ',')
    return f"{formatted} FCFA"
