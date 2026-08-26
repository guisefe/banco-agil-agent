from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

CreditRequestStatus = Literal["aprovado", "rejeitado"]


@dataclass(frozen=True, slots=True, kw_only=True)
class CreditRequest:
    customer_cpf: str
    requested_at: datetime
    current_limit: Decimal
    requested_limit: Decimal
    status: CreditRequestStatus

    def __post_init__(self) -> None:
        if not self.customer_cpf.strip():
            raise ValueError("customer_cpf must not be blank")
        if self.requested_at.utcoffset() != timedelta(0):
            raise ValueError("requested_at must use UTC")
        if not self.current_limit.is_finite() or self.current_limit < 0:
            raise ValueError("current_limit must be non-negative")
        if not self.requested_limit.is_finite() or self.requested_limit <= self.current_limit:
            raise ValueError("requested_limit must be greater than current_limit")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoreBand:
    minimum_score: int
    maximum_score: int
    maximum_limit: Decimal

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_score <= self.maximum_score <= 1000:
            raise ValueError("score band must stay between 0 and 1000")
        if not self.maximum_limit.is_finite() or self.maximum_limit < 0:
            raise ValueError("maximum_limit must be non-negative")
