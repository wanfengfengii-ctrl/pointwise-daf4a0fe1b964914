from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..quality.effective import EffectiveRow


@dataclass(frozen=True, slots=True)
class PresentedLine:
    label: str
    value: int


def resolve_selection(
    rows: Iterable[EffectiveRow], occurrence_ids: Sequence[str]
) -> tuple[PresentedLine, ...]:
    if not isinstance(occurrence_ids, Sequence) or isinstance(occurrence_ids, (str, bytes, bytearray)):
        raise ValueError('occurrence_ids must be an ordered sequence')
    by_id = {row.occurrence_id: row for row in rows}
    selected = []
    for position, occurrence_id in enumerate(occurrence_ids):
        if not isinstance(occurrence_id, str) or occurrence_id not in by_id:
            raise ValueError(f'occurrence at position {position} is not visible: {occurrence_id!r}')
        row = by_id[occurrence_id]
        selected.append(PresentedLine(row.label, row.value))
    return tuple(selected)
