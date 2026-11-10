#!/usr/bin/env python3
"""
CSIT314 — Master Feature & Unit Test Verification Runner (PASS / FAIL Report)
Place this script in the root of CSIT-314-Group-Assignment-main and run:
    python3 check_all_features.py
"""
import os
import sys
import csv
import shutil
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

# ANSI color helpers for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _ensure_demo_seed_state_for_admin_tests():
    """Ensures at least 1 active duplicate cluster and 1 pending business verification
    exist in a temporary backup/restore context if someone previously clicked 'Resolve All' in the UI.
    Returns a restore callback so the repo's CSV files remain untouched after the check.
    """
    data_dir = os.path.join(REPO_ROOT, "data")
    users_csv = os.path.join(data_dir, "registered_users.csv")
    ver_csv = os.path.join(data_dir, "verification_evidence.csv")
    audit_csv = os.path.join(data_dir, "account_audit_entries.csv")
    tokens_csv = os.path.join(data_dir, "password_reset_tokens.csv")

    tmp_backup = tempfile.mkdtemp()
    backups = []
    for fpath in (users_csv, ver_csv, audit_csv, tokens_csv):
        if os.path.exists(fpath):
            bpath = os.path.join(tmp_backup, os.path.basename(fpath))
            shutil.copy2(fpath, bpath)
            backups.append((fpath, bpath))

    # If all _dup accounts were already marked Duplicate_Disabled in the repo, reactivate them for the test run
    if os.path.exists(users_csv):
        with open(users_csv, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
            fieldnames = rows[0].keys() if rows else []
        changed = False
        for r in rows:
            if r.get("username", "").endswith("_dup") and r.get("status") == "Duplicate_Disabled":
                r["status"] = "Active"
                changed = True
        if changed:
            with open(users_csv, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(rows)

    # If all 100 business verifications were already marked Verified in the repo, set #1-#3 to Pending for the test run
    if os.path.exists(ver_csv):
        with open(ver_csv, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
            fieldnames = rows[0].keys() if rows else []
        pending_count = sum(1 for r in rows if r.get("verification_status") == "Pending")
        if pending_count == 0 and rows:
            for r in rows[:3]:
                r["verification_status"] = "Pending"
                r["listing_status"] = "Pending Approval"
            with open(ver_csv, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(rows)

    def restore():
        for orig, bkp in backups:
            shutil.copy2(bkp, orig)
        shutil.rmtree(tmp_backup, ignore_errors=True)

    return restore


class FeatureCheckResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.records = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append(("PASS", test, ""))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append(("FAIL", test, self._exc_info_to_string(err, test)))

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append(("FAIL", test, self._exc_info_to_string(err, test)))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records.append(("SKIP", test, reason))


# Additional integration checks for Platform Management & Designer Portfolio B-C-E modules
class TestPlatformManagementAndDesignerPortfolio(unittest.TestCase):
    def test_01_platform_management_categories_and_projects_loaded(self):
        from app import create_app
        from platform_management.controls import PlatformManagementControl
        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            ctrl = PlatformManagementControl("4")  # pm_demo (user_id=4)
            stats, recent_reports = ctrl.dashboard()
            self.assertIn("Projects", stats)
            self.assertGreaterEqual(stats["Categories"], 1)
            categories = ctrl.searchCategories("")
            self.assertGreaterEqual(len(categories), 1)

    def test_02_platform_management_business_reports_daily_weekly_monthly(self):
        from app import create_app
        from platform_management.controls import PlatformManagementControl
        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            ctrl = PlatformManagementControl("4")
            for period in ("daily", "weekly", "monthly"):
                filters = ctrl.reportFilters({"start": "2026-10-15", "end": "2026-11-10", "period": period})
                rows, totals = ctrl.generateBusinessReports(filters)
                self.assertGreaterEqual(len(rows), 1)
                self.assertIn("views", totals)
                self.assertIn("shortlists", totals)

    def test_03_platform_management_moderation_cases_and_appeals(self):
        from app import create_app
        from platform_management.workflow_controls import ModerationWorkflowControl, FeatureScheduleControl
        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            mw = ModerationWorkflowControl("4")
            cases = mw.cases()
            appeals = mw.appeals()
            schedules = FeatureScheduleControl("4").schedules()
            self.assertIsInstance(cases, list)
            self.assertIsInstance(appeals, list)
            self.assertIsInstance(schedules, list)

    def test_04_designer_portfolio_dashboard_and_company_profile(self):
        from app import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = "2"  # id_demo (Chloe Tan, Interior Designer)
                sess["role"] = "Interior Designer"
            resp_dash = client.get("/designer/")
            self.assertEqual(resp_dash.status_code, 200)
            resp_comp = client.get("/designer/company")
            self.assertEqual(resp_comp.status_code, 200)
            resp_rev = client.get("/designer/reviews")
            self.assertEqual(resp_rev.status_code, 200)

    def test_05_customer_favourites_shortlist_and_groups(self):
        from app import create_app
        from customer_features.controls import ManageFavouritesControl
        import tempfile
        app = create_app()
        with tempfile.TemporaryDirectory() as tmpdir:
            shutil.copytree(os.path.join(REPO_ROOT, "data", "platform"), os.path.join(tmpdir, "platform"))
            app.config.update(PM_CSV_DIR=os.path.join(tmpdir, "platform"), TESTING=True)
            with app.app_context():
                fav_ctrl = ManageFavouritesControl()
                ok_grp, _ = fav_ctrl.createGroup("3", "Dream Condo Ideas")
                self.assertTrue(ok_grp)
                groups = fav_ctrl.viewGroups("3")
                self.assertGreaterEqual(len(groups), 1)


SUITES = [
    ("1. User Auth & Account Administration (test_development.py)", "test_development"),
    ("2. Customer Browse, Compare, Shortlist & Recommendations (test_customer_features.py)", "test_customer_features"),
    ("3. Designer Engagement Analytics & Follower Tracking (engagement_analytics)", "engagement_analytics.test_engagement_analytics"),
    ("4. Designer Active Renovation Project & Milestones (manage_active_project)", "manage_active_project.test_manage_active_project"),
    ("5. Service Requests, Itemised Quotations & Consultations (process_service_requests)", "process_service_requests.test_service_requests"),
    ("6. Designer Consultation Availability Slots (set_consultation_availability)", "set_consultation_availability.test_set_consultation_availability"),
    ("7. Platform Management & Designer Portfolio Workspace Integration", "__main__.TestPlatformManagementAndDesignerPortfolio"),
]


def run_all_checks():
    print("=" * 88)
    print(f"{BOLD}{CYAN}314 INTERIOR DESIGN HELP — FULL SYSTEM FEATURE VERIFICATION (PASS / FAIL){RESET}")
    print("=" * 88)

    restore_fn = _ensure_demo_seed_state_for_admin_tests()
    total_pass = 0
    total_fail = 0
    suite_summaries = []

    try:
        loader = unittest.TestLoader()
        for suite_title, module_name in SUITES:
            print(f"\n{BOLD}{suite_title}{RESET}")
            print("-" * 88)
            try:
                if module_name.startswith("__main__."):
                    suite = loader.loadTestsFromTestCase(TestPlatformManagementAndDesignerPortfolio)
                else:
                    suite = loader.loadTestsFromName(module_name)
            except Exception as exc:
                print(f"  [{RED}FAIL{RESET}] Could not load module '{module_name}': {exc}")
                total_fail += 1
                suite_summaries.append((suite_title, 0, 1))
                continue

            result = FeatureCheckResult()
            suite.run(result)

            spass = 0
            sfail = 0
            for status, test, err_text in result.records:
                test_name = test._testMethodName
                doc = test.shortDescription()
                label = f"{test_name} ({doc})" if doc else test_name
                if status == "PASS":
                    spass += 1
                    total_pass += 1
                    print(f"  [{GREEN}PASS{RESET}] {label}")
                else:
                    sfail += 1
                    total_fail += 1
                    print(f"  [{RED}FAIL{RESET}] {label}")
                    last_line = [ln.strip() for ln in err_text.strip().splitlines() if ln.strip()][-1]
                    print(f"         {YELLOW}-> {last_line}{RESET}")

            suite_summaries.append((suite_title, spass, sfail))
    finally:
        restore_fn()

    print("\n" + "=" * 88)
    print(f"{BOLD}MODULE SUMMARY TABLE{RESET}")
    print("=" * 88)
    print(f"{'Module / Feature Group':<66} | {'Passed':>6} | {'Failed':>6} | {'Verdict':>7}")
    print("-" * 88)
    for title, p, f in suite_summaries:
        verdict = f"{GREEN}PASS{RESET}" if f == 0 and p > 0 else f"{RED}FAIL{RESET}"
        short_title = title[:64]
        print(f"{short_title:<66} | {p:>6} | {f:>6} | {verdict}")
    print("-" * 88)
    overall = f"{GREEN}ALL FEATURES PASSED{RESET}" if total_fail == 0 else f"{RED}{total_fail} FEATURE(S) FAILED{RESET}"
    print(f"{BOLD}TOTAL CHECKS: {total_pass + total_fail}   |   PASSED: {total_pass}   |   FAILED: {total_fail}   |   {overall}{RESET}")
    print("=" * 88)
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all_checks())
