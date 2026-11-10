from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from entities import RegisteredUser
from .controls import PlatformManagementControl
from .db import get_db
from .entities import PlatformData,utc_now
from .workflow_entities import WorkflowEntity as E

TZ=ZoneInfo('Asia/Singapore')


class ModerationWorkflowControl(PlatformManagementControl):
    def sync(self): self.authorize();return E.syncReports(self.user_id)
    def cases(self):
        self.authorize()
        db = get_db()
        titles = {p['id']: p['title'] for p in db.all('projects')}
        cases = [dict(c, title=titles[c['project_id']], reports=len(db.all('case_reports', case_id=c['id'])))
                 for c in db.all('moderation_cases')]
        cases.sort(key=lambda c:(c['created_at'],c['id']), reverse=True)
        return sorted(cases, key=lambda c:(c['violation_category'], c['state']=='resolved',
                                           ('urgent','high','normal').index(c['priority'])))
    def case(self,pk):
        self.authorize();case=E.row('moderation_cases',pk)
        ids = {r['report_id'] for r in get_db().all('case_reports', case_id=pk)}
        reports = sorted((r for r in get_db().all('content_reports') if r['id'] in ids), key=lambda r:r['id'])
        return case, E.row('projects',case['project_id']), reports
    def act(self,pk,action,reason,priority):
        self.authorize()
        if priority not in ('normal','high','urgent'): raise ValueError('Invalid priority.')
        E.caseAction(self.user_id,pk,action,self.reason(reason),priority)
    def appeals(self):
        self.authorize()
        cases = {c['id']:c['title'] for c in self.cases()}
        rows = [dict(a, title=cases[a['case_id']]) for a in get_db().all('project_appeals')]
        return sorted(rows, key=lambda a:(a['state'] not in ('pending','under_review'), -a['id']))
    def appeal(self,pk):
        self.authorize();a=E.row('project_appeals',pk);return a,self.case(a['case_id'])
    def decide(self,pk,action,reason):
        self.authorize()
        note = 'Started appeal review.' if action == 'claim' else self.reason(reason)
        E.appealAction(self.user_id, pk, action, note)


class DesignerAppealControl:
    def __init__(self,uid): self.user_id=str(uid)
    def authorize(self):
        u=RegisteredUser.findById(self.user_id)
        if not u or u['role']!='Interior Designer' or u['status']!='Active': raise PermissionError('An active Interior Designer account is required.')
    def cases(self):
        self.authorize()
        db = get_db()
        titles = {p['id']:p['title'] for p in db.all('projects', designer_id=self.user_id)}
        appeals = {a['case_id']:a for a in db.all('project_appeals')}
        rows = []
        for c in db.all('moderation_cases'):
            if c['project_id'] in titles:
                a = appeals.get(c['id'], {})
                rows.append(dict(c,title=titles[c['project_id']],appeal_id=a.get('id'),appeal_state=a.get('state'),appeal_reason=a.get('reason')))
        return sorted(rows,key=lambda c:-c['id'])
    def submit(self,pk,explanation,evidence):
        self.authorize()
        E.submitAppeal(self.user_id,pk,PlatformManagementControl.reason(explanation),PlatformManagementControl.reason(evidence))
    def respond(self,pk,response):
        self.authorize();E.ownerResponse(self.user_id,pk,PlatformManagementControl.reason(response))


class FeatureScheduleControl(PlatformManagementControl):
    def schedules(self):
        self.authorize()
        db = get_db()
        projects = {p['id']:p for p in db.all('projects')}
        rows = [dict(s, title=projects[s['project_id']]['title'], project_status=projects[s['project_id']]['status'])
                for s in db.all('feature_schedules')]
        rows.sort(key=lambda s:s['slot'])
        rows.sort(key=lambda s:s['starts_at'], reverse=True)
        now=utc_now()
        for r in rows:
            r['display_state']='cancelled' if r['state']=='cancelled' else 'expired' if r['ends_at']<=now else 'suppressed' if r['project_status']!='published' else 'upcoming' if r['starts_at']>now else 'active'
            r['start_local']=datetime.fromisoformat(r['starts_at']).astimezone(TZ).strftime('%Y-%m-%d %H:%M')
            r['end_local']=datetime.fromisoformat(r['ends_at']).astimezone(TZ).strftime('%Y-%m-%d %H:%M')
        return rows
    def save(self,data,pk=None):
        self.authorize()
        try:
            project=int(data.get('project_id',''));slot=int(data.get('slot',''))
            start=datetime.fromisoformat(data.get('starts_at',''));end=datetime.fromisoformat(data.get('ends_at',''))
            if start.tzinfo or end.tzinfo: raise ValueError()
            start=start.replace(tzinfo=TZ).astimezone(timezone.utc);end=end.replace(tzinfo=TZ).astimezone(timezone.utc)
        except (ValueError,TypeError): raise ValueError('Enter a project, slot and valid Singapore start/end times.')
        if slot not in range(1,7) or end<=start or end<=datetime.now(timezone.utc): raise ValueError('Use slot 1–6 and an end time after the start and current time.')
        # Start may be in the past to feature immediately; window remains [start, end).
        return E.saveSchedule(self.user_id,project,slot,start.isoformat(timespec='seconds'),end.isoformat(timespec='seconds'),self.reason(data.get('reason','')),pk)
    def cancel(self,pk,reason):
        self.authorize();E.cancelSchedule(self.user_id,pk,self.reason(reason))
