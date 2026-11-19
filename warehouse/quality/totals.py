from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from .effective import EffectiveRow


@dataclass(frozen=True, slots=True)
class GroupTotal:
    group_id: str
    total: int
    exceedance_count: int


def summarize_groups(
    rows: Iterable[EffectiveRow], exceedances: Iterable[EffectiveRow]
) -> tuple[GroupTotal, ...]:
    totals = {}
    for row in rows:
        totals[row.group_id] = totals.get(row.group_id, 0) + row.value
    counts = Counter(row.group_id for row in exceedances)
    return tuple(GroupTotal(key, totals[key], counts[key]) for key in sorted(totals))
