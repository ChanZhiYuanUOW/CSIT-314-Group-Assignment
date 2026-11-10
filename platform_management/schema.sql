-- Temporary project data only. User IDs refer to Zhiyuan's CSV accounts. No duplicate users table.
CREATE TABLE IF NOT EXISTS categories (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK(length(trim(name)) BETWEEN 1 AND 80),
 description TEXT NOT NULL DEFAULT '' CHECK(length(description)<=240)
);
CREATE TABLE IF NOT EXISTS projects (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 designer_id TEXT NOT NULL,
 category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
 status TEXT NOT NULL CHECK(status IN ('draft','published','hidden','removed')),
 featured INTEGER NOT NULL DEFAULT 0 CHECK(featured IN (0,1)), created_at TEXT NOT NULL,
 CHECK(featured=0 OR status='published')
);
CREATE TABLE IF NOT EXISTS engagement_events (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
 customer_id TEXT,
 kind TEXT NOT NULL CHECK(kind IN ('view','shortlist')), occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS content_reports (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
 reporter_id TEXT NOT NULL,
 reason TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','dismissed','actioned')),
 created_at TEXT NOT NULL, reviewed_by TEXT,
 reviewed_at TEXT, decision_note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY, actor_id TEXT NOT NULL,
 action TEXT NOT NULL, target TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demo_metadata (name TEXT PRIMARY KEY);
CREATE INDEX IF NOT EXISTS events_time ON engagement_events(occurred_at);
CREATE INDEX IF NOT EXISTS projects_time ON projects(created_at);
CREATE INDEX IF NOT EXISTS reports_time ON content_reports(created_at);
