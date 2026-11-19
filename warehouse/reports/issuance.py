from collections.abc import Sequence
from dataclasses import dataclass
from sqlite3 import Connection

from ..ledger.transactions import atomic_write
from ..quality.daily import read_effective_day
from .archive import store_report
from .selection import PresentedLine, resolve_selection


@dataclass(frozen=True, slots=True)
class IssuedReport:
    report_id: int
    lines: tuple[PresentedLine, ...]


def issue_report(
    db: Connection, day: str, revision: int, occurrence_ids: Sequence[str]
) -> IssuedReport:
    with atomic_write(db):
        rows = read_effective_day(db, day, revision)
        lines = resolve_selection(rows, occurrence_ids)
        report_id = store_report(db, revision, lines)
        return IssuedReport(report_id, lines)
