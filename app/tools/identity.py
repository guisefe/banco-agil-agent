from datetime import date, datetime


class IdentityInputError(ValueError):
    """Raised when a customer identity input has an invalid format."""


def normalize_cpf(value: str) -> str:
    digits = "".join(
        character for character in value if character.isascii() and character.isdigit()
    )
    if len(digits) != 11:
        raise IdentityInputError("cpf must contain 11 digits")
    return digits


def is_cpf_input(value: str) -> bool:
    try:
        normalize_cpf(value)
    except IdentityInputError:
        return False
    return True


def parse_birth_date(value: str, *, today: date | None = None) -> date:
    normalized_value = value.strip()
    parsed_date: date | None = None

    for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            parsed_date = datetime.strptime(normalized_value, date_format).date()
            break
        except ValueError:
            continue

    if parsed_date is None:
        raise IdentityInputError("birth date must use DD/MM/YYYY or YYYY-MM-DD")

    reference_date = today or date.today()
    if parsed_date > reference_date:
        raise IdentityInputError("birth date must not be in the future")

    return parsed_date
