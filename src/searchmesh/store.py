import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        c = self.connect()
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript((Path(__file__).parent / "migrations/001_initial.sql").read_text())
            c.execute("INSERT OR IGNORE INTO workspaces VALUES('demo','local-serpapi')")
        finally:
            c.close()

    def connect(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=10000")
        return c

    @contextmanager
    def transaction(self):
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def rows(self, sql, args=()):
        c = self.connect()
        try:
            return [dict(row) for row in c.execute(sql, args).fetchall()]
        finally:
            c.close()
