import csv
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _readCsv(path):
    with open(path, mode="r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _writeCsv(path, rows, fieldnames):
    with open(path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class ServiceRequest:
    """<<entity>> :ServiceRequest
    A customer's renovation request (brief, budget, quotation and/or consultation) sent to one designer.
    """
    CSV_FILE = os.path.join(DATA_DIR, "service_requests.csv")
    FIELDS = ["request_id", "customer_user_id", "designer_user_id", "renovation_brief", "budget",
              "request_type", "status", "submitted_at"]

    @classmethod
    def _readAll(cls):
        return _readCsv(cls.CSV_FILE)

    @classmethod
    def findById(cls, request_id: str):
        for row in cls._readAll():
            if str(row["request_id"]) == str(request_id):
                return row
        return None

    @classmethod
    def getRequestsForDesigner(cls, designer_user_id: str, status_filter: str = ""):
        rows = [r for r in cls._readAll() if str(r["designer_user_id"]) == str(designer_user_id)]
        if status_filter:
            rows = [r for r in rows if r["status"] == status_filter]
        return sorted(rows, key=lambda r: r["submitted_at"], reverse=True)

    @classmethod
    def getRequestsForCustomer(cls, customer_user_id: str):
        """Return all service requests submitted by a customer."""

        rows = [
            r for r in cls._readAll()
            if str(r["customer_user_id"]) == str(customer_user_id)
        ]

        return sorted(
            rows,
            key=lambda r: r["submitted_at"],
            reverse=True
        )

    @classmethod
    def changeStatus(cls, request_id: str, new_status: str) -> bool:
        rows = cls._readAll()
        updated = False
        for row in rows:
            if str(row["request_id"]) == str(request_id):
                row["status"] = new_status
                updated = True
        if updated:
            _writeCsv(cls.CSV_FILE, rows, cls.FIELDS)
        return updated
    
    @classmethod
    def createRequest(
        cls,
        customer_user_id,
        designer_user_id,
        renovation_brief,
        budget,
        request_type
    ):
        """Create a new service request from a customer."""

        rows = cls._readAll()

        new_id = str(
            max(
                (int(row["request_id"]) for row in rows),
                default=0
            ) + 1
        )

        new_request = {
            "request_id": new_id,
            "customer_user_id": str(customer_user_id),
            "designer_user_id": str(designer_user_id),
            "renovation_brief": renovation_brief.strip(),
            "budget": str(budget),
            "request_type": request_type,
            "status": "Pending",
            "submitted_at": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        }

        rows.append(new_request)

        _writeCsv(cls.CSV_FILE, rows, cls.FIELDS)

        return new_request


class Quotation:
    """<<entity>> :Quotation
    An itemised cost estimate for a service request. Line items are kept in quotation_items.csv.
    """
    CSV_FILE = os.path.join(DATA_DIR, "quotations.csv")
    ITEMS_CSV_FILE = os.path.join(DATA_DIR, "quotation_items.csv")
    FIELDS = ["quotation_id", "request_id", "total_amount", "scope", "exclusions", "created_at"]
    ITEM_FIELDS = ["quotation_id", "line_no", "description", "amount"]

    @staticmethod
    def calculateTotal(items) -> float:
        return round(sum(float(item["amount"]) for item in items), 2)

    @classmethod
    def findByRequest(cls, request_id: str):
        for row in _readCsv(cls.CSV_FILE):
            if str(row["request_id"]) == str(request_id):
                quotation = dict(row)
                quotation["items"] = sorted(
                    [i for i in _readCsv(cls.ITEMS_CSV_FILE) if i["quotation_id"] == row["quotation_id"]],
                    key=lambda i: int(i["line_no"])
                )
                return quotation
        return None

    @classmethod
    def saveQuotation(cls, request_id: str, items, scope: str, exclusions: str):
        """Creates the request's quotation, replacing any earlier one."""
        quotations = _readCsv(cls.CSV_FILE)
        all_items = _readCsv(cls.ITEMS_CSV_FILE)
        new_id = str(max([int(q["quotation_id"]) for q in quotations], default=0) + 1)

        old_ids = {q["quotation_id"] for q in quotations if str(q["request_id"]) == str(request_id)}
        quotations = [q for q in quotations if q["quotation_id"] not in old_ids]
        all_items = [i for i in all_items if i["quotation_id"] not in old_ids]
        new_quotation = {
            "quotation_id": new_id,
            "request_id": str(request_id),
            "total_amount": f"{cls.calculateTotal(items):.2f}",
            "scope": scope.strip(),
            "exclusions": exclusions.strip(),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        quotations.append(new_quotation)
        for line_no, item in enumerate(items, start=1):
            all_items.append({
                "quotation_id": new_id,
                "line_no": str(line_no),
                "description": item["description"].strip(),
                "amount": f"{float(item['amount']):.2f}"
            })
        _writeCsv(cls.CSV_FILE, quotations, cls.FIELDS)
        _writeCsv(cls.ITEMS_CSV_FILE, all_items, cls.ITEM_FIELDS)
        return new_quotation


class Consultation:
    """<<entity>> :Consultation
    A consultation session requested by the customer and answered by the designer.
    """
    CSV_FILE = os.path.join(DATA_DIR, "consultations.csv")
    FIELDS = ["consultation_id", "request_id", "proposed_time", "confirmed_time", "status",
              "designer_note", "responded_at"]

    @classmethod
    def createConsultation(cls, request_id: str, proposed_time: str):
        """Create a consultation request for a service request."""

        rows = _readCsv(cls.CSV_FILE)

        new_id = str(
            max(
                (int(row["consultation_id"]) for row in rows),
                default=0
            ) + 1
        )

        consultation = {
            "consultation_id": new_id,
            "request_id": str(request_id),
            "proposed_time": proposed_time,
            "confirmed_time": "",
            "status": "Requested",
            "designer_note": "",
            "responded_at": ""
        }

        rows.append(consultation)
        _writeCsv(cls.CSV_FILE, rows, cls.FIELDS)

        return consultation

    @classmethod
    def findByRequest(cls, request_id: str):
        for row in _readCsv(cls.CSV_FILE):
            if str(row["request_id"]) == str(request_id):
                return row
        return None

    @classmethod
    def respondToProposedTime(cls, consultation_id: str, status: str, proposed_time: str = None,
                              confirmed_time: str = None, designer_note: str = "") -> bool:
        rows = _readCsv(cls.CSV_FILE)
        updated = False
        for row in rows:
            if str(row["consultation_id"]) == str(consultation_id):
                row["status"] = status
                if proposed_time:
                    row["proposed_time"] = proposed_time
                if confirmed_time:
                    row["confirmed_time"] = confirmed_time
                row["designer_note"] = designer_note.strip()
                row["responded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                updated = True
        if updated:
            _writeCsv(cls.CSV_FILE, rows, cls.FIELDS)
        return updated


class ConsultationAvailability:
    """<<entity>> :ConsultationAvailability
    One-hour consultation slots a designer has opened, and whether each is still free.
    """
    CSV_FILE = os.path.join(DATA_DIR, "consultation_availability.csv")
    FIELDS = ["slot_id", "designer_user_id", "start_time", "end_time", "is_available"]

    @classmethod
    def _readAll(cls):
        return _readCsv(cls.CSV_FILE)

    @classmethod
    def findById(cls, slot_id: str):
        for row in cls._readAll():
            if str(row["slot_id"]) == str(slot_id):
                return row
        return None

    @classmethod
    def getAvailableSlots(cls, designer_user_id: str):
        """Free slots for the designer that have not started yet, earliest first."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return sorted(
            [r for r in cls._readAll()
             if str(r["designer_user_id"]) == str(designer_user_id)
             and r["is_available"] == "True" and r["start_time"] > now],
            key=lambda r: r["start_time"]
        )

    @classmethod
    def findFreeSlotAt(cls, designer_user_id: str, start_time: str):
        for row in cls._readAll():
            if (str(row["designer_user_id"]) == str(designer_user_id)
                    and row["start_time"] == start_time and row["is_available"] == "True"):
                return row
        return None

    @classmethod
    def updateSlot(cls, slot_id: str, is_available: bool) -> bool:
        rows = cls._readAll()
        updated = False
        for row in rows:
            if str(row["slot_id"]) == str(slot_id):
                row["is_available"] = "True" if is_available else "False"
                updated = True
        if updated:
            _writeCsv(cls.CSV_FILE, rows, cls.FIELDS)
        return updated

class RenovationProgress:
    CSV_FILE = os.path.join(DATA_DIR, "renovation_progress.csv")

    FIELDS = [
        "progress_id",
        "request_id",
        "designer_user_id",
        "stage",
        "completion_percentage",
        "note",
        "updated_at"
    ]

    @classmethod
    def _readAll(cls):
        if not os.path.exists(cls.CSV_FILE):
            return []

        return _readCsv(cls.CSV_FILE)

    @classmethod
    def _writeAll(cls, rows):
        _writeCsv(cls.CSV_FILE, rows, cls.FIELDS)

    @classmethod
    def addUpdate(cls, request_id, designer_user_id, stage,
                  completion_percentage, note=""):
        rows = cls._readAll()

        next_id = max(
            [int(row["progress_id"]) for row in rows],
            default=0
        ) + 1

        new_update = {
            "progress_id": str(next_id),
            "request_id": str(request_id),
            "designer_user_id": str(designer_user_id),
            "stage": stage,
            "completion_percentage": str(completion_percentage),
            "note": note,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        rows.append(new_update)
        cls._writeAll(rows)
        return new_update

    @classmethod
    def getHistory(cls, request_id):
        rows = [
            row for row in cls._readAll()
            if str(row["request_id"]) == str(request_id)
        ]

        return sorted(
            rows,
            key=lambda row: row["updated_at"],
            reverse=True
        )

    @classmethod
    def getLatest(cls, request_id):
        history = cls.getHistory(request_id)
        return history[0] if history else None