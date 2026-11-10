from datetime import datetime
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from service_controls import ServiceRequestControl

service_request_bp = Blueprint("service_request", __name__, template_folder="templates")

service_request_control = ServiceRequestControl()


@service_request_bp.app_template_filter("friendly_time")
def _friendlyTime(value: str) -> str:
    """'2026-11-11 14:00:00' -> 'Wed 11 Nov 2026, 2:00 PM'"""
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return value or ""
    return dt.strftime("%a %d %b %Y, %I:%M %p").replace(", 0", ", ")


class ServiceRequestBoundary:
    """<<boundary>> :ServiceRequestBoundary"""

    @staticmethod
    def _isDesigner():
        return "user_id" in session and session.get("role") == "Interior Designer"

    @staticmethod
    @service_request_bp.route("/designer/requests", methods=["GET"])
    def processServiceRequest():
        if not ServiceRequestBoundary._isDesigner():
            flash("Unauthorised: Please log in as an Interior Designer.", "danger")
            return redirect(url_for("auth.authenticateLogin"))

        status_filter = request.args.get("status", "")
        selected_id = request.args.get("selected_id")
        try:
            request_list, selected = service_request_control.processServiceRequest(
                actor_role=session["role"],
                designer_user_id=session["user_id"],
                status_filter=status_filter,
                selected_request_id=selected_id
            )
        except (PermissionError, LookupError) as e:
            flash(str(e), "danger")
            return redirect(url_for("service_request.processServiceRequest"))

        progress_history = []

        if selected:
            progress_history = service_request_control.getRenovationProgress(
                designer_user_id=session["user_id"],
                request_id=selected["request"]["request_id"]
            )

        return render_template(
            "service_requests.html",
            requests=request_list,
            selected=selected,
            status_filter=status_filter,
            statuses=service_request_control.REQUEST_STATUSES,
            progress_history=progress_history
        )
    
    @staticmethod
    @service_request_bp.route("/designer/requests/<request_id>/estimate", methods=["POST"])
    def generateItemisedCostEstimate(request_id):
        if not ServiceRequestBoundary._isDesigner():
            return redirect(url_for("auth.authenticateLogin"))

        descriptions = request.form.getlist("item_description")
        amounts = request.form.getlist("item_amount")
        items = [{"description": d, "amount": a} for d, a in zip(descriptions, amounts)]
        try:
            ok, msg = service_request_control.generateItemisedCostEstimate(
                actor_role=session["role"],
                designer_user_id=session["user_id"],
                request_id=request_id,
                items=items,
                scope=request.form.get("scope", ""),
                exclusions=request.form.get("exclusions", "")
            )
        except (PermissionError, LookupError) as e:
            flash(str(e), "danger")
            return redirect(url_for("service_request.processServiceRequest"))

        flash(msg, ("warning" if "over the customer's budget" in msg else "success") if ok else "danger")
        return redirect(url_for("service_request.processServiceRequest", selected_id=request_id))
    @staticmethod
    @service_request_bp.route(
        "/designer/requests/<request_id>/progress",
        methods=["POST"]
    )
    def updateRenovationProgress(request_id):
        if not ServiceRequestBoundary._isDesigner():
            flash("Unauthorised: Please log in as an Interior Designer.", "danger")
            return redirect(url_for("auth.authenticateLogin"))

        try:
            completion_percentage = int(
                request.form.get("completion_percentage", "")
            )

            ok, msg = service_request_control.updateRenovationProgress(
                designer_user_id=session["user_id"],
                request_id=request_id,
                stage=request.form.get("stage", ""),
                completion_percentage=completion_percentage,
                note=request.form.get("note", "")
            )

        except ValueError:
            ok, msg = False, "Please enter a valid completion percentage."

        except (PermissionError, LookupError) as e:
            flash(str(e), "danger")
            return redirect(
                url_for(
                    "service_request.processServiceRequest",
                    selected_id=request_id
                )
            )

        flash(msg, "success" if ok else "danger")

        return redirect(
            url_for(
                "service_request.processServiceRequest",
                selected_id=request_id
            )
        )

    @staticmethod
    @service_request_bp.route("/designer/requests/<request_id>/consultation", methods=["POST"])
    def acceptDeclineOrProposeTime(request_id):
        if not ServiceRequestBoundary._isDesigner():
            return redirect(url_for("auth.authenticateLogin"))

        try:
            ok, msg = service_request_control.acceptDeclineOrProposeTime(
                actor_role=session["role"],
                designer_user_id=session["user_id"],
                request_id=request_id,
                decision=request.form.get("decision", ""),
                slot_id=request.form.get("slot_id") or None,
                note=request.form.get("note", "")
            )
        except (PermissionError, LookupError) as e:
            flash(str(e), "danger")
            return redirect(url_for("service_request.processServiceRequest"))

        flash(msg, "success" if ok else "danger")
        return redirect(url_for("service_request.processServiceRequest", selected_id=request_id))
