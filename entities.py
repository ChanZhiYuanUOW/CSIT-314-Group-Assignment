import csv
import os
import random
import hashlib
import secrets
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class RegisteredUser:
    """<<entity>> :RegisteredUser
    Handles all persistence for user accounts, PBKDF2-SHA256 password hashing,
    authentication, personal profiles, notification preferences, and status/role updates.
    """
    CSV_FILE = os.path.join(DATA_DIR, "registered_users.csv")

    @staticmethod
    def hashPassword(password: str, salt: str = None) -> str:
        """Hashes a plaintext password using PBKDF2-HMAC-SHA256 (100,000 iterations)."""
        if not salt:
            salt = secrets.token_hex(8)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
        return f"pbkdf2_sha256$100000${salt}${dk.hex()}"

    @classmethod
    def verifyPassword(cls, stored_password: str, provided_password: str) -> bool:
        """Verifies a plaintext password against a stored PBKDF2 hash (with fallback for legacy plain text)."""
        if stored_password.startswith("pbkdf2_sha256$"):
            parts = stored_password.split("$")
            if len(parts) == 4:
                salt = parts[2]
                expected_hash = cls.hashPassword(provided_password, salt=salt)
                return secrets.compare_digest(stored_password, expected_hash)
        return stored_password == provided_password

    @classmethod
    def _readAll(cls):
        with open(cls.CSV_FILE, mode="r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    @classmethod
    def _writeAll(cls, rows, fieldnames=None):
        if not fieldnames and rows:
            fieldnames = list(rows[0].keys())
        with open(cls.CSV_FILE, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    @classmethod
    def findByEmailOrUsername(cls, identifier: str):
        ident = identifier.strip().lower()
        for row in cls._readAll():
            if row["email"].lower() == ident or row["username"].lower() == ident:
                return row
        return None

    @classmethod
    def findById(cls, user_id: str):
        for row in cls._readAll():
            if str(row["user_id"]) == str(user_id):
                return row
        return None

    @classmethod
    def createAccount(cls, username: str, email: str, password: str, full_name: str, phone: str, role: str):
        rows = cls._readAll()
        new_id = max([int(r["user_id"]) for r in rows], default=0) + 1
        password_hash = cls.hashPassword(password)
        new_user = {
            "user_id": str(new_id),
            "username": username.strip(),
            "email": email.strip().lower(),
            "password": password_hash,
            "full_name": full_name.strip(),
            "phone": phone.strip(),
            "role": role,
            "status": "Active",
            "notify_email": "True",
            "notify_sms": "False",
            "notify_marketing": "False",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        rows.append(new_user)
        cls._writeAll(rows)
        return new_user

    @classmethod
    def getAccountRecords(cls, search_query="", role_filter="", status_filter=""):
        records = []
        q = search_query.strip().lower()
        for row in cls._readAll():
            if q and q not in (row["full_name"] + " " + row["email"] + " " + row["username"]).lower():
                continue
            if role_filter and row["role"] != role_filter:
                continue
            if status_filter and row["status"] != status_filter:
                continue
            records.append(row)
        return records

    @classmethod
    def findPotentialDuplicates(cls, include_resolved=False):
        """Groups accounts that share the same full_name or phone number.
        By default, only returns unresolved duplicate clusters where >1 account is still active.
        """
        rows = cls._readAll()
        by_key = {}
        for r in rows:
            if not include_resolved and r["status"] == "Duplicate_Disabled":
                continue
            key = (r["full_name"].strip().lower(), r["phone"].strip())
            by_key.setdefault(key, []).append(r)

        duplicate_groups = []
        for (name, phone), group in by_key.items():
            if len(group) > 1:
                duplicate_groups.append(group)
        return duplicate_groups

    @classmethod
    def getResolvedDuplicates(cls):
        """Returns accounts that have already been disabled as confirmed duplicates."""
        return [r for r in cls._readAll() if r["status"] == "Duplicate_Disabled"]

    @classmethod
    def changeAccountStatus(cls, user_id: str, new_status: str) -> bool:
        rows = cls._readAll()
        updated = False
        for row in rows:
            if str(row["user_id"]) == str(user_id):
                row["status"] = new_status
                updated = True
        if updated:
            cls._writeAll(rows)
        return updated

    @classmethod
    def updateAccountRole(cls, user_id: str, new_role: str) -> bool:
        rows = cls._readAll()
        updated = False
        for row in rows:
            if str(row["user_id"]) == str(user_id):
                row["role"] = new_role
                updated = True
        if updated:
            cls._writeAll(rows)
        return updated

    @classmethod
    def updatePersonalProfile(cls, user_id: str, full_name: str, phone: str, email: str) -> bool:
        rows = cls._readAll()
        updated = False
        for row in rows:
            if str(row["user_id"]) == str(user_id):
                row["full_name"] = full_name.strip()
                row["phone"] = phone.strip()
                row["email"] = email.strip().lower()
                updated = True
        if updated:
            cls._writeAll(rows)
        return updated

    @classmethod
    def updateNotificationPreferences(cls, user_id: str, notify_email: bool, notify_sms: bool, notify_marketing: bool) -> bool:
        rows = cls._readAll()
        updated = False
        for row in rows:
            if str(row["user_id"]) == str(user_id):
                row["notify_email"] = "True" if notify_email else "False"
                row["notify_sms"] = "True" if notify_sms else "False"
                row["notify_marketing"] = "True" if notify_marketing else "False"
                updated = True
        if updated:
            cls._writeAll(rows)
        return updated

    @classmethod
    def updatePassword(cls, email: str, new_password: str) -> bool:
        rows = cls._readAll()
        updated = False
        hashed_pw = cls.hashPassword(new_password)
        for row in rows:
            if row["email"].lower() == email.strip().lower():
                row["password"] = hashed_pw
                updated = True
        if updated:
            cls._writeAll(rows)
        return updated


class PasswordResetToken:
    """<<entity>> :PasswordResetToken"""
    CSV_FILE = os.path.join(DATA_DIR, "password_reset_tokens.csv")

    @classmethod
    def _readAll(cls):
        with open(cls.CSV_FILE, mode="r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    @classmethod
    def _writeAll(cls, rows):
        if not rows:
            return
        with open(cls.CSV_FILE, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    @classmethod
    def createToken(cls, user_id: str, email: str) -> str:
        rows = cls._readAll()
        new_id = max([int(r["token_id"]) for r in rows], default=0) + 1
        token_str = f"RST-{random.randint(100000, 999999)}"
        rows.append({
            "token_id": str(new_id),
            "user_id": str(user_id),
            "email": email.strip().lower(),
            "token": token_str,
            "is_used": "False",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        cls._writeAll(rows)
        return token_str

    @classmethod
    def validateAndConsumeToken(cls, email: str, token_str: str) -> bool:
        rows = cls._readAll()
        matched = False
        for row in reversed(rows):
            if (row["email"].lower() == email.strip().lower()
                    and row["token"].strip() == token_str.strip()
                    and row["is_used"] == "False"):
                row["is_used"] = "True"
                matched = True
                break
        if matched:
            cls._writeAll(rows)
        return matched


class VerificationEvidence:
    """<<entity>> :VerificationEvidence
    Manages business registration verification queue and listed verified businesses.
    """
    CSV_FILE = os.path.join(DATA_DIR, "verification_evidence.csv")

    @classmethod
    def getAllEvidence(cls):
        with open(cls.CSV_FILE, mode="r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    @classmethod
    def _writeAll(cls, rows):
        if not rows:
            return
        with open(cls.CSV_FILE, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    @classmethod
    def getPendingEvidence(cls):
        """Returns only pending business registration submissions awaiting review."""
        return [r for r in cls.getAllEvidence() if r.get("verification_status") == "Pending"]

    @classmethod
    def getEvidenceById(cls, evidence_id: str):
        for row in cls.getAllEvidence():
            if str(row["evidence_id"]) == str(evidence_id):
                return row
        return None

    @classmethod
    def searchListedBusinesses(cls, search_query="", specialty_filter="", listing_status_filter=""):
        """Searches and filters businesses that have been Verified (or previously listed)."""
        results = []
        q = search_query.strip().lower()
        for row in cls.getAllEvidence():
            if row.get("verification_status") != "Verified":
                continue
            if q and q not in (
                row.get("company_name", "") + " " +
                row.get("designer_name", "") + " " +
                row.get("registration_uen", "") + " " +
                row.get("address", "")
            ).lower():
                continue
            if specialty_filter and row.get("specialty") != specialty_filter:
                continue
            if listing_status_filter and row.get("listing_status") != listing_status_filter:
                continue
            results.append(row)
        return results

    @classmethod
    def recordReviewOutcome(cls, evidence_id: str, outcome: str, reviewer_id: str, remarks: str) -> bool:
        rows = cls.getAllEvidence()
        updated = False
        for row in rows:
            if str(row["evidence_id"]) == str(evidence_id):
                row["verification_status"] = outcome
                row["reviewed_by"] = str(reviewer_id)
                row["review_remarks"] = remarks.strip() or f"Marked as {outcome}"
                row["reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if outcome == "Verified":
                    row["listing_status"] = "Active"
                else:
                    row["listing_status"] = "Unlisted"
                updated = True
        if updated:
            cls._writeAll(rows)
        return updated

    @classmethod
    def updateVerifiedBusinessListing(cls, evidence_id: str, listing_status: str = None, specialty: str = None, remarks: str = None) -> bool:
        """Moderates a verified business listing (e.g. Active, Suspended, Unlisted/Revoked) or updates its specialty category."""
        rows = cls.getAllEvidence()
        updated = False
        for row in rows:
            if str(row["evidence_id"]) == str(evidence_id):
                if listing_status:
                    row["listing_status"] = listing_status
                    if listing_status == "Revoked":
                        row["verification_status"] = "Pending"
                if specialty:
                    row["specialty"] = specialty
                if remarks is not None and remarks.strip():
                    row["review_remarks"] = remarks.strip()
                row["reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                updated = True
        if updated:
            cls._writeAll(rows)
        return updated


class AccountAuditEntry:
    """<<entity>> :AccountAuditEntry"""
    CSV_FILE = os.path.join(DATA_DIR, "account_audit_entries.csv")

    @classmethod
    def getAuditLog(cls, target_user_id=None):
        with open(cls.CSV_FILE, mode="r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if target_user_id:
            rows = [r for r in rows if str(r["target_user_id"]) == str(target_user_id)]
        return list(reversed(rows))

    @classmethod
    def recordAction(cls, admin_user_id: str, target_user_id: str, target_email: str, action: str, details: str):
        with open(cls.CSV_FILE, mode="r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        new_id = max([int(r["audit_id"]) for r in rows], default=0) + 1
        new_row = {
            "audit_id": str(new_id),
            "admin_user_id": str(admin_user_id),
            "target_user_id": str(target_user_id),
            "target_email": target_email,
            "action": action,
            "details": details,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        rows.append(new_row)
        with open(cls.CSV_FILE, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return new_row
