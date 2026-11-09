import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analytics_controls import DiscoveryControl
from analytics_entities import Project

DEMO_DESIGNER_ID = "2"

class TestMonitorEngagementAnalyticsBCE(unittest.TestCase):
    def setUp(self):
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

    def test_04_summaries_only_include_designers_own_projects(self):
        summaries, _ = self.discovery.monitorEngagementAnalytics("Interior Designer", DEMO_DESIGNER_ID)
        own_ids = {p["project_id"] for p in Project.getProjectsByDesigner(DEMO_DESIGNER_ID)}
        self.assertGreater(len(summaries), 0)
        self.assertEqual({s["project_id"] for s in summaries}, own_ids)
        for s in summaries:
            self.assertGreaterEqual(s["views"], s["shortlists"])

    def test_05_chart_totals_never_exceed_all_time_totals(self):
        summaries, _ = self.discovery.monitorEngagementAnalytics("Interior Designer", DEMO_DESIGNER_ID)
        total_views = sum(s["views"] for s in summaries)
        total_shortlists = sum(s["shortlists"] for s in summaries)
        for period in DiscoveryControl.REPORTING_PERIODS:
            chart = self.discovery.generateViewsShortlistChart([s["project_id"] for s in summaries], period)
            self.assertLessEqual(sum(chart["views"]), total_views)
            self.assertLessEqual(sum(chart["shortlists"]), total_shortlists)

    def test_06_designer_without_projects_gets_empty_analytics(self):
        summaries, chart = self.discovery.monitorEngagementAnalytics("Interior Designer", "25")
        self.assertEqual(summaries, [])
        self.assertEqual(sum(chart["views"]), 0)

    def test_07_view_follower_list_permission_guard(self):
        with self.assertRaises(PermissionError):
            self.discovery.viewFollowerList(actor_role="User Admin", designer_user_id=DEMO_DESIGNER_ID)

    def test_08_follower_list_only_returns_designers_followers(self):
        followers = self.discovery.viewFollowerList("Interior Designer", DEMO_DESIGNER_ID)
        other_followers = self.discovery.viewFollowerList("Interior Designer", "25")
        self.assertGreaterEqual(len(followers), 20)
        self.assertGreater(len(other_followers), 0)
        self.assertFalse({f["follow_id"] for f in followers} & {f["follow_id"] for f in other_followers})
        followed_dates = [f["followed_at"] for f in followers]
        self.assertEqual(followed_dates, sorted(followed_dates, reverse=True))

    def test_09_follower_list_search_narrows_results(self):
        followers = self.discovery.viewFollowerList("Interior Designer", DEMO_DESIGNER_ID)
        target = followers[0]
        matches = self.discovery.viewFollowerList("Interior Designer", DEMO_DESIGNER_ID, search_query=target["email"])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["customer_user_id"], target["customer_user_id"])


if __name__ == "__main__":
    unittest.main()
