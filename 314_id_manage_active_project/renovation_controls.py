from datetime import date, datetime
from help_page_bridge import RegisteredUser
from renovation_entities import RenovationProject, ProgressMilestone, ServiceRequest


def _friendlyDate(iso_date: str) -> str:
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d %b %Y")


class RenovationControl:
    """<<control>> :RenovationControl"""

    PROJECT_STATUSES = ("Not Started", "In Progress", "On Hold", "Completed")
    MILESTONE_STATUSES = ("Pending", "In Progress", "Completed")
    MAX_DESCRIPTION_LENGTH = 120

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
            milestones = ProgressMilestone.getMilestonesForProject(p["renovation_id"])
            customer = self._customerFor(ServiceRequest.findById(p["source_request_id"]))
            p["customer_name"] = customer["full_name"] if customer else "Unknown customer"
            p["milestones_done"] = sum(1 for m in milestones if m["status"] == "Completed")
            p["milestones_total"] = len(milestones)
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
            milestones = ProgressMilestone.getMilestonesForProject(selected["renovation_id"])
            selected_details = {
                "project": selected,
                "milestones": milestones,
                "milestones_done": sum(1 for m in milestones if m["status"] == "Completed"),
                "source_request": source_request,
                "customer": self._customerFor(source_request),
                "is_overdue": self._isOverdue(selected)
            }
        return projects, selected_details

    def _validateMilestones(self, milestones, milestone_statuses, new_milestones):
        """Returns (True, (status_changes, additions)) or (False, error message)."""
        current = {m["milestone_id"]: m for m in milestones}
        status_changes = {}
        for milestone_id, status in milestone_statuses.items():
            if milestone_id not in current:
                return False, f"Milestone #{milestone_id} does not belong to this project."
            if status not in self.MILESTONE_STATUSES:
                return False, f"Choose a valid status for '{current[milestone_id]['description']}'."
            if status != current[milestone_id]["status"]:
                status_changes[milestone_id] = status

        additions = []
        seen = {m["description"].strip().lower() for m in milestones}
        for item in new_milestones:
            description = str(item.get("description", "")).strip()
            status = item.get("status") or "Pending"
            if not description:
                continue  # blank form row
            if len(description) > self.MAX_DESCRIPTION_LENGTH:
                return False, f"Milestone descriptions must be {self.MAX_DESCRIPTION_LENGTH} characters or fewer."
            if description.lower() in seen:
                return False, f"'{description}' is already a milestone for this project."
            if status not in self.MILESTONE_STATUSES:
                return False, f"Choose a valid status for '{description}'."
            seen.add(description.lower())
            additions.append({"description": description, "status": status})
        return True, (status_changes, additions)

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

    def recordProgressMilestones(self, renovation_id: str, status_changes, additions):
        """<<include>> Records the milestone statuses that changed and any new milestones."""
        for milestone_id, status in status_changes.items():
            ProgressMilestone.updateProgress(milestone_id, status)
        for item in additions:
            ProgressMilestone.addMilestone(renovation_id, item["description"], item["status"])
        return len(status_changes) + len(additions)

    def recordExpectedCompletionDate(self, renovation_id: str, expected_completion_date: str):
        """<<include>> Records a new expected completion date, or confirms the current one."""
        return RenovationProject.updateExpectedCompletionDate(renovation_id, expected_completion_date)

    def manageActiveProject(self, actor_role: str, designer_user_id: str, renovation_id: str, status: str,
                            milestone_statuses, new_milestones, expected_completion_date: str):
        """Updates an active project's status, always recording its milestones and expected completion date."""
        if not self._checkDesignerPermissions(actor_role):
            raise PermissionError("Unauthorised: Only Interior Designers may manage renovation projects.")
        project = self._getOwnedProject(designer_user_id, renovation_id)
        if project["status"] == "Completed":
            return False, "This project is completed and can no longer be updated."
        if status not in self.PROJECT_STATUSES:
            return False, "Choose a valid project status."

        milestones = ProgressMilestone.getMilestonesForProject(project["renovation_id"])
        ok, result = self._validateMilestones(milestones, milestone_statuses, new_milestones)
        if not ok:
            return False, result
        status_changes, additions = result
        ok, result = self._validateExpectedCompletionDate(project, status, expected_completion_date)
        if not ok:
            return False, result
        new_date = result

        final_statuses = [status_changes.get(m["milestone_id"], m["status"]) for m in milestones]
        final_statuses += [item["status"] for item in additions]
        if not final_statuses:
            return False, "Record at least one progress milestone for this project."
        if status == "Completed" and any(s != "Completed" for s in final_statuses):
            return False, "Complete every milestone before marking the project as completed."
        if status == "Not Started" and any(s != "Pending" for s in final_statuses):
            return False, "A project with milestones in progress or completed can't be Not Started."

        # Every check has passed, so nothing is written unless the whole update is valid
        self.recordProgressMilestones(project["renovation_id"], status_changes, additions)
        self.recordExpectedCompletionDate(project["renovation_id"], new_date)
        RenovationProject.updateStatus(project["renovation_id"], status)

        done = sum(1 for s in final_statuses if s == "Completed")
        msg = f"Project updated: {status}, {done} of {len(final_statuses)} milestones completed."
        if new_date != project["expected_completion_date"]:
            msg += (f" Expected completion moved from {_friendlyDate(project['expected_completion_date'])}"
                    f" to {_friendlyDate(new_date)}.")
        else:
            msg += f" Expected completion confirmed for {_friendlyDate(new_date)}."
        return True, msg
