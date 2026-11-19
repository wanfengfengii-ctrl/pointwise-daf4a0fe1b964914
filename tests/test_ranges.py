import sqlite3
from contextlib import closing

from tests import DAY, NEXT_DAY, StoreTestCase, measurement
from warehouse import (
    Observation,
    accept_batch,
    find_batch,
    get_day_head,
    initialize_store,
    inspect_day,
    issue_report,
    load_batch_payload,
    open_store,
    read_report,
    set_offsets,
    set_range_offset,
)


def reading(key, sequence, *, eligible=False, raw=100, group='G'):
    return Observation(key, group, key, raw, eligible, source_sequence=sequence)


def install_commit_failure(db):
    db.execute('CREATE TABLE range_fixture_parent (id INTEGER PRIMARY KEY)')
    db.execute(
        '''
        CREATE TABLE range_fixture_child (
            parent_id INTEGER NOT NULL REFERENCES range_fixture_parent(id)
            DEFERRABLE INITIALLY DEFERRED
        )
        '''
    )
    db.execute(
        '''
        CREATE TEMP TRIGGER range_fixture_on_revision
        AFTER INSERT ON main.revisions
        BEGIN
            INSERT INTO range_fixture_child (parent_id) VALUES (1);
        END
        '''
    )


class SequenceAcceptTests(StoreTestCase):
    def test_optional_sequence_and_payload(self):
        ordered = [reading('B', 12), reading('A', 9, group='H')]
        first = accept_batch(self.db, 'source', DAY, ordered)
        header = find_batch(self.db, 'source')
        self.assertEqual(load_batch_payload(self.db, header).observations, tuple(ordered))
        self.assertEqual(accept_batch(self.db, 'source', DAY, ordered), first)
        legacy = Observation('C', 'G', 'C', 100, False)
        self.assertIsNone(legacy.source_sequence)
        self.assertEqual(accept_batch(self.db, 'legacy', DAY, [legacy]), first + 1)

    def test_sequence_must_be_non_negative_integer(self):
        for value in (-1, 1.5, True, '12', object()):
            with self.subTest(value=value), self.assertRaises(ValueError):
                accept_batch(self.db, 'bad', DAY, [reading('A', value)])
            self.assertIsNone(find_batch(self.db, 'bad'))
            self.assertIsNone(get_day_head(self.db, DAY))

    def test_sequence_uniqueness_across_batches(self):
        first = accept_batch(self.db, 'first', DAY, [reading('A', 12)])
        with self.assertRaises(ValueError):
            accept_batch(self.db, 'second', DAY, [reading('B', 12)])
        self.assertIsNone(find_batch(self.db, 'second'))
        self.assertEqual(get_day_head(self.db, DAY), first)
        # Different group or different day may reuse a sequence.
        other = accept_batch(self.db, 'other', DAY, [reading('B', 12, group='H')])
        next_day = accept_batch(self.db, 'next', NEXT_DAY, [reading('C', 12)])
        self.assertEqual((other, next_day), (first + 1, first + 2))
        # Unsequenced rows may coexist with sequenced ones.
        third = accept_batch(self.db, 'plain', DAY, [measurement('D')])
        self.assertEqual(third, next_day + 1)

    def test_duplicate_sequence_in_batch(self):
        with self.assertRaises(ValueError):
            accept_batch(self.db, 'collision', DAY, [reading('A', 12), reading('B', 12)])
        self.assertIsNone(find_batch(self.db, 'collision'))
        self.assertIsNone(get_day_head(self.db, DAY))
        # The same number in different groups is not a batch collision.
        first = accept_batch(
            self.db, 'mixed', DAY, [reading('A', 12), reading('B', 12, group='H')]
        )
        self.assertEqual([row.occurrence_id for row in inspect_day(self.db, DAY, first, 0).rows],
                         ['A', 'B'])

    def test_changed_sequence_rejects_retry(self):
        original = [reading('A', 12)]
        first = accept_batch(self.db, 'source', DAY, original)
        with self.assertRaises(ValueError):
            accept_batch(self.db, 'source', DAY, [reading('A', 13)])
        with self.assertRaises(ValueError):
            accept_batch(self.db, 'source', DAY, [Observation('A', 'G', 'A', 100, False)])
        self.assertEqual(get_day_head(self.db, DAY), first)
        self.assertEqual(load_batch_payload(self.db, find_batch(self.db, 'source')).observations,
                         tuple(original))


