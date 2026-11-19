from collections.abc import Mapping, Set
from sqlite3 import Connection

from ..ledger.integer_storage import decode_integer, encode_integer, require_integer


def create_group_offset_schema(db: Connection) -> None:
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS group_offset_events (
            revision INTEGER NOT NULL REFERENCES revisions(revision),
            day TEXT NOT NULL,
            group_id TEXT NOT NULL,
            offset_hex TEXT NOT NULL,
            PRIMARY KEY (revision, group_id)
        )
        '''
    )
    db.execute(
        '''
        CREATE INDEX IF NOT EXISTS group_events_by_day
        ON group_offset_events(day, revision)
        '''
    )


def validate_group_updates(
    updates: object, visible_groups: Set[str]
) -> tuple[tuple[str, int], ...]:
    if updates is None:
        return ()
    if not isinstance(updates, Mapping):
        raise ValueError('group_offsets must be a mapping')

    validated = []
    for group_id, value in updates.items():
        if not isinstance(group_id, str) or group_id not in visible_groups:
            raise ValueError(f'group is not visible on this day: {group_id!r}')
        validated.append((group_id, require_integer(value, 'group offset')))
    return tuple(sorted(validated))


def write_group_offsets(
    db: Connection, day: str, revision: int, updates: tuple[tuple[str, int], ...]
) -> None:
    db.executemany(
        '''
        INSERT INTO group_offset_events (revision, day, group_id, offset_hex)
        VALUES (?, ?, ?, ?)
        ''',
        ((revision, day, group_id, encode_integer(value)) for group_id, value in updates),
    )


def read_group_offsets(db: Connection, day: str, revision: int) -> dict[str, int]:
    events = db.execute(
        '''
        SELECT group_id, offset_hex FROM group_offset_events
        WHERE day = ? AND revision <= ? ORDER BY revision
        ''',
        (day, revision),
    )
    offsets = {}
    for group_id, offset_hex in events:
        offsets[group_id] = decode_integer(offset_hex)
    return offsets


def read_group_events(db: Connection, revision: int) -> tuple[tuple[str, int], ...]:
    events = db.execute(
        '''
        SELECT group_id, offset_hex FROM group_offset_events
        WHERE revision = ? ORDER BY group_id COLLATE BINARY
        ''',
        (revision,),
    )
    return tuple((group_id, decode_integer(offset)) for group_id, offset in events)
