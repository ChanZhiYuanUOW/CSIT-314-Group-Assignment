"""Boundary layer: HTTP in/out for the customer features. Business rules live in controls.py."""
from functools import wraps
from urllib.parse import urlencode
from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for)
from werkzeug.routing import BuildError
from platform_management.access import current_manager
from platform_management.project_cost import parse_amount
from service_controls import ServiceRequestControl
from service_entities import (
    ServiceRequest,
    Quotation,
    Consultation,
    RenovationProgress
)

from .controls import (
    BrowseProjectsControl,
    CompareProjectsControl,
    ProjectDetailsControl,
    RecentlyViewedControl,
    RecommendationControl,
    ReportContentControl,
    ShareProjectControl,
    ManageFavouritesControl,
    CustomerReviewControl,
    PER_PAGE
)


bp = Blueprint('customer', __name__, template_folder='templates', static_folder='static', static_url_path='/static')

browse_control = BrowseProjectsControl()
details_control = ProjectDetailsControl()
compare_control = CompareProjectsControl()
report_control = ReportContentControl()
recent_control = RecentlyViewedControl()
recommend_control = RecommendationControl()
favourites_control = ManageFavouritesControl()
reviews_control = CustomerReviewControl()
service_request_control = ServiceRequestControl()


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
        try:
            minimum = parse_amount(request.args.get('min_price'))
            maximum = parse_amount(request.args.get('max_price'))
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError('Minimum price must be less than or equal to maximum price.')
        except ValueError as exc:
            flash(str(exc), 'warning')
            return redirect(url_for('customer.browsePlatformProjects', q=request.args.get('q', ''),
                                    style=request.args.getlist('style'), sort=request.args.get('sort', 'newest')))
        result = browse_control.searchFilterProjects(
            minimum=minimum, maximum=maximum,
            keyword=request.args.get('q', ''), category_ids=request.args.getlist('category'), styles=request.args.getlist('style'),
            sort=request.args.get('sort', 'newest'), page=request.args.get('page', 1))

        def page_url(n):
            args = [('q', result['keyword'])] if result['keyword'] else []
            args += [('category', c) for c in result['category_ids']]
            args += [('style', s) for s in result['styles']]
            if result['sort'] != 'newest':
                args.append(('sort', result['sort']))
            for key, amount in [('min_price', minimum), ('max_price', maximum)]:
                if amount is not None:
                    args.append((key, amount))
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
            recommended=recommend_control.viewPersonalisedRecommendations(user['user_id'], 4) if first_page_unfiltered else None,
            favourite_groups=favourites_control.viewGroups(user['user_id']))

    @staticmethod
    @bp.get('/public/projects/<int:project_id>', endpoint='publicProject')
    def public_project(project_id):
        project = details_control.viewPublicProject(project_id)
        if project is None:
            abort(404)
        return render_template('customer/shared.html', project=project)

    # ---- View Project Details ------------------------------------------------------------------------------
    @staticmethod
    @bp.get('/projects/<int:project_id>', endpoint='viewProjectDetails')
    @customer_required
    def viewProjectDetails(user, project_id):
        project = details_control.viewProjectDetails(
            user['user_id'],
            project_id
        )

        if project is None:
            flash('That project is no longer available.', 'warning')
            return redirect(url_for('customer.browsePlatformProjects'))

        return render_template(
            'customer/project.html',
            project=project,
            project_id=project_id,
            favourite_groups=favourites_control.viewGroups(user['user_id'])
        )
    
    # ---- Submit Service Request -------------------------------------------------------------------------
    @staticmethod
    @bp.get('/projects/<int:project_id>/request-service', endpoint='submitServiceRequest')
    @customer_required
    def showServiceRequestForm(user, project_id):
        project = details_control.viewProjectDetails(
            user['user_id'],
            project_id
        )

        if project is None:
            flash('That project is no longer available.', 'warning')
            return redirect(url_for('customer.browsePlatformProjects'))

        return render_template(
            'customer/service_request.html',
            project=project,
            project_id=project_id
        )

    @staticmethod
    @bp.post('/projects/<int:project_id>/request-service', endpoint='createServiceRequest')
    @customer_required
    def createServiceRequest(user, project_id):
        project = details_control.viewProjectDetails(
            user['user_id'],
            project_id
        )

        if project is None:
            flash('That project is no longer available.', 'warning')
            return redirect(url_for('customer.browsePlatformProjects'))

        renovation_brief = request.form.get('renovation_brief', '')
        budget = request.form.get('budget', '')
        request_type = request.form.get('request_type', '')
        proposed_time = request.form.get('proposed_time', '')

        success, message = service_request_control.submitServiceRequest(
            customer_user_id=user['user_id'],
            designer_user_id=project['designer_id'],
            renovation_brief=renovation_brief,
            budget=budget,
            request_type=request_type,
            proposed_time=proposed_time
        )

        if success:
            flash(message, 'success')
            return redirect(url_for(
                'customer.viewProjectDetails',
                project_id=project_id
            ))

        flash(message, 'danger')
        return render_template(
            'customer/service_request.html',
            project=project,
            project_id=project_id
        )

    # ---- Customer Service Request Tracking ---------------------------------------------------------------
    @staticmethod
    @bp.get('/service-requests', endpoint='myServiceRequests')
    @customer_required
    def myServiceRequests(user):
        service_requests = ServiceRequest.getRequestsForCustomer(
            user['user_id']
        )
        for item in service_requests:
            item['quotation'] = Quotation.findByRequest(
                item['request_id']
            )

            item['consultation'] = Consultation.findByRequest(
                item['request_id']
            )

            item['progress_history'] = RenovationProgress.getHistory(
                item['request_id']
            )

            item['latest_progress'] = (
                item['progress_history'][0]
                if item['progress_history']
                else None
            )

        return render_template(
            'customer/service_requests.html',
            service_requests=service_requests,
            comparison_ids=session.get('quotation_compare_ids', [])
        )

    @staticmethod
    @bp.post('/service-requests/<request_id>/consultation-response',
             endpoint='respondToConsultation')
    @customer_required
    def respondToConsultation(user, request_id):
        success, message = service_request_control.respondToProposedConsultation(
            actor_role=user['role'],
            customer_user_id=user['user_id'],
            request_id=request_id,
            decision=request.form.get('decision', '')
        )

        flash(message, 'success' if success else 'danger')

        return redirect(url_for('customer.myServiceRequests'))
    
    # ---- Add Quotation to Comparison -----------------------------------------
    @staticmethod
    @bp.post('/service-requests/<request_id>/compare',
             endpoint='addQuotationToCompare')
    @customer_required
    def addQuotationToCompare(user, request_id):
        customer_requests = ServiceRequest.getRequestsForCustomer(
            user['user_id']
        )

        selected_request = next(
            (
                item for item in customer_requests
                if str(item['request_id']) == str(request_id)
            ),
            None
        )

        if not selected_request:
            flash('Service request not found.', 'danger')
            return redirect(url_for('customer.myServiceRequests'))

        quotation = Quotation.findByRequest(request_id)

        if not quotation:
            flash('This request does not have a quotation yet.', 'danger')
            return redirect(url_for('customer.myServiceRequests'))

        comparison_ids = session.get('quotation_compare_ids', [])

        if str(request_id) in comparison_ids:
            flash('This quotation is already in your comparison list.', 'info')
        else:
            comparison_ids.append(str(request_id))
            session['quotation_compare_ids'] = comparison_ids
            session.modified = True
            flash('Quotation added to comparison list.', 'success')

        return redirect(url_for('customer.myServiceRequests'))

    # ---- Compare Selected Quotations -----------------------------------------
    @staticmethod
    @bp.get('/quotation-comparison', endpoint='quotationComparison')
    @customer_required
    def quotationComparison(user):
        customer_requests = ServiceRequest.getRequestsForCustomer(
            user['user_id']
        )

        comparison_ids = session.get('quotation_compare_ids', [])
        comparison_requests = []

        for request_id in comparison_ids:
            for item in customer_requests:
                if str(item['request_id']) == str(request_id):
                    quotation = Quotation.findByRequest(request_id)

                    if quotation:
                        item['quotation'] = quotation
                        comparison_requests.append(item)

                    break

        return render_template(
            'customer/quotation_comparison.html',
            comparison_requests=comparison_requests
        )

    # ---- Remove Quotation from Comparison ------------------------------------
    @staticmethod
    @bp.post('/quotation-comparison/<request_id>/remove',
             endpoint='removeQuotationFromCompare')
    @customer_required
    def removeQuotationFromCompare(user, request_id):
        comparison_ids = session.get('quotation_compare_ids', [])

        comparison_ids = [
            selected_id for selected_id in comparison_ids
            if str(selected_id) != str(request_id)
        ]

        session['quotation_compare_ids'] = comparison_ids
        session.modified = True

        flash('Quotation removed from comparison.', 'success')

        return redirect(url_for('customer.quotationComparison'))

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



    # ---- Manage Favourite Groups and Projects --------------------------------

    @staticmethod
    @bp.get('/favourites', endpoint='viewFavourites')
    @customer_required
    def viewFavourites(user):
        group_id = request.args.get('group_id', '')
        keyword = request.args.get('q', '')

        groups = favourites_control.viewGroups(user['user_id'])
        projects = favourites_control.searchFavourites(
            user['user_id'], keyword, group_id
        )

        return render_template(
            'customer/favourites.html',
            groups=groups,
            projects=projects,
            selected_group=group_id,
            keyword=keyword
        )

    @staticmethod
    @bp.post('/favourites/groups/create', endpoint='createFavouriteGroup')
    @customer_required
    def createFavouriteGroup(user):
        ok, message = favourites_control.createGroup(
            user['user_id'], request.form.get('name', '')
        )
        flash(message, 'success' if ok else 'warning')
        return redirect(url_for('customer.viewFavourites'))

    @staticmethod
    @bp.post('/favourites/groups/<int:group_id>/delete',
             endpoint='deleteFavouriteGroup')
    @customer_required
    def deleteFavouriteGroup(user, group_id):
        ok, message = favourites_control.deleteGroup(
            user['user_id'], group_id
        )
        flash(message, 'success' if ok else 'warning')
        return redirect(url_for('customer.viewFavourites'))

    @staticmethod
    @bp.post('/favourites/add', endpoint='addFavourite')
    @customer_required
    def addFavourite(user):
        ok, message = favourites_control.addFavourite(
            user['user_id'],
            request.form.get('group_id'),
            request.form.get('project_id')
        )
        flash(message, 'success' if ok else 'warning')
        return redirect(url_for('customer.viewFavourites'))

    @staticmethod
    @bp.post('/favourites/remove', endpoint='removeFavourite')
    @customer_required
    def removeFavourite(user):
        ok, message = favourites_control.removeFavourite(
            user['user_id'],
            request.form.get('group_id'),
            request.form.get('project_id')
        )
        flash(message, 'success' if ok else 'warning')
        return redirect(url_for('customer.viewFavourites'))

    # ---- Customer Reviews ----------------------------------------------------

    @staticmethod
    @bp.get('/reviews', endpoint='viewCustomerReviews')
    @customer_required
    def viewCustomerReviews(user):
        renovations = reviews_control.viewCustomerRenovations(
            user['user_id']
        )

        return render_template(
            'customer/reviews.html',
            renovations=renovations
        )

    @staticmethod
    @bp.post(
        '/reviews/<renovation_id>',
        endpoint='submitCustomerReview'
    )
    @customer_required
    def submitCustomerReview(user, renovation_id):
        ok, message = reviews_control.submitReview(
            customer_id=user['user_id'],
            customer_name=(
                user.get('full_name')
                or user.get('name')
                or 'Customer'
            ),
            renovation_id=renovation_id,
            rating=request.form.get('rating'),
            review_text=request.form.get('review', '')
        )

        flash(message, 'success' if ok else 'danger')

        return redirect(url_for('customer.viewCustomerReviews'))
