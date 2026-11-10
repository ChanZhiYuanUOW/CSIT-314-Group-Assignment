import unittest
import os
import shutil
import tempfile

from process_service_requests.service_controls import ServiceRequestControl
from process_service_requests.service_entities import ServiceRequest, Quotation, Consultation, ConsultationAvailability, DATA_DIR

DESIGNER = "Interior Designer"
DEMO_DESIGNER_ID = "2"
OTHER_DESIGNER_ID = "25"
# Seeded requests (see data/service_requests.csv)
QUOTATION_ONLY_ID = "1"          # Pending, quotation only
CONSULT_FREE_SLOT_ID = "2"       # consultation requested at a free slot
CONSULT_SUNDAY_ID = "3"          # quotation & consultation, requested on a Sunday (no slot)
CONSULT_ANSWERED_ID = "7"        # consultation already accepted
OTHER_DESIGNERS_REQUEST_ID = "9"

ENTITY_FILES = [
    (ServiceRequest, "CSV_FILE"), (Quotation, "CSV_FILE"), (Quotation, "ITEMS_CSV_FILE"),
    (Consultation, "CSV_FILE"), (ConsultationAvailability, "CSV_FILE")
]


class TestProcessServiceRequestBCE(unittest.TestCase):
    def setUp(self):
        # Work on a copy of the seeded CSVs so tests never change the real data
        self.temp_dir = tempfile.mkdtemp()
        self.original_paths = []
        for entity, attr in ENTITY_FILES:
            original = getattr(entity, attr)
            self.original_paths.append((entity, attr, original))
            copy_path = os.path.join(self.temp_dir, os.path.relpath(original, DATA_DIR))
            shutil.copy(original, copy_path)
            setattr(entity, attr, copy_path)
        self.control = ServiceRequestControl()

    def tearDown(self):
        for entity, attr, original in self.original_paths:
            setattr(entity, attr, original)
        shutil.rmtree(self.temp_dir)

    def _estimate(self, request_id, items, scope="Full scope of works"):
        return self.control.generateItemisedCostEstimate(DESIGNER, DEMO_DESIGNER_ID, request_id, items, scope, "")

    def test_01_process_service_request_permission_guard(self):
        with self.assertRaises(PermissionError):
            self.control.processServiceRequest(actor_role="Customer", designer_user_id=DEMO_DESIGNER_ID)

    def test_02_designer_cannot_open_another_designers_request(self):
        with self.assertRaises(PermissionError):
            self.control.processServiceRequest(DESIGNER, DEMO_DESIGNER_ID, selected_request_id=OTHER_DESIGNERS_REQUEST_ID)
        with self.assertRaises(PermissionError):
            self._estimate(OTHER_DESIGNERS_REQUEST_ID, [{"description": "Fit-out", "amount": "1000"}])

    def test_03_request_list_and_status_filter(self):
        requests, selected = self.control.processServiceRequest(DESIGNER, DEMO_DESIGNER_ID)
        self.assertEqual(len(requests), 8)
        self.assertTrue(all(r["designer_user_id"] == DEMO_DESIGNER_ID for r in requests))
        self.assertIsNotNone(selected)
        pending, _ = self.control.processServiceRequest(DESIGNER, DEMO_DESIGNER_ID, status_filter="Pending")
        self.assertTrue(pending)
        self.assertTrue(all(r["status"] == "Pending" for r in pending))

    def test_04_estimate_validation(self):
        cases = [
            ([], "at least one line item"),
            ([{"description": "", "amount": "500"}], "needs a description"),
            ([{"description": "Painting", "amount": "abc"}], "must be a number"),
            ([{"description": "Painting", "amount": "-20"}], "greater than 0"),
        ]
        for items, expected in cases:
            ok, msg = self._estimate(QUOTATION_ONLY_ID, items)
            self.assertFalse(ok)
            self.assertIn(expected, msg)
        ok, msg = self._estimate(QUOTATION_ONLY_ID, [{"description": "Painting", "amount": "500"}], scope=" ")
        self.assertFalse(ok)
        self.assertIn("scope", msg)
        self.assertIsNone(Quotation.findByRequest(QUOTATION_ONLY_ID))

    def test_05_calculate_total(self):
        items = [{"amount": "1200.50"}, {"amount": 300}, {"amount": "0.25"}]
        self.assertEqual(Quotation.calculateTotal(items), 1500.75)

    def test_06_estimate_rejected_for_consultation_only_request(self):
        ok, msg = self._estimate(CONSULT_FREE_SLOT_ID, [{"description": "Design fee", "amount": "800"}])
        self.assertFalse(ok)
        self.assertIn("did not request a quotation", msg)

    def test_07_estimate_saved_and_request_status_updated(self):
        ok, msg = self._estimate(QUOTATION_ONLY_ID, [
            {"description": "Kitchen cabinets", "amount": "9000"},
            {"description": "Vinyl flooring", "amount": "4500.50"},
            {"description": "", "amount": ""},  # blank form row is ignored
        ])
        self.assertTrue(ok, msg)
        quote = Quotation.findByRequest(QUOTATION_ONLY_ID)
        self.assertEqual(quote["total_amount"], "13500.50")
        self.assertEqual(len(quote["items"]), 2)
        self.assertEqual(ServiceRequest.findById(QUOTATION_ONLY_ID)["status"], "Responded")

        # Quotation & Consultation request with consultation still open -> In Progress
        ok, _ = self._estimate(CONSULT_SUNDAY_ID, [{"description": "Bathroom works", "amount": "40000"}])
        self.assertTrue(ok)
        self.assertEqual(ServiceRequest.findById(CONSULT_SUNDAY_ID)["status"], "In Progress")

    def test_08_estimate_over_budget_is_saved_with_warning(self):
        ok, msg = self._estimate(QUOTATION_ONLY_ID, [{"description": "Whole unit", "amount": "50000"}])
        self.assertTrue(ok)
        self.assertIn("over the customer's budget", msg)

    def test_09_accept_requires_free_slot_at_requested_time(self):
        ok, msg = self.control.acceptDeclineOrProposeTime(DESIGNER, DEMO_DESIGNER_ID, CONSULT_SUNDAY_ID, "accept")
        self.assertFalse(ok)
        self.assertIn("no free availability slot", msg)
        self.assertEqual(Consultation.findByRequest(CONSULT_SUNDAY_ID)["status"], "Requested")

    def test_10_accept_books_the_slot(self):
        requested_time = Consultation.findByRequest(CONSULT_FREE_SLOT_ID)["proposed_time"]
        slot = ConsultationAvailability.findFreeSlotAt(DEMO_DESIGNER_ID, requested_time)
        self.assertIsNotNone(slot)

        ok, msg = self.control.acceptDeclineOrProposeTime(DESIGNER, DEMO_DESIGNER_ID, CONSULT_FREE_SLOT_ID, "accept")
        self.assertTrue(ok, msg)
        consultation = Consultation.findByRequest(CONSULT_FREE_SLOT_ID)
        self.assertEqual(consultation["status"], "Accepted")
        self.assertEqual(consultation["confirmed_time"], requested_time)
        self.assertEqual(ConsultationAvailability.findById(slot["slot_id"])["is_available"], "False")
        self.assertEqual(ServiceRequest.findById(CONSULT_FREE_SLOT_ID)["status"], "Responded")

    def test_11_propose_requires_one_of_the_designers_free_slots(self):
        booked = [s for s in ConsultationAvailability._readAll() if s["is_available"] == "False"][0]
        ok, msg = self.control.acceptDeclineOrProposeTime(DESIGNER, DEMO_DESIGNER_ID, CONSULT_SUNDAY_ID,
                                                          "propose", slot_id=booked["slot_id"])
        self.assertFalse(ok)
        ok, msg = self.control.acceptDeclineOrProposeTime(DESIGNER, DEMO_DESIGNER_ID, CONSULT_SUNDAY_ID, "propose")
        self.assertFalse(ok)

        free_slot = ConsultationAvailability.getAvailableSlots(DEMO_DESIGNER_ID)[0]
        ok, msg = self.control.acceptDeclineOrProposeTime(DESIGNER, DEMO_DESIGNER_ID, CONSULT_SUNDAY_ID,
                                                          "propose", slot_id=free_slot["slot_id"])
        self.assertTrue(ok, msg)
        consultation = Consultation.findByRequest(CONSULT_SUNDAY_ID)
        self.assertEqual(consultation["status"], "Time Proposed")
        self.assertEqual(consultation["proposed_time"], free_slot["start_time"])

    def test_12_decline_requires_a_note(self):
        ok, msg = self.control.acceptDeclineOrProposeTime(DESIGNER, DEMO_DESIGNER_ID, CONSULT_FREE_SLOT_ID, "decline")
        self.assertFalse(ok)
        ok, msg = self.control.acceptDeclineOrProposeTime(DESIGNER, DEMO_DESIGNER_ID, CONSULT_FREE_SLOT_ID,
                                                          "decline", note="Fully booked this month.")
        self.assertTrue(ok, msg)
        self.assertEqual(Consultation.findByRequest(CONSULT_FREE_SLOT_ID)["status"], "Declined")

    def test_13_answered_consultation_cannot_be_answered_again(self):
        ok, msg = self.control.acceptDeclineOrProposeTime(DESIGNER, DEMO_DESIGNER_ID, CONSULT_ANSWERED_ID,
                                                          "decline", note="Changed my mind")
        self.assertFalse(ok)
        self.assertIn("already been answered", msg)


if __name__ == "__main__":
    unittest.main()
