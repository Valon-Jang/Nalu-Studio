"""SQLite lifecycle, migrations, and transaction boundary."""
from __future__ import annotations
import contextlib, datetime as dt, sqlite3
from pathlib import Path
from .schema import MIGRATIONS

class ProsodyBankStore:
    def __init__(self, path: str | Path):
        self.path=Path(path); self.connection=sqlite3.connect(self.path); self.connection.row_factory=sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
    def close(self): self.connection.close()
    def migration_plan(self):
        self.connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        done={r[0] for r in self.connection.execute("SELECT version FROM schema_migrations")}
        return [version for version,_ in MIGRATIONS if version not in done]
    def migrate(self, dry_run=False):
        plan=self.migration_plan()
        if dry_run: self.connection.rollback(); return plan
        for version,sql in MIGRATIONS:
            if version in plan:
                self.connection.executescript(sql.replace("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);", ""))
                self.connection.execute("INSERT INTO schema_migrations VALUES (?,?)",(version,dt.datetime.now(dt.timezone.utc).isoformat()))
        self.connection.commit(); return plan
    @contextlib.contextmanager
    def transaction(self):
        try:
            self.connection.execute("BEGIN"); yield self.connection; self.connection.commit()
        except Exception:
            self.connection.rollback(); raise
