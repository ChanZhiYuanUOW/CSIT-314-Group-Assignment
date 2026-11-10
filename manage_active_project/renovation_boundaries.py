from datetime import date, datetime
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from .renovation_controls import RenovationControl

renovation_bp = Blueprint("renovation", __name__, template_folder="templates")

renovation_control = RenovationControl()


@renovation_bp.app_template_filter("friendly_date")
def _friendlyDate(value: str) -> str:
    """'2026-11-27' -> 'Fri 27 Nov 2026'"""
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%a %d %b %Y")
    except (TypeError, ValueError):
        return value or ""


@renovation_bp.app_template_filter("renovation_time")
def _friendlyTime(value: str) -> str:
    """'2026-11-05 18:20:00' -> '05 Nov 2026, 6:20 PM'"""
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return value or ""
    return dt.strftime("%d %b %Y, %I:%M %p").replace(", 0", ", ")


class RenovationBoundary:
    """<<boundary>> :RenovationBoundary"""

    @staticmethod
    def _isDesigner():
        return "user_id" in session and session.get("role") == "Interior Designer"

    @staticmethod
    @renovation_bp.route("/designer/projects", methods=["GET", "POST"])
    def manageActiveProject():
        if not RenovationBoundary._isDesigner():
            flash("Unauthorised: Please log in as an Interior Designer.", "danger")
            return redirect(url_for("auth.authenticateLogin"))

        status_filter = request.args.get("status", "")
        selected_id = request.args.get("selected_id")
        posted = None
        if request.method == "POST":
            renovation_id = request.form.get("renovation_id", "")
            milestone_statuses = {key[len("milestone_status_"):]: value for key, value in request.form.items()
                                  if key.startswith("milestone_status_")}
            new_milestones = [{"description": d, "status": s} for d, s in zip(
                request.form.getlist("new_milestone_description"), request.form.getlist("new_milestone_status"))]
            try:
                ok, msg = renovation_control.manageActiveProject(
                    actor_role=session["role"],
                    designer_user_id=session["user_id"],
                    renovation_id=renovation_id,
                    status=request.form.get("status", ""),
                    milestone_statuses=milestone_statuses,
                    new_milestones=new_milestones,
                    expected_completion_date=request.form.get("expected_completion_date", "")
                )
            except (PermissionError, LookupError) as e:
                flash(str(e), "danger")
                return redirect(url_for("renovation.manageActiveProject"))

            flash(msg, "success" if ok else "danger")
            if ok:
                return redirect(url_for("renovation.manageActiveProject", status=status_filter, selected_id=renovation_id))
            # Show the form again with what the designer entered
            selected_id = renovation_id
            posted = {
                "status": request.form.get("status", ""),
                "expected_completion_date": request.form.get("expected_completion_date", ""),
                "milestone_statuses": milestone_statuses,
                "new_milestones": [m for m in new_milestones if m["description"].strip()]
            }

        try:
            projects, selected = renovation_control.viewActiveProjects(
                actor_role=session["role"],
                designer_user_id=session["user_id"],
                status_filter=status_filter,
                selected_renovation_id=selected_id
            )
        except (PermissionError, LookupError) as e:
            flash(str(e), "danger")
            return redirect(url_for("renovation.manageActiveProject"))

        return render_template(
            "active_projects.html",
            projects=projects,
            selected=selected,
            status_filter=status_filter,
            project_statuses=renovation_control.PROJECT_STATUSES,
            milestone_statuses=renovation_control.MILESTONE_STATUSES,
            posted=posted,
            today=date.today().isoformat()
        )
