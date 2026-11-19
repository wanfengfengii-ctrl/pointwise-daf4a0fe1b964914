from dataclasses import dataclass
from sqlite3 import Connection

from ..ledger.integer_storage import decode_integer, encode_integer
from .selection import PresentedLine


@dataclass(frozen=True, slots=True)
class ReportHeader:
    report_id: int
    revision: int


@dataclass(frozen=True, slots=True)
class ArchivedLine:
    report_id: int
    position: int
    label: str
    value: int


def create_report_schema(db: Connection) -> None:
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS reports (
            report_id INTEGER PRIMARY KEY,
            revision INTEGER NOT NULL REFERENCES revisions(revision)
        )
        '''
    )
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS report_lines (
            report_id INTEGER NOT NULL REFERENCES reports(report_id),
            position INTEGER NOT NULL CHECK (position >= 0),
            label TEXT NOT NULL,
            value_hex TEXT NOT NULL,
            PRIMARY KEY (report_id, position)
        )
        '''
    )


def store_report(db: Connection, revision: int, lines: tuple[PresentedLine, ...]) -> int:
    report_id = db.execute('INSERT INTO reports (revision) VALUES (?)', (revision,)).lastrowid
    db.executemany(
        'INSERT INTO report_lines (report_id, position, label, value_hex) VALUES (?, ?, ?, ?)',
        (
            (report_id, position, line.label, encode_integer(line.value))
            for position, line in enumerate(lines)
        ),
    )
    return report_id


def load_report_header(db: Connection, report_id: int) -> ReportHeader:
    if type(report_id) is not int or not 0 < report_id <= 2**63 - 1:
        raise ValueError('report_id must be a positive SQLite report number')
    row = db.execute(
        'SELECT report_id, revision FROM reports WHERE report_id = ?', (report_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f'unknown report: {report_id}')
    return ReportHeader(*row)


def load_report_lines(db: Connection, report_id: int) -> tuple[ArchivedLine, ...]:
    rows = db.execute(
        '''
        SELECT position, label, value_hex FROM report_lines
        WHERE report_id = ? ORDER BY position
        ''',
        (report_id,),
    )
    return tuple(
        ArchivedLine(report_id, position, label, decode_integer(value))
        for position, label, value in rows
    )
