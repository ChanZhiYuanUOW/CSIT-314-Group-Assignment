"""Report categories and the migration from one active case per project."""

CATEGORIES = (
    'Copyright infringement',
    'Inappropriate content',
    'Misleading description',
    'Incorrect category',
    'Other violation',
)
LEGACY_REASONS = {
    'Possible copied content': 'Copyright infringement',
    'Demo photo ownership complaint': 'Copyright infringement',
}


def report_category(reason):
    if reason in CATEGORIES:
        return reason
    return LEGACY_REASONS.get(reason, 'Other violation')


def upgrade_cases(db):
    with db:
        db.execute('BEGIN IMMEDIATE')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(moderation_cases)')}
        if 'violation_category' not in columns:
            db.execute("ALTER TABLE moderation_cases ADD COLUMN violation_category TEXT NOT NULL DEFAULT 'Other violation'")
            db.execute('DROP INDEX IF EXISTS one_active_case')
            for case in db.execute('SELECT * FROM moderation_cases ORDER BY id').fetchall():
                reports = db.execute(
                    'SELECT r.id, r.reason FROM content_reports r JOIN case_reports cr ON cr.report_id=r.id '
                    'WHERE cr.case_id=? ORDER BY r.id', (case['id'],)
                )
                groups = {}
                for report in reports:
                    groups.setdefault(report_category(report['reason']), []).append(report['id'])
                first = next(iter(groups), 'Other violation')
                closed = case['state'] == 'resolved'
                if closed and len(groups) > 1:
                    first = 'Multiple categories (historical)'
                db.execute('UPDATE moderation_cases SET violation_category=? WHERE id=?', (first, case['id']))
                if closed:
                    continue
                for category, ids in groups.items():
                    case_id = case['id']
                    if category != first:
                        case_id = db.execute(
                            'INSERT INTO moderation_cases(project_id,violation_category,created_at) VALUES(?,?,?)',
                            (case['project_id'], category, case['created_at'])
                        ).lastrowid
                        db.executemany('UPDATE case_reports SET case_id=? WHERE report_id=?',
                                       [(case_id, rid) for rid in ids])
                    if len(ids) >= 3:
                        db.execute("UPDATE moderation_cases SET priority='high' WHERE id=? AND priority='normal'", (case_id,))
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS active_project_category ON moderation_cases(project_id,violation_category) WHERE state!='resolved'")
