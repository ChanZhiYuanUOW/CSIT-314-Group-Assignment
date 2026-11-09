"""
Links this feature to the existing 314_id_help_page app (login, registered accounts)
-- without modifying any of its files
-- in order to use help page data, entities and templates for our code
Import this module before importing anything from the help page.
"""

import os
import sys

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELP_PAGE_CODE_DIR = os.path.join(REPO_DIR, "314_id_help_page")


def _findHelpPageFolder(name: str) -> str:
    # temp fix for help page
    for folder in ("314_id_help_page", "314_id_help_page "):
        path = os.path.join(REPO_DIR, folder, name)
        if os.path.isdir(path):
            return path
    raise FileNotFoundError(f"Could not find the help page's {name}/ folder in {REPO_DIR}")


HELP_PAGE_TEMPLATES_DIR = _findHelpPageFolder("templates")
HELP_PAGE_DATA_DIR = _findHelpPageFolder("data")

if HELP_PAGE_CODE_DIR not in sys.path:
    sys.path.insert(1, HELP_PAGE_CODE_DIR)

# don't write pyc files in help page folder
sys.dont_write_bytecode = True

import entities as help_page_entities
from entities import RegisteredUser, PasswordResetToken, VerificationEvidence, AccountAuditEntry  # noqa: E402

# if the help page's data folder doesn't exist, use the data folder in this folder
if not os.path.isdir(help_page_entities.DATA_DIR):
    for entity in (RegisteredUser, PasswordResetToken, VerificationEvidence, AccountAuditEntry):
        entity.CSV_FILE = os.path.join(HELP_PAGE_DATA_DIR, os.path.basename(entity.CSV_FILE))
