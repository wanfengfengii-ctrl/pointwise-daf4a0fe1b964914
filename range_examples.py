"""Run the documented range calibration scenarios against the public APIs."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from warehouse import (
    Observation,
    accept_batch,
    find_batch,
    get_day_head,
    inspect_day,
    issue_report,
    load_batch_payload,
    open_store,
    read_report,
    set_offsets,
)


DAY = "2026-04-15"


def install_commit_failure(db):
    db.execute("CREATE TABLE range_fixture_parent (id INTEGER PRIMARY KEY)")
    db.execute("""
        CREATE TABLE range_fixture_child (
            parent_id INTEGER NOT NULL REFERENCES range_fixture_parent(id)
            DEFERRABLE INITIALLY DEFERRED
        )
    """)
    db.execute("""
        CREATE TEMP TRIGGER range_fixture_on_revision
        AFTER INSERT ON main.revisions
        BEGIN
            INSERT INTO range_fixture_child (parent_id) VALUES (1);
        END
    """)


def require_equal(actual, expected):
    if actual != expected:
        raise AssertionError(f"expected {expected!r}, got {actual!r}")


def require_error(expected, operation, *args):
    try:
        operation(*args)
    except expected:
        return
    raise AssertionError(f"{operation.__name__} should raise {expected.__name__}")


def reading(key, sequence, *, eligible=False):
    return Observation(key, "G", key, 100, eligible, source_sequence=sequence)


def day_values(db, revision):
    return {row.occurrence_id: row.value for row in inspect_day(db, DAY, revision, 105).rows}


def run_examples():
    from warehouse import set_range_offset

    with TemporaryDirectory(prefix="chengwan-ranges-") as directory:
        path = Path(directory) / "ranges.sqlite3"
        with closing(open_store(path)) as db:
            p12 = [reading("P12", 12)]
            first = accept_batch(db, "p12", DAY, p12)
            head = accept_batch(db, "p23", DAY, [reading("P23", 23)])
            head = set_range_offset(db, DAY, head, "G", "low-zero", (10, 20, 1, 0))
            head = set_range_offset(db, DAY, head, "G", "A", (15, 20, 2, 9))
            head = set_range_offset(db, DAY, head, "G", "low-five", (15, 25, 1, 5))
            require_equal(day_values(db, head), {"P12": 100, "P23": 105})
            require_error(ValueError, set_range_offset, db, DAY, head, "G", "A", None)
            require_equal(get_day_head(db, DAY), head)
            empty_span_head = head

            head = set_range_offset(db, DAY, head, "G", "B", (15, 20, 2, 9))
            head = set_range_offset(db, DAY, head, "G", "A", None)
            require_error(ValueError, set_range_offset, db, DAY, head, "G", "B", None)
            require_equal(get_day_head(db, DAY), head)
            require_equal(accept_batch(db, "p12", DAY, p12), first)
            require_equal(load_batch_payload(db, find_batch(db, "p12")).observations, tuple(p12))
            require_error(ValueError, accept_batch, db, "p12", DAY, [reading("P12", 13)])
            require_error(ValueError, accept_batch, db, "collision", DAY,
                          [reading("candidate", 14), reading("duplicate", 12)])
            require_equal(find_batch(db, "collision"), None)
            require_equal(get_day_head(db, DAY), head)

            issued_at = accept_batch(db, "late", DAY, [reading("P18", 18)])
            checked = inspect_day(db, DAY, issued_at, 105)
            require_equal([(row.occurrence_id, row.value) for row in checked.rows],
                          [("P12", 100), ("P18", 109), ("P23", 105)])
            require_equal([(g.group_id, g.total, g.exceedance_count) for g in checked.groups],
                          [("G", 314, 1)])
            require_equal([row.occurrence_id for row in checked.exceedances], ["P18"])
            issued = issue_report(db, DAY, issued_at, ["P18", "P12", "P18"])
            require_equal([line.value for line in issued.lines], [109, 100, 109])

            extra = [Observation("old", "G", "old", 100, False), reading("P17", 17, eligible=True)]
            head = accept_batch(db, "extra", DAY, extra)
            head = set_offsets(db, DAY, head, {"G": 4}, {"P17": 0})
            before_failure = set_range_offset(db, DAY, head, "G", "low-five", None)
            require_equal(day_values(db, before_failure),
                          {"P12": 100, "P17": 100, "P18": 109, "P23": 104, "old": 104})
            install_commit_failure(db)
            require_error(sqlite3.IntegrityError, set_range_offset,
                          db, DAY, before_failure, "G", "B", None)
            require_equal(db.in_transaction, False)

        with closing(open_store(path)) as db:
            require_equal(get_day_head(db, DAY), before_failure)
            require_equal(db.execute("SELECT parent_id FROM range_fixture_child").fetchall(), [])
            restored = day_values(db, before_failure)
            require_equal(restored, {"P12": 100, "P17": 100, "P18": 109, "P23": 104, "old": 104})
            current = set_range_offset(db, DAY, before_failure, "G", "B", None)
            after = day_values(db, current)
            require_equal(after, {"P12": 100, "P17": 100, "P18": 100, "P23": 104, "old": 104})
            historical = day_values(db, issued_at)
            require_equal(historical, {"P12": 100, "P18": 109, "P23": 105})
            reprinted = read_report(db, issued.report_id)
            require_equal(reprinted.revision, issued_at)
            require_equal(reprinted.lines, issued.lines)
            return {
                "revocation_rejected_at": empty_span_head,
                "late_value": historical["P18"],
                "reopened_after_failed_commit": restored["P18"],
                "current_after_retry": after["P18"],
                "reprinted_values": [line.value for line in reprinted.lines],
            }


if __name__ == "__main__":
    print(json.dumps(run_examples(), ensure_ascii=False))
