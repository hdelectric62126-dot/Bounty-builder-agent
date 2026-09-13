import os
import tempfile
import unittest

from database_migration import migrate_sqlite_to_postgres
from store import Store


class DatabaseMigrationTests(unittest.TestCase):
    def test_sqlite_mode_never_attempts_external_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "test.db")
            store = Store(path)
            self.assertEqual(
                {"status": "not_needed", "rows": 0},
                migrate_sqlite_to_postgres(path, store),
            )


if __name__ == "__main__":
    unittest.main()
