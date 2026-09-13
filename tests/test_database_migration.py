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

    def test_postgres_adapter_does_not_treat_literal_percent_as_placeholder(self):
        from store import PostgresConnection
        class Raw:
            def execute(self, sql, *args):
                self.call = (sql, args)
                return type("Cursor", (), {"rowcount": 0})()
        connection = object.__new__(PostgresConnection)
        connection.raw = Raw()
        connection.execute("SELECT 1 WHERE 'scout_event' LIKE 'scout_%'")
        self.assertEqual((), connection.raw.call[1])


if __name__ == "__main__":
    unittest.main()
