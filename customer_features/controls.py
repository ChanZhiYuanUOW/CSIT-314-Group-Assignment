"""Control layer: business rules for the customer use cases. No Flask request/session objects here
(the boundary passes plain values in), so every rule can be unit-tested without a web client."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from itsdangerous import BadSignature, URLSafeSerializer
from platform_management.violation_categories import CATEGORIES

from .entities import (
    EngagementLog,
    ProjectCatalogue,
    ProjectReport,
    RecentlyViewed,
    FavouriteGroups,
    CustomerReviews,
    SORTS,
    utc_now
)

PER_PAGE = 12


def _int_list(values):
    out = []
    for v in values or []:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in out:
            out.append(n)
    return out


def _style_list(values):
    out = []
    for v in values or []:
        v = str(v).strip()[:40]
        if v and v.casefold() not in [o.casefold() for o in out]:
            out.append(v)
    return out


class BrowseProjectsControl:
    """<<control>> :BrowseProjectsControl - Browse Platform Projects + Search/Filter by Keyword & Category."""

    def searchFilterProjects(self, keyword='', category_ids=(), sort='newest', page=1, styles=()):
        keyword = (keyword or '').strip()[:200]
        category_ids = _int_list(category_ids)
        styles = _style_list(styles)
        sort = sort if sort in SORTS else 'newest'
        try:
            page = max(1, int(page))
        except (TypeError, ValueError):
            page = 1
        projects, total = ProjectCatalogue.search(keyword, category_ids, sort, page, PER_PAGE, styles)
        pages = max(1, -(-total // PER_PAGE))
        if page > pages:  # a stale page number after filtering: show the last page instead of an empty list
            page = pages
            projects, total = ProjectCatalogue.search(keyword, category_ids, sort, page, PER_PAGE, styles)
        return {'projects': projects, 'total': total, 'page': page, 'pages': pages, 'keyword': keyword,
                'category_ids': category_ids, 'styles': styles, 'sort': sort,
                'filtered': bool(keyword or category_ids or styles)}

    def listFilterCategories(self):
        return ProjectCatalogue.categories()


class ProjectDetailsControl:
    """<<control>> :ProjectDetailsControl - View Project Details (also feeds history and analytics)."""

    def viewProjectDetails(self, customer_id, project_id):
        detail = ProjectCatalogue.published_detail(project_id)
        if detail is None:
            return None
        EngagementLog.record_view(customer_id, project_id)
        RecentlyViewed.record(customer_id, project_id)
        return detail

    def viewPublicProject(self, project_id):
        """Read-only detail for a shared link: nothing is recorded because the viewer may be a guest."""
        return ProjectCatalogue.published_detail(project_id)


class CompareProjectsControl:
    """<<control>> :CompareProjectsControl - Compare Projects Side-by-Side (selection lives in the session)."""
    MAX_PROJECTS = 4
    MIN_PROJECTS = 2

    def addToComparison(self, ids, project_id):
        ids = _int_list(ids)
        if not ProjectCatalogue.published_cards([project_id]):
            return ids, False, 'That project is no longer available.'
        if project_id in ids:
            return ids, True, 'Already in your comparison.'
        if len(ids) >= self.MAX_PROJECTS:
            return ids, False, f'You can compare up to {self.MAX_PROJECTS} projects. Remove one first.'
        return ids + [project_id], True, 'Added to comparison.'

    def removeFromComparison(self, ids, project_id):
        return [i for i in _int_list(ids) if i != project_id]

    def compareProjects(self, ids):
        """Returns the projects (still published, in selection order) and a row-per-attribute table."""
        projects = [d for d in (ProjectCatalogue.published_detail(i) for i in _int_list(ids)) if d]
        if not projects:
            return {'projects': [], 'rows': []}

        def text(value, empty='—'):
            return value if value else empty

        spec = [
            ('Category', lambda p: p['category']),
            ('Designer', lambda p: p['designer']),
            ('Company', lambda p: text(p['company']['name'] if p['company'] else '')),
            ('Location', lambda p: text(p['company']['location'] if p['company'] else '')),
            ('Style tags', lambda p: text(', '.join(p['tag_list']))),
            ('Photos', lambda p: str(p['photo_count'])),
            ("Designer's customer reviews", lambda p: str(p['review_count'])),
            ('Platform views', lambda p: str(p['views'])),
            ('Listed on', lambda p: str(p['created_at'])[:10]),
        ]
        rows = []
        for label, getter in spec:
            values = [getter(p) for p in projects]
            rows.append({'label': label, 'values': values, 'differs': len(set(values)) > 1})
        return {'projects': projects, 'rows': rows}


class ReportContentControl:
    """<<control>> :ReportContentControl - Report Misleading Content into the shared moderation queue."""
    REASONS = CATEGORIES
    DEFAULT_REASON = 'Misleading description'
    MIN_DETAIL, MAX_DETAIL = 10, 1000
    DAILY_LIMIT = 5

    def reportableProject(self, project_id):
        return ProjectCatalogue.published_detail(project_id)

    def reportMisleadingContent(self, customer_id, project_id, reason, details):
        """Returns (ok, message). Platform Management picks the report up from content_reports."""
        reason = (reason or '').strip()
        details = (details or '').strip()
        if reason not in self.REASONS:
            return False, 'Please choose a reason from the list.'
        if len(details) < self.MIN_DETAIL:
            return False, f'Please describe what is misleading (at least {self.MIN_DETAIL} characters).'
        if len(details) > self.MAX_DETAIL:
            return False, f'Details are too long (maximum {self.MAX_DETAIL} characters).'
        if ProjectCatalogue.published_cards([project_id]) == []:
            return False, 'This project is no longer available, so it cannot be reported.'
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec='seconds')
        if ProjectReport.count_since(customer_id, since) >= self.DAILY_LIMIT:
            return False, f'You have reached the limit of {self.DAILY_LIMIT} reports in 24 hours. Please try again later.'
        if ProjectReport.has_open(customer_id, project_id, reason):
            return False, 'You already have an open report for this project with the same reason. Our team is reviewing it.'
        ProjectReport.create(customer_id, project_id, reason, details)
        return True, 'Thank you. Your report has been sent to Platform Management for review.'


class ShareProjectControl:
    """<<control>> :ShareProjectControl - Share Project Link using signed, stateless tokens."""
    SALT = 'customer-project-share'

    def __init__(self, secret_key):
        self._serializer = URLSafeSerializer(secret_key, salt=self.SALT)

    def createShareToken(self, project_id):
        if not ProjectCatalogue.published_cards([project_id]):
            return None  # only published projects can be shared
        return self._serializer.dumps({'p': int(project_id)})

    def resolveShareToken(self, token):
        try:
            data = self._serializer.loads(token)
            return int(data['p'])
        except (BadSignature, KeyError, TypeError, ValueError):
            return None


class RecentlyViewedControl:
    """<<control>> :RecentlyViewedControl - View Recently Viewed Projects."""

    def viewRecentlyViewedProjects(self, customer_id, limit=RecentlyViewed.LIMIT):
        # Re-checks status: projects hidden/removed since the visit silently drop out of the history.
        return ProjectCatalogue.published_cards(RecentlyViewed.ids(customer_id, limit))

    def removeFromHistory(self, customer_id, project_id):
        return RecentlyViewed.remove(customer_id, project_id) > 0

    def clearHistory(self, customer_id):
        return RecentlyViewed.clear(customer_id)


class RecommendationControl:
    """<<control>> :RecommendationControl - View Personalised Recommendations.

    Content-based scoring from the customer's own behaviour:
      category affinity (views=1, shortlists=3, recent history weighted by recency)  -> up to 5 points
      style-tag overlap                                                              -> up to 2 points
      platform popularity (views)                                                    -> up to 1 point
      freshness (listed within ~6 months)                                            -> up to 0.5 points
    Already-seen projects (recent history) are excluded and no category fills more than MAX_PER_CATEGORY slots.
    Customers with no history get the most popular projects (cold start)."""
    KIND_WEIGHT = {'view': 1.0, 'shortlist': 3.0}
    MAX_PER_CATEGORY = 3

    @staticmethod
    def _age_days(created_at):
        try:
            when = datetime.fromisoformat(str(created_at))
        except ValueError:
            return 365
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - when).days)

    def viewPersonalisedRecommendations(self, customer_id, limit=8):
        """Returns {'items': [project + 'reason' + 'score'], 'personalised': bool}."""
        recent_ids = RecentlyViewed.ids(customer_id)
        recent = ProjectCatalogue.published_cards(recent_ids)
        category_weight, tag_weight, category_name = Counter(), Counter(), {}

        def learn(category_id, category, tags, weight):
            category_weight[category_id] += weight
            category_name[category_id] = category
            for tag in tags:
                tag_weight[tag.lower()] += weight

        for row in EngagementLog.history(customer_id):
            weight = self.KIND_WEIGHT.get(row['kind'], 1.0) * row['n']
            learn(row['category_id'], row['category'], [t.strip() for t in (row['tags'] or '').split(',') if t.strip()], weight)
        for rank, card in enumerate(recent):  # newest first: recent interest counts for more
            learn(card['category_id'], card['category'], card['tag_list'], 3.0 - min(rank, 10) * 0.2)

        pool = [p for p in ProjectCatalogue.all_published_cards() if p['id'] not in set(recent_ids)]
        if not pool:
            return {'items': [], 'personalised': False}
        max_views = max(p['views'] for p in pool) or 1
        personalised = bool(category_weight)
        max_cat = max(category_weight.values()) if personalised else 1
        max_tag = max(tag_weight.values()) if tag_weight else 1

        scored = []
        for p in pool:
            popularity = p['views'] / max_views
            freshness = 0.5 * max(0.0, 1 - self._age_days(p['created_at']) / 180)
            cat_part = 5 * category_weight.get(p['category_id'], 0) / max_cat
            matched_tags = [t for t in p['tag_list'] if tag_weight.get(t.lower())]
            tag_part = 2 * min(1.0, sum(tag_weight[t.lower()] for t in matched_tags) / max_tag) if matched_tags else 0
            score = cat_part + tag_part + popularity + freshness
            if cat_part:
                reason = f"Because you've been looking at {p['category']} projects"
            elif matched_tags:
                reason = f"Matches your interest in {matched_tags[0]}"
            else:
                reason = 'Popular on the platform'
            scored.append(dict(p, score=round(score, 3), reason=reason))

        scored.sort(key=lambda p: (-p['score'], -p['views'], -p['id']))
        picked, per_category = [], Counter()
        for p in scored:
            if per_category[p['category_id']] >= self.MAX_PER_CATEGORY:
                continue
            per_category[p['category_id']] += 1
            picked.append(p)
            if len(picked) == limit:
                break
        return {'items': picked, 'personalised': personalised}



class ManageFavouritesControl:
    """Control layer for managing customer favourite groups and projects."""

    def viewGroups(self, customer_id):
        """Retrieve all favourite groups belonging to a customer."""
        return FavouriteGroups.get_groups(customer_id)

    def createGroup(self, customer_id, name):
        """Create a new favourite group."""
        name = (name or '').strip()

        if not name:
            return False, 'Please enter a group name.'

        if len(name) > 50:
            return False, 'Group names cannot exceed 50 characters.'

        group_id = FavouriteGroups.create_group(customer_id, name)

        if group_id is None:
            return False, 'This group name already exists or is invalid.'

        return True, 'Favourite group created successfully.'

    def deleteGroup(self, customer_id, group_id):
        """Delete a favourite group."""
        try:
            group_id = int(group_id)
        except (TypeError, ValueError):
            return False, 'Invalid favourite group.'

        if not FavouriteGroups.delete_group(customer_id, group_id):
            return False, 'Favourite group not found.'

        return True, 'Favourite group deleted successfully.'


    def addFavourite(self, customer_id, group_id, project_id):
        """Add a published project to a favourite group."""
        try:
            project_id = int(project_id)
        except (TypeError, ValueError):
            return False, 'Invalid project.'

        # If no group was selected, use or create the default group.
        if group_id in (None, ''):
            groups = FavouriteGroups.get_groups(customer_id)

            default_group = next(
                (g for g in groups if g['name'].casefold() == 'my favourites'),
                None
            )

            if default_group:
                group_id = default_group['id']
            else:
                group_id = FavouriteGroups.create_group(
                    customer_id, 'My Favourites'
                )

        try:
            group_id = int(group_id)
        except (TypeError, ValueError):
            return False, 'Invalid favourite group.'

        if not FavouriteGroups.add_project(customer_id, group_id, project_id):
            return False, 'Unable to add project. It may already be saved or unavailable.'

        return True, 'Project added to favourites.'

    def removeFavourite(self, customer_id, group_id, project_id):
        """Remove a project from one favourite group."""
        try:
            group_id = int(group_id)
            project_id = int(project_id)
        except (TypeError, ValueError):
            return False, 'Invalid group or project.'

        if not FavouriteGroups.remove_project(customer_id, group_id, project_id):
            return False, 'Favourite not found.'

        return True, 'Project removed from favourites.'

    def viewFavourites(self, customer_id, group_id=None):
        """View all favourites or favourites belonging to one group."""
        try:
            if group_id not in (None, ''):
                group_id = int(group_id)
            else:
                group_id = None
        except (TypeError, ValueError):
            return []

        return FavouriteGroups.get_projects(customer_id, group_id)

    def searchFavourites(self, customer_id, keyword='', group_id=None):
        """Search saved projects by title, description, category or designer."""
        projects = self.viewFavourites(customer_id, group_id)
        keyword = (keyword or '').strip().casefold()

        if not keyword:
            return projects

        return [
            project for project in projects
            if keyword in ' '.join([
                project.get('title', ''),
                project.get('description', ''),
                project.get('category', ''),
                project.get('designer', '')
            ]).casefold()
        ]


class CustomerReviewControl:
    """Control layer for submitting and editing customer reviews."""

    def viewCustomerRenovations(self, customer_id):
        """Return completed renovations belonging to this customer."""
        return CustomerReviews.customer_renovations(customer_id)

    def submitReview(
        self,
        customer_id,
        customer_name,
        renovation_id,
        rating,
        review_text
    ):
        """Submit a new review or update an existing review."""
        return CustomerReviews.save_review(
            customer_id,
            customer_name,
            renovation_id,
            rating,
            review_text
        )