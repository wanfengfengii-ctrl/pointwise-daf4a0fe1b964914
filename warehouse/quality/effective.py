from collections.abc import Mapping
from dataclasses import dataclass

from ..calibration.eligibility import can_override
from ..calibration.ranges import RangeTicket, range_offset_for
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
    range_tickets: Mapping[str, tuple[RangeTicket, ...]] = {},
) -> int:
    group_offset = group_offsets.get(observation.group_id, 0)
    if can_override(observation) and observation.occurrence_id in overrides:
        # A row-level absolute override wins even when it is explicitly zero.
        return overrides[observation.occurrence_id]
    ranged = range_offset_for(
        range_tickets.get(observation.group_id, ()), observation.source_sequence
    )
    if ranged is not None:
        # A segment offset is a complete offset from the raw value; it is not
        # added on top of the group offset.
        return ranged
    return group_offset


def compute_effective_rows(facts: DayFacts) -> tuple[EffectiveRow, ...]:
    rows = []
    # The fixed-day source query supplies observations in occurrence ID order.
    for observation in facts.observations:
        offset = resolve_effective_offset(
            observation, facts.group_offsets, facts.overrides, facts.range_tickets
        )
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
