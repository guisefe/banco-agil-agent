from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Customer:
    cpf: str
    name: str
    birth_date: date
    credit_limit: Decimal
    credit_score: int

    def __post_init__(self) -> None:
        if not self.cpf.strip():
            raise ValueError("cpf must not be blank")
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if not self.credit_limit.is_finite() or self.credit_limit < 0:
            raise ValueError("credit_limit must be non-negative")
        if not 0 <= self.credit_score <= 1000:
            raise ValueError("credit_score must be between 0 and 1000")
