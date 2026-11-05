from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from controls import UserAuthControl, AccountAdminControl
from entities import RegisteredUser, VerificationEvidence

auth_bp = Blueprint("auth", __name__)
admin_bp = Blueprint("admin", __name__)

auth_control = UserAuthControl()
admin_control = AccountAdminControl()


def _refresh_human_challenge():
    challenge = auth_control.generateHumanVerificationChallenge()
    session["human_prompt"] = challenge["prompt"]
    session["human_tiles"] = challenge["tiles"]
    session["human_answer"] = challenge["expected_answer"]
    return challenge


class UserAuthBoundary:
    """<<boundary>> :UserAuthBoundary"""

    @staticmethod
    @auth_bp.route("/", methods=["GET"])
    @auth_bp.route("/home", methods=["GET"])
    def homePage():
        current_user = None
        role = "Guest"
        if "user_id" in session:
            current_user = RegisteredUser.findById(session["user_id"])
            role = session.get("role", "Customer")

        pending_list = VerificationEvidence.getPendingEvidence()
        dup_list = RegisteredUser.findPotentialDuplicates(include_resolved=False)
        listed_biz_list = VerificationEvidence.searchListedBusinesses()

        stats = {
            "total_users": len(RegisteredUser.getAccountRecords()),
            "total_designers": len(RegisteredUser.getAccountRecords(role_filter="Interior Designer")),
            "total_customers": len(RegisteredUser.getAccountRecords(role_filter="Customer")),
            "pending_verifications": len(pending_list),
            "duplicate_clusters": len(dup_list),
            "listed_businesses": len(listed_biz_list)
        }

        featured_projects = [
            {
                "idp_id": 101,
                "title": "Japandi 4-Room HDB at Bidadari Park Drive",
                "designer": "Chloe Tan Studio",
                "style": "Japandi",
                "property_type": "4-Room HDB",
                "estimated_cost_sgd": "48,000",
                "views_count": 1420,
                "shortlist_count": 38,
                "image_url": "https://picsum.photos/seed/idp101/600/400"
            },
            {
                "idp_id": 102,
                "title": "Modern Luxury Executive Condo at Tampines St 81",
                "designer": "Lim & Co Design Works",
                "style": "Modern Luxury",
                "property_type": "Executive Condo",
                "estimated_cost_sgd": "85,000",
                "views_count": 980,
                "shortlist_count": 29,
                "image_url": "https://picsum.photos/seed/idp102/600/400"
            },
            {
                "idp_id": 103,
                "title": "Scandinavian 5-Room HDB at Punggol Walk",
                "designer": "Spaces SG Atelier",
                "style": "Scandinavian",
                "property_type": "5-Room HDB",
                "estimated_cost_sgd": "56,000",
                "views_count": 1150,
                "shortlist_count": 44,
                "image_url": "https://picsum.photos/seed/idp103/600/400"
            }
        ]

        return render_template(
            "home.html",
            user=current_user,
            role=role,
            stats=stats,
            featured_projects=featured_projects
        )

    @staticmethod
    @auth_bp.route("/login", methods=["GET", "POST"])
    def authenticateLogin():
        if request.method == "POST":
            identifier = request.form.get("identifier", "")
            password = request.form.get("password", "")
            selected_pics = request.form.getlist("captcha_picks")
            human_checkbox = request.form.get("human_checkbox") == "on"
            expected_answer = session.get("human_answer", "")

            ok, msg, user = auth_control.authenticateLogin(
                identifier=identifier,
                password=password,
                human_answer=selected_pics,
                expected_human_answer=expected_answer,
                human_checkbox=human_checkbox
            )
            if ok and user:
                session["user_id"] = user["user_id"]
                session["username"] = user["username"]
                session["full_name"] = user["full_name"]
                session["role"] = user["role"]
                session["email"] = user["email"]
                flash(f"Welcome back, {user['full_name']} ({user['role']})!", "success")
                return redirect(url_for("auth.homePage"))
            flash(msg, "danger")

        challenge = _refresh_human_challenge()
        return render_template("auth.html", active_panel="login", captcha=challenge)

    @staticmethod
    @auth_bp.route("/register", methods=["GET", "POST"])
    def registerAccount():
        if request.method == "POST":
            username = request.form.get("username", "")
            email = request.form.get("email", "")
            password = request.form.get("password", "")
            full_name = request.form.get("full_name", "")
            phone = request.form.get("phone", "")
            role = request.form.get("role", "Customer")
            selected_pics = request.form.getlist("captcha_picks")
            human_checkbox = request.form.get("human_checkbox") == "on"
            expected_answer = session.get("human_answer", "")

            ok, msg, _ = auth_control.registerAccount(
                username=username,
                email=email,
                password=password,
                full_name=full_name,
                phone=phone,
                role=role,
                human_answer=selected_pics,
                expected_human_answer=expected_answer,
                human_checkbox=human_checkbox
            )
            if ok:
                flash(msg, "success")
                return redirect(url_for("auth.authenticateLogin"))
            flash(msg, "danger")

        challenge = _refresh_human_challenge()
        return render_template("auth.html", active_panel="register", captcha=challenge)

    @staticmethod
    @auth_bp.route("/recover", methods=["GET", "POST"])
    def resetForgottenPassword():
        step = request.args.get("step", "request")
        demo_token = session.get("demo_reset_token")
        demo_email = session.get("demo_reset_email")

        if request.method == "POST":
            action = request.form.get("action")
            if action == "dispatch_email":
                email = request.form.get("email", "")
                selected_pics = request.form.getlist("captcha_picks")
                human_checkbox = request.form.get("human_checkbox") == "on"
                expected_answer = session.get("human_answer", "")

                ok, msg, token = auth_control.dispatchRecoveryEmail(
                    email=email,
                    human_answer=selected_pics,
                    expected_human_answer=expected_answer,
                    human_checkbox=human_checkbox
                )
                if ok:
                    session["demo_reset_token"] = token
                    session["demo_reset_email"] = email
                    flash(f"{msg} (Simulated Recovery Token: {token})", "info")
                    return redirect(url_for("auth.resetForgottenPassword", step="verify"))
                flash(msg, "danger")
            elif action == "confirm_reset":
                email = request.form.get("email", "")
                token = request.form.get("token", "")
                new_password = request.form.get("new_password", "")
                ok, msg = auth_control.resetForgottenPassword(email, token, new_password)
                if ok:
                    session.pop("demo_reset_token", None)
                    session.pop("demo_reset_email", None)
                    flash(msg, "success")
                    return redirect(url_for("auth.authenticateLogin"))
                flash(msg, "danger")
                step = "verify"

        challenge = _refresh_human_challenge()
        return render_template(
            "auth.html",
            active_panel="recover",
            step=step,
            demo_token=demo_token,
            demo_email=demo_email,
            captcha=challenge
        )

    @staticmethod
    @auth_bp.route("/profile", methods=["GET", "POST"])
    def managePersonalProfile():
        if "user_id" not in session:
            return redirect(url_for("auth.authenticateLogin"))

        user_id = session["user_id"]
        if request.method == "POST":
            form_type = request.form.get("form_type")
            if form_type == "profile":
                full_name = request.form.get("full_name", "")
                phone = request.form.get("phone", "")
                email = request.form.get("email", "")
                ok, msg = auth_control.managePersonalProfile(user_id, full_name, phone, email)
                if ok:
                    session["full_name"] = full_name
                    session["email"] = email
                flash(msg, "success" if ok else "danger")
            elif form_type == "notifications":
                notify_email = request.form.get("notify_email") == "on"
                notify_sms = request.form.get("notify_sms") == "on"
                notify_marketing = request.form.get("notify_marketing") == "on"
                ok, msg = auth_control.configureNotificationPreferences(user_id, notify_email, notify_sms, notify_marketing)
                flash(msg, "success" if ok else "danger")

        current_user = RegisteredUser.findById(user_id)
        return render_template("profile.html", user=current_user)

    @staticmethod
    @auth_bp.route("/logout")
    def logOut():
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("auth.homePage"))


