import unittest
import os
import csv
import shutil
import tempfile
from datetime import date, timedelta
from unittest import mock

from manage_active_project.renovation_controls import RenovationControl
from manage_active_project.renovation_entities import RenovationProject, RenovationProgress, ServiceRequest
from process_service_requests.service_controls import ServiceRequestControl

DESIGNER = "Interior Designer"
DEMO_DESIGNER_ID = "2"
OTHER_DESIGNER_ID = "25"
# Seeded projects (see data/renovation_projects.csv)
LIVING_ROOM_ID = "1"     # In Progress, from service request 6
LIVING_ROOM_REQUEST_ID = "6"
BEDROOM_ID = "2"         # Not Started, from service request 8
TODAY = date.today().isoformat()
NEXT_MONTH = (date.today() + timedelta(days=30)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()

ENTITY_FILES = [RenovationProject, RenovationProgress, ServiceRequest]


class TestManageActiveProjectBCE(unittest.TestCase):
    def setUp(self):
        # Work on a copy of the CSVs so tests never change the real data
        self.temp_dir = tempfile.mkdtemp()
        self.original_paths = []
        for entity in ENTITY_FILES:
            self.original_paths.append((entity, entity.CSV_FILE))
            copy_path = os.path.join(self.temp_dir, os.path.basename(entity.CSV_FILE))
            if os.path.exists(entity.CSV_FILE):
                shutil.copy(entity.CSV_FILE, copy_path)
            entity.CSV_FILE = copy_path
        # The living room already has one progress update posted
        with open(RenovationProgress.CSV_FILE, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=RenovationProgress.FIELDS)
            writer.writeheader()
            writer.writerow({"progress_id": "1", "request_id": LIVING_ROOM_REQUEST_ID, "designer_user_id": DEMO_DESIGNER_ID,
                             "stage": "Construction", "completion_percentage": "40",
                             "note": "False ceiling done.", "updated_at": "2026-11-03 17:40:00"})
        self.control = RenovationControl()

    def tearDown(self):
        for entity, original in self.original_paths:
            entity.CSV_FILE = original
        shutil.rmtree(self.temp_dir)

    def _addProject(self, renovation_id, designer_user_id=DEMO_DESIGNER_ID, status="In Progress",
                    start_date="2026-10-01", expected=NEXT_MONTH, source_request_id="9"):
        with open(RenovationProject.CSV_FILE, "a", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=RenovationProject.FIELDS).writerow({
                "renovation_id": renovation_id, "source_request_id": source_request_id,
                "designer_user_id": designer_user_id, "title": f"Test project {renovation_id}", "status": status,
                "start_date": start_date, "expected_completion_date": expected, "updated_at": "2026-10-01 09:00:00"})

    def _history(self, request_id=LIVING_ROOM_REQUEST_ID):
        return RenovationProgress.getHistory(request_id)

    def _update(self, renovation_id=LIVING_ROOM_ID, status="In Progress", stage="Construction",
                completion_percentage="40", note="", expected=NEXT_MONTH):
        return self.control.manageActiveProject(DESIGNER, DEMO_DESIGNER_ID, renovation_id, status,
                                                stage, completion_percentage, note, expected)

    def test_01_permission_guard(self):
        with self.assertRaises(PermissionError):
            self.control.viewActiveProjects(actor_role="Customer", designer_user_id=DEMO_DESIGNER_ID)
        with self.assertRaises(PermissionError):
            self.control.manageActiveProject("Customer", DEMO_DESIGNER_ID, LIVING_ROOM_ID, "In Progress",
                                             "Construction", "40", "", NEXT_MONTH)

    def test_02_designer_cannot_manage_another_designers_project(self):
        with self.assertRaises(PermissionError):
            self.control.viewActiveProjects(DESIGNER, OTHER_DESIGNER_ID, selected_renovation_id=LIVING_ROOM_ID)
        with self.assertRaises(PermissionError):
            self.control.manageActiveProject(DESIGNER, OTHER_DESIGNER_ID, LIVING_ROOM_ID, "In Progress",
                                             "Construction", "40", "", NEXT_MONTH)
        with self.assertRaises(LookupError):
            self._update(renovation_id="999")

    def test_03_view_lists_own_projects_with_latest_progress_and_customer(self):
        self._addProject("50", designer_user_id=OTHER_DESIGNER_ID)
        projects, selected = self.control.viewActiveProjects(DESIGNER, DEMO_DESIGNER_ID)
        self.assertEqual(len(projects), 3)
        self.assertTrue(all(p["designer_user_id"] == DEMO_DESIGNER_ID for p in projects))
        by_id = {p["renovation_id"]: p for p in projects}
        self.assertEqual(by_id[LIVING_ROOM_ID]["latest_progress"]["stage"], "Construction")
        self.assertIsNone(by_id[BEDROOM_ID]["latest_progress"])
        self.assertEqual(by_id[LIVING_ROOM_ID]["customer_name"], "Jun Jie Ong")   # customer of service request 6

        projects, _ = self.control.viewActiveProjects(DESIGNER, DEMO_DESIGNER_ID, status_filter="Not Started")
        self.assertEqual([p["renovation_id"] for p in projects], [BEDROOM_ID])

        self._update(stage="Installation", completion_percentage="60")
        _, selected = self.control.viewActiveProjects(DESIGNER, DEMO_DESIGNER_ID, selected_renovation_id=LIVING_ROOM_ID)
        self.assertEqual(selected["source_request"]["request_id"], LIVING_ROOM_REQUEST_ID)
        self.assertEqual([u["stage"] for u in selected["progress_history"]], ["Installation", "Construction"])
        self.assertEqual(selected["latest_progress"]["completion_percentage"], "60")

    def test_04_view_flags_overdue_active_projects(self):
        self._addProject("51", expected=YESTERDAY)
        self._addProject("52", status="Completed", expected=YESTERDAY)
        projects, _ = self.control.viewActiveProjects(DESIGNER, DEMO_DESIGNER_ID)
        overdue = {p["renovation_id"]: p["is_overdue"] for p in projects}
        self.assertTrue(overdue["51"])
        self.assertFalse(overdue["52"])
        self.assertEqual(projects[-1]["renovation_id"], "52")   # completed projects listed last

    def test_05_update_records_progress_date_and_status(self):
        ok, msg = self._update(status="On Hold", stage="Installation", completion_percentage="55",
                               note="  Feature wall done; waiting on TV console delivery.  ", expected=NEXT_MONTH)
        self.assertTrue(ok, msg)
        self.assertIn("Installation stage at 55%", msg)
        self.assertIn("Expected completion moved", msg)

        latest = RenovationProgress.getLatest(LIVING_ROOM_REQUEST_ID)
        self.assertEqual((latest["stage"], latest["completion_percentage"], latest["designer_user_id"]),
                         ("Installation", "55", DEMO_DESIGNER_ID))
        self.assertEqual(latest["note"], "Feature wall done; waiting on TV console delivery.")
        self.assertEqual(len(self._history()), 2)
        project = RenovationProject.findById(LIVING_ROOM_ID)
        self.assertEqual((project["status"], project["expected_completion_date"]), ("On Hold", NEXT_MONTH))

    def test_06_unchanged_progress_and_date_are_confirmed_without_a_duplicate_update(self):
        RenovationProject.updateExpectedCompletionDate(LIVING_ROOM_ID, NEXT_MONTH)
        ok, msg = self._update(stage="Construction", completion_percentage="40", expected=NEXT_MONTH)
        self.assertTrue(ok, msg)
        self.assertIn("Expected completion confirmed", msg)
        self.assertEqual(len(self._history()), 1)

        ok, msg = self._update(stage="Construction", completion_percentage="40", note="Still on track.")
        self.assertTrue(ok, msg)
        self.assertEqual(len(self._history()), 2)   # a note on its own is still worth telling the customer

    def test_07_progress_validation(self):
        cases = [
            (dict(stage="Demolition"), "valid renovation stage"),
            (dict(completion_percentage="forty"), "valid completion percentage"),
            (dict(completion_percentage="101"), "between 0 and 100"),
            (dict(completion_percentage="-5"), "between 0 and 100"),
            (dict(stage="Completed", completion_percentage="90", status="Completed", expected=TODAY), "100% progress"),
            (dict(note="x" * 501), "500 characters"),
            (dict(status="Paused"), "valid project status"),
        ]
        for kwargs, expected in cases:
            ok, msg = self._update(**kwargs)
            self.assertFalse(ok, kwargs)
            self.assertIn(expected, msg, kwargs)
        self.assertEqual(len(self._history()), 1)

    def test_08_expected_completion_date_validation(self):
        cases = [
            (dict(expected="27/11/2026"), "valid expected completion date"),
            (dict(expected="2026-10-01"), "before the project started"),
            (dict(expected=YESTERDAY), "has passed"),
        ]
        for kwargs, expected in cases:
            ok, msg = self._update(**kwargs)
            self.assertFalse(ok, kwargs)
            self.assertIn(expected, msg, kwargs)

    def test_09_completing_a_project(self):
        ok, msg = self._update(status="Completed", stage="Finishing", completion_percentage="95", expected=TODAY)
        self.assertFalse(ok)
        self.assertIn("Set the renovation stage to Completed", msg)

        ok, msg = self._update(status="In Progress", stage="Completed", completion_percentage="100")
        self.assertFalse(ok)
        self.assertIn("mark the project as Completed", msg)

        ok, msg = self._update(status="Completed", stage="Completed", completion_percentage="100", expected=NEXT_MONTH)
        self.assertFalse(ok)
        self.assertIn("completion date in the future", msg)

        ok, msg = self._update(status="Completed", stage="Completed", completion_percentage="100", expected=TODAY)
        self.assertTrue(ok, msg)
        self.assertEqual(RenovationProgress.getLatest(LIVING_ROOM_REQUEST_ID)["stage"], "Completed")
        ok, msg = self._update(status="In Progress")
        self.assertFalse(ok)
        self.assertIn("can no longer be updated", msg)

    def test_10_not_started_project_cannot_have_progress(self):
        ok, msg = self._update(BEDROOM_ID, status="Not Started", stage="Planning", completion_percentage="10")
        self.assertFalse(ok)
        self.assertIn("can't be Not Started", msg)
        ok, msg = self._update(BEDROOM_ID, status="Not Started", stage="Planning", completion_percentage="0")
        self.assertTrue(ok, msg)
        ok, msg = self._update(BEDROOM_ID, status="In Progress", stage="Planning", completion_percentage="10")
        self.assertTrue(ok, msg)

    def test_11_failed_update_changes_nothing(self):
        projects_before = RenovationProject._readAll()
        progress_before = RenovationProgress._readAll()
        ok, msg = self._update(stage="Installation", completion_percentage="60", note="Tiling", expected=YESTERDAY)
        self.assertFalse(ok)
        self.assertEqual(RenovationProject._readAll(), projects_before)
        self.assertEqual(RenovationProgress._readAll(), progress_before)

    def test_12_first_update_posts_progress_for_a_project_without_any(self):
        self.assertEqual(self._history("8"), [])
        ok, msg = self._update(BEDROOM_ID, status="In Progress", stage="Planning", completion_percentage="5",
                               note="Final site measurement booked.")
        self.assertTrue(ok, msg)
        self.assertEqual([(u["stage"], u["completion_percentage"]) for u in self._history("8")], [("Planning", "5")])

    def test_13_update_always_includes_progress_and_completion_date(self):
        """<<include>>: every active project update records progress and the expected completion date."""
        with mock.patch.object(self.control, "recordRenovationProgress", wraps=self.control.recordRenovationProgress) as progress, \
             mock.patch.object(self.control, "recordExpectedCompletionDate", wraps=self.control.recordExpectedCompletionDate) as completion:
            ok, msg = self._update()
        self.assertTrue(ok, msg)
        progress.assert_called_once()
        completion.assert_called_once_with(LIVING_ROOM_ID, NEXT_MONTH)

    def test_14_progress_is_shared_with_process_service_requests(self):
        """Updates posted here are the same ones the service request page (and the customer) see."""
        ok, msg = self._update(stage="Installation", completion_percentage="70", note="Console installed.")
        self.assertTrue(ok, msg)
        history = ServiceRequestControl.getRenovationProgress(DEMO_DESIGNER_ID, LIVING_ROOM_REQUEST_ID)
        self.assertEqual((history[0]["stage"], history[0]["completion_percentage"], history[0]["note"]),
                         ("Installation", "70", "Console installed."))


if __name__ == "__main__":
    unittest.main()
