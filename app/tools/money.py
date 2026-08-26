import re
from decimal import Decimal, InvalidOperation

_MONEY_PATTERN = re.compile(
    r"^(?:R\$)?(?:(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?|\d+(?:\.\d{1,2})?)$"
)


def parse_money(value: str) -> Decimal:
    normalized = "".join(value.strip().split())
    if not _MONEY_PATTERN.fullmatch(normalized):
        raise ValueError("invalid monetary value")

    if normalized.startswith("R$"):
        normalized = normalized[2:]
    if "," in normalized or normalized.count(".") > 1:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "." in normalized and len(normalized.rsplit(".", maxsplit=1)[1]) == 3:
        normalized = normalized.replace(".", "")

    try:
        amount = Decimal(normalized).quantize(Decimal("0.01"))
    except InvalidOperation as error:
        raise ValueError("invalid monetary value") from error
    if amount <= 0:
        raise ValueError("monetary value must be positive")
    return amount


def format_brl(value: Decimal) -> str:
    formatted = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {formatted}"
