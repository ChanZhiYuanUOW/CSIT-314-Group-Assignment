CREATE TABLE IF NOT EXISTS moderation_cases (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','under_review','awaiting_response','resolved')),
 priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('normal','high','urgent')),
 assigned_to TEXT, request_note TEXT NOT NULL DEFAULT '', response_note TEXT NOT NULL DEFAULT '',
 decision TEXT CHECK(decision IN ('dismiss','hide','remove')), reason TEXT NOT NULL DEFAULT '',
 previous_status TEXT, restriction_version INTEGER, created_at TEXT NOT NULL, resolved_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_case ON moderation_cases(project_id) WHERE state!='resolved';
CREATE TABLE IF NOT EXISTS case_reports (
 report_id INTEGER PRIMARY KEY REFERENCES content_reports(id), case_id INTEGER NOT NULL REFERENCES moderation_cases(id)
);
CREATE TABLE IF NOT EXISTS project_appeals (
 id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES moderation_cases(id), owner_id TEXT NOT NULL,
 explanation TEXT NOT NULL, evidence TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','under_review','approved','rejected')),
 reviewer_id TEXT, reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, decided_at TEXT
);
-- One appeal per decision in this coursework policy, including after rejection.
CREATE UNIQUE INDEX IF NOT EXISTS one_appeal_per_decision ON project_appeals(case_id);
CREATE TABLE IF NOT EXISTS feature_schedules (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 6), starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'scheduled' CHECK(state IN ('scheduled','cancelled')),
 created_by TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
 CHECK(starts_at < ends_at)
);
CREATE INDEX IF NOT EXISTS schedule_window ON feature_schedules(slot,starts_at,ends_at);
CREATE TABLE IF NOT EXISTS pm_notifications (
 id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL,
 is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1))
);
