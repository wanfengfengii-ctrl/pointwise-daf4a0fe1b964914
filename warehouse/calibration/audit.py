from dataclasses import dataclass
from sqlite3 import Connection

from ..ledger.revisions import require_revision
from ..ledger.transactions import read_snapshot
from .groups import read_group_events, write_group_offsets
from .overrides import OverrideChange, read_override_events, write_override_changes


@dataclass(frozen=True, slots=True)
class CorrectionAudit:
    revision: int
    day: str
    group_offsets: tuple[tuple[str, int], ...]
    overrides: tuple[OverrideChange, ...]


def record_explicit_correction(
    db: Connection,
    day: str,
    revision: int,
    group_updates: tuple[tuple[str, int], ...],
    override_changes: tuple[OverrideChange, ...],
) -> None:
    write_group_offsets(db, day, revision, group_updates)
    write_override_changes(db, day, revision, override_changes)


def read_correction_audit(db: Connection, revision: int) -> CorrectionAudit:
    with read_snapshot(db):
        published = require_revision(db, revision)
        if published.kind != 'correction':
            raise ValueError(f'revision {revision} is not a correction')
        return CorrectionAudit(
            revision,
            published.day,
            read_group_events(db, revision),
            read_override_events(db, revision),
        )
