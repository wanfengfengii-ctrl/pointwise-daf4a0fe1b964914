from collections.abc import Sequence
from dataclasses import dataclass

from ..ledger.day_index import validate_day_key
from .observations import Observation, validate_observation
from .source_keys import validate_source_key


@dataclass(frozen=True, slots=True)
class SourceBatch:
    batch_id: str
    day: str
    observations: tuple[Observation, ...]


def validate_batch(batch_id: object, day: object, observations: object) -> SourceBatch:
    batch_id = validate_source_key(batch_id, 'batch_id')
    day = validate_day_key(day)
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes, bytearray)):
        raise ValueError('observations must be an ordered sequence')

    source_rows = []
    seen = set()
    for row in observations:
        observation = validate_observation(row)
        if observation.occurrence_id in seen:
            raise ValueError(f'duplicate occurrence in batch: {observation.occurrence_id!r}')
        seen.add(observation.occurrence_id)
        source_rows.append(observation)
    return SourceBatch(batch_id, day, tuple(source_rows))


def same_batch_payload(stored: SourceBatch, submitted: SourceBatch) -> bool:
    return stored.day == submitted.day and stored.observations == submitted.observations
