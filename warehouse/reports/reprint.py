from dataclasses import dataclass
from sqlite3 import Connection

from ..ledger.transactions import read_snapshot
from .archive import load_report_header, load_report_lines
from .selection import PresentedLine


@dataclass(frozen=True, slots=True)
class ReprintedReport:
    report_id: int
    revision: int
    lines: tuple[PresentedLine, ...]


def read_report(db: Connection, report_id: int) -> ReprintedReport:
    with read_snapshot(db):
        header = load_report_header(db, report_id)
        archived = load_report_lines(db, header.report_id)
    lines = tuple(PresentedLine(row.label, row.value) for row in archived)
    return ReprintedReport(header.report_id, header.revision, lines)
