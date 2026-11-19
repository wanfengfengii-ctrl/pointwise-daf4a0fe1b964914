from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from warehouse import Observation, open_store


DAY = '2026-04-15'
NEXT_DAY = '2026-04-16'


def measurement(
    occurrence_id: str,
    raw: int = 100,
    *,
    group: str = 'G',
    label: str | None = None,
    eligible: bool = True,
) -> Observation:
    return Observation(occurrence_id, group, occurrence_id if label is None else label, raw, eligible)


class StoreTestCase(TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='chengwan-test-')
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'warehouse.sqlite3'
        self.db = open_store(self.path)
        self.addCleanup(lambda: self.db.close())

    def reopen(self):
        self.db.close()
        self.db = open_store(self.path)
