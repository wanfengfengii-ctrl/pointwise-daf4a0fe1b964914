from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from sqlite3 import Connection

from ..ledger.integer_storage import decode_integer, encode_integer, require_integer
from .source_keys import SourcePosition, validate_source_key


@dataclass(frozen=True, slots=True)
class Observation:
    occurrence_id: str
    group_id: str
    label: str
    raw_value: int
    can_override: bool
    source_sequence: int | None = None


def validate_observation(value: object) -> Observation:
    if not isinstance(value, Observation):
        raise ValueError('each source row must be an Observation')
    validate_source_key(value.occurrence_id, 'occurrence_id')
    validate_source_key(value.group_id, 'group_id')
    validate_source_key(value.label, 'label')
    require_integer(value.raw_value, 'raw_value')
    if type(value.can_override) is not bool:
        raise ValueError('can_override must be a boolean')
    if value.source_sequence is not None:
        sequence = require_integer(value.source_sequence, 'source_sequence')
        if sequence < 0:
            raise ValueError('source_sequence must be a non-negative integer')
    return value


def create_observation_schema(db: Connection) -> None:
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS observations (
            occurrence_id TEXT PRIMARY KEY NOT NULL,
            batch_id TEXT NOT NULL REFERENCES source_batches(batch_id),
            source_index INTEGER NOT NULL CHECK (source_index >= 0),
            group_id TEXT NOT NULL,
            label TEXT NOT NULL,
            raw_hex TEXT NOT NULL,
            can_override INTEGER NOT NULL CHECK (can_override IN (0, 1)),
            source_sequence INTEGER,
            UNIQUE (batch_id, source_index)
        )
        '''
    )
    columns = {row[1] for row in db.execute('PRAGMA table_info(observations)')}
    if 'source_sequence' not in columns:
        db.execute('ALTER TABLE observations ADD COLUMN source_sequence INTEGER')
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS observation_sequences (
            day TEXT NOT NULL,
            group_id TEXT NOT NULL,
            source_sequence INTEGER NOT NULL,
            occurrence_id TEXT NOT NULL REFERENCES observations(occurrence_id),
            PRIMARY KEY (day, group_id, source_sequence)
        )
        '''
    )


def find_occurrence_conflicts(
    db: Connection, observations: Sequence[Observation]
) -> tuple[str, ...]:
    conflicts = []
    for observation in observations:
        key = observation.occurrence_id
        existing = db.execute(
            'SELECT 1 FROM observations WHERE occurrence_id = ?', (key,)
        ).fetchone()
        if existing is not None:
            conflicts.append(key)
    return tuple(conflicts)


def find_sequence_conflicts(
    db: Connection, day: str, observations: Sequence[Observation]
) -> tuple[int, ...]:
    conflicts = []
    for observation in observations:
        sequence = observation.source_sequence
        if sequence is None:
            continue
        existing = db.execute(
            '''
            SELECT 1 FROM observation_sequences
            WHERE day = ? AND group_id = ? AND source_sequence = ?
            ''',
            (day, observation.group_id, sequence),
        ).fetchone()
        if existing is not None:
            conflicts.append(sequence)
    return tuple(conflicts)


def insert_observations(
    db: Connection,
    day: str,
    observations: Sequence[Observation],
    positions: Sequence[SourcePosition],
) -> None:
    rows = (
        (
            observation.occurrence_id,
            position.batch_id,
            position.index,
            observation.group_id,
            observation.label,
            encode_integer(observation.raw_value),
            int(observation.can_override),
            observation.source_sequence,
        )
        for observation, position in zip(observations, positions, strict=True)
    )
    db.executemany(
        '''
        INSERT INTO observations (
            occurrence_id, batch_id, source_index, group_id, label, raw_hex,
            can_override, source_sequence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        rows,
    )
    db.executemany(
        '''
        INSERT INTO observation_sequences (day, group_id, source_sequence, occurrence_id)
        VALUES (?, ?, ?, ?)
        ''',
        (
            (day, observation.group_id, observation.source_sequence, observation.occurrence_id)
            for observation in observations
            if observation.source_sequence is not None
        ),
    )


def _decode_rows(rows: Iterable[tuple]) -> tuple[Observation, ...]:
    return tuple(
        Observation(key, group_id, label, decode_integer(raw_hex), bool(eligible), sequence)
        for key, group_id, label, raw_hex, eligible, sequence in rows
    )


def load_batch_observations(db: Connection, batch_id: str) -> tuple[Observation, ...]:
    rows = db.execute(
        '''
        SELECT occurrence_id, group_id, label, raw_hex, can_override, source_sequence
        FROM observations WHERE batch_id = ? ORDER BY source_index
        ''',
        (batch_id,),
    )
    return _decode_rows(rows)


def read_day_observations(db: Connection, day: str, revision: int) -> tuple[Observation, ...]:
    rows = db.execute(
        '''
        SELECT o.occurrence_id, o.group_id, o.label, o.raw_hex, o.can_override,
               o.source_sequence
        FROM source_batches AS b
        JOIN observations AS o ON o.batch_id = b.batch_id
        WHERE b.day = ? AND b.first_revision <= ?
        ORDER BY o.occurrence_id COLLATE BINARY
        ''',
        (day, revision),
    )
    return _decode_rows(rows)
