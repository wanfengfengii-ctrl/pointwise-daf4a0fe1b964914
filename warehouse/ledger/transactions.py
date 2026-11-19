from collections.abc import Iterator
from contextlib import contextmanager
from sqlite3 import Connection


@contextmanager
def _transaction(db: Connection, begin: str) -> Iterator[None]:
    # Leave an existing caller transaction alone if BEGIN fails.
    db.execute(begin)
    try:
        yield
        db.commit()
    except BaseException:
        if db.in_transaction:
            db.rollback()
        raise


@contextmanager
def atomic_write(db: Connection) -> Iterator[None]:
    """Serialize business preconditions with their corresponding writes."""
    with _transaction(db, 'BEGIN IMMEDIATE'):
        yield


@contextmanager
def read_snapshot(db: Connection) -> Iterator[None]:
    """Keep all reads for one result in a consistent SQLite snapshot."""
    with _transaction(db, 'BEGIN'):
        yield
