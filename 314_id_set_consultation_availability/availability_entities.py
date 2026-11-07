import csv
import os
from datetime import datetime

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED_DATA_DIR = os.path.join(REPO_DIR, "314_id_process_service_requests", "data")

if not os.path.isdir(SHARED_DATA_DIR):
    raise FileNotFoundError(f"Could not find Process Service Request's data/ folder at {SHARED_DATA_DIR}")


def _readCsv(path):
    with open(path, mode="r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _writeCsv(path, rows, fieldnames):
    with open(path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class ConsultationAvailability:
    """<<entity>> :ConsultationAvailability
    One-hour consultation slots a designer has opened, and whether each is still free.
    """
    CSV_FILE = os.path.join(SHARED_DATA_DIR, "consultation_availability.csv")
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
    def getSlotsForDesigner(cls, designer_user_id: str, upcoming_only: bool = False):
        """The designer's slots, earliest first. upcoming_only leaves out slots that have started."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return sorted(
            [r for r in cls._readAll()
             if str(r["designer_user_id"]) == str(designer_user_id)
             and (not upcoming_only or r["start_time"] > now)],
            key=lambda r: r["start_time"]
        )

    @classmethod
    def addSlots(cls, designer_user_id: str, slot_times):
        """Opens a free slot for each (start_time, end_time) pair."""
        rows = cls._readAll()
        next_id = max([int(r["slot_id"]) for r in rows], default=0) + 1
        new_rows = [{
            "slot_id": str(next_id + offset),
            "designer_user_id": str(designer_user_id),
            "start_time": start_time,
            "end_time": end_time,
            "is_available": "True"
        } for offset, (start_time, end_time) in enumerate(slot_times)]
        _writeCsv(cls.CSV_FILE, rows + new_rows, cls.FIELDS)
        return new_rows

    @classmethod
    def removeSlot(cls, slot_id: str) -> bool:
        rows = cls._readAll()
        remaining = [r for r in rows if str(r["slot_id"]) != str(slot_id)]
        if len(remaining) == len(rows):
            return False
        _writeCsv(cls.CSV_FILE, remaining, cls.FIELDS)
        return True
