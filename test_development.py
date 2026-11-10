import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from controls import UserAuthControl, AccountAdminControl
from entities import RegisteredUser, VerificationEvidence

class TestUserAuthAndAdminBCE(unittest.TestCase):
    def setUp(self):
        self.auth = UserAuthControl()
        self.admin = AccountAdminControl()

    def test_01_login_validation_success_with_pbkdf2_hash_and_picture_captcha(self):
        challenge = self.auth.generateHumanVerificationChallenge()
        expected = challenge["expected_answer"]
        selected_list = expected.split(",")
        ok, msg, user = self.auth.authenticateLogin(
            identifier="admin@help314id.sg",
            password="password123",
            human_answer=selected_list,
            expected_human_answer=expected,
            human_checkbox=True
        )
        self.assertTrue(ok)
        self.assertEqual(user["role"], "User Admin")
        self.assertTrue(user["password"].startswith("pbkdf2_sha256$"))

    def test_02_picture_captcha_blocks_wrong_selection(self):
        ok, msg, user = self.auth.authenticateLogin(
            identifier="admin@help314id.sg",
            password="password123",
            human_answer=["car", "plane", "burger"],
            expected_human_answer="lamp,plan,sofa",
            human_checkbox=True
        )
        self.assertFalse(ok)
        self.assertIn("Human verification", msg)

    def test_03_password_hashing_salted_and_verified(self):
        hashed = RegisteredUser.hashPassword("my_secret_pw")
        self.assertTrue(hashed.startswith("pbkdf2_sha256$100000$"))
        self.assertTrue(RegisteredUser.verifyPassword(hashed, "my_secret_pw"))
        self.assertFalse(RegisteredUser.verifyPassword(hashed, "wrong_pw"))

    def test_04_manage_user_accounts_permission_guard(self):
        with self.assertRaises(PermissionError):
            self.admin.manageUserAccounts(actor_role="Customer")

    def test_05_manage_user_accounts_search_filter(self):
        accounts, selected = self.admin.manageUserAccounts(
            actor_role="User Admin",
            role_filter="Interior Designer"
        )
        self.assertGreaterEqual(len(accounts), 100)
        self.assertIsNotNone(selected)

    def test_06_moderate_and_reactivate_account(self):
        ok_deact = self.admin.moderateOrDeactivateAccounts("User Admin", "1", "3", "Deactivated")
        self.assertTrue(ok_deact)
        self.assertEqual(RegisteredUser.findById("3")["status"], "Deactivated")

        ok_react = self.admin.moderateOrDeactivateAccounts("User Admin", "1", "3", "Active")
        self.assertTrue(ok_react)
        self.assertEqual(RegisteredUser.findById("3")["status"], "Active")

    def test_07_resolving_duplicate_removes_cluster_from_active_list(self):
        groups_before = self.admin.getDuplicateGroups("User Admin")
        initial_count = len(groups_before)
        self.assertGreaterEqual(initial_count, 1)
        dup_id = groups_before[0][-1]["user_id"]

        ok = self.admin.identifyRemoveDuplicates("User Admin", "1", dup_id)
        self.assertTrue(ok)
        groups_after = self.admin.getDuplicateGroups("User Admin")
        self.assertEqual(len(groups_after), initial_count - 1)

        # Restore so demo data stays rich
        RegisteredUser.changeAccountStatus(dup_id, "Active")

    def test_08_verifying_business_moves_from_pending_to_listed_directory(self):
        pending_before = self.admin.getPendingBusinessVerifications("User Admin")
        self.assertGreaterEqual(len(pending_before), 1)
        ev_id = pending_before[0]["evidence_id"]

        ok = self.admin.verifyBusinessRegistration("User Admin", "1", ev_id, "Verified", "Approved UEN")
        self.assertTrue(ok)

        pending_after = self.admin.getPendingBusinessVerifications("User Admin")
        self.assertEqual(len(pending_after), len(pending_before) - 1)

        listed, selected = self.admin.manageListedBusinesses("User Admin", selected_evidence_id=ev_id)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["listing_status"], "Active")

        # Restore back to Pending for demo
        VerificationEvidence.updateVerifiedBusinessListing(ev_id, listing_status="Revoked")

    def test_09_manage_and_moderate_listed_verified_businesses(self):
        listed, selected = self.admin.manageListedBusinesses("User Admin")
        self.assertGreaterEqual(len(listed), 50)
        target_id = selected["evidence_id"]

        ok_susp = self.admin.moderateVerifiedBusiness(
            "User Admin", "1", target_id,
            listing_status="Suspended",
            specialty="Condo & Luxury Specialist",
            remarks="Temporary compliance check"
        )
        self.assertTrue(ok_susp)
        updated = VerificationEvidence.getEvidenceById(target_id)
        self.assertEqual(updated["listing_status"], "Suspended")
        self.assertEqual(updated["specialty"], "Condo & Luxury Specialist")

        # Restore to Active
        self.admin.moderateVerifiedBusiness("User Admin", "1", target_id, listing_status="Active")

    def test_10_ai_todo_clears_both_duplicate_and_verification_queues(self):
        todos = self.admin.generateAiAdminTodoList("User Admin")
        self.assertGreaterEqual(len(todos), 1)
        first_item = todos[0]
        ok, msg = self.admin.executeAiAdminAction(
            actor_role="User Admin",
            admin_user_id="1",
            task_type=first_item["task_type"],
            target_id=first_item["target_id"],
            admin_reply="Yes, confirm and execute"
        )
        self.assertTrue(ok)
        todos_after = self.admin.generateAiAdminTodoList("User Admin")
        self.assertEqual(len(todos_after), len(todos) - 1)

        # Restore demo state
        if first_item["task_type"] == "duplicate":
            RegisteredUser.changeAccountStatus(first_item["target_id"], "Active")
        else:
            VerificationEvidence.updateVerifiedBusinessListing(first_item["target_id"], listing_status="Revoked")

    def test_11_platform_management_has_admin_access(self):
        accounts, selected = self.admin.manageUserAccounts(
            actor_role="Platform Management",
            role_filter="Customer"
        )
        self.assertGreaterEqual(len(accounts), 100)
        self.assertIsNotNone(selected)

if __name__ == "__main__":
    unittest.main()
