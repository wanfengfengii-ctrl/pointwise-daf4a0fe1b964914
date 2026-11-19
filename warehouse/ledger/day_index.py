from datetime import date
from sqlite3 import Connection


def validate_day_key(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError('day must be a YYYY-MM-DD string')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('day must be a valid YYYY-MM-DD date') from exc
    if parsed.isoformat() != value:
        raise ValueError('day must use YYYY-MM-DD form')
    return value


def create_day_index_schema(db: Connection) -> None:
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS day_heads (
            day TEXT PRIMARY KEY NOT NULL,
            revision INTEGER NOT NULL REFERENCES revisions(revision)
        )
        '''
    )


def get_day_head(db: Connection, day: str) -> int | None:
    day = validate_day_key(day)
    row = db.execute('SELECT revision FROM day_heads WHERE day = ?', (day,)).fetchone()
    return row[0] if row is not None else None


def advance_day_head(db: Connection, day: str, revision: int) -> None:
    db.execute(
        '''
        INSERT INTO day_heads (day, revision) VALUES (?, ?)
        ON CONFLICT (day) DO UPDATE SET revision = excluded.revision
        ''',
        (day, revision),
    )
