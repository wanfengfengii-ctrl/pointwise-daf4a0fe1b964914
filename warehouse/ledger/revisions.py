from dataclasses import dataclass
from sqlite3 import Connection


@dataclass(frozen=True, slots=True)
class Revision:
    revision: int
    day: str
    kind: str


def create_revision_schema(db: Connection) -> None:
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS revisions (
            revision INTEGER PRIMARY KEY,
            day TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('accept', 'correction'))
        )
        '''
    )


def append_revision(db: Connection, day: str, kind: str) -> int:
    cursor = db.execute('INSERT INTO revisions (day, kind) VALUES (?, ?)', (day, kind))
    return cursor.lastrowid


def require_revision(db: Connection, number: int) -> Revision:
    if type(number) is not int or not 0 < number <= 2**63 - 1:
        raise ValueError('revision must be a positive SQLite revision number')
    row = db.execute(
        'SELECT revision, day, kind FROM revisions WHERE revision = ?', (number,)
    ).fetchone()
    if row is None:
        raise ValueError(f'unknown revision: {number}')
    return Revision(*row)
