from datetime import datetime, timedelta
from analytics_entities import Project, EngagementRecord, DesignerFollow


class DiscoveryControl:
    """<<control>> :DiscoveryControl"""

    REPORTING_PERIODS = ("Daily", "Weekly", "Monthly")

    @staticmethod
    def _checkDesignerPermissions(actor_role: str) -> bool:
        return actor_role == "Interior Designer"

    def monitorEngagementAnalytics(self, actor_role: str, designer_user_id: str, period: str = "Daily"):
        """Returns per-project view/shortlist totals and the views/shortlist chart for the reporting period."""
        if not self._checkDesignerPermissions(actor_role):
            raise PermissionError("Unauthorised: Only Interior Designers may monitor engagement analytics.")
        if period not in self.REPORTING_PERIODS:
            raise ValueError(f"Reporting period must be one of {', '.join(self.REPORTING_PERIODS)}.")

        projects = Project.getProjectsByDesigner(designer_user_id)
        project_ids = [p["project_id"] for p in projects]
        records = EngagementRecord.getRecordsForProjects(project_ids)

        project_summaries = []
        for p in projects:
            project_records = [r for r in records if r["project_id"] == p["project_id"]]
            views = sum(1 for r in project_records if r["event_type"] == "View")
            shortlists = sum(1 for r in project_records if r["event_type"] == "Shortlist")
            project_summaries.append({
                "project_id": p["project_id"],
                "title": p["title"],
                "category": p["category"],
                "publication_status": p["publication_status"],
                "views": views,
                "shortlists": shortlists,
                "shortlist_rate": round(shortlists / views * 100, 1) if views else 0.0
            })

        # <<include>> Generate Views/Shortlist Chart
        chart_data = self.generateViewsShortlistChart(project_ids, period)
        return project_summaries, chart_data

    def generateViewsShortlistChart(self, project_ids, period: str = "Daily"):
        """Buckets View/Shortlist events into the last 14 days, 12 weeks or 6 months."""
        if period not in self.REPORTING_PERIODS:
            raise ValueError(f"Reporting period must be one of {', '.join(self.REPORTING_PERIODS)}.")

        today = datetime.now().date()
        if period == "Daily":
            buckets = [today - timedelta(days=i) for i in range(13, -1, -1)]
            labels = [d.strftime("%d %b") for d in buckets]
        elif period == "Weekly":
            this_monday = today - timedelta(days=today.weekday())
            buckets = [this_monday - timedelta(weeks=i) for i in range(11, -1, -1)]
            labels = [f"Wk of {d.strftime('%d %b')}" for d in buckets]
        else:
            buckets = []
            year, month = today.year, today.month
            for _ in range(6):
                buckets.insert(0, today.replace(year=year, month=month, day=1))
                year, month = (year, month - 1) if month > 1 else (year - 1, 12)
            labels = [d.strftime("%b %Y") for d in buckets]

        views = [0] * len(buckets)
        shortlists = [0] * len(buckets)
        index = {d: i for i, d in enumerate(buckets)}
        for r in EngagementRecord.getRecordsForProjects(project_ids):
            day = datetime.strptime(r["occurred_at"], "%Y-%m-%d %H:%M:%S").date()
            if period == "Daily":
                key = day
            elif period == "Weekly":
                key = day - timedelta(days=day.weekday())
            else:
                key = day.replace(day=1)
            if key not in index:
                continue
            if r["event_type"] == "View":
                views[index[key]] += 1
            elif r["event_type"] == "Shortlist":
                shortlists[index[key]] += 1

        return {"period": period, "labels": labels, "views": views, "shortlists": shortlists}

    def viewFollowerList(self, actor_role: str, designer_user_id: str, search_query: str = ""):
        """<<extend>> of Monitor Engagement Analytics: customers following the designer, newest first."""
        if not self._checkDesignerPermissions(actor_role):
            raise PermissionError("Unauthorised: Only Interior Designers may view their follower list.")

        followers = DesignerFollow.getFollowersOfDesigner(designer_user_id)
        q = search_query.strip().lower()
        if q:
            followers = [f for f in followers
                         if q in (f["full_name"] + " " + f["email"] + " " + f["username"]).lower()]
        return sorted(followers, key=lambda f: f["followed_at"], reverse=True)
