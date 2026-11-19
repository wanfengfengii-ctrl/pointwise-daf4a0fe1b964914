import sqlite3
from os import PathLike

from ..calibration.groups import create_group_offset_schema
from ..calibration.overrides import create_override_schema
from ..ingest.batch_store import create_batch_schema
from ..ingest.observations import create_observation_schema
from ..reports.archive import create_report_schema
from .day_index import create_day_index_schema
from .revisions import create_revision_schema
from .transactions import atomic_write


def initialize_store(db: sqlite3.Connection) -> None:
    """Create missing schema objects while preserving committed user data."""
    with atomic_write(db):
        create_revision_schema(db)
        create_day_index_schema(db)
        create_batch_schema(db)
        create_observation_schema(db)
        create_group_offset_schema(db)
        create_override_schema(db)
        create_report_schema(db)


def open_store(path: str | PathLike[str]) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys = ON')
        initialize_store(db)
    except BaseException:
        db.close()
        raise
    return db
