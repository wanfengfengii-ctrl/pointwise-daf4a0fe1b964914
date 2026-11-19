from collections.abc import Sequence
from sqlite3 import Connection

from ..ledger.day_index import advance_day_head
from ..ledger.revisions import append_revision
from ..ledger.transactions import atomic_write
from .batch_store import find_batch, load_batch_payload, save_batch
from .batches import same_batch_payload, validate_batch
from .observations import Observation, find_occurrence_conflicts, insert_observations
from .source_keys import index_source_positions


def accept_batch(
    db: Connection, batch_id: str, day: str, observations: Sequence[Observation]
) -> int:
    batch = validate_batch(batch_id, day, observations)
    with atomic_write(db):
        stored = find_batch(db, batch.batch_id)
        if stored is not None:
            payload = load_batch_payload(db, stored)
            if not same_batch_payload(payload, batch):
                raise ValueError(f'batch payload differs for {batch.batch_id!r}')
            return stored.first_revision

        conflicts = find_occurrence_conflicts(db, batch.observations)
        if conflicts:
            raise ValueError(f'occurrence IDs already accepted: {conflicts!r}')

        revision = append_revision(db, batch.day, 'accept')
        save_batch(db, batch, revision)
        positions = index_source_positions(batch.batch_id, batch.observations)
        insert_observations(db, batch.observations, positions)
        advance_day_head(db, batch.day, revision)
        return revision
