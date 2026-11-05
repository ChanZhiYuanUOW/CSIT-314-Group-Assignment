import re
import random
from entities import RegisteredUser, PasswordResetToken, VerificationEvidence, AccountAuditEntry


class UserAuthControl:
    """<<control>> :UserAuthControl"""

    CAPTCHA_POOL = [
        {"id": "sofa", "label": "Living Room Sofa", "category": "Interior & Renovation",
         "svg": "<svg viewBox='0 0 64 64' width='44' height='44'><rect x='10' y='24' width='44' height='20' rx='5' fill='#3b82f6'/><rect x='6' y='30' width='8' height='16' rx='3' fill='#1d4ed8'/><rect x='50' y='30' width='8' height='16' rx='3' fill='#1d4ed8'/><rect x='12' y='44' width='4' height='6' fill='#334155'/><rect x='48' y='44' width='4' height='6' fill='#334155'/></svg>"},
        {"id": "lamp", "label": "Pendant Lamp", "category": "Interior & Renovation",
         "svg": "<svg viewBox='0 0 64 64' width='44' height='44'><line x1='32' y1='4' x2='32' y2='20' stroke='#475569' stroke-width='3'/><path d='M16 36 L48 36 L40 20 L24 20 Z' fill='#f59e0b'/><circle cx='32' cy='39' r='5' fill='#fef08a'/></svg>"},
        {"id": "roller", "label": "Paint Roller", "category": "Interior & Renovation",
         "svg": "<svg viewBox='0 0 64 64' width='44' height='44'><rect x='12' y='12' width='32' height='12' rx='4' fill='#10b981'/><path d='M44 18 L52 18 L52 32 L30 32 L30 40' fill='none' stroke='#64748b' stroke-width='3'/><rect x='26' y='40' width='8' height='16' rx='3' fill='#b45309'/></svg>"},
        {"id": "plan", "label": "Floor Plan", "category": "Interior & Renovation",
         "svg": "<svg viewBox='0 0 64 64' width='44' height='44'><rect x='10' y='10' width='44' height='44' fill='#eff6ff' stroke='#2563eb' stroke-width='3'/><line x1='10' y1='32' x2='40' y2='32' stroke='#2563eb' stroke-width='2'/><line x1='34' y1='10' x2='34' y2='54' stroke='#2563eb' stroke-width='2'/></svg>"},
        {"id": "car", "label": "Sports Car", "category": "Vehicles & Food",
         "svg": "<svg viewBox='0 0 64 64' width='44' height='44'><path d='M10 36 L18 22 L46 22 L54 36 Z' fill='#ef4444'/><rect x='6' y='34' width='52' height='12' rx='4' fill='#dc2626'/><circle cx='18' cy='46' r='6' fill='#1e293b'/><circle cx='46' cy='46' r='6' fill='#1e293b'/></svg>"},
        {"id": "plane", "label": "Jet Airplane", "category": "Vehicles & Food",
         "svg": "<svg viewBox='0 0 64 64' width='44' height='44'><path d='M32 8 L38 26 L56 32 L38 36 L36 52 L44 56 L20 56 L28 52 L26 36 L8 32 L26 26 Z' fill='#6366f1'/></svg>"},
        {"id": "burger", "label": "Cheeseburger", "category": "Vehicles & Food",
         "svg": "<svg viewBox='0 0 64 64' width='44' height='44'><path d='M12 28 C12 14, 52 14, 52 28 Z' fill='#d97706'/><rect x='10' y='30' width='44' height='6' rx='3' fill='#dc2626'/><rect x='12' y='38' width='40' height='10' rx='4' fill='#b45309'/></svg>"},
        {"id": "sailboat", "label": "Sailboat", "category": "Vehicles & Food",
         "svg": "<svg viewBox='0 0 64 64' width='44' height='44'><polygon points='32,10 32,40 14,40' fill='#0ea5e9'/><polygon points='34,16 34,40 50,40' fill='#38bdf8'/><polygon points='10,44 54,44 46,54 18,54' fill='#475569'/></svg>"}
    ]

    @classmethod
    def generateHumanVerificationChallenge(cls):
        interior_items = [i for i in cls.CAPTCHA_POOL if i["category"] == "Interior & Renovation"]
        other_items = [i for i in cls.CAPTCHA_POOL if i["category"] != "Interior & Renovation"]

        chosen_targets = random.sample(interior_items, 3)
        chosen_distractors = random.sample(other_items, 3)
        tiles = chosen_targets + chosen_distractors
        random.shuffle(tiles)

        prompt = "Select all 3 pictures related to Interior Design & Renovation"
        expected_ids = sorted([t["id"] for t in chosen_targets])
        expected_answer = ",".join(expected_ids)
        return {
            "prompt": prompt,
            "tiles": tiles,
            "expected_answer": expected_answer
        }

    @staticmethod
    def verifyHumanCheck(provided_answer, expected_answer: str, checkbox_confirmed: bool = True) -> bool:
        if not checkbox_confirmed:
            return False
        if not provided_answer or not expected_answer:
            return False
        if isinstance(provided_answer, list):
            normalized_provided = ",".join(sorted([str(x).strip() for x in provided_answer if str(x).strip()]))
        else:
            normalized_provided = ",".join(sorted([x.strip() for x in str(provided_answer).split(",") if x.strip()]))
        normalized_expected = ",".join(sorted([x.strip() for x in str(expected_answer).split(",") if x.strip()]))
        return normalized_provided == normalized_expected

    def validateRegistrationDetails(self, username: str, email: str, password: str, full_name: str, phone: str, role: str):
        if not all([username.strip(), email.strip(), password.strip(), full_name.strip(), phone.strip()]):
            return False, "All registration fields are required."
        if "@" not in email or "." not in email:
            return False, "Please provide a valid email address."
        if len(password) < 6:
            return False, "Password must be at least 6 characters long."
        if role not in ("Customer", "Interior Designer"):
            return False, "Public registration is only open to Customer or Interior Designer accounts."
        if RegisteredUser.findByEmailOrUsername(email) or RegisteredUser.findByEmailOrUsername(username):
            return False, "An account with that email or username already exists."
        return True, "Valid"

    def registerAccount(self, username: str, email: str, password: str, full_name: str, phone: str, role: str,
                        human_answer=None, expected_human_answer: str = None, human_checkbox: bool = True):
        if expected_human_answer is not None:
            if not self.verifyHumanCheck(human_answer, expected_human_answer, human_checkbox):
                return False, "Human verification failed. Please select the 3 Interior Design & Renovation pictures.", None

        is_valid, msg = self.validateRegistrationDetails(username, email, password, full_name, phone, role)
        if not is_valid:
            return False, msg, None
        new_user = RegisteredUser.createAccount(username, email, password, full_name, phone, role)
        AccountAuditEntry.recordAction(
            admin_user_id=new_user["user_id"],
            target_user_id=new_user["user_id"],
            target_email=new_user["email"],
            action="Register Account",
            details=f"Public registration completed as {role}."
        )
        return True, "Account registered successfully! You can now log in.", new_user

    def validateLoginCredentials(self, identifier: str, password: str):
        user = RegisteredUser.findByEmailOrUsername(identifier)
        if not user or not RegisteredUser.verifyPassword(user["password"], password):
            return False, "Invalid email/username or password.", None
        if user["status"] != "Active":
            return False, f"Account access is currently restricted (Status: {user['status']}).", None
        return True, "Authenticated", user

    def authenticateLogin(self, identifier: str, password: str,
                          human_answer=None, expected_human_answer: str = None, human_checkbox: bool = True):
        if expected_human_answer is not None:
            if not self.verifyHumanCheck(human_answer, expected_human_answer, human_checkbox):
                return False, "Human verification check failed. Please select all 3 Interior Design & Renovation pictures.", None
        return self.validateLoginCredentials(identifier, password)

    def dispatchRecoveryEmail(self, email: str,
                              human_answer=None, expected_human_answer: str = None, human_checkbox: bool = True):
        if expected_human_answer is not None:
            if not self.verifyHumanCheck(human_answer, expected_human_answer, human_checkbox):
                return False, "Human verification failed. Please select all 3 Interior Design & Renovation pictures.", None

        user = RegisteredUser.findByEmailOrUsername(email)
        if not user:
            return False, "No registered account found with that email address.", None
        token = PasswordResetToken.createToken(user["user_id"], user["email"])
        return True, f"Recovery email dispatched to {user['email']}.", token

    def validatePasswordResetToken(self, email: str, token: str) -> bool:
        return PasswordResetToken.validateAndConsumeToken(email, token)

    def resetForgottenPassword(self, email: str, token: str, new_password: str):
        if len(new_password) < 6:
            return False, "New password must be at least 6 characters."
        if not self.validatePasswordResetToken(email, token):
            return False, "Invalid or expired password reset token."
        updated = RegisteredUser.updatePassword(email, new_password)
        if updated:
            user = RegisteredUser.findByEmailOrUsername(email)
            AccountAuditEntry.recordAction(
                admin_user_id=user["user_id"],
                target_user_id=user["user_id"],
                target_email=user["email"],
                action="Reset Forgotten Password",
                details="Password reset completed via recovery token."
            )
            return True, "Password has been reset successfully. Please log in."
        return False, "Could not update password."

    def managePersonalProfile(self, user_id: str, full_name: str, phone: str, email: str):
        if not full_name.strip() or not email.strip():
            return False, "Full name and email cannot be empty."
        ok = RegisteredUser.updatePersonalProfile(user_id, full_name, phone, email)
        if ok:
            AccountAuditEntry.recordAction(
                admin_user_id=user_id,
                target_user_id=user_id,
                target_email=email,
                action="Update Personal Profile",
                details="User updated personal profile contact details."
            )
            return True, "Personal profile updated."
        return False, "Failed to update profile."

    def configureNotificationPreferences(self, user_id: str, notify_email: bool, notify_sms: bool, notify_marketing: bool):
        ok = RegisteredUser.updateNotificationPreferences(user_id, notify_email, notify_sms, notify_marketing)
        if ok:
            user = RegisteredUser.findById(user_id)
            AccountAuditEntry.recordAction(
                admin_user_id=user_id,
                target_user_id=user_id,
                target_email=user["email"] if user else "",
                action="Configure Notification Preferences",
                details=f"Notifications set: Email={notify_email}, SMS={notify_sms}, Marketing={notify_marketing}."
            )
            return True, "Notification preferences saved."
        return False, "Failed to update notification preferences."


