import unittest
import os
import shutil
import tempfile
import importlib.util
from datetime import date, datetime, timedelta

from set_consultation_availability.availability_controls import ServiceRequestControl
from set_consultation_availability.availability_entities import ConsultationAvailability, SHARED_DATA_DIR

DESIGNER = "Interior Designer"
DEMO_DESIGNER_ID = "2"
OTHER_DESIGNER_ID = "25"

FREE_DATE = (date.today() + timedelta(days=60)).isoformat()


def _loadProcessServiceRequestEntities():
    """Process Service Request's own entity module, which reads the same slots CSV."""
    path = os.path.join(os.path.dirname(SHARED_DATA_DIR), "service_entities.py")
    spec = importlib.util.spec_from_file_location("process_service_request_entities", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSetConsultationAvailabilityBCE(unittest.TestCase):
    def setUp(self):
        # Work on a copy of the shared slots CSV so tests never change the real data
        self.temp_dir = tempfile.mkdtemp()
        self.original_csv = ConsultationAvailability.CSV_FILE
        ConsultationAvailability.CSV_FILE = os.path.join(self.temp_dir, "consultation_availability.csv")
        shutil.copy(self.original_csv, ConsultationAvailability.CSV_FILE)
        self.control = ServiceRequestControl()

    def tearDown(self):
        ConsultationAvailability.CSV_FILE = self.original_csv
        shutil.rmtree(self.temp_dir)

    def _set(self, from_time="09:00", to_time="12:00", repeat_weeks="0", slot_date=FREE_DATE):
        return self.control.setConsultationAvailability(DESIGNER, DEMO_DESIGNER_ID, slot_date, from_time, to_time, repeat_weeks)

    def _slotsOn(self, day, designer_user_id=DEMO_DESIGNER_ID):
        return [s for s in ConsultationAvailability.getSlotsForDesigner(designer_user_id) if s["start_time"].startswith(day)]

    def test_01_permission_guard(self):
        with self.assertRaises(PermissionError):
            self.control.viewConsultationAvailability(actor_role="Customer", designer_user_id=DEMO_DESIGNER_ID)
        with self.assertRaises(PermissionError):
            self.control.setConsultationAvailability("Customer", DEMO_DESIGNER_ID, FREE_DATE, "09:00", "12:00")
        with self.assertRaises(PermissionError):
            self.control.removeConsultationSlot("Customer", DEMO_DESIGNER_ID, "1")

    def test_02_time_range_split_into_one_hour_free_slots(self):
        ok, msg = self._set("09:00", "12:00")
        self.assertTrue(ok, msg)
        self.assertIn("Added 3 consultation slots", msg)
        slots = self._slotsOn(FREE_DATE)
        self.assertEqual([s["start_time"][11:16] for s in slots], ["09:00", "10:00", "11:00"])
        self.assertEqual([s["end_time"][11:16] for s in slots], ["10:00", "11:00", "12:00"])
        self.assertTrue(all(s["is_available"] == "True" for s in slots))

    def test_03_repeat_weekly(self):
        ok, msg = self._set("14:00", "16:00", repeat_weeks="2")
        self.assertTrue(ok, msg)
        self.assertIn("Added 6 consultation slots every", msg)
        first = date.fromisoformat(FREE_DATE)
        for week in range(3):
            day = (first + timedelta(weeks=week)).isoformat()
            self.assertEqual(len(self._slotsOn(day)), 2, day)

    def test_04_set_availability_validation(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        cases = [
            (dict(slot_date="not-a-date"), "valid date"),
            (dict(from_time="12:00", to_time="09:00"), "end time must be after"),
            (dict(from_time="09:00", to_time="10:30"), "whole hours"),
            (dict(from_time="07:00", to_time="09:00"), "between 8:00 AM and 10:00 PM"),
            (dict(from_time="21:00", to_time="23:00"), "between 8:00 AM and 10:00 PM"),
            (dict(slot_date=yesterday), "in the future"),
            (dict(repeat_weeks="9"), "up to 8 more weeks"),
            (dict(repeat_weeks="abc"), "whole number"),
        ]
        before = len(ConsultationAvailability._readAll())
        for kwargs, expected in cases:
            ok, msg = self._set(**kwargs)
            self.assertFalse(ok, kwargs)
            self.assertIn(expected, msg, kwargs)
        self.assertEqual(len(ConsultationAvailability._readAll()), before)

    def test_05_overlapping_slots_are_skipped(self):
        self._set("09:00", "12:00")
        ok, msg = self._set("09:00", "12:00")
        self.assertFalse(ok)
        self.assertIn("already have availability", msg)
        ok, msg = self._set("11:00", "13:00")
        self.assertTrue(ok, msg)
        self.assertIn("Added 1 consultation slot on", msg)
        self.assertIn("Skipped 1", msg)
        self.assertEqual(len(self._slotsOn(FREE_DATE)), 4)

    def test_06_another_designers_slots_do_not_block_mine(self):
        ConsultationAvailability.addSlots(OTHER_DESIGNER_ID, [(f"{FREE_DATE} 09:00:00", f"{FREE_DATE} 10:00:00")])
        ok, msg = self._set("09:00", "10:00")
        self.assertTrue(ok, msg)

    def test_07_remove_free_slot(self):
        self._set("09:00", "10:00")
        slot = self._slotsOn(FREE_DATE)[0]
        ok, msg = self.control.removeConsultationSlot(DESIGNER, DEMO_DESIGNER_ID, slot["slot_id"])
        self.assertTrue(ok, msg)
        self.assertIsNone(ConsultationAvailability.findById(slot["slot_id"]))

    def test_08_remove_rejects_booked_and_started_slots(self):
        booked = next(s for s in ConsultationAvailability.getSlotsForDesigner(DEMO_DESIGNER_ID) if s["is_available"] == "False")
        ok, msg = self.control.removeConsultationSlot(DESIGNER, DEMO_DESIGNER_ID, booked["slot_id"])
        self.assertFalse(ok)
        self.assertIn("booked", msg)

        past = datetime.now() - timedelta(days=1)
        started = ConsultationAvailability.addSlots(DEMO_DESIGNER_ID, [
            (past.strftime("%Y-%m-%d %H:%M:%S"), (past + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"))])[0]
        ok, msg = self.control.removeConsultationSlot(DESIGNER, DEMO_DESIGNER_ID, started["slot_id"])
        self.assertFalse(ok)
        self.assertIn("already started", msg)
        self.assertIsNotNone(ConsultationAvailability.findById(booked["slot_id"]))
        self.assertIsNotNone(ConsultationAvailability.findById(started["slot_id"]))

    def test_09_remove_ownership_and_missing_slot(self):
        others = ConsultationAvailability.addSlots(OTHER_DESIGNER_ID, [(f"{FREE_DATE} 09:00:00", f"{FREE_DATE} 10:00:00")])[0]
        with self.assertRaises(PermissionError):
            self.control.removeConsultationSlot(DESIGNER, DEMO_DESIGNER_ID, others["slot_id"])
        with self.assertRaises(LookupError):
            self.control.removeConsultationSlot(DESIGNER, DEMO_DESIGNER_ID, "99999")

    def test_10_view_lists_only_own_upcoming_slots_in_order(self):
        past = datetime.now() - timedelta(days=1)
        ConsultationAvailability.addSlots(DEMO_DESIGNER_ID, [
            (past.strftime("%Y-%m-%d %H:%M:%S"), (past + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"))])
        ConsultationAvailability.addSlots(OTHER_DESIGNER_ID, [(f"{FREE_DATE} 09:00:00", f"{FREE_DATE} 10:00:00")])
        self._set("15:00", "17:00")

        slots = self.control.viewConsultationAvailability(DESIGNER, DEMO_DESIGNER_ID)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.assertTrue(slots)
        self.assertTrue(all(s["designer_user_id"] == DEMO_DESIGNER_ID and s["start_time"] > now for s in slots))
        self.assertEqual(slots, sorted(slots, key=lambda s: s["start_time"]))

    def test_11_slots_are_shared_with_process_service_request(self):
        """A slot opened here is the free slot Process Service Request finds when accepting a consultation."""
        process_entities = _loadProcessServiceRequestEntities()
        self.assertEqual(os.path.abspath(process_entities.ConsultationAvailability.CSV_FILE), os.path.abspath(self.original_csv))

        process_entities.ConsultationAvailability.CSV_FILE = ConsultationAvailability.CSV_FILE
        start = f"{FREE_DATE} 10:00:00"
        self.assertIsNone(process_entities.ConsultationAvailability.findFreeSlotAt(DEMO_DESIGNER_ID, start))
        self._set("10:00", "11:00")
        self.assertIsNotNone(process_entities.ConsultationAvailability.findFreeSlotAt(DEMO_DESIGNER_ID, start))


if __name__ == "__main__":
    unittest.main()
