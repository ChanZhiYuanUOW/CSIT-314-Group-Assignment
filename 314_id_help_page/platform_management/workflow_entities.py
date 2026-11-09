"""Persistence and atomic state transitions for cases, appeals and schedules."""
from .db import get_db
from .violation_categories import report_category
from .entities import PlatformData,utc_now


class WorkflowEntity:
    @staticmethod
    def row(table, pk):
        if table not in ('moderation_cases','project_appeals','feature_schedules','projects'): raise ValueError('Invalid entity.')
        row=get_db().first(table, id=pk)
        if not row: raise ValueError('Record does not exist.')
        return dict(row)

    @staticmethod
    def notify(db,user_id,message):
        db.add('pm_notifications', user_id=str(user_id), message=message, created_at=utc_now())

    @staticmethod
    def audit(db,actor,action,target,reason):
        PlatformData.recordAudit(db,actor,action,target,reason)

    @classmethod
    def syncReports(cls,actor):
        db=get_db()
        with db:
            return cls._group_reports(db, actor)

    @classmethod
    def _group_reports(cls, db, actor, project_id=None, category_filter=None):
        count = 0
        linked = {r['report_id'] for r in db.all('case_reports')}
        reports = [r for r in db.all('content_reports', status='open') if r['id'] not in linked
                   and (project_id is None or r['project_id'] == project_id)]
        for r in reports:
            category = report_category(r['reason'])
            if category_filter and category != category_filter:
                continue
            case = next((c for c in db.all('moderation_cases', project_id=r['project_id'], violation_category=category)
                         if c['state'] != 'resolved'), None)
            cid=case['id'] if case else db.add('moderation_cases', project_id=r['project_id'], violation_category=category, created_at=utc_now())['id']
            db.add('case_reports', report_id=r['id'], case_id=cid);count+=1
            n=len(db.all('case_reports',case_id=cid))
            case = db.first('moderation_cases', id=cid)
            if n >= 3 and case['priority'] == 'normal':
                db.update('moderation_cases', case, priority='high')
        if count: cls.audit(db,actor,'group_reports','Moderation cases',f'Grouped {count} unassigned reports.')
        return count

    @classmethod
    def start_report_review(cls, actor, report_id):
        db = get_db()
        with db:
            report = db.first('content_reports', id=report_id)
            if not report or report['status'] != 'open':
                raise ValueError('This report is no longer open.')
            cls._group_reports(db, actor, report['project_id'], report_category(report['reason']))
            case_id = cls.report_case_id(report_id)
            case = cls.row('moderation_cases', case_id)
            if case['assigned_to'] and case['assigned_to'] != str(actor):
                raise ValueError('Another manager is reviewing this case.')
            if case['state'] == 'open':
                db.update('moderation_cases', db.first('moderation_cases', id=case_id), assigned_to=str(actor), state='under_review')
                cls.audit(db, actor, 'case_claim', f'Case #{case_id}', 'Started review from reported content.')

    @staticmethod
    def report_case_id(report_id):
        row = get_db().first('case_reports', report_id=report_id)
        return row['case_id'] if row else None


    @classmethod
    def caseAction(cls,actor,pk,action,reason,priority='normal',report_ids=None):
        db=get_db()
        with db:
            case=cls.row('moderation_cases',pk)
            if report_ids is not None:
                members = sorted(r['report_id'] for r in db.all('case_reports', case_id=pk))
                if report_ids != ','.join(str(member) for member in members):
                    raise ValueError('The reports in this case changed. Review the updated evidence before deciding.')
            if case['state']=='resolved': raise ValueError('This case is already resolved.')
            if action=='claim':
                if case['state']=='awaiting_response': raise ValueError('Wait for the designer response before continuing review.')
                if case['assigned_to'] and case['assigned_to']!=str(actor): raise ValueError('Another manager owns this case.')
                db.update('moderation_cases', db.first('moderation_cases', id=pk), assigned_to=str(actor), state='under_review')
            else:
                if case['assigned_to']!=str(actor): raise ValueError('Claim the case before making changes.')
                if action=='priority': db.update('moderation_cases', db.first('moderation_cases', id=pk), priority=priority)
                elif action=='request':
                    if case['state']!='under_review': raise ValueError('Case must be under review.')
                    db.update('moderation_cases', db.first('moderation_cases', id=pk), state='awaiting_response', request_note=reason, response_note='')
                    p=cls.row('projects',case['project_id']);cls.notify(db,p['designer_id'],f'Case #{pk}: clarification requested — {reason}')
                elif action in ('dismiss','hide','remove'):
                    if case['state']!='under_review': raise ValueError('Case must be under review; wait for the designer response if requested.')
                    p=cls.row('projects',case['project_id']);version=p['restriction_version']
                    if action in ('hide','remove'):
                        if p['status']=='removed': raise ValueError('Project already removed; dismiss this case if no further action is needed.')
                        version+=1
                        db.update('projects', db.first('projects', id=p['id']), status='hidden' if action == 'hide' else 'removed', featured=0, restriction_version=version)
                    db.update('moderation_cases', db.first('moderation_cases', id=pk), state='resolved', decision=action, reason=reason, previous_status=p['status'], restriction_version=version, resolved_at=utc_now())
                    for link in db.all('case_reports', case_id=pk):
                        report = db.first('content_reports', id=link['report_id'])
                        db.update('content_reports', report, status='dismissed' if action=='dismiss' else 'actioned',
                                  reviewed_by=str(actor), reviewed_at=utc_now(), decision_note=reason)
                    cls.notify(db,p['designer_id'],f'Case #{pk} resolved: {action}. Reason: {reason}')
                else: raise ValueError('Invalid case action.')
            cls.audit(db,actor,'case_'+action,f'Case #{pk}',reason)

    @classmethod
    def ownerResponse(cls,actor,pk,response):
        db=get_db()
        with db:
            case=cls.row('moderation_cases',pk);p=cls.row('projects',case['project_id'])
            if str(p['designer_id'])!=str(actor): raise PermissionError('Only the project owner can respond.')
            if case['state']!='awaiting_response': raise ValueError('No clarification response is pending.')
            db.update('moderation_cases', db.first('moderation_cases', id=pk), response_note=response, state='under_review')
            cls.notify(db,case['assigned_to'],f'Designer responded to case #{pk}.')
            cls.audit(db,actor,'case_response',f'Case #{pk}',response)

    @classmethod
    def submitAppeal(cls,actor,pk,explanation,evidence):
        db=get_db()
        with db:
            case=cls.row('moderation_cases',pk);p=cls.row('projects',case['project_id'])
            if str(p['designer_id'])!=str(actor): raise PermissionError('Only the project owner can appeal.')
            if case['state']!='resolved' or case['decision'] not in ('hide','remove'): raise ValueError('Only resolved restrictions can be appealed.')
            if case['restriction_version']!=p['restriction_version'] or p['status'] not in ('hidden','removed'): raise ValueError('This restriction has been superseded or is no longer active.')
            if db.first('project_appeals', case_id=pk): raise ValueError('This decision already has an appeal.')
            aid=db.add('project_appeals', case_id=pk, owner_id=str(actor), explanation=explanation, evidence=evidence, created_at=utc_now())['id']
            cls.notify(db,case['assigned_to'],f'New appeal #{aid} for case #{pk}.')
            cls.audit(db,actor,'submit_appeal',f'Appeal #{aid}',explanation)
            return aid

    @classmethod
    def appealAction(cls,actor,pk,action,reason):
        db=get_db()
        with db:
            appeal=cls.row('project_appeals',pk)
            if appeal['state'] in ('approved','rejected'): raise ValueError('Appeal is already decided.')
            if action=='claim':
                if appeal['reviewer_id'] and appeal['reviewer_id']!=str(actor): raise ValueError('Another manager is reviewing this appeal.')
                db.update('project_appeals', db.first('project_appeals', id=pk), reviewer_id=str(actor), state='under_review')
            else:
                if appeal['state']!='under_review' or appeal['reviewer_id']!=str(actor): raise ValueError('Claim the appeal before deciding.')
                case=cls.row('moderation_cases',appeal['case_id']);p=cls.row('projects',case['project_id'])
                if action=='approve':
                    if p['restriction_version']!=case['restriction_version'] or p['status'] not in ('hidden','removed'):
                        raise ValueError('A newer moderation decision exists, or the restriction is no longer active. This appeal cannot restore the project.')
                    db.update('projects', db.first('projects', id=p['id']), status=case['previous_status'], featured=0, restriction_version=p['restriction_version']+1)
                elif action!='reject': raise ValueError('Invalid appeal action.')
                db.update('project_appeals', db.first('project_appeals', id=pk), state='approved' if action == 'approve' else 'rejected', reason=reason, decided_at=utc_now())
                cls.notify(db,appeal['owner_id'],f'Appeal #{pk}: {action}. {reason}')
            cls.audit(db,actor,'appeal_'+action,f'Appeal #{pk}',reason)

    @classmethod
    def saveSchedule(cls,actor,project,slot,start,end,reason,pk=None):
        db=get_db()
        with db:
            p=cls.row('projects',project)
            if p['status']!='published': raise ValueError('Only published projects can be scheduled.')
            if pk:
                old=cls.row('feature_schedules',pk)
                if old['state']=='cancelled' or old['ends_at']<=utc_now(): raise ValueError('Cancelled/expired schedules cannot be edited.')
            clash = next((s for s in db.all('feature_schedules', state='scheduled')
                          if s['id'] != pk and (s['slot']==slot or s['project_id']==project)
                          and s['starts_at'] < end and s['ends_at'] > start), None)
            if clash: raise ValueError(f'Overlaps schedule #{clash["id"]}: choose another time, slot or project.')
            if pk:
                db.update('feature_schedules', db.first('feature_schedules', id=pk), project_id=project, slot=slot, starts_at=start, ends_at=end, reason=reason)
            else:
                pk=db.add('feature_schedules', project_id=project, slot=slot, starts_at=start, ends_at=end, created_by=str(actor), reason=reason, created_at=utc_now())['id']
            cls.audit(db,actor,'schedule_save',f'Schedule #{pk}',reason)
            return pk

    @classmethod
    def cancelSchedule(cls,actor,pk,reason):
        db=get_db()
        with db:
            s=cls.row('feature_schedules',pk)
            if s['state']=='cancelled' or s['ends_at']<=utc_now(): raise ValueError('Schedule is already cancelled or expired.')
            db.update('feature_schedules', db.first('feature_schedules', id=pk), state='cancelled', reason=reason)
            cls.audit(db,actor,'schedule_cancel',f'Schedule #{pk}',reason)

    @staticmethod
    def activeFeatured(at=None):
        stamp=at or utc_now()
        projects = {p['id']:p for p in PlatformData.listProjects(public=True)}
        rows = [dict(projects[s['project_id']], slot=s['slot']) for s in get_db().all('feature_schedules', state='scheduled')
                if s['project_id'] in projects and s['starts_at'] <= stamp < s['ends_at']]
        return sorted(rows, key=lambda r:r['slot'])
