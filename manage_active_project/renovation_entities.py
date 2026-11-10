import csv
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_REQUEST_DATA_DIR = os.path.join(REPO_DIR, "process_service_requests", "data")

if not os.path.isdir(SERVICE_REQUEST_DATA_DIR):
    raise FileNotFoundError(f"Could not find Process Service Request's data/ folder at {SERVICE_REQUEST_DATA_DIR}")


def _readCsv(path):
    with open(path, mode="r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _writeCsv(path, rows, fieldnames):
    with open(path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class RenovationProject:
    """<<entity>> :RenovationProject
    A renovation the designer is carrying out for the customer of a service request.
    """
    CSV_FILE = os.path.join(DATA_DIR, "renovation_projects.csv")
    FIELDS = ["renovation_id", "source_request_id", "designer_user_id", "title", "status",
              "start_date", "expected_completion_date", "updated_at"]

    @classmethod
    def _readAll(cls):
        return _readCsv(cls.CSV_FILE)

    @classmethod
    def _updateFields(cls, renovation_id: str, **fields) -> bool:
        rows = cls._readAll()
        updated = False
        for row in rows:
            if str(row["renovation_id"]) == str(renovation_id):
                row.update(fields, updated_at=_now())
                updated = True
        if updated:
            _writeCsv(cls.CSV_FILE, rows, cls.FIELDS)
        return updated

    @classmethod
    def findById(cls, renovation_id: str):
        for row in cls._readAll():
            if str(row["renovation_id"]) == str(renovation_id):
                return row
        return None

    @classmethod
    def getProjectsForDesigner(cls, designer_user_id: str, status_filter: str = ""):
        """Active projects first, soonest expected completion first; completed projects last."""
        rows = [r for r in cls._readAll() if str(r["designer_user_id"]) == str(designer_user_id)]
        if status_filter:
            rows = [r for r in rows if r["status"] == status_filter]
        return sorted(rows, key=lambda r: (r["status"] == "Completed", r["expected_completion_date"]))

    @classmethod
    def updateExpectedCompletionDate(cls, renovation_id: str, expected_completion_date: str) -> bool:
        return cls._updateFields(renovation_id, expected_completion_date=expected_completion_date)

    @classmethod
    def updateStatus(cls, renovation_id: str, new_status: str) -> bool:
        return cls._updateFields(renovation_id, status=new_status)


class ProgressMilestone:
    """<<entity>> :ProgressMilestone
    One stage of a renovation project and how far along it is.
    """
    CSV_FILE = os.path.join(DATA_DIR, "progress_milestones.csv")
    FIELDS = ["milestone_id", "renovation_id", "description", "status", "recorded_at"]

    @classmethod
    def _readAll(cls):
        return _readCsv(cls.CSV_FILE)

    @classmethod
    def getMilestonesForProject(cls, renovation_id: str):
        return sorted([r for r in cls._readAll() if str(r["renovation_id"]) == str(renovation_id)],
                      key=lambda r: int(r["milestone_id"]))

    @classmethod
    def updateProgress(cls, milestone_id: str, status: str) -> bool:
        rows = cls._readAll()
        updated = False
        for row in rows:
            if str(row["milestone_id"]) == str(milestone_id):
                row["status"] = status
                row["recorded_at"] = _now()
                updated = True
        if updated:
            _writeCsv(cls.CSV_FILE, rows, cls.FIELDS)
        return updated

    @classmethod
    def addMilestone(cls, renovation_id: str, description: str, status: str = "Pending"):
        rows = cls._readAll()
        new_milestone = {
            "milestone_id": str(max([int(r["milestone_id"]) for r in rows], default=0) + 1),
            "renovation_id": str(renovation_id),
            "description": description.strip(),
            "status": status,
            "recorded_at": _now()
        }
        _writeCsv(cls.CSV_FILE, rows + [new_milestone], cls.FIELDS)
        return new_milestone


class ServiceRequest:
    """<<entity>> :ServiceRequest
    Read-only view of Process Service Request's requests; each renovation project comes from one.
    """
    CSV_FILE = os.path.join(SERVICE_REQUEST_DATA_DIR, "service_requests.csv")

    @classmethod
    def findById(cls, request_id: str):
        for row in _readCsv(cls.CSV_FILE):
            if str(row["request_id"]) == str(request_id):
                return row
        return None