class RangePublishTests(StoreTestCase):
    def values(self, revision, threshold=105):
        return {row.occurrence_id: row.value
                for row in inspect_day(self.db, DAY, revision, threshold).rows}

    def setup_scenario(self):
        accept_batch(self.db, 'p12', DAY, [reading('P12', 12)])
        head = accept_batch(self.db, 'p23', DAY, [reading('P23', 23)])
        head = set_range_offset(self.db, DAY, head, 'G', 'low-zero', (10, 20, 1, 0))
        head = set_range_offset(self.db, DAY, head, 'G', 'A', (15, 20, 2, 9))
        head = set_range_offset(self.db, DAY, head, 'G', 'low-five', (15, 25, 1, 5))
        return head

    def test_hand_scenario(self):
        head = self.setup_scenario()
        self.assertEqual(self.values(head), {'P12': 100, 'P23': 105})
        with self.assertRaises(ValueError):
            set_range_offset(self.db, DAY, head, 'G', 'A', None)
        self.assertEqual(get_day_head(self.db, DAY), head)

        head = set_range_offset(self.db, DAY, head, 'G', 'B', (15, 20, 2, 9))
        head = set_range_offset(self.db, DAY, head, 'G', 'A', None)
        with self.assertRaises(ValueError):
            set_range_offset(self.db, DAY, head, 'G', 'B', None)
        self.assertEqual(get_day_head(self.db, DAY), head)

        late = accept_batch(self.db, 'late', DAY, [reading('P18', 18)])
        inspection = inspect_day(self.db, DAY, late, 105)
        self.assertEqual([(row.occurrence_id, row.value) for row in inspection.rows],
                         [('P12', 100), ('P18', 109), ('P23', 105)])
        self.assertEqual([(group.group_id, group.total, group.exceedance_count)
                          for group in inspection.groups], [('G', 314, 1)])
        self.assertEqual([row.occurrence_id for row in inspection.exceedances], ['P18'])
        issued = issue_report(self.db, DAY, late, ['P18', 'P12', 'P18'])
        self.assertEqual([line.value for line in issued.lines], [109, 100, 109])

        head = set_range_offset(self.db, DAY, late, 'G', 'low-five', None)
        head = set_range_offset(self.db, DAY, head, 'G', 'B', None)
        self.assertEqual(self.values(head)['P18'], 100)
        self.assertEqual(self.values(late)['P18'], 109)
        self.reopen()
        report = read_report(self.db, issued.report_id)
        self.assertEqual((report.revision, [line.value for line in report.lines]),
                         (late, [109, 100, 109]))

    def test_group_offset_fallback_and_precedence(self):
        first = accept_batch(self.db, 'source', DAY, [
            reading('S18', 18, eligible=False),
            reading('S30', 30, eligible=True),
            Observation('NONE', 'G', 'NONE', 100, False),
        ])
        second = set_offsets(self.db, DAY, first, {'G': 4}, {'S30': 0})
        third = set_range_offset(self.db, DAY, second, 'G', 'seg', (15, 20, 5, 9))
        rows = {row.occurrence_id: (row.offset, row.value)
                for row in inspect_day(self.db, DAY, third, 0).rows}
        # Locked rows still take the segment; an explicit zero beats everything.
        self.assertEqual(rows['S18'], (9, 109))
        self.assertEqual(rows['S30'], (0, 100))
        self.assertEqual(rows['NONE'], (4, 104))

    def test_revoke_then_reregister(self):
        first = accept_batch(self.db, 'source', DAY, [reading('P12', 12)])
        second = set_range_offset(self.db, DAY, first, 'G', 'T', (10, 20, 1, 7))
        third = set_range_offset(self.db, DAY, second, 'G', 'T', None)
        fourth = set_range_offset(self.db, DAY, third, 'G', 'T', (10, 20, 1, 3))
        self.assertEqual(self.values(second), {'P12': 107})
        self.assertEqual(self.values(third), {'P12': 100})
        self.assertEqual(self.values(fourth), {'P12': 103})
        self.assertEqual(self.values(second), {'P12': 107})

    def test_ambiguity_validation(self):
        first = accept_batch(self.db, 'source', DAY, [reading('P12', 12)])
        second = set_range_offset(self.db, DAY, first, 'G', 'a', (10, 20, 1, 0))
        with self.assertRaises(ValueError):
            set_range_offset(self.db, DAY, second, 'G', 'b', (15, 25, 1, 5))
        self.assertEqual(get_day_head(self.db, DAY), second)
        # A higher layer may hide the lower-layer conflict.
        third = set_range_offset(self.db, DAY, second, 'G', 'top', (15, 20, 2, 9))
        fourth = set_range_offset(self.db, DAY, third, 'G', 'b', (15, 25, 1, 5))
        self.assertEqual(self.values(fourth), {'P12': 100})
        # Same value at the same layer may overlap; either ticket revokes alone.
        fifth = set_range_offset(self.db, DAY, fourth, 'G', 'same', (10, 20, 1, 0))
        sixth = set_range_offset(self.db, DAY, fifth, 'G', 'same', None)
        self.assertEqual(get_day_head(self.db, DAY), sixth)

    def test_unknown_group_and_invalid_interval(self):
        first = accept_batch(self.db, 'source', DAY, [reading('P12', 12)])
        invalid = (
            ('unknown group', 'H', 'T', (10, 20, 1, 0)),
            ('short interval', 'G', 'T', (10, 20, 1)),
            ('list interval', 'G', 'T', [10, 20, 1, 0]),
            ('bool bound', 'G', 'T', (10, True, 1, 0)),
            ('reversed', 'G', 'T', (20, 10, 1, 0)),
            ('empty', 'G', 'T', (10, 10, 1, 0)),
            ('negative', 'G', 'T', (-1, 10, 1, 0)),
            ('float priority', 'G', 'T', (10, 20, 1.5, 0)),
            ('empty ticket', 'G', '', (10, 20, 1, 0)),
            ('missing group', '', 'T', (10, 20, 1, 0)),
        )
        for case, group, ticket, interval in invalid:
            with self.subTest(case=case), self.assertRaises(ValueError):
                set_range_offset(self.db, DAY, first, group, ticket, interval)
        self.assertEqual(get_day_head(self.db, DAY), first)
        second = set_range_offset(self.db, DAY, first, 'G', 'T', (10, 20, -3, -5))
        self.assertEqual(inspect_day(self.db, DAY, second, 0).rows[0].value, 95)

    def test_duplicate_and_missing_ticket(self):
        first = accept_batch(self.db, 'source', DAY, [reading('P12', 12)])
        second = set_range_offset(self.db, DAY, first, 'G', 'T', (10, 20, 1, 0))
        with self.assertRaises(ValueError):
            set_range_offset(self.db, DAY, second, 'G', 'T', (30, 40, 1, 1))
        with self.assertRaises(ValueError):
            set_range_offset(self.db, DAY, second, 'G', 'other', None)
        with self.assertRaises(ValueError):
            set_range_offset(self.db, DAY, first, 'G', 'new', (30, 40, 1, 1))
        self.assertEqual(get_day_head(self.db, DAY), second)
        third = set_range_offset(self.db, DAY, second, 'G', 'T', None)
        self.assertEqual(inspect_day(self.db, DAY, third, 0).rows[0].value, 100)
        # A second group on another day reuses the ticket id independently.
        other_day = accept_batch(self.db, 'other', NEXT_DAY, [reading('Q', 5, group='H')])
        reused = set_range_offset(self.db, NEXT_DAY, other_day, 'H', 'T', (0, 10, 1, 2))
        self.assertEqual([row.value for row in inspect_day(self.db, NEXT_DAY, reused, 0).rows],
                         [102])

    def test_failed_commit_and_retry(self):
        first = accept_batch(self.db, 'source', DAY, [reading('P12', 12)])
        second = set_range_offset(self.db, DAY, first, 'G', 'T', (10, 20, 1, 6))
        install_commit_failure(self.db)
        with self.assertRaises(sqlite3.IntegrityError):
            set_range_offset(self.db, DAY, second, 'G', 'T', None)
        self.assertFalse(self.db.in_transaction)
        with self.assertRaises(sqlite3.IntegrityError):
            accept_batch(self.db, 'late', DAY, [reading('P13', 13)])
        self.reopen()
        self.assertEqual(get_day_head(self.db, DAY), second)
        self.assertEqual(self.values(second), {'P12': 106})
        third = set_range_offset(self.db, DAY, second, 'G', 'T', None)
        self.assertEqual(self.values(third), {'P12': 100})


class LegacyStoreTests(StoreTestCase):
    def test_legacy_schema_reopens(self):
        first = accept_batch(self.db, 'source', DAY, [measurement('A')])
        with closing(open_store(self.path)) as other:
            self.assertEqual(get_day_head(other, DAY), first)
        # Simulate a store written before source sequences existed.
        self.db.execute('DROP TABLE observation_sequences')
        self.db.execute('ALTER TABLE observations DROP COLUMN source_sequence')
        self.db.execute('DROP TABLE range_offset_events')
        self.reopen()
        initialize_store(self.db)
        self.assertEqual(get_day_head(self.db, DAY), first)
        self.assertEqual(inspect_day(self.db, DAY, first, 0).rows[0].value, 100)
        second = set_range_offset(self.db, DAY, first, 'G', 'T', (10, 20, 1, 6))
        # The legacy row has no sequence, so it keeps the unscoped value.
        self.assertEqual([row.value for row in inspect_day(self.db, DAY, second, 0).rows], [100])
        late = accept_batch(self.db, 'late', DAY, [reading('B', 15)])
        self.assertEqual([row.value for row in inspect_day(self.db, DAY, late, 0).rows],
                         [100, 106])
