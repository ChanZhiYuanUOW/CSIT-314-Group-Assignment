import sqlite3
from flask import current_app, g


def get_db():
    if 'pm_db' not in g:
        g.pm_db = sqlite3.connect(current_app.config['PM_DATABASE'], timeout=10)
        g.pm_db.row_factory = sqlite3.Row
        g.pm_db.execute('PRAGMA foreign_keys = ON')
    return g.pm_db


def init_db():
    from pathlib import Path
    with (Path(__file__).parent / 'schema.sql').open('rb') as file:
        get_db().executescript(file.read().decode())
    # Additive, idempotent upgrade: preserve existing project/demo data.
    db = get_db()
    columns = {row['name'] for row in db.execute('PRAGMA table_info(projects)')}
    if 'restriction_version' not in columns:
        db.execute('ALTER TABLE projects ADD COLUMN restriction_version INTEGER NOT NULL DEFAULT 0')
        db.commit()
    with (Path(__file__).parent / 'workflow_schema.sql').open() as file:
        db.executescript(file.read())


def init_app(app):
    @app.teardown_appcontext
    def close_db(error=None):
        db = g.pop('pm_db', None)
        if db is not None:
            db.close()
