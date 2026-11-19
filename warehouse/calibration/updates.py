from collections.abc import Mapping
from sqlite3 import Connection

from ..ledger.day_index import advance_day_head, get_day_head, validate_day_key
from ..ledger.history import load_day_facts
from ..ledger.integer_storage import require_integer
from ..ledger.revisions import append_revision
from ..ledger.transactions import atomic_write
from .audit import record_explicit_correction
from .eligibility import validate_override_targets
from .groups import validate_group_updates
from .overrides import parse_override_updates


def set_offsets(
    db: Connection,
    day: str,
    expected_revision: int,
    group_offsets: Mapping[str, int] | None = None,
    overrides: Mapping[str, int | None] | None = None,
) -> int:
    day = validate_day_key(day)
    expected_revision = require_integer(expected_revision, 'expected_revision')
    with atomic_write(db):
        head = get_day_head(db, day)
        if head != expected_revision:
            raise ValueError(f'expected revision {expected_revision} is not the current head for {day}')

        facts = load_day_facts(db, day, expected_revision)
        visible_rows = {row.occurrence_id: row for row in facts.observations}
        visible_groups = {row.group_id for row in facts.observations}
        validated_groups = validate_group_updates(group_offsets, visible_groups)
        changes = parse_override_updates(overrides)
        validate_override_targets(changes, visible_rows)

        revision = append_revision(db, day, 'correction')
        record_explicit_correction(db, day, revision, validated_groups, changes)
        advance_day_head(db, day, revision)
        return revision
