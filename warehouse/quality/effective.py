from collections.abc import Mapping
from dataclasses import dataclass

from ..calibration.eligibility import can_override
from ..ingest.observations import Observation
from ..ledger.history import DayFacts


@dataclass(frozen=True, slots=True)
class EffectiveRow:
    occurrence_id: str
    group_id: str
    label: str
    raw_value: int
    offset: int
    value: int


def resolve_effective_offset(
    observation: Observation,
    group_offsets: Mapping[str, int],
    overrides: Mapping[str, int],
) -> int:
    group_offset = group_offsets.get(observation.group_id, 0)
    if can_override(observation):
        return overrides.get(observation.occurrence_id, group_offset)
    return group_offset


def compute_effective_rows(facts: DayFacts) -> tuple[EffectiveRow, ...]:
    rows = []
    # The fixed-day source query supplies observations in occurrence ID order.
    for observation in facts.observations:
        offset = resolve_effective_offset(observation, facts.group_offsets, facts.overrides)
        rows.append(
            EffectiveRow(
                occurrence_id=observation.occurrence_id,
                group_id=observation.group_id,
                label=observation.label,
                raw_value=observation.raw_value,
                offset=offset,
                value=observation.raw_value + offset,
            )
        )
    return tuple(rows)
