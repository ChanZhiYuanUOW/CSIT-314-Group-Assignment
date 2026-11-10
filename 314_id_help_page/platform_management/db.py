"""Shared CSV tables. Hold a process-safe lock while reading or changing linked rows."""
import csv
import os
from pathlib import Path
import shutil
from tempfile import mkdtemp, mkstemp

from contextlib import contextmanager
from flask import current_app, g


def migrate_reviews_csv(path):
    old_fields = 'id designer_id customer review reply'.split()
    new_fields = FIELDS['reviews'].split()

    if not path.exists():
        return

    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)

        # Only migrate the exact old reviews schema.
        if reader.fieldnames != old_fields:
            return

        rows = list(reader)

    fd, temp_path = mkstemp(dir=path.parent, suffix='.tmp')

    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=new_fields)
            writer.writeheader()

            for row in rows:
                for field in new_fields:
                    row.setdefault(field, '')
                writer.writerow(row)

            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temp_path, path)

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


FIELDS = {
    'categories': 'id name description',
    'projects': 'id title description designer_id category_id status featured created_at restriction_version tags',
    'engagement_events': 'id project_id customer_id kind occurred_at',
    'content_reports': 'id project_id reporter_id reason evidence status created_at reviewed_by reviewed_at decision_note',
    'audit_log': 'id actor_id action target reason created_at',
    'demo_metadata': 'name',
    'moderation_cases': 'id project_id state priority assigned_to request_note response_note decision reason previous_status restriction_version created_at resolved_at violation_category',
    'case_reports': 'report_id case_id',
    'project_appeals': 'id case_id owner_id explanation evidence state reviewer_id reason created_at decided_at',
    'feature_schedules': 'id project_id slot starts_at ends_at state created_by reason created_at',
    'pm_notifications': 'id user_id message created_at is_read',
    'photos': 'id project_id filename photo_type position',
    'company': 'id designer_id name description email phone location',
    'reviews': 'id designer_id customer review reply customer_id renovation_id rating created_at',
    'favourite_groups': 'id customer_id name created_at',
    'favourites': 'id customer_id group_id project_id',
}
NUMERIC = set('id project_id category_id group_id case_id report_id featured slot restriction_version is_read position rating'.split())
DEFAULTS = {
    'projects': dict(featured=0, restriction_version=0),
    'content_reports': dict(status='open'),
    'moderation_cases': dict(state='open', priority='normal', violation_category='Other violation'),
    'project_appeals': dict(state='pending'),
    'feature_schedules': dict(state='scheduled'),
    'pm_notifications': dict(is_read=0),
    'photos': dict(position=0, photo_type='After'),
}


@contextmanager
def exclusive_lock(path):
    with path.open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class CsvStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock = exclusive_lock(self.folder / '.write.lock')
        self.lock.__enter__()
        try:
            self.recover()
            self.load()
        except BaseException:
            self.lock.__exit__(None, None, None)
            raise

    def recover(self):
        pending = self.folder / '.pending'
        if pending.exists():
            for file in pending.glob('*.csv'):
                os.replace(file, self.folder / file.name)
            pending.rmdir()

    def load(self):
        self.tables = {}
        self.next_ids = {}

        for table, fields in FIELDS.items():
            path = self.folder / (table + '.csv')
            rows = []

            if table == 'reviews':
                migrate_reviews_csv(path)

            if path.exists():
                with path.open(encoding='utf-8-sig', newline='') as stream:
                    reader = csv.DictReader(stream)
                    if reader.fieldnames != fields.split():
                        raise ValueError(f'Unexpected CSV columns in {path}')

                    for row in reader:
                        if None in row or any(value is None for value in row.values()):
                            raise ValueError(f'Incomplete CSV row in {path} at line {reader.line_num}')

                        for key in NUMERIC.intersection(row):
                            if row[key]:
                                row[key] = int(row[key])

                        rows.append(row)

            self.tables[table] = rows
            self.next_ids[table] = max(
                (r.get('id', 0) for r in rows), default=0
            ) + 1

        self.dirty = set()
        
    def all(self, table, **criteria):
        return [r for r in self.tables[table] if all(r[k] == v for k, v in criteria.items())]

    def first(self, table, **criteria):
        return next((r for r in self.tables[table] if all(r[k] == v for k, v in criteria.items())), None)

    def add(self, table, **values):
        row = dict.fromkeys(FIELDS[table].split(), '')
        row.update(DEFAULTS.get(table, {}))
        if 'id' in row:
            row['id'] = self.next_ids[table]
        row.update(values)
        if 'id' in row:
            self.next_ids[table] = max(self.next_ids[table], row['id'] + 1)
        self.tables[table].append(row)
        self.dirty.add(table)
        return row

    def update(self, table, row, **values):
        row.update(values)
        self.dirty.add(table)

    def remove(self, table, row):
        self.tables[table].remove(row)
        self.dirty.add(table)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type:
            self.load()
        elif self.dirty:
            self.save()

    def save(self):
        stage = Path(mkdtemp(dir=self.folder, prefix='.stage-'))
        try:
            for table in self.dirty:
                with (stage / (table + '.csv')).open('w', encoding='utf-8', newline='') as stream:
                    writer = csv.DictWriter(stream, FIELDS[table].split())
                    writer.writeheader()
                    writer.writerows(self.tables[table])
                    stream.flush()
                    os.fsync(stream.fileno())
            os.replace(stage, self.folder / '.pending')
            self.recover()
            self.dirty.clear()
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def get_db():
    if 'pm_csv' not in g:
        store = CsvStore(current_app.config['PM_CSV_DIR'])
        g.pm_csv = store
        source = Path(current_app.config.get('PM_DATABASE', Path(current_app.instance_path) / 'platform_management.sqlite3'))
        if source.is_file() and not any((store.folder / (t + '.csv')).exists() for t in FIELDS):
            from .legacy_import import import_legacy
            import_legacy(store, source)
    return g.pm_csv


def init_db():
    db = get_db()
    with db:
        db.dirty.update(t for t in FIELDS if not (db.folder / (t + '.csv')).exists())


def init_app(app):
    @app.teardown_appcontext
    def close_csv(error=None):
        db = g.pop('pm_csv', None)
        if db is not None:
            db.lock.__exit__(None, None, None)
