from dataclasses import dataclass
from sqlite3 import Connection

from ..calibration.groups import read_group_offsets
from ..calibration.overrides import read_overrides
from ..ingest.observations import Observation, read_day_observations
from .day_index import validate_day_key
from .revisions import require_revision


@dataclass(frozen=True, slots=True)
class DayFacts:
    day: str
    revision: int
    observations: tuple[Observation, ...]
    group_offsets: dict[str, int]
    overrides: dict[str, int]


def load_day_facts(db: Connection, day: str, revision: int) -> DayFacts:
    """Read facts at a published upper bound inside the caller's transaction."""
    day = validate_day_key(day)
    require_revision(db, revision)
    return DayFacts(
        day=day,
        revision=revision,
        observations=read_day_observations(db, day, revision),
        group_offsets=read_group_offsets(db, day, revision),
        overrides=read_overrides(db, day, revision),
    )