class AccountAdminBoundary:
    """<<boundary>> :AccountAdminBoundary"""

    @staticmethod
    @admin_bp.route("/admin/accounts", methods=["GET"])
    def manageUserAccounts():
        if "user_id" not in session or session.get("role") not in ("User Admin", "Platform Management"):
            flash("Unauthorised: Please log in as a User Admin or Platform Management.", "danger")
            return redirect(url_for("auth.authenticateLogin"))

        # Tab 1: Search, Inspect & Moderate User Accounts
        search_q = request.args.get("q", "")
        role_filter = request.args.get("role", "")
        status_filter = request.args.get("status", "")
        selected_id = request.args.get("selected_id")
        active_tab = request.args.get("tab", "accounts")

        # Tab 4: Search, Inspect & Moderate Listed Verified Businesses
        biz_q = request.args.get("biz_q", "")
        biz_specialty = request.args.get("biz_specialty", "")
        biz_status = request.args.get("biz_status", "")
        selected_biz_id = request.args.get("selected_biz_id")

        account_list, selected_account = admin_control.manageUserAccounts(
            actor_role=session["role"],
            search_query=search_q,
            role_filter=role_filter,
            status_filter=status_filter,
            selected_user_id=selected_id
        )
        duplicate_groups = admin_control.getDuplicateGroups(session["role"])
        resolved_duplicates = admin_control.getResolvedDuplicatesList(session["role"])
        pending_evidence_list = admin_control.getPendingBusinessVerifications(session["role"])
        listed_businesses, selected_business = admin_control.manageListedBusinesses(
            actor_role=session["role"],
            search_query=biz_q,
            specialty_filter=biz_specialty,
            listing_status_filter=biz_status,
            selected_evidence_id=selected_biz_id
        )
        audit_log = admin_control.viewAccountAuditLog(session["role"])
        ai_todos = admin_control.generateAiAdminTodoList(session["role"])

        return render_template(
            "admin_dashboard.html",
            accounts=account_list,
            selected_account=selected_account,
            duplicate_groups=duplicate_groups,
            resolved_duplicates=resolved_duplicates,
            evidence_list=pending_evidence_list,
            listed_businesses=listed_businesses,
            selected_business=selected_business,
            audit_log=audit_log,
            ai_todos=ai_todos,
            search_q=search_q,
            role_filter=role_filter,
            status_filter=status_filter,
            biz_q=biz_q,
            biz_specialty=biz_specialty,
            biz_status=biz_status,
            active_tab=active_tab
        )

    @staticmethod
    @admin_bp.route("/admin/ai-todo/execute", methods=["POST"])
    def executeAiAdminTodo():
        if session.get("role") not in ("User Admin", "Platform Management"):
            return redirect(url_for("auth.authenticateLogin"))

        task_type = request.form.get("task_type", "")
        target_id = request.form.get("target_id", "")
        admin_reply = request.form.get("admin_reply", "Yes, proceed")

        ok, msg = admin_control.executeAiAdminAction(
            actor_role=session["role"],
            admin_user_id=session["user_id"],
            task_type=task_type,
            target_id=target_id,
            admin_reply=admin_reply
        )
        flash(msg, "success" if ok else "info")
        return redirect(url_for("admin.manageUserAccounts", tab="ai_assistant"))

    @staticmethod
    @admin_bp.route("/admin/duplicates/resolve", methods=["POST"])
    def identifyRemoveDuplicates():
        if session.get("role") not in ("User Admin", "Platform Management"):
            return redirect(url_for("auth.authenticateLogin"))

        dup_user_id = request.form.get("duplicate_user_id", "")
        ok = admin_control.identifyRemoveDuplicates(
            actor_role=session["role"],
            admin_user_id=session["user_id"],
            duplicate_user_id=dup_user_id
        )
        if ok:
            flash(f"Duplicate account #{dup_user_id} disabled and removed from the active duplicate queue.", "warning")
        else:
            flash("Could not resolve duplicate account.", "danger")
        return redirect(url_for("admin.manageUserAccounts", tab="duplicates"))

    @staticmethod
    @admin_bp.route("/admin/accounts/moderate", methods=["POST"])
    def moderateOrDeactivateAccounts():
        if session.get("role") not in ("User Admin", "Platform Management"):
            return redirect(url_for("auth.authenticateLogin"))

        target_user_id = request.form.get("target_user_id", "")
        selected_status = request.form.get("selected_status", "Deactivated")
        return_tab = request.form.get("return_tab", "accounts")
        ok = admin_control.moderateOrDeactivateAccounts(
            actor_role=session["role"],
            admin_user_id=session["user_id"],
            target_user_id=target_user_id,
            selected_status=selected_status
        )
        if ok:
            flash(f"Account #{target_user_id} status updated to {selected_status}.", "success")
        else:
            flash("Failed to update account status.", "danger")
        return redirect(url_for("admin.manageUserAccounts", selected_id=target_user_id, tab=return_tab))

    @staticmethod
    @admin_bp.route("/admin/accounts/role", methods=["POST"])
    def assignUpdateAccountRole():
        if session.get("role") not in ("User Admin", "Platform Management"):
            return redirect(url_for("auth.authenticateLogin"))

        target_user_id = request.form.get("target_user_id", "")
        new_role = request.form.get("new_role", "Customer")
        ok = admin_control.assignUpdateAccountRole(
            actor_role=session["role"],
            admin_user_id=session["user_id"],
            target_user_id=target_user_id,
            new_role=new_role
        )
        if ok:
            flash(f"Account #{target_user_id} role updated to {new_role}.", "success")
        else:
            flash("Failed to update role.", "danger")
        return redirect(url_for("admin.manageUserAccounts", selected_id=target_user_id, tab="accounts"))

    @staticmethod
    @admin_bp.route("/admin/verification/verify", methods=["POST"])
    def verifyBusinessRegistration():
        if session.get("role") not in ("User Admin", "Platform Management"):
            return redirect(url_for("auth.authenticateLogin"))

        evidence_id = request.form.get("evidence_id", "")
        outcome = request.form.get("outcome", "Verified")
        remarks = request.form.get("remarks", "")
        ok = admin_control.verifyBusinessRegistration(
            actor_role=session["role"],
            admin_user_id=session["user_id"],
            evidence_id=evidence_id,
            outcome=outcome,
            remarks=remarks
        )
        if ok:
            if outcome == "Verified":
                flash(f"Business #{evidence_id} approved and added to the Listed Verified Businesses directory!", "success")
            else:
                flash(f"Business #{evidence_id} registration marked as Rejected.", "warning")
        else:
            flash("Verification review failed.", "danger")
        return redirect(url_for("admin.manageUserAccounts", tab="verification"))

    @staticmethod
    @admin_bp.route("/admin/businesses/moderate", methods=["POST"])
    def moderateListedBusiness():
        if session.get("role") not in ("User Admin", "Platform Management"):
            return redirect(url_for("auth.authenticateLogin"))

        evidence_id = request.form.get("evidence_id", "")
        listing_status = request.form.get("listing_status")
        specialty = request.form.get("specialty")
        remarks = request.form.get("remarks", "")

        ok = admin_control.moderateVerifiedBusiness(
            actor_role=session["role"],
            admin_user_id=session["user_id"],
            evidence_id=evidence_id,
            listing_status=listing_status,
            specialty=specialty,
            remarks=remarks
        )
        if ok:
            if listing_status == "Revoked":
                flash(f"Business #{evidence_id} verification revoked and returned to Pending Verification queue.", "warning")
            else:
                flash(f"Verified Business #{evidence_id} updated successfully.", "success")
        else:
            flash("Failed to update verified business.", "danger")
        return redirect(url_for("admin.manageUserAccounts", tab="listed_businesses", selected_biz_id=evidence_id))

    @staticmethod
    @admin_bp.route("/admin/audit", methods=["GET"])
    def viewAccountAuditLog():
        return redirect(url_for("admin.manageUserAccounts", tab="audit"))
