"""
Links this feature to the help page app (login, registered accounts), which lives in the repo root
-- without modifying any of its files
-- in order to use help page data, entities and templates for our code
Run from the repo root so the help page's modules (e.g. entities) can be imported.
"""

import os

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HELP_PAGE_TEMPLATES_DIR = os.path.join(REPO_DIR, "templates")
HELP_PAGE_DATA_DIR = os.path.join(REPO_DIR, "data")

for _name, _path in (("templates", HELP_PAGE_TEMPLATES_DIR), ("data", HELP_PAGE_DATA_DIR)):
    if not os.path.isdir(_path):
        raise FileNotFoundError(f"Could not find the help page's {_name}/ folder in {REPO_DIR}")

from entities import RegisteredUser, PasswordResetToken, VerificationEvidence, AccountAuditEntry  # noqa: E402,F401
