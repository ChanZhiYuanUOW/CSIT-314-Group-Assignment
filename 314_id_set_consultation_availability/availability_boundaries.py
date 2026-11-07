from datetime import date, datetime
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from availability_controls import ServiceRequestControl

availability_bp = Blueprint("availability", __name__, template_folder="templates")

service_request_control = ServiceRequestControl()


@availability_bp.app_template_filter("friendly_date")
def _friendlyDate(value: str) -> str:
    """'2026-11-16 14:00:00' -> 'Mon 16 Nov 2026'"""
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%a %d %b %Y")
    except (TypeError, ValueError):
        return value or ""


@availability_bp.app_template_filter("friendly_clock")
def _friendlyClock(value: str) -> str:
    """'2026-11-16 14:00:00' -> '2:00 PM'"""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError):
        return value or ""


class ServiceRequestBoundary:
    """<<boundary>> :ServiceRequestBoundary"""

    @staticmethod
    def _isDesigner():
        return "user_id" in session and session.get("role") == "Interior Designer"

    @staticmethod
    @availability_bp.route("/designer/availability", methods=["GET", "POST"])
    def setConsultationAvailability():
        if not ServiceRequestBoundary._isDesigner():
            flash("Unauthorised: Please log in as an Interior Designer.", "danger")
            return redirect(url_for("auth.authenticateLogin"))

        form_values = {}
        if request.method == "POST":
            try:
                if request.form.get("form_type") == "remove":
                    ok, msg = service_request_control.removeConsultationSlot(
                        actor_role=session["role"],
                        designer_user_id=session["user_id"],
                        slot_id=request.form.get("slot_id", "")
                    )
                else:
                    ok, msg = service_request_control.setConsultationAvailability(
                        actor_role=session["role"],
                        designer_user_id=session["user_id"],
                        slot_date=request.form.get("slot_date", ""),
                        from_time=request.form.get("from_time", ""),
                        to_time=request.form.get("to_time", ""),
                        repeat_weeks=request.form.get("repeat_weeks", "0")
                    )
                    form_values = request.form
            except (PermissionError, LookupError) as e:
                ok, msg = False, str(e)

            flash(msg, "success" if ok else "danger")
            if ok:
                return redirect(url_for("availability.setConsultationAvailability"))

        slots = service_request_control.viewConsultationAvailability(
            actor_role=session["role"],
            designer_user_id=session["user_id"]
        )
        return render_template(
            "consultation_availability.html",
            slots=slots,
            form=form_values,
            today=date.today().isoformat(),
            max_repeat_weeks=service_request_control.MAX_REPEAT_WEEKS
        )
