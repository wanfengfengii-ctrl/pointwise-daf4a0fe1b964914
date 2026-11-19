from collections.abc import Mapping
from dataclasses import dataclass
from sqlite3 import Connection

from ..ledger.integer_storage import decode_integer, encode_integer, require_integer


@dataclass(frozen=True, slots=True)
class OverrideChange:
    occurrence_id: str
    value: int | None


def create_override_schema(db: Connection) -> None:
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS override_events (
            revision INTEGER NOT NULL REFERENCES revisions(revision),
            day TEXT NOT NULL,
            occurrence_id TEXT NOT NULL REFERENCES observations(occurrence_id),
            offset_hex TEXT,
            PRIMARY KEY (revision, occurrence_id)
        )
        '''
    )
    db.execute(
        'CREATE INDEX IF NOT EXISTS override_events_by_day ON override_events(day, revision)'
    )


def parse_override_updates(updates: object) -> tuple[OverrideChange, ...]:
    if updates is None:
        return ()
    if not isinstance(updates, Mapping):
        raise ValueError('overrides must be a mapping')

    changes = []
    for occurrence_id, value in updates.items():
        if not isinstance(occurrence_id, str) or not occurrence_id:
            raise ValueError('override occurrence_id must be a nonempty string')
        if value is not None:
            require_integer(value, 'row override')
        changes.append(OverrideChange(occurrence_id, value))
    return tuple(sorted(changes, key=lambda change: change.occurrence_id))


def write_override_changes(
    db: Connection, day: str, revision: int, changes: tuple[OverrideChange, ...]
) -> None:
    rows = (
        (
            revision,
            day,
            change.occurrence_id,
            None if change.value is None else encode_integer(change.value),
        )
        for change in changes
    )
    db.executemany(
        '''
        INSERT INTO override_events (revision, day, occurrence_id, offset_hex)
        VALUES (?, ?, ?, ?)
        ''',
        rows,
    )


def read_overrides(db: Connection, day: str, revision: int) -> dict[str, int]:
    events = db.execute(
        '''
        SELECT occurrence_id, offset_hex FROM override_events
        WHERE day = ? AND revision <= ? ORDER BY revision
        ''',
        (day, revision),
    )
    overrides = {}
    for occurrence_id, offset in events:
        if offset is None:
            overrides.pop(occurrence_id, None)
        else:
            overrides[occurrence_id] = decode_integer(offset)
    return overrides


def read_override_events(db: Connection, revision: int) -> tuple[OverrideChange, ...]:
    events = db.execute(
        '''
        SELECT occurrence_id, offset_hex FROM override_events
        WHERE revision = ? ORDER BY occurrence_id COLLATE BINARY
        ''',
        (revision,),
    )
    return tuple(
        OverrideChange(key, None if offset is None else decode_integer(offset))
        for key, offset in events
    )
