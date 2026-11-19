from collections.abc import Iterable

from ..ledger.integer_storage import require_integer
from .effective import EffectiveRow


def validate_threshold(value: object) -> int:
    return require_integer(value, 'threshold')


def is_exceedance(row: EffectiveRow, threshold: int) -> bool:
    return row.value > threshold


def select_exceedances(
    rows: Iterable[EffectiveRow], threshold: int
) -> tuple[EffectiveRow, ...]:
    return tuple(row for row in rows if is_exceedance(row, threshold))
