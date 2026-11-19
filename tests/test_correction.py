import sqlite3
from contextlib import closing

from tests import DAY, NEXT_DAY, StoreTestCase, measurement
from warehouse import (
    accept_batch,
    get_day_head,
    inspect_day,
    open_store,
    read_correction_audit,
    set_offsets,
)
from warehouse.calibration.overrides import OverrideChange
from warehouse.quality.totals import GroupTotal


def install_commit_failure(db):
    # The trigger allows each write to finish. SQLite rejects the unresolved
    # foreign key at COMMIT. The trigger disappears when the connection closes.
    db.execute('CREATE TABLE commit_fixture_parent (id INTEGER PRIMARY KEY)')
    db.execute(
        '''
        CREATE TABLE commit_fixture_child (
            parent_id INTEGER NOT NULL REFERENCES commit_fixture_parent(id)
            DEFERRABLE INITIALLY DEFERRED
        )
        '''
    )
    db.execute(
        '''
        CREATE TEMP TRIGGER commit_fixture_on_group_offset
        AFTER INSERT ON main.group_offset_events
        BEGIN
            INSERT INTO commit_fixture_child (parent_id) VALUES (1);
        END
        '''
    )


class CorrectionTests(StoreTestCase):
    def accept_pair(self):
        return accept_batch(
            self.db, 'pair', DAY, [measurement('B'), measurement('A', eligible=False)]
        )

    def test_historical_totals(self):
        first = self.accept_pair()
        second = set_offsets(self.db, DAY, first, {'G': 10}, {'B': 2})
        before = inspect_day(self.db, DAY, first, 102)
        after = inspect_day(self.db, DAY, second, 102)
        self.assertEqual([row.value for row in before.rows], [100, 100])
        self.assertEqual([(row.occurrence_id, row.raw_value, row.value) for row in after.rows],
                         [('A', 100, 110), ('B', 100, 102)])
        self.assertEqual(before.groups, (GroupTotal('G', 200, 0),))
        self.assertEqual(after.groups, (GroupTotal('G', 212, 1),))
        self.assertEqual([row.occurrence_id for row in after.exceedances], ['A'])

    def test_explicit_zero(self):
        first = self.accept_pair()
        second = set_offsets(self.db, DAY, first, {'G': 10}, {'B': 0})
        inspection = inspect_day(self.db, DAY, second, 100)
        self.assertEqual([(row.occurrence_id, row.offset, row.value) for row in inspection.rows],
                         [('A', 10, 110), ('B', 0, 100)])
        self.assertEqual(inspection.groups, (GroupTotal('G', 210, 1),))

    def test_exact_integer_groups(self):
        limit = 9223372036854775808
        rows = [measurement('C', 0, group='H'), measurement('B', -9223372036854775809),
                measurement('A', limit)]
        first = accept_batch(self.db, 'wide', DAY, rows)
        second = set_offsets(self.db, DAY, first, {'G': 1})
        inspection = inspect_day(self.db, DAY, second, limit)
        self.assertEqual([row.raw_value for row in inspection.rows],
                         [9223372036854775808, -9223372036854775809, 0])
        self.assertEqual([row.value for row in inspection.rows],
                         [9223372036854775809, -9223372036854775808, 0])
        self.assertEqual(inspection.groups, (GroupTotal('G', 1, 1), GroupTotal('H', 0, 0)))
        self.assertEqual([row.occurrence_id for row in inspection.exceedances], ['A'])

    def test_empty_day(self):
        first = self.accept_pair()
        inspection = inspect_day(self.db, NEXT_DAY, first, 0)
        self.assertEqual((inspection.rows, inspection.exceedances, inspection.groups), ((), (), ()))
        for threshold in (1.25, None, False):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                inspect_day(self.db, NEXT_DAY, first, threshold)
        with self.assertRaises(ValueError):
            inspect_day(self.db, DAY, first + 1, 0)

    def test_day_scoped_head(self):
        first = self.accept_pair()
        other = accept_batch(self.db, 'other', NEXT_DAY, [measurement('C', 50)])
        self.assertEqual(get_day_head(self.db, DAY), first)
        self.assertEqual(inspect_day(self.db, DAY, other, 100).groups, (GroupTotal('G', 200, 0),))
        corrected = set_offsets(self.db, DAY, first, {'G': 10})
        self.assertGreater(corrected, other)
        self.assertEqual(get_day_head(self.db, NEXT_DAY), other)
        self.assertEqual(inspect_day(self.db, NEXT_DAY, corrected, 100).groups,
                         (GroupTotal('G', 50, 0),))
        self.assertEqual(inspect_day(self.db, DAY, corrected, 100).groups,
                         (GroupTotal('G', 220, 2),))

    def test_explicit_audit(self):
        first = self.accept_pair()
        second = set_offsets(self.db, DAY, first, {'G': 10}, {'B': 2})
        audit = read_correction_audit(self.db, second)
        self.assertEqual((audit.revision, audit.day), (second, DAY))
        self.assertEqual(audit.group_offsets, (('G', 10),))
        self.assertEqual(audit.overrides, (OverrideChange('B', 2),))
        with self.assertRaises(ValueError):
            read_correction_audit(self.db, first)

    def test_locked_row_rolls_back(self):
        first = self.accept_pair()
        with self.assertRaises(ValueError):
            set_offsets(self.db, DAY, first, {'G': 10}, {'A': 2})
        self.reopen()
        self.assertEqual(get_day_head(self.db, DAY), first)
        self.assertEqual([row.value for row in inspect_day(self.db, DAY, first, 0).rows], [100, 100])
        with self.assertRaises(ValueError):
            read_correction_audit(self.db, first + 1)

    def test_unknown_target(self):
        first = self.accept_pair()
        other = accept_batch(self.db, 'other', NEXT_DAY, [measurement('C')])
        rejected = (
            ({'G': 10, 'unknown': 1}, {'B': 2}),
            ({'G': 10}, {'C': 2}),
            ({'G': 10}, {'missing': None}),
            ({'G': 10}, {'B': 1.5}),
            ({'G': False}, {'B': 2}),
        )
        for groups, overrides in rejected:
            with self.subTest(groups=groups, overrides=overrides), self.assertRaises(ValueError):
                set_offsets(self.db, DAY, first, groups, overrides)
        self.assertEqual(get_day_head(self.db, DAY), first)
        self.assertEqual(get_day_head(self.db, NEXT_DAY), other)
        self.assertEqual(inspect_day(self.db, DAY, other, 100).groups, (GroupTotal('G', 200, 0),))
        with self.assertRaises(ValueError):
            read_correction_audit(self.db, other + 1)

    def test_clear_override(self):
        first = self.accept_pair()
        second = set_offsets(self.db, DAY, first, {'G': 10}, {'B': 2})
        third = set_offsets(self.db, DAY, second, overrides={'B': None})
        self.assertEqual([row.value for row in inspect_day(self.db, DAY, second, 0).rows], [110, 102])
        self.assertEqual([row.value for row in inspect_day(self.db, DAY, third, 0).rows], [110, 110])
        audit = read_correction_audit(self.db, third)
        self.assertEqual(audit.group_offsets, ())
        self.assertEqual(audit.overrides, (OverrideChange('B', None),))

    def test_failed_commit_and_retry(self):
        first = self.accept_pair()
        install_commit_failure(self.db)
        with self.assertRaises(sqlite3.IntegrityError):
            set_offsets(self.db, DAY, first, {'G': 10}, {'B': 2})
        self.assertFalse(self.db.in_transaction)
        self.reopen()
        self.assertEqual(get_day_head(self.db, DAY), first)
        self.assertEqual(inspect_day(self.db, DAY, first, 102).groups, (GroupTotal('G', 200, 0),))
        self.assertEqual(self.db.execute('SELECT parent_id FROM commit_fixture_child').fetchall(), [])
        with self.assertRaises(ValueError):
            inspect_day(self.db, DAY, first + 1, 102)
        with self.assertRaises(ValueError):
            read_correction_audit(self.db, first + 1)
        second = set_offsets(self.db, DAY, first, {'G': 10}, {'B': 2})
        self.assertEqual(second, first + 1)
        self.assertEqual(inspect_day(self.db, DAY, second, 102).groups, (GroupTotal('G', 212, 1),))
        self.assertEqual(read_correction_audit(self.db, second).overrides, (OverrideChange('B', 2),))

    def test_stale_retry_after_other_commit(self):
        first = self.accept_pair()
        install_commit_failure(self.db)
        with self.assertRaises(sqlite3.IntegrityError):
            set_offsets(self.db, DAY, first, {'G': 10})
        self.reopen()
        with closing(open_store(self.path)) as other_connection:
            second = set_offsets(other_connection, DAY, first, {'G': 20})
        with self.assertRaises(ValueError):
            set_offsets(self.db, DAY, first, {'G': 10})
        self.assertEqual(get_day_head(self.db, DAY), second)
        self.assertEqual([row.value for row in inspect_day(self.db, DAY, second, 0).rows], [120, 120])
        self.assertEqual(read_correction_audit(self.db, second).group_offsets, (('G', 20),))
        with self.assertRaises(ValueError):
            inspect_day(self.db, DAY, second + 1, 0)
