import csv
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from flask import Flask

from engagement_analytics import analytics_entities
from engagement_analytics.analytics_controls import DiscoveryControl
from engagement_analytics.analytics_entities import Project, EngagementRecord

DEMO_DESIGNER_ID = "2"
OTHER_DESIGNER_ID = "25"
NO_PROJECTS_DESIGNER_ID = "999"


def _utc(local_dt: datetime) -> str:
    """A local wall-clock time written the way the platform stores it (ISO 8601, UTC)."""
    return local_dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _write(folder, table, fields, rows):
    with open(os.path.join(folder, table + ".csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class PlatformFixture(unittest.TestCase):
    """Points the analytics entities at a small, known copy of the platform's shared CSV tables."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)
        patcher = mock.patch.object(analytics_entities, "DEFAULT_PLATFORM_DATA_DIR", self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)

        now = datetime.now().replace(microsecond=0)
        self.today_noon = now.replace(hour=12, minute=0, second=0)
        # Just after local midnight: in UTC this is still "yesterday" for timezones ahead of UTC (e.g. Singapore)
        self.today_early = now.replace(hour=0, minute=30, second=0)

        _write(self.folder, "categories", ["id", "name", "description"], [
            {"id": "1", "name": "Modern Kitchen", "description": ""},
            {"id": "2", "name": "Scandinavian Bedroom", "description": ""},
        ])
        project_fields = ["id", "title", "description", "designer_id", "category_id", "status", "featured",
                          "created_at", "restriction_version", "tags", "estimated_cost_sgd"]
        _write(self.folder, "projects", project_fields, [
            {"id": "1", "title": "Kitchen refresh", "description": "", "designer_id": DEMO_DESIGNER_ID,
             "category_id": "1", "status": "published", "featured": "0", "created_at": _utc(now),
             "restriction_version": "0", "tags": "", "estimated_cost_sgd": ""},
            {"id": "2", "title": "Bedroom draft", "description": "", "designer_id": DEMO_DESIGNER_ID,
             "category_id": "2", "status": "draft", "featured": "0", "created_at": _utc(now),
             "restriction_version": "0", "tags": "", "estimated_cost_sgd": ""},
            {"id": "3", "title": "Someone else's", "description": "", "designer_id": OTHER_DESIGNER_ID,
             "category_id": "1", "status": "published", "featured": "0", "created_at": _utc(now),
             "restriction_version": "0", "tags": "", "estimated_cost_sgd": ""},
        ])
        events = [
            ("1", "view", self.today_noon), ("1", "view", self.today_early), ("1", "view", self.today_noon),
            ("1", "shortlist", self.today_noon),
            ("1", "view", self.today_noon - timedelta(days=400)),  # outside every chart window
            ("2", "view", self.today_noon - timedelta(days=1)),
            ("3", "view", self.today_noon), ("3", "shortlist", self.today_noon),
        ]
        _write(self.folder, "engagement_events", ["id", "project_id", "customer_id", "kind", "occurred_at"], [
            {"id": str(i), "project_id": pid, "customer_id": "138", "kind": kind, "occurred_at": _utc(when)}
            for i, (pid, kind, when) in enumerate(events, start=1)
        ])


class TestMonitorEngagementAnalyticsBCE(PlatformFixture):
    def setUp(self):
        super().setUp()
        self.discovery = DiscoveryControl()

    def test_01_monitor_engagement_analytics_permission_guard(self):
        with self.assertRaises(PermissionError):
            self.discovery.monitorEngagementAnalytics(actor_role="Customer", designer_user_id=DEMO_DESIGNER_ID)

    def test_02_invalid_reporting_period_rejected(self):
        with self.assertRaises(ValueError):
            self.discovery.monitorEngagementAnalytics("Interior Designer", DEMO_DESIGNER_ID, period="Yearly")

    def test_03_chart_buckets_for_each_reporting_period(self):
        for period, expected_buckets in (("Daily", 14), ("Weekly", 12), ("Monthly", 6)):
            _, chart = self.discovery.monitorEngagementAnalytics("Interior Designer", DEMO_DESIGNER_ID, period=period)
            self.assertEqual(chart["period"], period)
            self.assertEqual(len(chart["labels"]), expected_buckets)
            self.assertEqual(len(chart["views"]), expected_buckets)
            self.assertEqual(len(chart["shortlists"]), expected_buckets)

    def test_04_summaries_only_include_designers_own_platform_projects(self):
        summaries, _ = self.discovery.monitorEngagementAnalytics("Interior Designer", DEMO_DESIGNER_ID)
        by_id = {s["project_id"]: s for s in summaries}
        self.assertEqual(set(by_id), {"1", "2"})
        self.assertEqual(by_id["1"]["category"], "Modern Kitchen")
        self.assertEqual(by_id["1"]["publication_status"], "Published")
        self.assertEqual(by_id["2"]["publication_status"], "Draft")

    def test_05_totals_count_platform_view_and_shortlist_events(self):
        summaries, _ = self.discovery.monitorEngagementAnalytics("Interior Designer", DEMO_DESIGNER_ID)
        by_id = {s["project_id"]: s for s in summaries}
        self.assertEqual((by_id["1"]["views"], by_id["1"]["shortlists"]), (4, 1))
        self.assertEqual(by_id["1"]["shortlist_rate"], 25.0)
        self.assertEqual((by_id["2"]["views"], by_id["2"]["shortlists"]), (1, 0))

    def test_06_chart_totals_never_exceed_all_time_totals(self):
        summaries, _ = self.discovery.monitorEngagementAnalytics("Interior Designer", DEMO_DESIGNER_ID)
        total_views = sum(s["views"] for s in summaries)
        total_shortlists = sum(s["shortlists"] for s in summaries)
        for period in DiscoveryControl.REPORTING_PERIODS:
            chart = self.discovery.generateViewsShortlistChart([s["project_id"] for s in summaries], period)
            self.assertLessEqual(sum(chart["views"]), total_views)
            self.assertLessEqual(sum(chart["shortlists"]), total_shortlists)

    def test_07_utc_events_are_charted_on_the_local_day(self):
        chart = self.discovery.generateViewsShortlistChart(["1", "2"], "Daily")
        # today: 3 views on project 1 (including the one just after local midnight); yesterday: 1 on project 2
        self.assertEqual(chart["views"][-1], 3)
        self.assertEqual(chart["shortlists"][-1], 1)
        self.assertEqual(chart["views"][-2], 1)

    def test_08_designer_without_projects_gets_empty_analytics(self):
        summaries, chart = self.discovery.monitorEngagementAnalytics("Interior Designer", NO_PROJECTS_DESIGNER_ID)
        self.assertEqual(summaries, [])
        self.assertEqual(sum(chart["views"]), 0)

    def test_09_pm_csv_dir_setting_is_used_inside_the_site_app(self):
        app = Flask(__name__)
        app.config["PM_CSV_DIR"] = self.folder
        with mock.patch.object(analytics_entities, "DEFAULT_PLATFORM_DATA_DIR", "/nonexistent"):
            self.assertEqual(Project.getProjectsByDesigner(DEMO_DESIGNER_ID), [])
            with app.app_context():
                self.assertEqual(len(Project.getProjectsByDesigner(DEMO_DESIGNER_ID)), 2)
                self.assertEqual(len(EngagementRecord.getRecordsForProjects(["1"])), 5)


class TestPlatformDataIntegration(unittest.TestCase):
    def test_10_reads_the_shared_platform_tables_by_default(self):
        self.assertTrue(analytics_entities.platformDataDir().endswith(os.path.join("data", "platform")))
        self.assertGreater(len(Project.getProjectsByDesigner(DEMO_DESIGNER_ID)), 0)


class TestViewFollowerListBCE(unittest.TestCase):
    def setUp(self):
        self.discovery = DiscoveryControl()

    def test_11_view_follower_list_permission_guard(self):
        with self.assertRaises(PermissionError):
            self.discovery.viewFollowerList(actor_role="User Admin", designer_user_id=DEMO_DESIGNER_ID)

    def test_12_follower_list_only_returns_designers_followers(self):
        followers = self.discovery.viewFollowerList("Interior Designer", DEMO_DESIGNER_ID)
        other_followers = self.discovery.viewFollowerList("Interior Designer", OTHER_DESIGNER_ID)
        self.assertGreaterEqual(len(followers), 20)
        self.assertGreater(len(other_followers), 0)
        self.assertFalse({f["follow_id"] for f in followers} & {f["follow_id"] for f in other_followers})
        followed_dates = [f["followed_at"] for f in followers]
        self.assertEqual(followed_dates, sorted(followed_dates, reverse=True))

    def test_13_follower_list_search_narrows_results(self):
        followers = self.discovery.viewFollowerList("Interior Designer", DEMO_DESIGNER_ID)
        target = followers[0]
        matches = self.discovery.viewFollowerList("Interior Designer", DEMO_DESIGNER_ID, search_query=target["email"])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["customer_user_id"], target["customer_user_id"])


if __name__ == "__main__":
    unittest.main()
