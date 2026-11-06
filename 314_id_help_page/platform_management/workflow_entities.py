"""Persistence and atomic state transitions for cases, appeals and schedules."""
from .db import get_db
from .entities import PlatformData,utc_now


class WorkflowEntity:
    @staticmethod
    def row(table, pk):
        if table not in ('moderation_cases','project_appeals','feature_schedules','projects'): raise ValueError('Invalid entity.')
        row=get_db().execute(f'SELECT * FROM {table} WHERE id=?',(pk,)).fetchone()
        if not row: raise ValueError('Record does not exist.')
        return dict(row)

    @staticmethod
    def notify(db,user_id,message):
        db.execute('INSERT INTO pm_notifications(user_id,message,created_at) VALUES(?,?,?)',(str(user_id),message,utc_now()))

    @staticmethod
    def audit(db,actor,action,target,reason):
        PlatformData.recordAudit(db,actor,action,target,reason)

    @classmethod
    def syncReports(cls,actor):
        db=get_db();count=0
        with db:
            db.execute('BEGIN IMMEDIATE')
            reports=db.execute("SELECT r.* FROM content_reports r LEFT JOIN case_reports cr ON cr.report_id=r.id WHERE cr.report_id IS NULL AND r.status='open' ORDER BY r.id").fetchall()
            for r in reports:
                case=db.execute("SELECT id FROM moderation_cases WHERE project_id=? AND state!='resolved'",(r['project_id'],)).fetchone()
                cid=case['id'] if case else db.execute('INSERT INTO moderation_cases(project_id,created_at) VALUES(?,?)',(r['project_id'],utc_now())).lastrowid
                db.execute('INSERT INTO case_reports(report_id,case_id) VALUES(?,?)',(r['id'],cid));count+=1
                n=db.execute('SELECT COUNT(*) FROM case_reports WHERE case_id=?',(cid,)).fetchone()[0]
                if n>=3: db.execute("UPDATE moderation_cases SET priority='high' WHERE id=? AND priority='normal'",(cid,))
            if count: cls.audit(db,actor,'group_reports','Moderation cases',f'Grouped {count} unassigned reports.')
        return count

    @classmethod
    def caseAction(cls,actor,pk,action,reason,priority='normal'):
        db=get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            case=cls.row('moderation_cases',pk)
            if case['state']=='resolved': raise ValueError('This case is already resolved.')
            if action=='claim':
                if case['state']=='awaiting_response': raise ValueError('Wait for the designer response before continuing review.')
                if case['assigned_to'] and case['assigned_to']!=str(actor): raise ValueError('Another manager owns this case.')
                db.execute("UPDATE moderation_cases SET assigned_to=?,state='under_review' WHERE id=?",(str(actor),pk))
            else:
                if case['assigned_to']!=str(actor): raise ValueError('Claim the case before making changes.')
                if action=='priority': db.execute('UPDATE moderation_cases SET priority=? WHERE id=?',(priority,pk))
                elif action=='request':
                    if case['state']!='under_review': raise ValueError('Case must be under review.')
                    db.execute("UPDATE moderation_cases SET state='awaiting_response',request_note=?,response_note='' WHERE id=?",(reason,pk))
                    p=cls.row('projects',case['project_id']);cls.notify(db,p['designer_id'],f'Case #{pk}: clarification requested — {reason}')
                elif action in ('dismiss','hide','remove'):
                    if case['state']!='under_review': raise ValueError('Case must be under review; wait for the designer response if requested.')
                    p=cls.row('projects',case['project_id']);version=p['restriction_version']
                    if action in ('hide','remove'):
                        if p['status']=='removed': raise ValueError('Project already removed; dismiss this case if no further action is needed.')
                        version+=1
                        db.execute('UPDATE projects SET status=?,featured=0,restriction_version=? WHERE id=?',('hidden' if action=='hide' else 'removed',version,p['id']))
                    db.execute("UPDATE moderation_cases SET state='resolved',decision=?,reason=?,previous_status=?,restriction_version=?,resolved_at=? WHERE id=?",(action,reason,p['status'],version,utc_now(),pk))
                    db.execute("UPDATE content_reports SET status=?,reviewed_by=?,reviewed_at=?,decision_note=? WHERE id IN (SELECT report_id FROM case_reports WHERE case_id=?)",('dismissed' if action=='dismiss' else 'actioned',str(actor),utc_now(),reason,pk))
                    cls.notify(db,p['designer_id'],f'Case #{pk} resolved: {action}. Reason: {reason}')
                else: raise ValueError('Invalid case action.')
            cls.audit(db,actor,'case_'+action,f'Case #{pk}',reason)

    @classmethod
    def ownerResponse(cls,actor,pk,response):
        db=get_db()
        with db:
            db.execute('BEGIN IMMEDIATE');case=cls.row('moderation_cases',pk);p=cls.row('projects',case['project_id'])
            if str(p['designer_id'])!=str(actor): raise PermissionError('Only the project owner can respond.')
            if case['state']!='awaiting_response': raise ValueError('No clarification response is pending.')
            db.execute("UPDATE moderation_cases SET response_note=?,state='under_review' WHERE id=?",(response,pk))
            cls.notify(db,case['assigned_to'],f'Designer responded to case #{pk}.')
            cls.audit(db,actor,'case_response',f'Case #{pk}',response)

    @classmethod
    def submitAppeal(cls,actor,pk,explanation,evidence):
        db=get_db()
        with db:
            db.execute('BEGIN IMMEDIATE');case=cls.row('moderation_cases',pk);p=cls.row('projects',case['project_id'])
            if str(p['designer_id'])!=str(actor): raise PermissionError('Only the project owner can appeal.')
            if case['state']!='resolved' or case['decision'] not in ('hide','remove'): raise ValueError('Only resolved restrictions can be appealed.')
            if case['restriction_version']!=p['restriction_version'] or p['status'] not in ('hidden','removed'): raise ValueError('This restriction has been superseded or is no longer active.')
            if db.execute('SELECT 1 FROM project_appeals WHERE case_id=?',(pk,)).fetchone(): raise ValueError('This decision already has an appeal; only one appeal per decision is allowed.')
            aid=db.execute('INSERT INTO project_appeals(case_id,owner_id,explanation,evidence,created_at) VALUES(?,?,?,?,?)',(pk,str(actor),explanation,evidence,utc_now())).lastrowid
            cls.notify(db,case['assigned_to'],f'New appeal #{aid} for case #{pk}.')
            cls.audit(db,actor,'submit_appeal',f'Appeal #{aid}',explanation)
            return aid

    @classmethod
    def appealAction(cls,actor,pk,action,reason):
        db=get_db()
        with db:
            db.execute('BEGIN IMMEDIATE');appeal=cls.row('project_appeals',pk)
            if appeal['state'] in ('approved','rejected'): raise ValueError('Appeal is already decided.')
            if action=='claim':
                if appeal['reviewer_id'] and appeal['reviewer_id']!=str(actor): raise ValueError('Another manager is reviewing this appeal.')
                db.execute("UPDATE project_appeals SET reviewer_id=?,state='under_review' WHERE id=?",(str(actor),pk))
            else:
                if appeal['state']!='under_review' or appeal['reviewer_id']!=str(actor): raise ValueError('Claim the appeal before deciding.')
                case=cls.row('moderation_cases',appeal['case_id']);p=cls.row('projects',case['project_id'])
                if action=='approve':
                    if p['restriction_version']!=case['restriction_version'] or p['status'] not in ('hidden','removed'):
                        raise ValueError('A newer moderation decision exists, or the restriction is no longer active. This appeal cannot restore the project.')
                    db.execute('UPDATE projects SET status=?,featured=0,restriction_version=restriction_version+1 WHERE id=?',(case['previous_status'],p['id']))
                elif action!='reject': raise ValueError('Invalid appeal action.')
                db.execute('UPDATE project_appeals SET state=?,reason=?,decided_at=? WHERE id=?',('approved' if action=='approve' else 'rejected',reason,utc_now(),pk))
                cls.notify(db,appeal['owner_id'],f'Appeal #{pk}: {action}. {reason}')
            cls.audit(db,actor,'appeal_'+action,f'Appeal #{pk}',reason)

    @classmethod
    def saveSchedule(cls,actor,project,slot,start,end,reason,pk=None):
        db=get_db()
        with db:
            db.execute('BEGIN IMMEDIATE');p=cls.row('projects',project)
            if p['status']!='published': raise ValueError('Only published projects can be scheduled.')
            if pk:
                old=cls.row('feature_schedules',pk)
                if old['state']=='cancelled' or old['ends_at']<=utc_now(): raise ValueError('Cancelled/expired schedules cannot be edited.')
            clash=db.execute("SELECT id FROM feature_schedules WHERE state='scheduled' AND id!=? AND (slot=? OR project_id=?) AND starts_at<? AND ends_at>?",(pk or -1,slot,project,end,start)).fetchone()
            if clash: raise ValueError(f'Overlaps schedule #{clash["id"]}: choose another time, slot or project.')
            if pk:
                db.execute('UPDATE feature_schedules SET project_id=?,slot=?,starts_at=?,ends_at=?,reason=? WHERE id=?',(project,slot,start,end,reason,pk))
            else:
                pk=db.execute('INSERT INTO feature_schedules(project_id,slot,starts_at,ends_at,created_by,reason,created_at) VALUES(?,?,?,?,?,?,?)',(project,slot,start,end,str(actor),reason,utc_now())).lastrowid
            cls.audit(db,actor,'schedule_save',f'Schedule #{pk}',reason)
            return pk

    @classmethod
    def cancelSchedule(cls,actor,pk,reason):
        db=get_db()
        with db:
            db.execute('BEGIN IMMEDIATE');s=cls.row('feature_schedules',pk)
            if s['state']=='cancelled' or s['ends_at']<=utc_now(): raise ValueError('Schedule is already cancelled or expired.')
            db.execute("UPDATE feature_schedules SET state='cancelled',reason=? WHERE id=?",(reason,pk))
            cls.audit(db,actor,'schedule_cancel',f'Schedule #{pk}',reason)

    @staticmethod
    def activeFeatured(at=None):
        stamp=at or utc_now()
        return PlatformData.rows("SELECT p.*,c.name AS category,s.slot FROM feature_schedules s JOIN projects p ON p.id=s.project_id JOIN categories c ON c.id=p.category_id WHERE s.state='scheduled' AND s.starts_at<=? AND s.ends_at>? AND p.status='published' ORDER BY s.slot",(stamp,stamp))
