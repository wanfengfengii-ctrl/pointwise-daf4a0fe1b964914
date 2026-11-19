"""Run this project's full unittest suite and joint range checks from the repository root."""
import sys
import unittest


def run_suite():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    if suite.countTestCases():
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        print('No tests discovered in tests/', file=sys.stderr)
        result = unittest.TestResult()
    for status, failed_cases in (
        ('FAIL', (test for test, _ in result.failures)),
        ('ERROR', (test for test, _ in result.errors)),
        ('UNEXPECTED_SUCCESS', result.unexpectedSuccesses),
    ):
        for test in failed_cases:
            print(f'{status} {test.id()}')
    successful = result.testsRun > 0 and result.wasSuccessful()
    print(f'TEST SUMMARY total={result.testsRun} failures={len(result.failures)} '
          f'errors={len(result.errors)} skipped={len(result.skipped)} '
          f'expected_failures={len(result.expectedFailures)} '
          f'unexpected_successes={len(result.unexpectedSuccesses)} '
          f'result={"PASS" if successful else "FAIL"}')
    return successful


def run_range_examples():
    try:
        from range_examples import run_examples

        summary = run_examples()
    except BaseException as exc:  # noqa: BLE001 - verification entry point
        print(f'RANGE EXAMPLES FAIL {type(exc).__name__}: {exc}', file=sys.stderr)
        return False
    print(f'RANGE EXAMPLES PASS {summary!r}')
    return True


def main():
    suite_ok = run_suite()
    ranges_ok = run_range_examples()
    return 0 if suite_ok and ranges_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
