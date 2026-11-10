import csv
import os

from .help_page_bridge import RegisteredUser

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class Project:
    """<<entity>> :Project
    Project listings owned by Interior Designers (imported from the portfolio app's projects table).
    """
    CSV_FILE = os.path.join(DATA_DIR, "projects.csv")

    @classmethod
    def _readAll(cls):
        with open(cls.CSV_FILE, mode="r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    @classmethod
    def findById(cls, project_id: str):
        for row in cls._readAll():
            if str(row["project_id"]) == str(project_id):
                return row
        return None

    @classmethod
    def getProjectsByDesigner(cls, designer_user_id: str):
        return [r for r in cls._readAll() if str(r["designer_user_id"]) == str(designer_user_id)]


class EngagementRecord:
    """<<entity>> :EngagementRecord
    One customer engagement event (View or Shortlist) on a project.
    """
    CSV_FILE = os.path.join(DATA_DIR, "engagement_records.csv")

    @classmethod
    def _readAll(cls):
        with open(cls.CSV_FILE, mode="r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    @classmethod
    def getRecordsForProjects(cls, project_ids):
        wanted = {str(pid) for pid in project_ids}
        return [r for r in cls._readAll() if str(r["project_id"]) in wanted]


class DesignerFollow:
    """<<entity>> :DesignerFollow
    A customer following an Interior Designer.
    """
    CSV_FILE = os.path.join(DATA_DIR, "designer_follows.csv")

    @classmethod
    def _readAll(cls):
        with open(cls.CSV_FILE, mode="r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    @classmethod
    def getFollowersOfDesigner(cls, designer_user_id: str):
        """Returns follow records for the designer, joined with each follower's account details."""
        followers = []
        for row in cls._readAll():
            if str(row["designer_user_id"]) != str(designer_user_id):
                continue
            customer = RegisteredUser.findById(row["customer_user_id"])
            if not customer:
                continue
            followers.append({
                "follow_id": row["follow_id"],
                "customer_user_id": row["customer_user_id"],
                "full_name": customer["full_name"],
                "username": customer["username"],
                "email": customer["email"],
                "followed_at": row["followed_at"]
            })
        return followers
