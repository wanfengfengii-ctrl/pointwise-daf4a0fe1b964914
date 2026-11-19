from dataclasses import replace

from tests import DAY, NEXT_DAY, StoreTestCase, measurement
from warehouse import (
    accept_batch,
    find_batch,
    get_day_head,
    initialize_store,
    inspect_day,
    load_batch_payload,
)
from warehouse.quality.totals import GroupTotal


class AcceptTests(StoreTestCase):
    def test_duplicate_values_and_retry(self):
        observations = [measurement('B', label='probe'), measurement('A', label='probe')]
        first = accept_batch(self.db, 'original', DAY, observations)
        self.assertEqual(accept_batch(self.db, 'original', DAY, observations), first)
        initialize_store(self.db)
        inspection = inspect_day(self.db, DAY, first, 100)
        self.assertEqual([(row.occurrence_id, row.raw_value) for row in inspection.rows],
                         [('A', 100), ('B', 100)])
        self.assertEqual(inspection.groups, (GroupTotal('G', 200, 0),))
        self.assertEqual(get_day_head(self.db, DAY), first)

    def test_source_order_and_identity(self):
        observations = [measurement('B', label='probe'), measurement('A', label='probe')]
        first = accept_batch(self.db, 'original', DAY, observations)
        header = find_batch(self.db, 'original')
        self.assertEqual((header.day, header.first_revision), (DAY, first))
        payload = load_batch_payload(self.db, header)
        self.assertEqual(payload.observations, tuple(observations))
        positions = self.db.execute(
            'SELECT occurrence_id, source_index FROM observations ORDER BY source_index'
        ).fetchall()
        self.assertEqual(positions, [('B', 0), ('A', 1)])
        inspection = inspect_day(self.db, DAY, first, 99)
        self.assertEqual([row.occurrence_id for row in inspection.rows], ['A', 'B'])
        self.assertEqual(inspection.groups, (GroupTotal('G', 200, 2),))

    def test_retry_after_head_advance(self):
        original = [measurement('A')]
        first = accept_batch(self.db, 'original', DAY, original)
        second = accept_batch(self.db, 'late', DAY, [measurement('B', 101)])
        self.assertGreater(second, first)
        self.assertEqual(accept_batch(self.db, 'original', DAY, original), first)
        self.assertEqual(get_day_head(self.db, DAY), second)
        self.assertEqual([row.value for row in inspect_day(self.db, DAY, second, 0).rows], [100, 101])

    def test_reinitialize_preserves(self):
        original = [measurement('B', 105), measurement('A', 99, eligible=False)]
        first = accept_batch(self.db, 'original', DAY, original)
        self.reopen()
        initialize_store(self.db)
        initialize_store(self.db)
        header = find_batch(self.db, 'original')
        self.assertEqual(header.first_revision, first)
        self.assertEqual(load_batch_payload(self.db, header).observations, tuple(original))
        self.assertEqual(accept_batch(self.db, 'original', DAY, original), first)
        self.assertEqual(get_day_head(self.db, DAY), first)

    def test_conflicting_batch_id(self):
        original = [measurement('A')]
        first = accept_batch(self.db, 'original', DAY, original)
        with self.assertRaises(ValueError):
            accept_batch(self.db, 'original', DAY, [measurement('A', 101)])
        with self.assertRaises(ValueError):
            accept_batch(self.db, 'original', NEXT_DAY, original)
        self.assertEqual(get_day_head(self.db, DAY), first)
        self.assertIsNone(get_day_head(self.db, NEXT_DAY))
        header = find_batch(self.db, 'original')
        self.assertEqual(header.first_revision, first)
        self.assertEqual(load_batch_payload(self.db, header).observations, tuple(original))
        self.assertEqual(inspect_day(self.db, DAY, first, 0).rows[0].raw_value, 100)

    def test_reordered_source(self):
        rows = [measurement('B'), measurement('A')]
        first = accept_batch(self.db, 'original', DAY, rows)
        with self.assertRaises(ValueError):
            accept_batch(self.db, 'original', DAY, list(reversed(rows)))
        header = find_batch(self.db, 'original')
        self.assertEqual(load_batch_payload(self.db, header).observations, tuple(rows))
        self.assertEqual(accept_batch(self.db, 'original', DAY, rows), first)
        self.assertEqual(get_day_head(self.db, DAY), first)

    def test_occurrence_conflict(self):
        first = accept_batch(self.db, 'original', DAY, [measurement('A')])
        with self.assertRaises(ValueError):
            accept_batch(self.db, 'second', NEXT_DAY, [measurement('C'), measurement('A')])
        self.assertIsNone(find_batch(self.db, 'second'))
        self.assertIsNone(get_day_head(self.db, NEXT_DAY))
        self.assertEqual(inspect_day(self.db, NEXT_DAY, first, 0).rows, ())
        second = accept_batch(self.db, 'second', NEXT_DAY, [measurement('C')])
        self.assertEqual(second, first + 1)
        self.assertEqual([row.occurrence_id for row in inspect_day(self.db, NEXT_DAY, second, 0).rows], ['C'])
        self.assertEqual(get_day_head(self.db, DAY), first)

    def test_invalid_fields(self):
        valid = measurement('A')
        invalid = (
            ('bad calendar date', '2026-02-30', [valid]),
            ('missing raw value', DAY, [valid, measurement('B', None)]),
            ('float raw value', DAY, [valid, measurement('B', 1.5)]),
            ('boolean raw value', DAY, [valid, measurement('B', True)]),
            ('missing eligibility', DAY, [valid, measurement('B', eligible=None)]),
            ('integer eligibility', DAY, [valid, measurement('B', eligible=1)]),
            ('missing group', DAY, [valid, replace(measurement('B'), group_id='')]),
            ('missing label', DAY, [valid, replace(measurement('B'), label='')]),
            ('duplicate identity', DAY, [valid, measurement('A', 101)]),
        )
        for case, day, rows in invalid:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    accept_batch(self.db, 'original', day, rows)
                self.assertIsNone(find_batch(self.db, 'original'))
                self.assertIsNone(get_day_head(self.db, DAY))
        first = accept_batch(self.db, 'original', DAY, [valid])
        self.assertEqual(first, 1)
        self.assertEqual(len(inspect_day(self.db, DAY, first, 0).rows), 1)
