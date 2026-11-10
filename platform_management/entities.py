"""Platform records shared with the designer portfolio."""
from collections import Counter
from datetime import datetime, timezone
from entities import RegisteredUser
from .db import get_db


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class PlatformData:
    @staticmethod
    def users():
        return {str(r['user_id']): r for r in RegisteredUser._readAll()}

    @staticmethod
    def getCategory(pk):
        return get_db().first('categories', id=pk)

    @staticmethod
    def listCategories(query=''):
        db = get_db()
        counts = Counter(p['category_id'] for p in db.all('projects'))
        items = [dict(c, project_count=counts[c['id']]) for c in db.all('categories')
                 if any(query.casefold() in c[k].casefold() for k in ('name','description'))]
        return sorted(items, key=lambda c: c['name'].casefold())

    @staticmethod
    def recordAudit(db, actor, action, target, reason=''):
        db.add('audit_log', actor_id=str(actor), action=action, target=target, reason=reason, created_at=utc_now())

    @classmethod
    def saveCategory(cls, actor, name, description, pk=None):
        with get_db() as db:
            if any(c['name'].casefold() == name.casefold() and c['id'] != pk for c in db.all('categories')):
                raise ValueError('A category with this name already exists.')
            action = 'edit_category' if pk else 'create_category'
            if pk:
                row = cls.getCategory(pk)
                if not row:
                    raise ValueError('Category no longer exists.')
                db.update('categories', row, name=name, description=description)
            else:
                pk = db.add('categories', name=name, description=description)['id']
            cls.recordAudit(db, actor, action, f'Category #{pk}: {name}')
            return pk

    @classmethod
    def deleteCategory(cls, actor, pk, destination_id=None, *, uncategorise=False):
        with get_db() as db:
            row = cls.getCategory(pk)
            if not row:
                raise ValueError('Category no longer exists.')
            projects = db.all('projects', category_id=pk)
            reason = ''
            if uncategorise:
                if destination_id is not None:
                    raise ValueError('Choose one action for linked projects.')
                reason = f'Kept {len(projects)} projects as Uncategorised.'
            elif destination_id is not None:
                destination = db.first('categories', id=destination_id)
                if not destination or destination_id == pk:
                    raise ValueError('Select another existing category.')
                reason = f'Moved {len(projects)} projects to {destination["name"]} (#{destination_id}).'
            elif projects:
                raise ValueError('Choose a destination or keep the projects as Uncategorised.')
            for project in projects:
                db.update('projects', project, category_id='' if uncategorise else destination_id)
            db.remove('categories', row)
            cls.recordAudit(db, actor, 'remove_category', f'Category #{pk}: {row["name"]}', reason)
            return reason

    @staticmethod
    def projectCount(category):
        return len(get_db().all('projects', category_id=category))

    @staticmethod
    def listProjects(query='', status='', public=False):
        db = get_db()
        names = {c['id']: c['name'] for c in db.all('categories')}
        if public:
            status = 'published'
        rows = [dict(p, category=names.get(p['category_id'], 'Uncategorised')) for p in db.all('projects')
                if query.casefold() in p['title'].casefold() and (not status or p['status'] == status)]
        return sorted(rows, key=lambda p: (p['featured'],p['created_at'],p['id']), reverse=True)

    @classmethod
    def getProject(cls, pk):
        project = get_db().first('projects', id=pk)
        if project:
            user = RegisteredUser.findById(str(project['designer_id']))
            category = cls.getCategory(project['category_id'])
            return dict(project, category=category['name'] if category else 'Uncategorised',
                        designer=user['username'] if user else f'Unavailable account #{project["designer_id"]}')

    @classmethod
    def listReports(cls, status=''):
        db = get_db()
        users = cls.users()
        projects = {p['id']:p for p in db.all('projects')}
        rows = []
        for r in db.all('content_reports'):
            if status and status != r['status']:
                continue
            p = projects[r['project_id']]
            reporter = users.get(str(r['reporter_id']), {}).get('username', f'Account #{r["reporter_id"]}')
            rows.append(dict(r, title=p['title'], description=p['description'], reporter=reporter))
        return sorted(rows, key=lambda r: (r['created_at'],r['id']), reverse=True)

    @classmethod
    def getReport(cls, pk):
        return next((r for r in cls.listReports() if r['id'] == pk), None)

    @classmethod
    def listAudit(cls):
        users = cls.users()
        rows = [dict(r, username=users.get(r['actor_id'],{}).get('username',f'Account #{r["actor_id"]}'))
                for r in get_db().all('audit_log')]
        return sorted(rows, key=lambda r: (r['created_at'],r['id']), reverse=True)

    @staticmethod
    def counts():
        db = get_db()
        return {'Projects':len(db.all('projects')), 'Published':len(db.all('projects',status='published')),
                'Open reports':len(db.all('content_reports',status='open')), 'Categories':len(db.all('categories'))}

    @staticmethod
    def reportEvents(start, stop, category=None):
        db = get_db()
        projects = {p['id'] for p in db.all('projects') if not category or p['category_id'] == category}
        events = []
        for table, key, field in [('projects','created_at','projects'),('content_reports','created_at','reports'),
                                  ('engagement_events','occurred_at',None)]:
            for row in db.all(table):
                if row.get('project_id', row['id']) in projects and start <= row[key] < stop:
                    events.append((row[key], field or ('views' if row['kind']=='view' else 'shortlists')))
        return events
