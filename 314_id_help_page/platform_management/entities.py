"""Entity layer: temporary project persistence and shared CSV user lookup."""
import sqlite3
from datetime import datetime, timezone
from entities import RegisteredUser
from .db import get_db


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class PlatformData:
    @staticmethod
    def users():
        return {str(u['user_id']):u for u in RegisteredUser._readAll()}

    @staticmethod
    def rows(sql, params=()):
        return [dict(row) for row in get_db().execute(sql,params)]

    @classmethod
    def getCategory(cls, pk):
        rows=cls.rows('SELECT * FROM categories WHERE id=?',(pk,))
        return rows[0] if rows else None

    @classmethod
    def listCategories(cls, query=''):
        return cls.rows('SELECT c.*, (SELECT COUNT(*) FROM projects p WHERE p.category_id=c.id) AS project_count FROM categories c WHERE name LIKE ? OR description LIKE ? ORDER BY name,id',(f'%{query}%',f'%{query}%'))

    @staticmethod
    def recordAudit(db, actor, action, target, reason=''):
        db.execute('INSERT INTO audit_log(actor_id,action,target,reason,created_at) VALUES(?,?,?,?,?)',(str(actor),action,target,reason,utc_now()))

    @classmethod
    def saveCategory(cls, actor, name, description, pk=None):
        db=get_db()
        try:
            with db:
                if pk:
                    if db.execute('UPDATE categories SET name=?,description=? WHERE id=?',(name,description,pk)).rowcount != 1:
                        raise ValueError('Category no longer exists.')
                    saved=pk
                else:
                    saved=db.execute('INSERT INTO categories(name,description) VALUES(?,?)',(name,description)).lastrowid
                cls.recordAudit(db,actor,'edit_category' if pk else 'create_category',f'Category #{saved}: {name}')
            return saved
        except sqlite3.IntegrityError as exc:
            raise ValueError('A category with this name already exists.') from exc

    @classmethod
    def deleteCategory(cls, actor, pk):
        db=get_db()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                item=cls.getCategory(pk)
                if not item: raise ValueError('Category no longer exists.')
                db.execute('DELETE FROM categories WHERE id=?',(pk,))
                cls.recordAudit(db,actor,'remove_category',f'Category #{pk}: {item["name"]}')
        except sqlite3.IntegrityError as exc:
            raise ValueError('Reassign projects using this category before removing it.') from exc

    @classmethod
    def projectCount(cls, category):
        return cls.rows('SELECT COUNT(*) AS total FROM projects WHERE category_id=?',(category,))[0]['total']

    @classmethod
    def listProjects(cls, query='', status='', public=False):
        sql='SELECT p.*,c.name AS category FROM projects p JOIN categories c ON c.id=p.category_id WHERE p.title LIKE ?'
        params=[f'%{query}%']
        if public: status='published'
        if status: sql+=' AND p.status=?';params.append(status)
        return cls.rows(sql+' ORDER BY p.featured DESC,p.created_at DESC,p.id DESC',params)

    @classmethod
    def getProject(cls, pk):
        rows=cls.rows('SELECT p.*,c.name AS category FROM projects p JOIN categories c ON c.id=p.category_id WHERE p.id=?',(pk,))
        if not rows: return None
        row=rows[0];user=RegisteredUser.findById(str(row['designer_id']))
        row['designer']=user['username'] if user else f'Unavailable account #{row["designer_id"]}'
        return row

    @classmethod
    def listReports(cls, status=''):
        sql='SELECT r.*,p.title,p.description FROM content_reports r JOIN projects p ON p.id=r.project_id'
        rows=cls.rows(sql+(' WHERE r.status=?' if status else '')+' ORDER BY r.created_at DESC,r.id DESC',(status,) if status else ())
        users=cls.users()
        for row in rows: row['reporter']=users.get(str(row['reporter_id']),{}).get('username',f'Account #{row["reporter_id"]}')
        return rows

    @classmethod
    def getReport(cls, pk):
        return next((r for r in cls.listReports() if r['id']==pk),None)

    @classmethod
    def listAudit(cls):
        rows=cls.rows('SELECT * FROM audit_log ORDER BY created_at DESC,id DESC');users=cls.users()
        for row in rows: row['username']=users.get(str(row['actor_id']),{}).get('username',f'Account #{row["actor_id"]}')
        return rows

    @classmethod
    def counts(cls):
        return {label:cls.rows(sql)[0]['total'] for label,sql in [
            ('Projects','SELECT COUNT(*) AS total FROM projects'),('Published',"SELECT COUNT(*) AS total FROM projects WHERE status='published'"),
            ('Open reports',"SELECT COUNT(*) AS total FROM content_reports WHERE status='open'"),('Categories','SELECT COUNT(*) AS total FROM categories')]}

    @classmethod
    def changeProject(cls, actor, pk, action, reason, report_id=None):
        # A single transaction commits both project change and report decision.
        db=get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            if report_id is not None:
                report=db.execute('SELECT * FROM content_reports WHERE id=?',(report_id,)).fetchone()
                if not report or report['status']!='open': raise ValueError('Report is missing or already reviewed.')
                pk=report['project_id']
            project=db.execute('SELECT * FROM projects WHERE id=?',(pk,)).fetchone()
            if not project: raise ValueError('Project no longer exists.')
            if action=='feature':
                if project['status']!='published': raise ValueError('Only published projects can be featured.')
                db.execute('UPDATE projects SET featured=1 WHERE id=?',(pk,))
            elif action=='unfeature': db.execute('UPDATE projects SET featured=0 WHERE id=?',(pk,))
            elif action in ('hide','remove'):
                if project['status']=='removed': raise ValueError('Project has already been removed.')
                db.execute('UPDATE projects SET status=?,featured=0,restriction_version=restriction_version+1 WHERE id=?',('hidden' if action=='hide' else 'removed',pk))
            elif action!='dismiss' or report_id is None: raise ValueError('Invalid action.')
            if action!='dismiss': cls.recordAudit(db,actor,action,f'Project #{pk}: {project["title"]}',reason)
            if report_id is not None:
                db.execute('UPDATE content_reports SET status=?,reviewed_by=?,reviewed_at=?,decision_note=? WHERE id=?',('dismissed' if action=='dismiss' else 'actioned',str(actor),utc_now(),reason,report_id))
                cls.recordAudit(db,actor,'review_report',f'Report #{report_id}',reason)

    @classmethod
    def reportEvents(cls,start,stop,category=None):
        events=[]
        for table,stamp,join,field in [('projects p','p.created_at','','projects'),('engagement_events e','e.occurred_at','JOIN projects p ON p.id=e.project_id',None),('content_reports r','r.created_at','JOIN projects p ON p.id=r.project_id','reports')]:
            sql=f'SELECT {stamp} AS stamp'+(',e.kind' if field is None else '')+f' FROM {table} {join} WHERE {stamp}>=? AND {stamp}<?';params=[start,stop]
            if category: sql+=' AND p.category_id=?';params.append(category)
            for row in cls.rows(sql,params): events.append((row['stamp'],field or ('views' if row['kind']=='view' else 'shortlists')))
        return events
