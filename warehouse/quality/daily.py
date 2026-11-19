from dataclasses import dataclass
from sqlite3 import Connection

from ..ledger.history import load_day_facts
from ..ledger.transactions import read_snapshot
from .effective import EffectiveRow, compute_effective_rows
from .exceedance import select_exceedances, validate_threshold
from .totals import GroupTotal, summarize_groups


@dataclass(frozen=True, slots=True)
class DayInspection:
    day: str
    revision: int
    threshold: int
    rows: tuple[EffectiveRow, ...]
    groups: tuple[GroupTotal, ...]
    exceedances: tuple[EffectiveRow, ...]


def read_effective_day(db: Connection, day: str, revision: int) -> tuple[EffectiveRow, ...]:
    """Materialize fixed effective rows within the caller's transaction."""
    return compute_effective_rows(load_day_facts(db, day, revision))


def inspect_day(db: Connection, day: str, revision: int, threshold: int) -> DayInspection:
    threshold = validate_threshold(threshold)
    with read_snapshot(db):
        rows = read_effective_day(db, day, revision)
    exceedances = select_exceedances(rows, threshold)
    return DayInspection(day, revision, threshold, rows, summarize_groups(rows, exceedances), exceedances)
