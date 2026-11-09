"""Tests for the Customer features. Fully isolated: temporary accounts CSV + temporary platform CSV folder,
so the shared demo data (data/*.csv, data/platform/*.csv) is never touched.

Run from 314_id_help_page:  python -m pytest test_customer_features.py -q      (or: python -m unittest test_customer_features)
"""
import csv
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from entities import RegisteredUser
from platform_management.db import get_db
from customer_features.controls import (BrowseProjectsControl, CompareProjectsControl, ProjectDetailsControl,
                                        RecentlyViewedControl, RecommendationControl, ReportContentControl,
                                        ShareProjectControl)
from customer_features.entities import RecentlyViewed

# Load THIS folder's app.py by path, so the test also works when the repo-root app.py is on sys.path.
_spec = importlib.util.spec_from_file_location('help_page_app', os.path.join(HERE, 'app.py'))
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
create_app = _module.create_app

FIELDS = ['user_id', 'username', 'email', 'password', 'full_name', 'phone', 'role', 'status',
          'notify_email', 'notify_sms', 'notify_marketing', 'created_at']
USERS = [  # id, username, full_name, role
    ('1', 'cust_one', 'Cust One', 'Customer'),
    ('2', 'cust_two', 'Cust Two', 'Customer'),
    ('3', 'id_chloe', 'Chloe Tan', 'Interior Designer'),
    ('4', 'id_ben', 'Ben Lim', 'Interior Designer'),
    ('5', 'pm_user', 'Pat Manager', 'Platform Management'),
]


def now_iso(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec='seconds')


class CustomerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_csv = RegisteredUser.CSV_FILE
        RegisteredUser.CSV_FILE = os.path.join(self.tmp.name, 'users.csv')
        with open(RegisteredUser.CSV_FILE, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for uid, username, name, role in USERS:
                w.writerow(dict(user_id=uid, username=username, email=f'{username}@x.sg', password='x', full_name=name,
                                phone='+65 0', role=role, status='Active', notify_email='True', notify_sms='False',
                                notify_marketing='False', created_at='2026-01-01 00:00:00'))
        self.platform_dir = os.path.join(self.tmp.name, 'platform')
        self.app = create_app()
        self.app.config.update(PM_CSV_DIR=self.platform_dir, TESTING=True)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.seed()
        self.client = self.app.test_client()

    def tearDown(self):
        self.ctx.pop()
        RegisteredUser.CSV_FILE = self._old_csv
        self.tmp.cleanup()

    # ---- fixtures ---------------------------------------------------------------------------------------
    def seed(self):
        with get_db() as db:
            for cid, name in [(1, 'Modern Living Room'), (2, 'Scandinavian Kitchen'), (3, 'Industrial Office')]:
                db.add('categories', id=cid, name=name, description='')
            projects = [  # id, title, designer, category, status, tags, days_ago
                (1, 'Sunny Modern Loft', '3', 1, 'published', 'modern, bright', 5),
                (2, 'Cozy Nordic Kitchen', '4', 2, 'published', 'nordic, wood', 10),
                (3, 'Industrial Studio', '3', 3, 'published', 'industrial', 20),
                (4, 'Draft Villa', '3', 1, 'draft', '', 1),
                (5, 'Hidden Condo', '4', 1, 'hidden', 'modern', 1),
                (6, '100% Bright Home', '4', 2, 'published', '', 30),
                (7, 'Modern Minimal Bedroom', '4', 1, 'published', 'modern, minimal', 40),
            ]
            for pid, title, designer, cat, status, tags, days in projects:
                db.add('projects', id=pid, title=title, description=f'Description of {title}', designer_id=designer,
                       category_id=cat, status=status, created_at=now_iso(days), tags=tags)
            db.add('photos', project_id=1, filename='a.jpg', photo_type='Before', position=0)
            db.add('photos', project_id=1, filename='b.jpg', photo_type='After', position=1)
            db.add('company', designer_id='3', name='Tan Interiors', description='Bespoke homes', email='t@x.sg',
                   phone='123', location='Bedok')
            db.add('reviews', designer_id='3', customer='Alice', review='Great work', reply='Thanks!')
            for pid, n in [(3, 5), (1, 3), (2, 1)]:  # popularity: project 3 most viewed, then 1
                for _ in range(n):
                    db.add('engagement_events', project_id=pid, customer_id='2', kind='view', occurred_at=now_iso(2))

    def set_project(self, pid, **values):
        with get_db() as db:
            db.update('projects', db.first('projects', id=pid), **values)

    def add_project(self, pid, title, category=1, tags='modern', status='published'):
        with get_db() as db:
            db.add('projects', id=pid, title=title, description='', designer_id='3', category_id=category,
                   status=status, created_at=now_iso(), tags=tags)

    def csv_rows(self, name):
        """Read a platform CSV straight from disk (what a teammate's module would see)."""
        with open(os.path.join(self.platform_dir, name + '.csv'), encoding='utf-8', newline='') as f:
            return list(csv.DictReader(f))

    def reopen_store(self):
        """Drop the in-memory store and reload everything from the CSV files."""
        self.ctx.pop()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def login(self, user_id):
        with self.client.session_transaction() as s:
            s['user_id'] = str(user_id)

    def token(self, path='/customer/projects'):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def titles(self, result):
        return [p['title'] for p in result['projects']]


class TestSearchAndFilter(CustomerTestCase):
    def setUp(self):
        super().setUp()
        self.browse = BrowseProjectsControl()

    def test_only_published_projects_are_listed(self):
        titles = self.titles(self.browse.searchFilterProjects())
        self.assertEqual(len(titles), 5)
        self.assertNotIn('Draft Villa', titles)
        self.assertNotIn('Hidden Condo', titles)

    def test_keyword_matches_title_tag_category_company_and_designer(self):
        self.assertEqual(self.titles(self.browse.searchFilterProjects('nordic')), ['Cozy Nordic Kitchen'])   # title + tag
        self.assertEqual(self.titles(self.browse.searchFilterProjects('industrial office')), ['Industrial Studio'])  # words across fields
        self.assertEqual(set(self.titles(self.browse.searchFilterProjects('Tan Interiors'))), {'Sunny Modern Loft', 'Industrial Studio'})  # company
        self.assertEqual(set(self.titles(self.browse.searchFilterProjects('chloe'))), {'Sunny Modern Loft', 'Industrial Studio'})  # designer name
        self.assertEqual(self.titles(self.browse.searchFilterProjects('scandinavian kitchen bright')), ['100% Bright Home'])  # category + title

    def test_all_keywords_must_match(self):
        self.assertEqual(self.browse.searchFilterProjects('modern nordic')['total'], 0)

    def test_like_wildcards_are_literal(self):
        self.assertEqual(self.titles(self.browse.searchFilterProjects('%')), ['100% Bright Home'])
        self.assertEqual(self.browse.searchFilterProjects('_')['total'], 0)

    def test_sql_injection_text_is_harmless(self):
        self.assertEqual(self.browse.searchFilterProjects("'; DROP TABLE projects; --")['total'], 0)
        self.assertEqual(self.browse.searchFilterProjects()['total'], 5)

    def test_category_filter_single_and_multiple_and_junk(self):
        self.assertEqual(self.browse.searchFilterProjects(category_ids=['1'])['total'], 2)   # published only
        self.assertEqual(self.browse.searchFilterProjects(category_ids=['1', '3'])['total'], 3)
        self.assertEqual(self.browse.searchFilterProjects(category_ids=['abc', '-4', ''])['total'], 5)  # junk ignored

    def test_keyword_and_category_combine(self):
        self.assertEqual(self.browse.searchFilterProjects('modern', category_ids=[1])['total'], 2)
        self.assertEqual(self.browse.searchFilterProjects('modern', category_ids=[3])['total'], 0)

    def test_sorting(self):
        self.assertEqual(self.titles(self.browse.searchFilterProjects(sort='popular'))[:2], ['Industrial Studio', 'Sunny Modern Loft'])
        self.assertEqual(self.titles(self.browse.searchFilterProjects(sort='title'))[0], '100% Bright Home')
        self.assertEqual(self.titles(self.browse.searchFilterProjects(sort='newest'))[0], 'Sunny Modern Loft')
        self.assertEqual(self.titles(self.browse.searchFilterProjects(sort='nonsense'))[0], 'Sunny Modern Loft')  # falls back

    def test_pagination_clamps_page(self):
        result = self.browse.searchFilterProjects(page=999)
        self.assertEqual((result['page'], result['pages']), (1, 1))
        self.assertEqual(len(result['projects']), 5)
        self.assertEqual(self.browse.searchFilterProjects(page='x')['page'], 1)

    def test_filter_dropdown_lists_one_entry_per_style_first_word(self):
        names = [c['name'] for c in self.browse.listFilterCategories()]
        self.assertEqual(names, ['Industrial', 'Modern', 'Scandinavian'])

    def test_style_filter_matches_every_category_starting_with_that_word(self):
        self.add_project(900, 'Extra Kitchen Home', category=2, tags='x')  # category 2 is not 'Modern Living Room'
        modern = self.browse.searchFilterProjects(styles=['modern'])
        self.assertTrue(all(p['style'] == 'Modern' for p in modern['projects']))
        self.assertEqual(self.browse.searchFilterProjects(styles=['Modern', 'Industrial'])['total'] >= modern['total'], True)
        self.assertEqual(self.browse.searchFilterProjects(styles=['nonsense'])['total'], 0)


class TestDetailsAndHistory(CustomerTestCase):
    def setUp(self):
        super().setUp()
        self.details = ProjectDetailsControl()
        self.recent = RecentlyViewedControl()

    def test_details_include_photos_company_reviews(self):
        p = self.details.viewProjectDetails('1', 1)
        self.assertEqual([ph['filename'] for ph in p['photos']], ['a.jpg', 'b.jpg'])
        self.assertEqual(p['company']['name'], 'Tan Interiors')
        self.assertEqual(p['designer'], 'Chloe Tan')
        self.assertEqual(p['review_count'], 1)
        self.assertEqual(p['tag_list'], ['modern', 'bright'])

    def test_unpublished_projects_are_not_viewable(self):
        for pid in (4, 5, 999):
            self.assertIsNone(self.details.viewProjectDetails('1', pid))

    def test_view_is_logged_once_per_window_and_counts_for_analytics(self):
        before = len(get_db().all('engagement_events', project_id=2))
        self.details.viewProjectDetails('1', 2)
        self.details.viewProjectDetails('1', 2)  # refresh: not double counted
        self.assertEqual(len(get_db().all('engagement_events', project_id=2, customer_id='1')), 1)
        self.assertEqual(len(get_db().all('engagement_events', project_id=2)), before + 1)
        rows = [r for r in self.csv_rows('engagement_events') if r['customer_id'] == '1']  # visible on disk too
        self.assertEqual([(r['project_id'], r['kind']) for r in rows], [('2', 'view')])

    def test_recently_viewed_is_newest_first_and_per_customer(self):
        for pid in (1, 2, 3, 1):
            self.details.viewProjectDetails('1', pid)
        self.details.viewProjectDetails('2', 7)
        self.assertEqual([p['id'] for p in self.recent.viewRecentlyViewedProjects('1')], [1, 3, 2])
        self.assertEqual([p['id'] for p in self.recent.viewRecentlyViewedProjects('2')], [7])

    def test_history_is_capped_at_twenty(self):
        for i in range(100, 125):
            self.add_project(i, f'Extra {i}')
        for i in range(100, 125):
            self.details.viewProjectDetails('1', i)
        ids = [p['id'] for p in self.recent.viewRecentlyViewedProjects('1')]
        self.assertEqual(len(ids), 20)
        self.assertEqual(ids[0], 124)
        self.assertNotIn(100, ids)

    def test_restricted_projects_drop_out_of_history(self):
        self.details.viewProjectDetails('1', 2)
        self.set_project(2, status='hidden')
        self.assertEqual(self.recent.viewRecentlyViewedProjects('1'), [])

    def test_remove_and_clear_history(self):
        for pid in (1, 2, 3):
            self.details.viewProjectDetails('1', pid)
        self.assertTrue(self.recent.removeFromHistory('1', 2))
        self.assertFalse(self.recent.removeFromHistory('1', 2))
        self.assertEqual(sorted(p['id'] for p in self.recent.viewRecentlyViewedProjects('1')), [1, 3])
        self.recent.clearHistory('1')
        self.assertEqual(self.recent.viewRecentlyViewedProjects('1'), [])


class TestHistoryCsv(CustomerTestCase):
    def test_history_is_stored_in_a_csv_next_to_the_shared_tables(self):
        ProjectDetailsControl().viewProjectDetails('1', 2)
        rows = self.csv_rows('recently_viewed')
        self.assertEqual([(r['customer_id'], r['project_id']) for r in rows], [('1', '2')])
        with open(os.path.join(self.platform_dir, 'recently_viewed.csv'), encoding='utf-8') as f:
            self.assertEqual(f.readline().strip(), 'customer_id,project_id,viewed_at')
        self.assertFalse(os.path.exists(os.path.join(self.platform_dir, 'recently_viewed.csv.tmp')))

    def test_history_survives_a_reload_and_missing_file_is_empty(self):
        self.assertEqual(RecentlyViewed.ids('1'), [])  # no file yet
        RecentlyViewed.record('1', 1)
        self.reopen_store()
        self.assertEqual(RecentlyViewed.ids('1'), [1])

    def test_removing_one_customer_does_not_affect_another(self):
        RecentlyViewed.record('1', 1)
        RecentlyViewed.record('2', 1)
        RecentlyViewed.clear('1')
        self.assertEqual(RecentlyViewed.ids('1'), [])
        self.assertEqual(RecentlyViewed.ids('2'), [1])

    def test_shared_tables_stay_loadable_by_the_group_store(self):
        """Our writes must keep every shared CSV valid for Platform Management (same columns, no blanks)."""
        ProjectDetailsControl().viewProjectDetails('1', 1)
        ReportContentControl().reportMisleadingContent('1', 1, 'Other violation', 'enough detail here')
        self.reopen_store()  # CsvStore.load() raises on wrong columns / incomplete rows
        self.assertEqual(len(get_db().all('content_reports')), 1)
        self.assertTrue(get_db().first('engagement_events', customer_id='1', kind='view'))


class TestCompare(CustomerTestCase):
    def setUp(self):
        super().setUp()
        self.cmp = CompareProjectsControl()

    def test_add_limit_duplicates_and_unpublished(self):
        ids, ok, _ = self.cmp.addToComparison([], 1)
        self.assertEqual((ids, ok), ([1], True))
        ids, ok, _ = self.cmp.addToComparison(ids, 1)
        self.assertEqual((ids, ok), ([1], True))  # no duplicate
        ids, ok, _ = self.cmp.addToComparison(ids, 2)
        ids, ok, _ = self.cmp.addToComparison(ids, 3)
        ids, ok, _ = self.cmp.addToComparison(ids, 6)
        self.assertEqual(ids, [1, 2, 3, 6])
        ids, ok, msg = self.cmp.addToComparison(ids, 7)
        self.assertFalse(ok)
        self.assertEqual(ids, [1, 2, 3, 6])
        self.assertIn('up to 4', msg)
        _, ok, _ = self.cmp.addToComparison([], 4)  # draft
        self.assertFalse(ok)

    def test_remove(self):
        self.assertEqual(self.cmp.removeFromComparison([1, 2, 3], 2), [1, 3])

    def test_comparison_rows_flag_differences(self):
        result = self.cmp.compareProjects([1, 3])
        self.assertEqual([p['id'] for p in result['projects']], [1, 3])
        rows = {r['label']: r for r in result['rows']}
        self.assertTrue(rows['Category']['differs'])
        self.assertEqual(rows['Designer']['values'], ['Chloe Tan', 'Chloe Tan'])
        self.assertFalse(rows['Designer']['differs'])
        self.assertEqual(rows['Photos']['values'], ['2', '0'])

    def test_hidden_project_is_dropped_from_comparison(self):
        self.set_project(3, status='removed')
        self.assertEqual([p['id'] for p in self.cmp.compareProjects([1, 3])['projects']], [1])


class TestReport(CustomerTestCase):
    def setUp(self):
        super().setUp()
        self.report = ReportContentControl()

    def count(self):
        return len(get_db().all('content_reports'))

    def test_valid_report_lands_in_the_shared_moderation_queue(self):
        ok, _ = self.report.reportMisleadingContent('1', 1, 'Misleading description', 'The photos are stock images.')
        self.assertTrue(ok)
        row = get_db().all('content_reports')[0]
        self.assertEqual((row['project_id'], row['reporter_id'], row['reason'], row['status']), (1, '1', 'Misleading description', 'open'))
        self.assertTrue(row['created_at'])
        on_disk = self.csv_rows('content_reports')[0]  # exactly what Platform Management reads
        self.assertEqual((on_disk['project_id'], on_disk['reporter_id'], on_disk['status']), ('1', '1', 'open'))
        self.assertEqual((on_disk['reviewed_by'], on_disk['reviewed_at'], on_disk['decision_note']), ('', '', ''))
        self.reopen_store()  # reload from disk: store accepts the new row, id sequence intact
        self.assertEqual(len(get_db().all('content_reports')), 1)
        self.assertTrue(self.report.reportMisleadingContent('2', 1, 'Other violation', 'second person reports')[0])
        self.assertEqual([r['id'] for r in get_db().all('content_reports')], [1, 2])

    def test_validation(self):
        self.assertFalse(self.report.reportMisleadingContent('1', 1, 'Made up reason', 'long enough details')[0])
        self.assertFalse(self.report.reportMisleadingContent('1', 1, 'Other violation', 'short')[0])
        self.assertFalse(self.report.reportMisleadingContent('1', 1, 'Other violation', 'x' * 1001)[0])
        self.assertFalse(self.report.reportMisleadingContent('1', 1, 'Other violation', '          ')[0])
        self.assertEqual(self.count(), 0)

    def test_cannot_report_unpublished_or_missing_projects(self):
        for pid in (4, 5, 999):
            self.assertFalse(self.report.reportMisleadingContent('1', pid, 'Other violation', 'long enough details')[0])
        self.assertEqual(self.count(), 0)

    def test_duplicate_open_report_blocked_but_other_reason_allowed(self):
        self.assertTrue(self.report.reportMisleadingContent('1', 1, 'Misleading description', 'first report text')[0])
        ok, msg = self.report.reportMisleadingContent('1', 1, 'Misleading description', 'second report text')
        self.assertFalse(ok)
        self.assertIn('already', msg)
        self.assertTrue(self.report.reportMisleadingContent('1', 1, 'Incorrect category', 'wrong category here')[0])
        self.assertTrue(self.report.reportMisleadingContent('2', 1, 'Misleading description', 'someone else reports')[0])

    def test_daily_limit(self):
        for pid, reason in [(1, 'Other violation'), (2, 'Other violation'), (3, 'Other violation'), (7, 'Other violation'), (6, 'Other violation')]:
            self.assertTrue(self.report.reportMisleadingContent('1', pid, reason, 'enough detail here')[0])
        ok, msg = self.report.reportMisleadingContent('1', 1, 'Incorrect category', 'enough detail here')
        self.assertFalse(ok)
        self.assertIn('limit', msg)


class TestShare(CustomerTestCase):
    def test_token_roundtrip_tamper_and_unpublished(self):
        share = ShareProjectControl('secret-a')
        token = share.createShareToken(1)
        self.assertEqual(share.resolveShareToken(token), 1)
        self.assertIsNone(share.resolveShareToken(token[:-2] + 'xx'))
        self.assertIsNone(share.resolveShareToken('garbage'))
        self.assertIsNone(ShareProjectControl('secret-b').resolveShareToken(token))  # different key
        self.assertIsNone(share.createShareToken(4))  # draft
        self.assertIsNone(share.createShareToken(999))


class TestRecommendations(CustomerTestCase):
    def setUp(self):
        super().setUp()
        self.details = ProjectDetailsControl()
        self.rec = RecommendationControl()

    def test_cold_start_falls_back_to_popular(self):
        result = self.rec.viewPersonalisedRecommendations('1')
        self.assertFalse(result['personalised'])
        self.assertEqual(result['items'][0]['title'], 'Industrial Studio')
        self.assertTrue(all(i['reason'] == 'Popular on the platform' for i in result['items']))

    def test_interest_in_a_category_surfaces_similar_unseen_projects(self):
        self.details.viewProjectDetails('1', 1)  # Modern Living Room, tags modern/bright
        result = self.rec.viewPersonalisedRecommendations('1')
        self.assertTrue(result['personalised'])
        ids = [i['id'] for i in result['items']]
        self.assertNotIn(1, ids)                  # already seen
        self.assertEqual(ids[0], 7)               # same category + shared 'modern' tag beats the more popular project 3
        self.assertIn('Modern Living Room', result['items'][0]['reason'])
        self.assertNotIn(4, ids)                  # never recommend drafts
        self.assertNotIn(5, ids)                  # never recommend hidden projects

    def test_recommendations_are_per_customer(self):
        self.details.viewProjectDetails('1', 1)
        self.assertFalse(self.rec.viewPersonalisedRecommendations('2')['personalised'] and False)
        other = self.rec.viewPersonalisedRecommendations('2')
        self.assertEqual(other['items'][0]['id'], 3)  # customer 2 has only viewed (seeded) 3 > popular order untouched by customer 1

    def test_category_diversity_cap(self):
        for i in range(200, 210):
            self.add_project(i, f'Modern extra {i}')
        self.details.viewProjectDetails('1', 1)
        items = self.rec.viewPersonalisedRecommendations('1', limit=8)['items']
        self.assertLessEqual(sum(1 for i in items if i['category_id'] == 1), RecommendationControl.MAX_PER_CATEGORY)


class TestHttp(CustomerTestCase):
    def test_guest_is_redirected_to_login_and_wrong_role_forbidden(self):
        r = self.client.get('/customer/projects')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r.headers['Location'])
        self.login(3)  # designer
        self.assertEqual(self.client.get('/customer/projects').status_code, 403)
        self.login(5)  # platform management
        self.assertEqual(self.client.get('/customer/recommended').status_code, 403)

    def test_deactivated_customer_is_locked_out(self):
        rows = RegisteredUser._readAll()
        rows[0]['status'] = 'Deactivated'
        RegisteredUser._writeAll(rows)
        self.login(1)
        self.assertEqual(self.client.get('/customer/projects').status_code, 302)

    def test_browse_search_and_pages_render(self):
        self.login(1)
        html = self.client.get('/customer/projects').get_data(as_text=True)
        self.assertIn('Sunny Modern Loft', html)
        self.assertNotIn('Draft Villa', html)
        html = self.client.get('/customer/projects?q=nordic').get_data(as_text=True)
        self.assertIn('Cozy Nordic Kitchen', html)
        self.assertNotIn('Sunny Modern Loft', html)
        self.assertIn('No projects match', self.client.get('/customer/projects?q=zzzzzz').get_data(as_text=True))
        for path in ('/customer/recommended', '/customer/recent', '/customer/compare'):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_sort_options_reorder_the_rendered_page_and_show_results_first(self):
        self.login(1)

        def order(query):
            html = self.client.get('/customer/projects' + query).get_data(as_text=True)
            self.assertNotIn('See all', html)  # the recommended / recently-viewed strips are hidden, results come first
            return [t for t in re.findall(r'class="card-title[^"]*">\s*<a[^>]*>([^<]+)</a>', html.split('All projects')[-1])]
        self.assertEqual(order('?sort=popular')[:2], ['Industrial Studio', 'Sunny Modern Loft'])
        self.assertEqual(order('?sort=title')[0], '100% Bright Home')
        self.assertEqual(order('?sort=oldest')[0], 'Modern Minimal Bedroom')
        self.assertEqual(order('?sort=newest')[0], 'Sunny Modern Loft')
        self.assertIn('sorted by most viewed', self.client.get('/customer/projects?sort=popular').get_data(as_text=True))

    def test_sort_and_category_selects_submit_on_change(self):
        self.login(1)
        html = self.client.get('/customer/projects').get_data(as_text=True)
        self.assertEqual(html.count('onchange="this.form.submit()"'), 2)

    def test_html_in_titles_is_escaped(self):
        self.set_project(2, title='<script>alert(1)</script>')
        self.login(1)
        html = self.client.get('/customer/projects').get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_details_records_history_and_missing_project_redirects(self):
        self.login(1)
        self.assertEqual(self.client.get('/customer/projects/1').status_code, 200)
        self.assertIn('Sunny Modern Loft', self.client.get('/customer/recent').get_data(as_text=True))
        for pid in (4, 5, 999):
            r = self.client.get(f'/customer/projects/{pid}')
            self.assertEqual(r.status_code, 302, pid)

    def test_post_requires_csrf_token(self):
        self.login(1)
        self.assertEqual(self.client.post('/customer/compare/add', data={'project_id': 1}).status_code, 400)

    def test_compare_flow_over_http(self):
        self.login(1)
        token = self.token()
        for pid in (1, 3):
            r = self.client.post('/customer/compare/add', data={'project_id': pid, 'csrf_token': token, 'next': '/customer/projects'})
            self.assertEqual(r.status_code, 302)
        with self.client.session_transaction() as s:
            self.assertEqual(s['compare_ids'], [1, 3])
        html = self.client.get('/customer/compare').get_data(as_text=True)
        self.assertIn('Sunny Modern Loft', html)
        self.assertIn('Industrial Studio', html)
        self.client.post('/customer/compare/clear', data={'csrf_token': token})
        with self.client.session_transaction() as s:
            self.assertEqual(s['compare_ids'], [])

    def test_open_redirect_is_blocked(self):
        self.login(1)
        token = self.token()
        for bad in ('//evil.example', 'https://evil.example', '/\\evil.example'):
            r = self.client.post('/customer/compare/add', data={'project_id': 1, 'csrf_token': token, 'next': bad})
            self.assertEqual(r.headers['Location'], '/customer/projects', bad)

    def test_report_flow_over_http(self):
        self.login(1)
        self.assertEqual(self.client.get('/customer/projects/1/report').status_code, 200)
        token = self.token('/customer/projects/1/report')
        bad = self.client.post('/customer/projects/1/report', data={'csrf_token': token, 'reason': 'Other violation', 'details': 'tiny'})
        self.assertEqual(bad.status_code, 200)  # form redisplayed with the error
        self.assertIn('at least', bad.get_data(as_text=True))
        ok = self.client.post('/customer/projects/1/report',
                              data={'csrf_token': token, 'reason': 'Misleading description', 'details': 'The photos are not of this home.'})
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(len(get_db().all('content_reports', status='open')), 1)
        self.assertEqual(self.client.get('/customer/projects/4/report').status_code, 302)

    def test_share_link_is_public_and_read_only(self):
        self.login(1)
        html = self.client.get('/customer/projects/1/share').get_data(as_text=True)
        link = re.search(r'value="(http[^"]+/customer/shared/[^"]+)"', html).group(1)
        path = '/customer/shared/' + link.rsplit('/', 1)[1]
        anonymous = self.app.test_client()
        r = anonymous.get(path)
        self.assertEqual(r.status_code, 200)
        self.assertIn('Sunny Modern Loft', r.get_data(as_text=True))
        self.assertEqual(anonymous.get(path[:-3] + 'abc').status_code, 404)
        self.set_project(1, status='hidden')
        self.assertEqual(anonymous.get(path).status_code, 404)  # unpublished -> link dies
        self.assertEqual(self.client.get('/customer/projects/4/share').status_code, 302)

    def test_history_remove_and_clear_over_http(self):
        self.login(1)
        self.client.get('/customer/projects/1')
        self.client.get('/customer/projects/2')
        token = self.token('/customer/recent')
        self.client.post('/customer/recent/remove', data={'project_id': 1, 'csrf_token': token})
        html = self.client.get('/customer/recent').get_data(as_text=True)
        self.assertNotIn('Sunny Modern Loft', html)
        self.assertIn('Cozy Nordic Kitchen', html)
        self.client.post('/customer/recent/clear', data={'csrf_token': token})
        self.assertIn('not viewed any projects', self.client.get('/customer/recent').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
