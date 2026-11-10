from datetime import date, datetime
from .help_page_bridge import RegisteredUser
from .renovation_entities import RenovationProject, RenovationProgress, ServiceRequest


def _friendlyDate(iso_date: str) -> str:
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d %b %Y")


class RenovationControl:
    """<<control>> :RenovationControl"""

    PROJECT_STATUSES = ("Not Started", "In Progress", "On Hold", "Completed")
    # Same stages Process Service Requests accepts for a progress update, so both pages record compatible entries
    PROGRESS_STAGES = ("Planning", "Design", "Procurement", "Construction", "Installation", "Finishing", "Completed")
    MAX_NOTE_LENGTH = 500

    @staticmethod
    def _checkDesignerPermissions(actor_role: str) -> bool:
        return actor_role == "Interior Designer"

    @staticmethod
    def _getOwnedProject(designer_user_id: str, renovation_id: str):
        project = RenovationProject.findById(renovation_id)
        if not project:
            raise LookupError(f"Renovation project #{renovation_id} was not found.")
        if str(project["designer_user_id"]) != str(designer_user_id):
            raise PermissionError("Unauthorised: This renovation project belongs to another designer.")
        return project

    @staticmethod
    def _isOverdue(project) -> bool:
        return project["status"] != "Completed" and project["expected_completion_date"] < date.today().isoformat()

    @staticmethod
    def _customerFor(source_request):
        return RegisteredUser.findById(source_request["customer_user_id"]) if source_request else None

    def viewActiveProjects(self, actor_role: str, designer_user_id: str, status_filter="", selected_renovation_id=None):
        """Returns the designer's renovation projects and the full details of the selected one."""
        if not self._checkDesignerPermissions(actor_role):
            raise PermissionError("Unauthorised: Only Interior Designers may manage renovation projects.")

        projects = RenovationProject.getProjectsForDesigner(designer_user_id, status_filter)
        for p in projects:
            customer = self._customerFor(ServiceRequest.findById(p["source_request_id"]))
            p["customer_name"] = customer["full_name"] if customer else "Unknown customer"
            p["latest_progress"] = RenovationProgress.getLatest(p["source_request_id"])
            p["is_overdue"] = self._isOverdue(p)

        selected = None
        if selected_renovation_id:
            selected = self._getOwnedProject(designer_user_id, selected_renovation_id)
            selected = next((p for p in projects if p["renovation_id"] == selected["renovation_id"]), selected)
        elif projects:
            selected = projects[0]

        selected_details = None
        if selected:
            source_request = ServiceRequest.findById(selected["source_request_id"])
            progress_history = RenovationProgress.getHistory(selected["source_request_id"])
            selected_details = {
                "project": selected,
                "progress_history": progress_history,
                "latest_progress": progress_history[0] if progress_history else None,
                "source_request": source_request,
                "customer": self._customerFor(source_request),
                "is_overdue": self._isOverdue(selected)
            }
        return projects, selected_details

    def _validateProgress(self, stage: str, completion_percentage, note: str):
        """Returns (True, (stage, percentage, note)) or (False, error message)."""
        if stage not in self.PROGRESS_STAGES:
            return False, "Please select a valid renovation stage."
        try:
            percentage = int(str(completion_percentage).strip())
        except ValueError:
            return False, "Please enter a valid completion percentage."
        if not 0 <= percentage <= 100:
            return False, "Completion percentage must be between 0 and 100."
        if stage == "Completed" and percentage != 100:
            return False, "A completed renovation must have 100% progress."
        note = (note or "").strip()
        if len(note) > self.MAX_NOTE_LENGTH:
            return False, f"Progress notes must be {self.MAX_NOTE_LENGTH} characters or fewer."
        return True, (stage, percentage, note)

    @staticmethod
    def _validateExpectedCompletionDate(project, status: str, expected_completion_date: str):
        """Returns (True, 'YYYY-MM-DD') or (False, error message)."""
        try:
            new_date = datetime.strptime(expected_completion_date.strip(), "%Y-%m-%d").date().isoformat()
        except ValueError:
            return False, "Please enter a valid expected completion date."
        if new_date < project["start_date"]:
            return False, f"The expected completion date can't be before the project started ({_friendlyDate(project['start_date'])})."
        today = date.today().isoformat()
        if status != "Completed" and new_date < today:
            return False, "The expected completion date has passed. Set a new date for this active project."
        if status == "Completed" and new_date > today:
            return False, "A completed project can't have a completion date in the future."
        return True, new_date

    def recordRenovationProgress(self, project, stage: str, percentage: int, note: str) -> bool:
        """<<include>> Posts a progress update for the customer, unless nothing changed since the last one."""
        latest = RenovationProgress.getLatest(project["source_request_id"])
        if latest and latest["stage"] == stage and int(latest["completion_percentage"]) == percentage and not note:
            return False
        RenovationProgress.addUpdate(project["source_request_id"], project["designer_user_id"], stage, percentage, note)
        return True

    def recordExpectedCompletionDate(self, renovation_id: str, expected_completion_date: str):
        """<<include>> Records a new expected completion date, or confirms the current one."""
        return RenovationProject.updateExpectedCompletionDate(renovation_id, expected_completion_date)

    def manageActiveProject(self, actor_role: str, designer_user_id: str, renovation_id: str, status: str,
                            stage: str, completion_percentage, note: str, expected_completion_date: str):
        """Updates an active project's status, always recording its progress and expected completion date."""
        if not self._checkDesignerPermissions(actor_role):
            raise PermissionError("Unauthorised: Only Interior Designers may manage renovation projects.")
        project = self._getOwnedProject(designer_user_id, renovation_id)
        if project["status"] == "Completed":
            return False, "This project is completed and can no longer be updated."
        if status not in self.PROJECT_STATUSES:
            return False, "Choose a valid project status."

        ok, result = self._validateProgress(stage, completion_percentage, note)
        if not ok:
            return False, result
        stage, percentage, note = result
        ok, result = self._validateExpectedCompletionDate(project, status, expected_completion_date)
        if not ok:
            return False, result
        new_date = result

        if status == "Completed" and stage != "Completed":
            return False, "Set the renovation stage to Completed (100%) before marking the project as completed."
        if stage == "Completed" and status != "Completed":
            return False, "This renovation is at the Completed stage, so mark the project as Completed."
        if status == "Not Started" and percentage > 0:
            return False, "A project with progress recorded can't be Not Started."

        # Every check has passed, so nothing is written unless the whole update is valid
        self.recordRenovationProgress(project, stage, percentage, note)
        self.recordExpectedCompletionDate(project["renovation_id"], new_date)
        RenovationProject.updateStatus(project["renovation_id"], status)

        msg = f"Project updated: {status}, {stage} stage at {percentage}%."
        if new_date != project["expected_completion_date"]:
            msg += (f" Expected completion moved from {_friendlyDate(project['expected_completion_date'])}"
                    f" to {_friendlyDate(new_date)}.")
        else:
            msg += f" Expected completion confirmed for {_friendlyDate(new_date)}."
        return True, msg
