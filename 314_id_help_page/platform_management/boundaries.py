"""Boundary layer: HTTP input/output. Business operations go through controls."""
from urllib.parse import urlencode
from flask import Blueprint,request,g,render_template,redirect,url_for,flash,abort,current_app
from .access import manager_required, current_manager
from .violation_categories import CATEGORIES
from .controls import PlatformManagementControl,PublicProjectControl

bp=Blueprint('pm',__name__,template_folder='templates',static_folder='static',static_url_path='/static')


@bp.before_request
def protect_management_forms():
    if request.method in ('POST','PUT','PATCH','DELETE'):
        current_app.extensions['csrf'].protect()


@bp.errorhandler(PermissionError)
def denied(error):
    return render_template('pm/error.html',title='Access denied',message=str(error)),403


def control():
    return PlatformManagementControl(g.pm_user['user_id'])


def required(item):
    if item is None: abort(404)
    return item


def paginate(items):
    try: page=max(1,int(request.args.get('page',1)))
    except ValueError: page=1
    pages=max(1,(len(items)+14)//15);page=min(page,pages)
    def link(n):
        args=request.args.to_dict();args['page']=n;return '?'+urlencode(args)
    return dict(items=items[(page-1)*15:page*15],page=page,pages=pages,previous=link(page-1),next_page=link(page+1))


class PlatformManagementBoundary:
    @staticmethod
    @bp.get('/',endpoint='dashboard')
    @manager_required
    def dashboard():
        stats,recent=control().dashboard()
        return render_template('pm/dashboard.html',stats=stats,recent=recent)

    @staticmethod
    @bp.get('/categories',endpoint='categories')
    @manager_required
    def manageProjectCategories():
        q=request.args.get('q','')
        return render_template('pm/categories.html',q=q,**paginate(control().searchCategories(q)))

    @staticmethod
    @bp.route('/categories/new',methods=['GET','POST'],endpoint='category_edit')
    @bp.route('/categories/<int:pk>/edit',methods=['GET','POST'],endpoint='category_edit')
    @manager_required
    def saveProjectCategory(pk=None):
        c=control();item=required(c.getCategory(pk)) if pk else None
        if request.method=='POST':
            try:
                c.saveCategory(request.form.get('name',''),request.form.get('description',''),pk)
                flash('Category saved.');return redirect(url_for('pm.categories'))
            except ValueError as exc: flash(str(exc),'error')
        return render_template('pm/category_form.html',item=item)

    @staticmethod
    @bp.route('/categories/<int:pk>/remove',methods=['GET','POST'],endpoint='category_remove')
    @manager_required
    def removeProjectCategory(pk):
        c=control();item=required(c.getCategory(pk))
        if request.method=='POST':
            try:
                c.removeCategory(pk);flash('Category removed.');return redirect(url_for('pm.categories'))
            except ValueError as exc: flash(str(exc),'error')
        return render_template('pm/category_remove.html',item=item,count=c.categoryProjectCount(pk))

    @staticmethod
    @bp.get('/projects',endpoint='projects')
    @manager_required
    def curatePlatformContent():
        q=request.args.get('q','');status=request.args.get('status','')
        return render_template('pm/projects.html',q=q,status=status,**paginate(control().curatePlatformContent(q,status)))

    @staticmethod
    @bp.route('/projects/<int:pk>',methods=['GET','POST'],endpoint='project_action')
    @manager_required
    def moderateProject(pk):
        from .workflow_controls import FeatureScheduleControl
        c = FeatureScheduleControl(g.pm_user['user_id'])
        item = required(c.getProject(pk))
        if request.method == 'POST':
            try:
                data = request.form.to_dict()
                data['project_id'] = pk
                c.save(data)
            except ValueError as exc:
                flash(str(exc), 'error')
            else:
                flash(f"Featured placement scheduled for {item['title']}.")
                return redirect(url_for('pm.project_action', pk=pk))
        bookings = [r for r in c.schedules() if r['project_id'] == pk
                    and r['display_state'] in ('active', 'upcoming', 'suppressed')]
        return render_template('pm/project.html', item=item, bookings=bookings)

    @staticmethod
    @bp.get('/content-reports',endpoint='content_reports')
    @manager_required
    def listReportedContent():
        status=request.args.get('status','open')
        return render_template('pm/content_reports.html',status=status,**paginate(control().listContentReports(status)))

    @staticmethod
    @bp.route('/content-reports/<int:pk>',methods=['GET','POST'],endpoint='review_report')
    @manager_required
    def reviewReportedContent(pk):
        c=control();item=required(c.getContentReport(pk))
        if request.method=='POST':
            try:
                c.reviewReportedContent(pk, request.form.get('action', ''), request.form.get('reason', ''),
                                        request.form.get('report_ids', ''))
                if request.form.get('action') != 'claim':
                    flash('Decision recorded.')
                return redirect(url_for('pm.review_report', pk=pk))
            except ValueError as exc: flash(str(exc),'error')
        from .workflow_entities import WorkflowEntity
        from .workflow_controls import ModerationWorkflowControl
        case_id = WorkflowEntity.report_case_id(pk)
        case, reports = None, []
        if case_id:
            case, _, reports = ModerationWorkflowControl(g.pm_user['user_id']).case(case_id)
        return render_template('pm/review.html',item=required(c.getContentReport(pk)),case=case,reports=reports)

    @staticmethod
    @bp.get('/audit',endpoint='activity')
    @manager_required
    def viewManagementActivity():
        return render_template('pm/audit.html',**paginate(control().viewManagementActivity()))

    @staticmethod
    @bp.get('/reports',endpoint='reports')
    @manager_required
    def generateBusinessReports():
        c=control();categories=c.searchCategories()
        try:
            data=c.reportFilters(request.args);rows,totals=c.generateBusinessReports(data)
        except ValueError as exc:
            flash(str(exc),'error')
            return render_template('pm/reports.html',data=request.args,categories=categories,valid=False),400
        mode=request.args.get('export')
        if mode in ('csv','pdf'):
            from .exports import export_report
            return export_report(mode,data,rows,totals,categories)
        query=urlencode({k:str(v) if v is not None else '' for k,v in data.items()})
        return render_template('pm/reports.html',data=data,categories=categories,rows=rows,totals=totals,valid=True,export_query=query)

    @staticmethod
    @bp.get('/gallery',endpoint='gallery')
    def viewPublishedProjects():
        user = current_manager()
        return render_template('pm/gallery.html', can_report=bool(user and user['role'] == 'Customer'),
                               categories=CATEGORIES, **paginate(PublicProjectControl.viewPublishedProjects()))

    @staticmethod
    @bp.post('/gallery/<int:pk>/report', endpoint='submit_report')
    def submitReport(pk):
        user = current_manager()
        if not user:
            return redirect(url_for('auth.authenticateLogin'))
        if user['role'] != 'Customer':
            abort(403)
        try:
            PublicProjectControl.reportProject(pk, user['user_id'], request.form.get('category', ''),
                                               request.form.get('evidence', '').strip())
        except ValueError as exc:
            flash(str(exc), 'error')
        else:
            flash('Report submitted for moderation.')
        return redirect(url_for('pm.gallery', page=request.args.get('page', 1, type=int)))
