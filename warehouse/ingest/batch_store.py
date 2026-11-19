from dataclasses import dataclass
from sqlite3 import Connection

from .batches import SourceBatch
from .observations import load_batch_observations
from .source_keys import validate_source_key


@dataclass(frozen=True, slots=True)
class BatchHeader:
    batch_id: str
    day: str
    first_revision: int


def create_batch_schema(db: Connection) -> None:
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS source_batches (
            batch_id TEXT PRIMARY KEY NOT NULL,
            day TEXT NOT NULL,
            first_revision INTEGER NOT NULL UNIQUE REFERENCES revisions(revision)
        )
        '''
    )
    db.execute(
        'CREATE INDEX IF NOT EXISTS batches_by_day ON source_batches(day, first_revision)'
    )


def find_batch(db: Connection, batch_id: str) -> BatchHeader | None:
    batch_id = validate_source_key(batch_id, 'batch_id')
    row = db.execute(
        'SELECT batch_id, day, first_revision FROM source_batches WHERE batch_id = ?',
        (batch_id,),
    ).fetchone()
    return BatchHeader(*row) if row is not None else None


def save_batch(db: Connection, batch: SourceBatch, revision: int) -> None:
    db.execute(
        'INSERT INTO source_batches (batch_id, day, first_revision) VALUES (?, ?, ?)',
        (batch.batch_id, batch.day, revision),
    )


def load_batch_payload(db: Connection, header: BatchHeader) -> SourceBatch:
    observations = load_batch_observations(db, header.batch_id)
    return SourceBatch(header.batch_id, header.day, observations)
