import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from warehouse import (
    Observation,
    accept_batch,
    find_batch,
    inspect_day,
    issue_report,
    load_batch_payload,
    open_store,
    read_report,
    set_offsets,
)


DAY = '2026-04-15'


def require_result(actual, expected):
    if actual != expected:
        raise RuntimeError(f'expected {expected!r}, got {actual!r}')


def show_scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual,
                  code_paths, oracle):
    require_result(actual, expected)
    require_result(downstream_actual, downstream_expected)
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id,
        'input': inputs,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': code_paths,
        'oracle': oracle,
    }, ensure_ascii=False))


def main():
    source = [Observation('B', 'G', 'B', 100, True), Observation('A', 'G', 'A', 100, False)]
    selection = ['B', 'A', 'B']
    with TemporaryDirectory(prefix='chengwan-demo-') as directory:
        path = Path(directory) / 'warehouse.sqlite3'
        with closing(open_store(path)) as db:
            first = accept_batch(db, 'morning', DAY, source)
            require_result(accept_batch(db, 'morning', DAY, source), first)
            header = find_batch(db, 'morning')
            require_result([row.occurrence_id for row in load_batch_payload(db, header).observations], ['B', 'A'])
            second = set_offsets(db, DAY, first, {'G': 10}, {'B': 2})
            before = inspect_day(db, DAY, first, 102)
            after = inspect_day(db, DAY, second, 102)
            require_result([row.raw_value for row in after.rows], [100, 100])
            require_result(before.groups[0].total, 200)
            show_scenario(
                'v03',
                {'day': DAY, 'source': [['B', 100, True], ['A', 100, False]],
                 'group_offsets': {'G': 10}, 'overrides': {'B': 2}, 'threshold': 102},
                {'old': [['A', 100], ['B', 100]], 'new': [['A', 110], ['B', 102]]},
                {'old': [[row.occurrence_id, row.value] for row in before.rows],
                 'new': [[row.occurrence_id, row.value] for row in after.rows]},
                {'groups': [['G', 212, 1]], 'candidates': ['A']},
                {'groups': [[group.group_id, group.total, group.exceedance_count] for group in after.groups],
                 'candidates': [row.occurrence_id for row in after.exceedances]},
                ['warehouse/calibration/updates.py', 'warehouse/ledger/history.py',
                 'warehouse/quality/effective.py', 'warehouse/quality/daily.py',
                 'warehouse/quality/exceedance.py', 'warehouse/quality/totals.py'],
                'A uses 100+10 and B uses 100+2. Only A is strictly above 102.',
            )
            issued = issue_report(db, DAY, second, selection)
            third = set_offsets(db, DAY, second, overrides={'B': None})

        with closing(open_store(path)) as db:
            reprinted = read_report(db, issued.report_id)
            show_scenario(
                'v06',
                {'day': DAY, 'source_revision': second, 'selection': selection, 'clear': 'B'},
                [['B', 102], ['A', 110], ['B', 102]],
                [[line.label, line.value] for line in issued.lines],
                {'source_revision': second, 'reprint': [['B', 102], ['A', 110], ['B', 102]],
                 'current': [110, 110]},
                {'source_revision': reprinted.revision,
                 'reprint': [[line.label, line.value] for line in reprinted.lines],
                 'current': [row.value for row in inspect_day(db, DAY, third, 102).rows]},
                ['warehouse/reports/selection.py', 'warehouse/reports/issuance.py',
                 'warehouse/reports/archive.py', 'warehouse/reports/reprint.py',
                 'warehouse/calibration/overrides.py', 'warehouse/quality/daily.py'],
                'Read 102, 110, 102 from the published second revision in the selected order. '
                'After clearing B, both current rows use the group offset of 10.',
            )


if __name__ == '__main__':
    main()