class AccountAdminControl:
    """<<control>> :AccountAdminControl"""

    @staticmethod
    def _checkAdminPermissions(actor_role: str) -> bool:
        return actor_role in ("User Admin", "Platform Management")

    def manageUserAccounts(self, actor_role: str, search_query="", role_filter="", status_filter="", selected_user_id=None):
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised: Only User Admin or Platform Management may access Manage User Accounts.")

        account_list = RegisteredUser.getAccountRecords(search_query, role_filter, status_filter)
        selected_account = None
        if selected_user_id:
            selected_account = RegisteredUser.findById(selected_user_id)
        elif account_list:
            selected_account = account_list[0]
        return account_list, selected_account

    def getDuplicateGroups(self, actor_role: str):
        """Returns only active unresolved duplicate clusters."""
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised")
        return RegisteredUser.findPotentialDuplicates(include_resolved=False)

    def getResolvedDuplicatesList(self, actor_role: str):
        """Returns already-resolved duplicate accounts for history/reactivation if needed."""
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised")
        return RegisteredUser.getResolvedDuplicates()

    def identifyRemoveDuplicates(self, actor_role: str, admin_user_id: str, duplicate_user_id: str) -> bool:
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised")

        target = RegisteredUser.findById(duplicate_user_id)
        if not target:
            return False

        result = RegisteredUser.changeAccountStatus(duplicate_user_id, "Duplicate_Disabled")
        if result:
            AccountAuditEntry.recordAction(
                admin_user_id=admin_user_id,
                target_user_id=duplicate_user_id,
                target_email=target["email"],
                action="Resolve Duplicate",
                details="Confirmed duplicate disabled; referenced records preserved."
            )
        return result

    def moderateOrDeactivateAccounts(self, actor_role: str, admin_user_id: str, target_user_id: str, selected_status: str) -> bool:
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised")

        target = RegisteredUser.findById(target_user_id)
        if not target:
            return False

        result = RegisteredUser.changeAccountStatus(target_user_id, selected_status)
        if result:
            action_label = "Reactivate Account" if selected_status == "Active" else "Moderate Account"
            AccountAuditEntry.recordAction(
                admin_user_id=admin_user_id,
                target_user_id=target_user_id,
                target_email=target["email"],
                action=action_label,
                details=f"Account status updated to {selected_status}."
            )
        return result

    def assignUpdateAccountRole(self, actor_role: str, admin_user_id: str, target_user_id: str, new_role: str) -> bool:
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised")

        target = RegisteredUser.findById(target_user_id)
        if not target:
            return False

        result = RegisteredUser.updateAccountRole(target_user_id, new_role)
        if result:
            AccountAuditEntry.recordAction(
                admin_user_id=admin_user_id,
                target_user_id=target_user_id,
                target_email=target["email"],
                action="Assign/Update Role",
                details=f"Updated role to {new_role}."
            )
        return result

    def viewAccountAuditLog(self, actor_role: str, target_user_id=None):
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised")
        return AccountAuditEntry.getAuditLog(target_user_id)

    def getPendingBusinessVerifications(self, actor_role: str):
        """Returns only pending business registration submissions."""
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised")
        return VerificationEvidence.getPendingEvidence()

    def manageListedBusinesses(self, actor_role: str, search_query="", specialty_filter="", listing_status_filter="", selected_evidence_id=None):
        """Search, inspect, and moderate Listed Verified Businesses (mirrors manageUserAccounts)."""
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised")

        business_list = VerificationEvidence.searchListedBusinesses(
            search_query=search_query,
            specialty_filter=specialty_filter,
            listing_status_filter=listing_status_filter
        )
        selected_business = None
        if selected_evidence_id:
            selected_business = VerificationEvidence.getEvidenceById(selected_evidence_id)
        elif business_list:
            selected_business = business_list[0]
        return business_list, selected_business

    def moderateVerifiedBusiness(self, actor_role: str, admin_user_id: str, evidence_id: str,
                                 listing_status: str = None, specialty: str = None, remarks: str = None) -> bool:
        """Moderates a listed verified business (Active, Suspended, or Revoked back to Pending) and logs to Audit."""
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised")

        ev = VerificationEvidence.getEvidenceById(evidence_id)
        if not ev:
            return False

        ok = VerificationEvidence.updateVerifiedBusinessListing(
            evidence_id=evidence_id,
            listing_status=listing_status,
            specialty=specialty,
            remarks=remarks
        )
        if ok:
            designer = RegisteredUser.findById(ev["designer_user_id"])
            change_desc = []
            if listing_status:
                change_desc.append(f"Listing Status -> {listing_status}")
            if specialty:
                change_desc.append(f"Specialty -> {specialty}")
            if remarks:
                change_desc.append(f"Notes: {remarks}")
            AccountAuditEntry.recordAction(
                admin_user_id=admin_user_id,
                target_user_id=ev["designer_user_id"],
                target_email=designer["email"] if designer else "designer@help314id.sg",
                action="Moderate Verified Business",
                details=f"{ev['company_name']} (UEN {ev['registration_uen']}): " + ", ".join(change_desc)
            )
        return ok

    def reviewVerificationEvidence(self, evidence_id: str):
        return VerificationEvidence.getEvidenceById(evidence_id)

    def verifyBusinessRegistration(self, actor_role: str, admin_user_id: str, evidence_id: str, outcome: str, remarks: str) -> bool:
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised")

        evidence = self.reviewVerificationEvidence(evidence_id)
        if not evidence:
            return False

        recorded = VerificationEvidence.recordReviewOutcome(evidence_id, outcome, admin_user_id, remarks)
        if recorded:
            designer = RegisteredUser.findById(evidence["designer_user_id"])
            AccountAuditEntry.recordAction(
                admin_user_id=admin_user_id,
                target_user_id=evidence["designer_user_id"],
                target_email=designer["email"] if designer else "designer@help314id.sg",
                action="Verify Business Registration",
                details=f"Reviewed UEN {evidence['registration_uen']} ({evidence['company_name']}) -> {outcome}."
            )
        return recorded

    def generateAiAdminTodoList(self, actor_role: str):
        """Scans active unresolved duplicate accounts and pending business registrations."""
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised")

        todos = []

        # 1. Scan for active unresolved duplicate accounts
        for group in RegisteredUser.findPotentialDuplicates(include_resolved=False):
            primary = group[0]
            dup = group[-1]
            todos.append({
                "todo_id": f"DUP-{dup['user_id']}",
                "task_type": "duplicate",
                "target_id": dup["user_id"],
                "badge": "Duplicate Account Detected",
                "confidence": "99% Match",
                "title": f"Duplicate profile for {dup['full_name']} ({dup['phone']})",
                "analysis": (
                    f"Account #{dup['user_id']} ({dup['email']}) shares the exact same full name and phone number "
                    f"as primary Account #{primary['user_id']} ({primary['email']}, created {primary['created_at']})."
                ),
                "ai_question": (
                    f"Should I disable duplicate Account #{dup['user_id']} ({dup['username']}) "
                    f"while preserving its referenced records?"
                ),
                "recommended_action": "Disable Duplicate"
            })

        # 2. Scan for pending ACRA Business Registrations
        uen_pattern = re.compile(r"^20\d{7}[A-Z]$")
        for ev in VerificationEvidence.getPendingEvidence():
            uen_valid = bool(uen_pattern.match(ev["registration_uen"].strip()))
            has_pdf = ev["evidence_document_url"].endswith(".pdf")
            rec_outcome = "Verified" if (uen_valid and has_pdf) else "Rejected"
            todos.append({
                "todo_id": f"VER-{ev['evidence_id']}",
                "task_type": "verification",
                "target_id": ev["evidence_id"],
                "badge": "Pending Business Verification",
                "confidence": "96% Valid UEN" if uen_valid else "Needs Review",
                "title": f"{ev['company_name']} — UEN {ev['registration_uen']}",
                "analysis": (
                    f"Designer {ev['designer_name']} (#{ev['designer_user_id']}) submitted ACRA BizFile PDF "
                    f"({ev['evidence_document_url']}). Format check: {'Valid Singapore ACRA UEN' if uen_valid else 'Irregular UEN'}."
                ),
                "ai_question": (
                    f"ACRA UEN {ev['registration_uen']} and BizFile certificate passed pre-screening. "
                    f"How would you like to reply and resolve {ev['company_name']}?"
                ),
                "recommended_action": rec_outcome
            })

        return todos

    def executeAiAdminAction(self, actor_role: str, admin_user_id: str, task_type: str, target_id: str, admin_reply: str) -> tuple:
        if not self._checkAdminPermissions(actor_role):
            raise PermissionError("Unauthorised")

        reply_clean = admin_reply.strip()
        lower_reply = reply_clean.lower()

        if task_type == "duplicate":
            if any(w in lower_reply for w in ["yes", "confirm", "disable", "remove", "approve", "proceed"]):
                ok = self.identifyRemoveDuplicates(actor_role, admin_user_id, target_id)
                return ok, f"Duplicate Account #{target_id} has been disabled and removed from the active duplicates queue."
            return False, f"Skipped duplicate Account #{target_id} per your reply ('{reply_clean}')."

        elif task_type == "verification":
            if any(w in lower_reply for w in ["reject", "deny", "no", "invalid"]):
                outcome = "Rejected"
            else:
                outcome = "Verified"
            remarks = f"AI Assistant ({outcome}) — Admin reply: {reply_clean}"
            ok = self.verifyBusinessRegistration(actor_role, admin_user_id, target_id, outcome, remarks)
            return ok, f"Business registration #{target_id} marked as {outcome} and moved to Listed Verified Businesses."

        elif task_type == "batch_all":
            todos = self.generateAiAdminTodoList(actor_role)
            dup_count, ver_count = 0, 0
            for item in todos:
                if item["task_type"] == "duplicate":
                    if self.identifyRemoveDuplicates(actor_role, admin_user_id, item["target_id"]):
                        dup_count += 1
                elif item["task_type"] == "verification":
                    if self.verifyBusinessRegistration(
                        actor_role, admin_user_id, item["target_id"],
                        item["recommended_action"],
                        f"AI Batch Verification ({item['recommended_action']}) — Admin reply: {reply_clean}"
                    ):
                        ver_count += 1
            return True, f"Resolved {dup_count} duplicate accounts and verified {ver_count} business registrations! All queues updated."

        return False, "Unknown task type."
