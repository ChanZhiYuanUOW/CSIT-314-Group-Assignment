from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from .analytics_controls import DiscoveryControl

discovery_bp = Blueprint("discovery", __name__, template_folder="templates")

discovery_control = DiscoveryControl()


class DiscoveryBoundary:
    """<<boundary>> :DiscoveryBoundary"""

    @staticmethod
    def _isDesigner():
        return "user_id" in session and session.get("role") == "Interior Designer"

    @staticmethod
    @discovery_bp.route("/designer/analytics", methods=["GET"])
    def monitorEngagementAnalytics():
        if not DiscoveryBoundary._isDesigner():
            flash("Unauthorised: Please log in as an Interior Designer.", "danger")
            return redirect(url_for("auth.authenticateLogin"))

        period = request.args.get("period", "Daily")
        try:
            project_summaries, chart = discovery_control.monitorEngagementAnalytics(
                actor_role=session["role"],
                designer_user_id=session["user_id"],
                period=period
            )
        except ValueError as e:
            flash(str(e), "warning")
            return redirect(url_for("discovery.monitorEngagementAnalytics"))

        return render_template(
            "engagement_analytics.html",
            project_summaries=project_summaries,
            chart=chart,
            period=period,
            periods=discovery_control.REPORTING_PERIODS
        )

    @staticmethod
    @discovery_bp.route("/designer/followers", methods=["GET"])
    def viewFollowerList():
        if not DiscoveryBoundary._isDesigner():
            flash("Unauthorised: Please log in as an Interior Designer.", "danger")
            return redirect(url_for("auth.authenticateLogin"))

        search_q = request.args.get("q", "")
        followers = discovery_control.viewFollowerList(
            actor_role=session["role"],
            designer_user_id=session["user_id"],
            search_query=search_q
        )
        return render_template("follower_list.html", followers=followers, search_q=search_q)
