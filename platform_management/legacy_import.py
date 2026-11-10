"""One-time import of an existing integrated database. Only its in-memory copy is upgraded."""
from contextlib import closing
from pathlib import Path
import sqlite3

from .db import FIELDS
from .violation_categories import upgrade_cases


def import_legacy(store, source):
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as old:
        with closing(sqlite3.connect(':memory:')) as copy:
            old.backup(copy)
            copy.row_factory = sqlite3.Row
            if not copy.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects'").fetchone():
                raise ValueError('Expected the integrated Platform Management database.')
            root = Path(__file__).parent
            copy.executescript((root / 'schema.sql').read_text())
            columns = {r['name'] for r in copy.execute('PRAGMA table_info(projects)')}
            if 'restriction_version' not in columns:
                copy.execute('ALTER TABLE projects ADD COLUMN restriction_version INTEGER NOT NULL DEFAULT 0')
            if 'tags' not in columns:
                copy.execute("ALTER TABLE projects ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
            copy.executescript((root.parent / 'designer_portfolio' / 'schema.sql').read_text())
            copy.executescript((root / 'workflow_schema.sql').read_text())
            upgrade_cases(copy)
            with store:
                for table, fields in FIELDS.items():
                    for row in copy.execute(f'SELECT {",".join(fields.split())} FROM {table}'):
                        store.add(table, **dict(row))
                store.dirty.update(FIELDS)
