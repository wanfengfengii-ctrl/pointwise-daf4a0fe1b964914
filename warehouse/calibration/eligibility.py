from collections.abc import Iterable, Mapping

from ..ingest.observations import Observation
from .overrides import OverrideChange


def can_override(observation: Observation) -> bool:
    return observation.can_override


def validate_override_targets(
    changes: Iterable[OverrideChange], visible_rows: Mapping[str, Observation]
) -> None:
    for change in changes:
        observation = visible_rows.get(change.occurrence_id)
        if observation is None:
            raise ValueError(f'occurrence is not visible on this day: {change.occurrence_id!r}')
        if not can_override(observation):
            raise ValueError(f'occurrence does not allow an override: {change.occurrence_id!r}')
