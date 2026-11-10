import unittest
import os
import csv
import shutil
import tempfile
from datetime import date, timedelta
from unittest import mock

from manage_active_project.renovation_controls import RenovationControl
from manage_active_project.renovation_entities import RenovationProject, ProgressMilestone, ServiceRequest

DESIGNER = "Interior Designer"
DEMO_DESIGNER_ID = "2"
OTHER_DESIGNER_ID = "25"
# Seeded projects (see data/renovation_projects.csv)
LIVING_ROOM_ID = "1"     # In Progress, 2 of 5 milestones completed, from service request 6
BEDROOM_ID = "2"         # Not Started, all milestones Pending
TODAY = date.today().isoformat()
NEXT_MONTH = (date.today() + timedelta(days=30)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()

ENTITY_FILES = [RenovationProject, ProgressMilestone, ServiceRequest]


class TestManageActiveProjectBCE(unittest.TestCase):
    def setUp(self):
        # Work on a copy of the CSVs so tests never change the real data
        self.temp_dir = tempfile.mkdtemp()
        self.original_paths = []
        for entity in ENTITY_FILES:
            self.original_paths.append((entity, entity.CSV_FILE))
            copy_path = os.path.join(self.temp_dir, os.path.basename(entity.CSV_FILE))
            shutil.copy(entity.CSV_FILE, copy_path)
            entity.CSV_FILE = copy_path
        self.control = RenovationControl()

    def tearDown(self):
        for entity, original in self.original_paths:
            entity.CSV_FILE = original
        shutil.rmtree(self.temp_dir)

    def _addProject(self, renovation_id, designer_user_id=DEMO_DESIGNER_ID, status="In Progress",
                    start_date="2026-10-01", expected=NEXT_MONTH):
        with open(RenovationProject.CSV_FILE, "a", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=RenovationProject.FIELDS).writerow({
                "renovation_id": renovation_id, "source_request_id": "9", "designer_user_id": designer_user_id,
                "title": f"Test project {renovation_id}", "status": status, "start_date": start_date,
                "expected_completion_date": expected, "updated_at": "2026-10-01 09:00:00"})

    def _milestones(self, renovation_id=LIVING_ROOM_ID):
        return ProgressMilestone.getMilestonesForProject(renovation_id)

    def _update(self, renovation_id=LIVING_ROOM_ID, status="In Progress", milestone_statuses=None,
                new_milestones=None, expected=NEXT_MONTH):
        return self.control.manageActiveProject(DESIGNER, DEMO_DESIGNER_ID, renovation_id, status,
                                                milestone_statuses or {}, new_milestones or [], expected)

    def test_01_permission_guard(self):
        with self.assertRaises(PermissionError):
            self.control.viewActiveProjects(actor_role="Customer", designer_user_id=DEMO_DESIGNER_ID)
        with self.assertRaises(PermissionError):
            self.control.manageActiveProject("Customer", DEMO_DESIGNER_ID, LIVING_ROOM_ID, "In Progress", {}, [], NEXT_MONTH)

    def test_02_designer_cannot_manage_another_designers_project(self):
        with self.assertRaises(PermissionError):
            self.control.viewActiveProjects(DESIGNER, OTHER_DESIGNER_ID, selected_renovation_id=LIVING_ROOM_ID)
        with self.assertRaises(PermissionError):
            self.control.manageActiveProject(DESIGNER, OTHER_DESIGNER_ID, LIVING_ROOM_ID, "In Progress", {}, [], NEXT_MONTH)
        with self.assertRaises(LookupError):
            self._update(renovation_id="999")

    def test_03_view_lists_own_projects_with_progress_and_customer(self):
        self._addProject("50", designer_user_id=OTHER_DESIGNER_ID)
        projects, selected = self.control.viewActiveProjects(DESIGNER, DEMO_DESIGNER_ID)
        self.assertEqual(len(projects), 3)
        self.assertTrue(all(p["designer_user_id"] == DEMO_DESIGNER_ID for p in projects))
        living_room = next(p for p in projects if p["renovation_id"] == LIVING_ROOM_ID)
        self.assertEqual((living_room["milestones_done"], living_room["milestones_total"]), (2, 5))
        self.assertEqual(living_room["customer_name"], "Jun Jie Ong")   # customer of service request 6

        projects, _ = self.control.viewActiveProjects(DESIGNER, DEMO_DESIGNER_ID, status_filter="Not Started")
        self.assertEqual([p["renovation_id"] for p in projects], [BEDROOM_ID])

        _, selected = self.control.viewActiveProjects(DESIGNER, DEMO_DESIGNER_ID, selected_renovation_id=LIVING_ROOM_ID)
        self.assertEqual(selected["source_request"]["request_id"], "6")
        self.assertEqual(len(selected["milestones"]), 5)

    def test_04_view_flags_overdue_active_projects(self):
        self._addProject("51", expected=YESTERDAY)
        self._addProject("52", status="Completed", expected=YESTERDAY)
        projects, _ = self.control.viewActiveProjects(DESIGNER, DEMO_DESIGNER_ID)
        overdue = {p["renovation_id"]: p["is_overdue"] for p in projects}
        self.assertTrue(overdue["51"])
        self.assertFalse(overdue["52"])
        self.assertEqual(projects[-1]["renovation_id"], "52")   # completed projects listed last

    def test_05_update_records_milestones_date_and_status(self):
        wall = next(m for m in self._milestones() if m["description"] == "Fluted feature wall")
        ok, msg = self._update(milestone_statuses={wall["milestone_id"]: "Completed"},
                               new_milestones=[{"description": "Touch-up painting", "status": "Pending"}],
                               status="On Hold", expected=NEXT_MONTH)
        self.assertTrue(ok, msg)
        self.assertIn("3 of 6 milestones completed", msg)
        self.assertIn("Expected completion moved", msg)

        milestones = {m["description"]: m for m in self._milestones()}
        self.assertEqual(milestones["Fluted feature wall"]["status"], "Completed")
        self.assertGreater(milestones["Fluted feature wall"]["recorded_at"], wall["recorded_at"])
        self.assertEqual(milestones["Touch-up painting"]["status"], "Pending")
        project = RenovationProject.findById(LIVING_ROOM_ID)
        self.assertEqual((project["status"], project["expected_completion_date"]), ("On Hold", NEXT_MONTH))

    def test_06_unchanged_date_is_confirmed(self):
        RenovationProject.updateExpectedCompletionDate(LIVING_ROOM_ID, NEXT_MONTH)
        before = {m["milestone_id"]: m["recorded_at"] for m in self._milestones()}
        ok, msg = self._update(expected=NEXT_MONTH)
        self.assertTrue(ok, msg)
        self.assertIn("Expected completion confirmed", msg)
        self.assertEqual({m["milestone_id"]: m["recorded_at"] for m in self._milestones()}, before)

    def test_07_milestone_validation(self):
        bedroom_milestone = self._milestones(BEDROOM_ID)[0]["milestone_id"]
        first = self._milestones()[0]
        cases = [
            (dict(milestone_statuses={first["milestone_id"]: "Done"}), "valid status"),
            (dict(milestone_statuses={bedroom_milestone: "Completed"}), "does not belong to this project"),
            (dict(new_milestones=[{"description": first["description"].upper(), "status": "Pending"}]), "already a milestone"),
            (dict(new_milestones=[{"description": "Tiling", "status": "Pending"},
                                  {"description": "tiling", "status": "Pending"}]), "already a milestone"),
            (dict(new_milestones=[{"description": "x" * 121, "status": "Pending"}]), "120 characters"),
            (dict(new_milestones=[{"description": "Tiling", "status": "Started"}]), "valid status"),
            (dict(status="Paused"), "valid project status"),
        ]
        for kwargs, expected in cases:
            ok, msg = self._update(**kwargs)
            self.assertFalse(ok, kwargs)
            self.assertIn(expected, msg, kwargs)

        ok, msg = self._update(new_milestones=[{"description": "   ", "status": "Pending"}])
        self.assertTrue(ok, msg)
        self.assertEqual(len(self._milestones()), 5)

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
        milestones = self._milestones()
        ok, msg = self._update(status="Completed", expected=TODAY)
        self.assertFalse(ok)
        self.assertIn("Complete every milestone", msg)

        all_done = {m["milestone_id"]: "Completed" for m in milestones}
        ok, msg = self._update(status="Completed", milestone_statuses=all_done, expected=NEXT_MONTH)
        self.assertFalse(ok)
        self.assertIn("completion date in the future", msg)

        ok, msg = self._update(status="Completed", milestone_statuses=all_done, expected=TODAY)
        self.assertTrue(ok, msg)
        ok, msg = self._update(status="In Progress")
        self.assertFalse(ok)
        self.assertIn("can no longer be updated", msg)

    def test_10_not_started_project_cannot_have_progress(self):
        first = self._milestones(BEDROOM_ID)[0]["milestone_id"]
        ok, msg = self._update(BEDROOM_ID, status="Not Started", milestone_statuses={first: "In Progress"})
        self.assertFalse(ok)
        self.assertIn("can't be Not Started", msg)
        ok, msg = self._update(BEDROOM_ID, status="In Progress", milestone_statuses={first: "In Progress"})
        self.assertTrue(ok, msg)

    def test_11_failed_update_changes_nothing(self):
        projects_before = RenovationProject._readAll()
        milestones_before = ProgressMilestone._readAll()
        first = self._milestones()[0]["milestone_id"]
        ok, msg = self._update(milestone_statuses={first: "In Progress"},
                               new_milestones=[{"description": "Tiling", "status": "Pending"}], expected=YESTERDAY)
        self.assertFalse(ok)
        self.assertEqual(RenovationProject._readAll(), projects_before)
        self.assertEqual(ProgressMilestone._readAll(), milestones_before)

    def test_12_project_needs_at_least_one_milestone(self):
        self._addProject("53")
        ok, msg = self._update("53")
        self.assertFalse(ok)
        self.assertIn("at least one progress milestone", msg)
        ok, msg = self._update("53", new_milestones=[{"description": "Site survey", "status": "In Progress"}])
        self.assertTrue(ok, msg)

    def test_13_update_always_includes_milestones_and_completion_date(self):
        """<<include>>: every active project update records milestones and the expected completion date."""
        with mock.patch.object(self.control, "recordProgressMilestones", wraps=self.control.recordProgressMilestones) as milestones, \
             mock.patch.object(self.control, "recordExpectedCompletionDate", wraps=self.control.recordExpectedCompletionDate) as completion:
            ok, msg = self._update()
        self.assertTrue(ok, msg)
        milestones.assert_called_once()
        completion.assert_called_once_with(LIVING_ROOM_ID, NEXT_MONTH)


if __name__ == "__main__":
    unittest.main()
