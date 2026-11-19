from tests import DAY, NEXT_DAY, StoreTestCase, measurement
from warehouse import (
    accept_batch,
    get_day_head,
    initialize_store,
    inspect_day,
    issue_report,
    read_report,
    set_offsets,
)
from warehouse.reports.archive import ArchivedLine, load_report_lines
from warehouse.reports.selection import PresentedLine


class ReportTests(StoreTestCase):
    def archive_counts(self):
        return self.db.execute(
            'SELECT (SELECT COUNT(*) FROM reports), (SELECT COUNT(*) FROM report_lines)'
        ).fetchone()

    def test_order_and_reprint(self):
        first = accept_batch(self.db, 'pair', DAY, [measurement('A', 99), measurement('B', 100)])
        issued = issue_report(self.db, DAY, first, ['B', 'A', 'B'])
        expected = (PresentedLine('B', 100), PresentedLine('A', 99), PresentedLine('B', 100))
        self.assertEqual(issued.lines, expected)
        self.assertEqual(get_day_head(self.db, DAY), first)
        second = set_offsets(self.db, DAY, first, {'G': 10})
        self.reopen()
        report = read_report(self.db, issued.report_id)
        self.assertEqual((report.report_id, report.revision, report.lines), (issued.report_id, first, expected))
        self.assertEqual([row.value for row in inspect_day(self.db, DAY, second, 0).rows], [109, 110])
        self.assertEqual([row.value for row in inspect_day(self.db, DAY, first, 0).rows], [99, 100])

    def test_same_presentation(self):
        first = accept_batch(
            self.db, 'pair', DAY, [measurement('A', label='probe'), measurement('B', label='probe')]
        )
        from_a = issue_report(self.db, DAY, first, ['A'])
        from_b = issue_report(self.db, DAY, first, ['B'])
        self.assertNotEqual(from_a.report_id, from_b.report_id)
        self.assertEqual(from_a.lines, from_b.lines)
        issued = issue_report(self.db, DAY, first, ['B', 'A', 'B'])
        self.assertEqual(issued.lines, (PresentedLine('probe', 100),) * 3)
        self.assertEqual(read_report(self.db, issued.report_id).lines, issued.lines)
        self.assertEqual(
            load_report_lines(self.db, issued.report_id),
            tuple(ArchivedLine(issued.report_id, position, 'probe', 100) for position in range(3)),
        )
        columns = [row[1] for row in self.db.execute('PRAGMA table_info(report_lines)')]
        self.assertEqual(columns, ['report_id', 'position', 'label', 'value_hex'])
        headers = [row[1] for row in self.db.execute('PRAGMA table_info(reports)')]
        self.assertEqual(headers, ['report_id', 'revision'])

    def test_reinitialize_reprint(self):
        first = accept_batch(self.db, 'pair', DAY, [measurement('B'), measurement('A', eligible=False)])
        second = set_offsets(self.db, DAY, first, {'G': 10}, {'B': 2})
        issued = issue_report(self.db, DAY, second, ['B', 'A', 'B'])
        third = set_offsets(self.db, DAY, second, overrides={'B': None})
        self.reopen()
        initialize_store(self.db)
        self.assertEqual(get_day_head(self.db, DAY), third)
        self.assertEqual([row.value for row in inspect_day(self.db, DAY, third, 102).rows], [110, 110])
        report = read_report(self.db, issued.report_id)
        self.assertEqual(report.revision, second)
        self.assertEqual(report.lines, (PresentedLine('B', 102), PresentedLine('A', 110), PresentedLine('B', 102)))

    def test_empty_selection(self):
        first = accept_batch(self.db, 'source', DAY, [measurement('A')])
        issued = issue_report(self.db, DAY, first, [])
        self.assertEqual(issued.lines, ())
        self.reopen()
        self.assertEqual(self.archive_counts(), (1, 0))
        report = read_report(self.db, issued.report_id)
        self.assertEqual((report.revision, report.lines), (first, ()))

    def test_unknown_report(self):
        with self.assertRaises(ValueError):
            read_report(self.db, 1)
        first = accept_batch(self.db, 'source', DAY, [measurement('A')])
        issued = issue_report(self.db, DAY, first, ['A'])
        with self.assertRaises(ValueError):
            read_report(self.db, issued.report_id + 1)
        self.assertEqual(self.archive_counts(), (1, 1))

    def test_exact_integer_reprint(self):
        first = accept_batch(self.db, 'source', DAY, [measurement('A', 9223372036854775808)])
        second = set_offsets(self.db, DAY, first, {'G': 90}, {'A': 9223372036854775809})
        issued = issue_report(self.db, DAY, second, ['A', 'A'])
        expected = (PresentedLine('A', 18446744073709551617),) * 2
        self.assertEqual(issued.lines, expected)
        self.reopen()
        report = read_report(self.db, issued.report_id)
        self.assertEqual((report.revision, report.lines), (second, expected))

    def test_future_occurrence_rejected(self):
        first = accept_batch(self.db, 'early', DAY, [measurement('A')])
        second = accept_batch(self.db, 'late', DAY, [measurement('B')])
        existing = issue_report(self.db, DAY, first, ['A'])
        with self.assertRaises(ValueError):
            issue_report(self.db, DAY, first, ['A', 'B'])
        self.assertEqual(self.archive_counts(), (1, 1))
        self.assertEqual(read_report(self.db, existing.report_id).revision, first)
        self.assertEqual([row.occurrence_id for row in inspect_day(self.db, DAY, first, 0).rows], ['A'])
        issued = issue_report(self.db, DAY, second, ['A', 'B'])
        self.assertEqual(issued.report_id, existing.report_id + 1)

    def test_wrong_day(self):
        accept_batch(self.db, 'early', DAY, [measurement('A')])
        second = accept_batch(self.db, 'other', NEXT_DAY, [measurement('B')])
        with self.assertRaises(ValueError):
            issue_report(self.db, DAY, second, ['A', 'B'])
        self.assertEqual(self.archive_counts(), (0, 0))
        self.assertEqual(issue_report(self.db, NEXT_DAY, second, ['B']).lines, (PresentedLine('B', 100),))

    def test_unknown_revision(self):
        first = accept_batch(self.db, 'early', DAY, [measurement('A')])
        with self.assertRaises(ValueError):
            issue_report(self.db, DAY, first + 1, ['A'])
        with self.assertRaises(ValueError):
            issue_report(self.db, DAY, first + 1, [])
        self.assertEqual(self.archive_counts(), (0, 0))
