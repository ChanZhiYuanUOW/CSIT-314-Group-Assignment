from functools import wraps
from flask import request,session,g,redirect,url_for,render_template,flash,abort
from entities import RegisteredUser
from .boundaries import bp, paginate
from .access import manager_required
from .workflow_controls import ModerationWorkflowControl as M,DesignerAppealControl as D,FeatureScheduleControl as F
from .entities import PlatformData
from .db import get_db


def designer_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        user=RegisteredUser.findById(str(session.get('user_id','')))
        if not user or user['status']!='Active': return redirect(url_for('auth.authenticateLogin'))
        if user['role']!='Interior Designer': abort(403)
        g.pm_user=user
        return view(*args,**kwargs)
    return wrapped


class ModerationCaseBoundary:
    @staticmethod
    @bp.route('/cases',methods=['GET','POST'])
    @manager_required
    def cases():
        c=M(g.pm_user['user_id'])
        if request.method=='POST':
            flash(f'Grouped {c.sync()} new reports into cases.');return redirect(url_for('pm.cases'))
        rows = c.cases()
        categories = sorted({row['violation_category'] for row in rows})
        category = request.args.get('category', '')
        if category:
            rows = [row for row in rows if row['violation_category'] == category]
        return render_template('pm/cases.html', categories=categories, category=category, **paginate(rows))

    @staticmethod
    @bp.route('/cases/<int:pk>',methods=['GET','POST'])
    @manager_required
    def case_detail(pk):
        c=M(g.pm_user['user_id'])
        if request.method=='POST':
            try:
                c.act(pk,request.form.get('action',''),request.form.get('reason',''),request.form.get('priority','normal'))
                flash('Case updated.');return redirect(url_for('pm.case_detail',pk=pk))
            except ValueError as exc: flash(str(exc),'error')
        try: case,project,reports=c.case(pk)
        except ValueError: abort(404)
        return render_template('pm/case.html',case=case,project=project,reports=reports)


class ProjectAppealBoundary:
    @staticmethod
    @bp.get('/appeals')
    @manager_required
    def appeals():
        return render_template('pm/appeals.html',**paginate(M(g.pm_user['user_id']).appeals()))

    @staticmethod
    @bp.route('/appeals/<int:pk>',methods=['GET','POST'])
    @manager_required
    def appeal_detail(pk):
        c=M(g.pm_user['user_id'])
        if request.method=='POST':
            try:
                c.decide(pk,request.form.get('action',''),request.form.get('reason',''));flash('Appeal updated.')
                return redirect(url_for('pm.appeal_detail',pk=pk))
            except ValueError as exc: flash(str(exc),'error')
        try: appeal,(case,project,reports)=c.appeal(pk)
        except ValueError: abort(404)
        return render_template('pm/appeal.html',appeal=appeal,case=case,project=project,reports=reports)

    @staticmethod
    @bp.route('/designer/appeals',methods=['GET','POST'])
    @designer_required
    def designer_appeals():
        c=D(g.pm_user['user_id'])
        if request.method=='POST':
            try:
                pk=int(request.form.get('case_id',''))
                if request.form.get('action')=='respond': c.respond(pk,request.form.get('explanation',''))
                else: c.submit(pk,request.form.get('explanation',''),request.form.get('evidence',''))
                flash('Submitted.');return redirect(url_for('pm.designer_appeals'))
            except ValueError as exc: flash(str(exc),'error')
        return render_template('pm/designer_appeals.html',items=c.cases())


class FeatureScheduleBoundary:
    @staticmethod
    @bp.get('/schedules')
    @manager_required
    def schedules():
        return render_template('pm/schedules.html',**paginate(F(g.pm_user['user_id']).schedules()))

    @staticmethod
    @bp.route('/schedules/new',methods=['GET','POST'])
    @bp.route('/schedules/<int:pk>/edit',methods=['GET','POST'])
    @manager_required
    def schedule_edit(pk=None):
        c=F(g.pm_user['user_id']);item=None
        if pk:
            item=next((r for r in c.schedules() if r['id']==pk),None)
            if item is None: abort(404)
        if request.method=='POST':
            try:
                if request.form.get('action')=='cancel' and pk: c.cancel(pk,request.form.get('reason',''))
                else: c.save(request.form,pk)
                flash('Schedule updated.');return redirect(url_for('pm.schedules'))
            except ValueError as exc: flash(str(exc),'error')
        return render_template('pm/schedule_form.html',item=item,projects=c.curatePlatformContent(status='published'))


@bp.route('/notifications',methods=['GET','POST'])
def notifications():
    user=RegisteredUser.findById(str(session.get('user_id','')))
    if not user or user['status']!='Active': return redirect(url_for('auth.authenticateLogin'))
    g.pm_user=user;db=get_db()
    if request.method=='POST':
        with db: db.execute('UPDATE pm_notifications SET is_read=1 WHERE user_id=?',(user['user_id'],))
        return redirect(url_for('pm.notifications'))
    return render_template('pm/notifications.html',items=PlatformData.rows('SELECT * FROM pm_notifications WHERE user_id=? ORDER BY id DESC',(user['user_id'],)))
