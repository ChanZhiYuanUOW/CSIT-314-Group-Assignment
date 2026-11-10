import csv
import os
from datetime import datetime

from flask import current_app, has_app_context

from .help_page_bridge import RegisteredUser, HELP_PAGE_DATA_DIR

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

DEFAULT_PLATFORM_DATA_DIR = os.path.join(HELP_PAGE_DATA_DIR, "platform")


def platformDataDir() -> str:
    if has_app_context() and current_app.config.get("PM_CSV_DIR"):
        return str(current_app.config["PM_CSV_DIR"])
    return DEFAULT_PLATFORM_DATA_DIR


def _readPlatformCsv(table: str):
    path = os.path.join(platformDataDir(), table + ".csv")
    if not os.path.exists(path):
        return []
    with open(path, mode="r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _localTimestamp(value: str) -> str:
    """'2026-09-24T21:40:23+00:00' (UTC) -> '2026-09-25 05:40:23' in this machine's local time."""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


class Project:
    """<<entity>> :Project
    Project listings owned by Interior Designers (the portfolio's shared projects table).
    """

    @staticmethod
    def _fromPlatformRow(row, category_names):
        return {
            "project_id": row["id"],
            "designer_user_id": row["designer_id"],
            "title": row["title"],
            "description": row["description"],
            "category": category_names.get(row["category_id"], "Uncategorised"),
            "tags": row.get("tags", ""),
            "publication_status": row["status"].capitalize(),
            "created_at": row["created_at"]
        }

    @classmethod
    def _readAll(cls):
        category_names = {c["id"]: c["name"] for c in _readPlatformCsv("categories")}
        return [cls._fromPlatformRow(r, category_names) for r in _readPlatformCsv("projects")]

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
    One customer engagement event (View or Shortlist) on a project, from the shared engagement_events table.
    """
    EVENT_TYPES = {"view": "View", "shortlist": "Shortlist"}

    @classmethod
    def _readAll(cls):
        return [{
            "record_id": r["id"],
            "project_id": r["project_id"],
            "customer_user_id": r["customer_id"],
            "event_type": cls.EVENT_TYPES.get(r["kind"].lower(), r["kind"]),
            "occurred_at": _localTimestamp(r["occurred_at"])
        } for r in _readPlatformCsv("engagement_events")]

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
