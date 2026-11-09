"""Boundary layer: HTTP in/out for the customer features. Business rules live in controls.py."""
from functools import wraps
from urllib.parse import urlencode
from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for)
from werkzeug.routing import BuildError
from platform_management.access import current_manager
from .controls import (BrowseProjectsControl, CompareProjectsControl, ProjectDetailsControl, RecentlyViewedControl,
                       RecommendationControl, ReportContentControl, ShareProjectControl, PER_PAGE)

bp = Blueprint('customer', __name__, template_folder='templates', static_folder='static', static_url_path='/static')

browse_control = BrowseProjectsControl()
details_control = ProjectDetailsControl()
compare_control = CompareProjectsControl()
report_control = ReportContentControl()
recent_control = RecentlyViewedControl()
recommend_control = RecommendationControl()


def customer_required(view):
    """Customers only. The role is re-read from the shared CSV, never trusted from the cookie."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_manager()
        if user is None:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('auth.authenticateLogin'))
        if user['role'] != 'Customer':
            abort(403)
        return view(user, *args, **kwargs)
    return wrapped


@bp.before_request
def protect_forms():
    if request.method == 'POST':
        current_app.extensions['csrf'].protect()


@bp.context_processor
def helpers():
    def photo_url(filename):
        if not filename:
            return ''
        try:
            return url_for('designer.static', filename=f'uploads/{filename}')
        except BuildError:  # designer blueprint not registered
            return ''

    ids = session.get('compare_ids', [])
    return {'photo_url': photo_url, 'compare_ids': ids, 'compare_max': CompareProjectsControl.MAX_PROJECTS}


def safe_next(default):
    """Only follow same-site relative redirects (prevents open redirects through the `next` field)."""
    target = request.form.get('next') or request.args.get('next') or ''
    if target.startswith('/') and not target.startswith('//') and '\\' not in target:
        return target
    return default


class CustomerBoundary:
    """<<boundary>> :CustomerBoundary"""

    # ---- Browse Platform Projects + Search/Filter by Keyword & Category -------------------------------------
    @staticmethod
    @bp.get('/', endpoint='home')
    @customer_required
    def home(user):
        return redirect(url_for('customer.browsePlatformProjects'))

    @staticmethod
    @bp.get('/projects', endpoint='browsePlatformProjects')
    @customer_required
    def browsePlatformProjects(user):
        result = browse_control.searchFilterProjects(
            keyword=request.args.get('q', ''), category_ids=request.args.getlist('category'), styles=request.args.getlist('style'),
            sort=request.args.get('sort', 'newest'), page=request.args.get('page', 1))

        def page_url(n):
            args = [('q', result['keyword'])] if result['keyword'] else []
            args += [('category', c) for c in result['category_ids']]
            args += [('style', s) for s in result['styles']]
            if result['sort'] != 'newest':
                args.append(('sort', result['sort']))
            args.append(('page', n))
            return url_for('customer.browsePlatformProjects') + '?' + urlencode(args)

        # Show the recommended / recently viewed strips only on the plain landing view, so a search,
        # category filter or non-default sort puts the results at the top of the page.
        refined = result['filtered'] or 'sort' in request.args
        first_page_unfiltered = result['page'] == 1 and not refined
        return render_template(
            'customer/browse.html', result=result, refined=refined, categories=browse_control.listFilterCategories(),
            page_url=page_url, per_page=PER_PAGE,
            recent=recent_control.viewRecentlyViewedProjects(user['user_id'], 6) if first_page_unfiltered else [],
            recommended=recommend_control.viewPersonalisedRecommendations(user['user_id'], 4) if first_page_unfiltered else None)

    # ---- View Project Details ------------------------------------------------------------------------------
    @staticmethod
    @bp.get('/projects/<int:project_id>', endpoint='viewProjectDetails')
    @customer_required
    def viewProjectDetails(user, project_id):
        project = details_control.viewProjectDetails(user['user_id'], project_id)
        if project is None:
            flash('That project is no longer available.', 'warning')
            return redirect(url_for('customer.browsePlatformProjects'))
        return render_template('customer/project.html', project=project)

    # ---- Compare Projects Side-by-Side ---------------------------------------------------------------------
    @staticmethod
    @bp.post('/compare/add', endpoint='addToComparison')
    @customer_required
    def addToComparison(user):
        try:
            project_id = int(request.form.get('project_id', ''))
        except ValueError:
            abort(400)
        ids, ok, message = compare_control.addToComparison(session.get('compare_ids', []), project_id)
        session['compare_ids'] = ids
        flash(message, 'success' if ok else 'warning')
        return redirect(safe_next(url_for('customer.browsePlatformProjects')))

    @staticmethod
    @bp.post('/compare/remove', endpoint='removeFromComparison')
    @customer_required
    def removeFromComparison(user):
        try:
            project_id = int(request.form.get('project_id', ''))
        except ValueError:
            abort(400)
        session['compare_ids'] = compare_control.removeFromComparison(session.get('compare_ids', []), project_id)
        return redirect(safe_next(url_for('customer.compareProjects')))

    @staticmethod
    @bp.post('/compare/clear', endpoint='clearComparison')
    @customer_required
    def clearComparison(user):
        session['compare_ids'] = []
        return redirect(safe_next(url_for('customer.browsePlatformProjects')))

    @staticmethod
    @bp.get('/compare', endpoint='compareProjects')
    @customer_required
    def compareProjects(user):
        comparison = compare_control.compareProjects(session.get('compare_ids', []))
        # Drop projects that were hidden/removed since they were added.
        session['compare_ids'] = [p['id'] for p in comparison['projects']]
        return render_template('customer/compare.html', comparison=comparison,
                               min_projects=CompareProjectsControl.MIN_PROJECTS)

    # ---- Report Misleading Content -------------------------------------------------------------------------
    @staticmethod
    @bp.route('/projects/<int:project_id>/report', methods=['GET', 'POST'], endpoint='reportMisleadingContent')
    @customer_required
    def reportMisleadingContent(user, project_id):
        project = report_control.reportableProject(project_id)
        if project is None:
            flash('That project is no longer available.', 'warning')
            return redirect(url_for('customer.browsePlatformProjects'))
        form = {'reason': ReportContentControl.DEFAULT_REASON, 'details': ''}
        if request.method == 'POST':
            form = {'reason': request.form.get('reason', ''), 'details': request.form.get('details', '')}
            ok, message = report_control.reportMisleadingContent(user['user_id'], project_id, form['reason'], form['details'])
            if ok:
                flash(message, 'success')
                return redirect(url_for('customer.viewProjectDetails', project_id=project_id))
            flash(message, 'danger')
        return render_template('customer/report.html', project=project, form=form, reasons=ReportContentControl.REASONS,
                               min_detail=ReportContentControl.MIN_DETAIL, max_detail=ReportContentControl.MAX_DETAIL)

    # ---- Share Project Link --------------------------------------------------------------------------------
    @staticmethod
    @bp.get('/projects/<int:project_id>/share', endpoint='shareProjectLink')
    @customer_required
    def shareProjectLink(user, project_id):
        project = details_control.viewPublicProject(project_id)
        token = ShareProjectControl(current_app.secret_key).createShareToken(project_id) if project else None
        if not token:
            flash('Only published projects can be shared.', 'warning')
            return redirect(url_for('customer.browsePlatformProjects'))
        link = url_for('customer.viewSharedProject', token=token, _external=True)
        return render_template('customer/share.html', project=project, link=link)

    @staticmethod
    @bp.get('/shared/<token>', endpoint='viewSharedProject')
    def viewSharedProject(token):
        """Public, read-only landing page for a shared link (no login needed, nothing is recorded)."""
        project_id = ShareProjectControl(current_app.secret_key).resolveShareToken(token)
        project = details_control.viewPublicProject(project_id) if project_id else None
        if project is None:
            abort(404)
        return render_template('customer/shared.html', project=project)

    # ---- View Recently Viewed Projects ---------------------------------------------------------------------
    @staticmethod
    @bp.get('/recent', endpoint='viewRecentlyViewedProjects')
    @customer_required
    def viewRecentlyViewedProjects(user):
        return render_template('customer/recent.html', projects=recent_control.viewRecentlyViewedProjects(user['user_id']))

    @staticmethod
    @bp.post('/recent/remove', endpoint='removeRecentlyViewed')
    @customer_required
    def removeRecentlyViewed(user):
        try:
            project_id = int(request.form.get('project_id', ''))
        except ValueError:
            abort(400)
        recent_control.removeFromHistory(user['user_id'], project_id)
        return redirect(url_for('customer.viewRecentlyViewedProjects'))

    @staticmethod
    @bp.post('/recent/clear', endpoint='clearRecentlyViewed')
    @customer_required
    def clearRecentlyViewed(user):
        recent_control.clearHistory(user['user_id'])
        flash('Your viewing history has been cleared.', 'info')
        return redirect(url_for('customer.viewRecentlyViewedProjects'))

    # ---- View Personalised Recommendations -----------------------------------------------------------------
    @staticmethod
    @bp.get('/recommended', endpoint='viewPersonalisedRecommendations')
    @customer_required
    def viewPersonalisedRecommendations(user):
        return render_template('customer/recommended.html',
                               rec=recommend_control.viewPersonalisedRecommendations(user['user_id'], 12))
