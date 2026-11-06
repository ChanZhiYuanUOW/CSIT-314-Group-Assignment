from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from entities import RegisteredUser
from .controls import PlatformManagementControl
from .entities import PlatformData,utc_now
from .workflow_entities import WorkflowEntity as E

TZ=ZoneInfo('Asia/Singapore')


class ModerationWorkflowControl(PlatformManagementControl):
    def sync(self): self.authorize();return E.syncReports(self.user_id)
    def cases(self):
        self.authorize()
        return PlatformData.rows("SELECT c.*,p.title,(SELECT COUNT(*) FROM case_reports cr WHERE cr.case_id=c.id) AS reports FROM moderation_cases c JOIN projects p ON p.id=c.project_id ORDER BY CASE c.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,c.created_at DESC,c.id DESC")
    def case(self,pk):
        self.authorize();case=E.row('moderation_cases',pk)
        return case,E.row('projects',case['project_id']),PlatformData.rows('SELECT r.* FROM content_reports r JOIN case_reports cr ON cr.report_id=r.id WHERE cr.case_id=? ORDER BY r.id',(pk,))
    def act(self,pk,action,reason,priority):
        self.authorize()
        if priority not in ('normal','high','urgent'): raise ValueError('Invalid priority.')
        E.caseAction(self.user_id,pk,action,self.reason(reason),priority)
    def appeals(self):
        self.authorize();return PlatformData.rows('SELECT a.*,p.title FROM project_appeals a JOIN moderation_cases c ON c.id=a.case_id JOIN projects p ON p.id=c.project_id ORDER BY a.id DESC')
    def appeal(self,pk):
        self.authorize();a=E.row('project_appeals',pk);return a,self.case(a['case_id'])
    def decide(self,pk,action,reason):
        self.authorize();E.appealAction(self.user_id,pk,action,self.reason(reason))


class DesignerAppealControl:
    def __init__(self,uid): self.user_id=str(uid)
    def authorize(self):
        u=RegisteredUser.findById(self.user_id)
        if not u or u['role']!='Interior Designer' or u['status']!='Active': raise PermissionError('An active Interior Designer account is required.')
    def cases(self):
        self.authorize()
        return PlatformData.rows('SELECT c.*,p.title,a.id AS appeal_id,a.state AS appeal_state,a.reason AS appeal_reason FROM moderation_cases c JOIN projects p ON p.id=c.project_id LEFT JOIN project_appeals a ON a.case_id=c.id WHERE p.designer_id=? ORDER BY c.id DESC',(self.user_id,))
    def submit(self,pk,explanation,evidence):
        self.authorize()
        E.submitAppeal(self.user_id,pk,PlatformManagementControl.reason(explanation),PlatformManagementControl.reason(evidence))
    def respond(self,pk,response):
        self.authorize();E.ownerResponse(self.user_id,pk,PlatformManagementControl.reason(response))


class FeatureScheduleControl(PlatformManagementControl):
    def schedules(self):
        self.authorize()
        rows=PlatformData.rows('SELECT s.*,p.title,p.status AS project_status FROM feature_schedules s JOIN projects p ON p.id=s.project_id ORDER BY s.starts_at DESC,s.slot')
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
