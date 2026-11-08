"""Control layer: role checks, validation and use-case orchestration."""
from datetime import datetime,date,timedelta,timezone
from zoneinfo import ZoneInfo
from entities import RegisteredUser
from .entities import PlatformData

LOCAL_TZ=ZoneInfo('Asia/Singapore')


class PlatformManagementControl:
    def __init__(self,user_id):
        self.user_id=str(user_id)

    def authorize(self):
        user=RegisteredUser.findById(self.user_id)
        if not user or user['status']!='Active' or user['role']!='Platform Management':
            raise PermissionError('An active Platform Management account is required.')
        return user

    def dashboard(self):
        self.authorize();return PlatformData.counts(),PlatformData.listReports('open')[:5]

    def searchCategories(self,query=''):
        self.authorize();return PlatformData.listCategories(query.strip())

    def getCategory(self,pk):
        self.authorize();return PlatformData.getCategory(pk)

    def saveCategory(self,name,description,pk=None):
        self.authorize();name=name.strip();description=description.strip()
        if not 1<=len(name)<=80 or len(description)>240:
            raise ValueError('Name must be 1–80 characters; description at most 240.')
        return PlatformData.saveCategory(self.user_id,name,description,pk)

    def removeCategory(self,pk):
        self.authorize();PlatformData.deleteCategory(self.user_id,pk)

    def categoryProjectCount(self,pk):
        self.authorize();return PlatformData.projectCount(pk)

    def curatePlatformContent(self,query='',status=''):
        self.authorize();return PlatformData.listProjects(query.strip(),status)

    def getProject(self,pk):
        self.authorize();return PlatformData.getProject(pk)

    def listContentReports(self,status=''):
        self.authorize();return PlatformData.listReports(status)

    def getContentReport(self,pk):
        self.authorize();return PlatformData.getReport(pk)

    def viewManagementActivity(self):
        self.authorize();return PlatformData.listAudit()

    @staticmethod
    def reason(value):
        value=value.strip()
        if not 5<=len(value)<=1000: raise ValueError('Enter a reason between 5 and 1,000 characters.')
        return value

    def moderateProject(self,pk,action,reason):
        self.authorize()
        raise ValueError('Use Moderation Cases for restrictions and Featured Schedule for homepage placement.')

    def reviewReportedContent(self, pk, action, reason, report_ids):
        self.authorize()
        from .workflow_entities import WorkflowEntity
        if action == 'claim':
            WorkflowEntity.start_report_review(self.user_id, pk)
            return
        case_id = WorkflowEntity.report_case_id(pk)
        if not case_id or action not in ('dismiss', 'hide', 'remove'):
            raise ValueError('Start the review before submitting a decision.')
        WorkflowEntity.caseAction(self.user_id, case_id, action, self.reason(reason), report_ids=report_ids)

    def reportFilters(self,args):
        self.authorize()
        today=datetime.now(LOCAL_TZ).date()
        if not args: args={'start':str(today-timedelta(days=29)),'end':str(today),'period':'daily'}
        try:
            start,end=date.fromisoformat(args.get('start','')),date.fromisoformat(args.get('end',''))
            category=int(args['category']) if args.get('category') else None
        except (ValueError,TypeError): raise ValueError('Enter valid dates and a category.')
        period=args.get('period','')
        if period not in ('daily','weekly','monthly') or end<start or (end-start).days>366 or end==date.max:
            raise ValueError('Choose daily/weekly/monthly and a range of 1–367 days.')
        if category is not None and not PlatformData.getCategory(category): raise ValueError('Category does not exist.')
        return dict(start=start,end=end,period=period,category=category)

    def generateBusinessReports(self,data):
        self.authorize()
        def bucket(day):
            return day-timedelta(days=day.weekday()) if data['period']=='weekly' else day.replace(day=1) if data['period']=='monthly' else day
        rows={};day=data['start']
        while day<=data['end']:
            key = bucket(day)
            row = rows.setdefault(key, dict(date=str(day), projects=0, views=0, shortlists=0, reports=0))
            row['end_date'] = str(day)
            day += timedelta(days=1)
        start=datetime.combine(data['start'],datetime.min.time(),LOCAL_TZ).astimezone(timezone.utc).isoformat(timespec='seconds')
        stop=datetime.combine(data['end']+timedelta(days=1),datetime.min.time(),LOCAL_TZ).astimezone(timezone.utc).isoformat(timespec='seconds')
        for stamp,field in PlatformData.reportEvents(start,stop,data['category']):
            key=bucket(datetime.fromisoformat(stamp).astimezone(LOCAL_TZ).date());rows[key][field]+=1
        result=list(rows.values());peak=max((r['views'] for r in result),default=0)
        for row in result: row['width']=round(100*row['views']/peak) if peak else 0
        totals={k:sum(r[k] for r in result) for k in ['projects','views','shortlists','reports']}
        return result,totals


class PublicProjectControl:
    @staticmethod
    def reportProject(project_id, customer_id, category, evidence):
        from .violation_categories import CATEGORIES
        from .db import get_db
        from .entities import utc_now
        if category not in CATEGORIES or len(evidence) > 1000:
            raise ValueError('Choose a listed violation category and limit details to 1000 characters.')
        db = get_db()
        with db:
            result = db.execute(
                "INSERT INTO content_reports(project_id, reporter_id, reason, evidence, created_at) "
                "SELECT id, ?, ?, ?, ? FROM projects WHERE id=? AND status='published'",
                (customer_id, category, evidence, utc_now(), project_id)
            )
            if not result.rowcount:
                raise ValueError('This project is no longer published.')

    @staticmethod
    def viewPublishedProjects():
        from .workflow_entities import WorkflowEntity
        active={p['id'] for p in WorkflowEntity.activeFeatured()}
        rows=PlatformData.listProjects(public=True)
        for row in rows: row['featured']=int(row['id'] in active)
        return sorted(rows,key=lambda r: -r['featured'])
