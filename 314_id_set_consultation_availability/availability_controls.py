from datetime import datetime, timedelta
from availability_entities import ConsultationAvailability

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class ServiceRequestControl:
    """<<control>> :ServiceRequestControl"""

    SLOT_LENGTH = timedelta(hours=1)
    EARLIEST_HOUR = 8    # consultations run from 8:00 AM...
    LATEST_HOUR = 22     # ...to 10:00 PM
    MAX_REPEAT_WEEKS = 8

    @staticmethod
    def _checkDesignerPermissions(actor_role: str) -> bool:
        return actor_role == "Interior Designer"

    def viewConsultationAvailability(self, actor_role: str, designer_user_id: str):
        """Returns the designer's upcoming slots, earliest first."""
        if not self._checkDesignerPermissions(actor_role):
            raise PermissionError("Unauthorised: Only Interior Designers may manage consultation availability.")
        return ConsultationAvailability.getSlotsForDesigner(designer_user_id, upcoming_only=True)

    def setConsultationAvailability(self, actor_role: str, designer_user_id: str, slot_date: str,
                                    from_time: str, to_time: str, repeat_weeks="0"):
        """Opens 1-hour slots from from_time to to_time on slot_date, repeated weekly for repeat_weeks more weeks."""
        if not self._checkDesignerPermissions(actor_role):
            raise PermissionError("Unauthorised: Only Interior Designers may set consultation availability.")
        try:
            first_start = datetime.strptime(f"{slot_date} {from_time}", "%Y-%m-%d %H:%M")
            first_end = datetime.strptime(f"{slot_date} {to_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return False, "Please choose a valid date, start time and end time."
        try:
            repeat_weeks = int(repeat_weeks or 0)
        except ValueError:
            return False, "Weeks to repeat must be a whole number."

        if not 0 <= repeat_weeks <= self.MAX_REPEAT_WEEKS:
            return False, f"Availability can be repeated for up to {self.MAX_REPEAT_WEEKS} more weeks."
        if first_end <= first_start:
            return False, "The end time must be after the start time."
        if (first_end - first_start) % self.SLOT_LENGTH:
            return False, "Consultation slots are 1 hour long, so the time range must be in whole hours."
        if first_start.hour < self.EARLIEST_HOUR or first_end > first_end.replace(hour=self.LATEST_HOUR, minute=0):
            return False, "Consultation hours must be between 8:00 AM and 10:00 PM."
        if first_start <= datetime.now():
            return False, "Availability must start in the future."

        existing = ConsultationAvailability.getSlotsForDesigner(designer_user_id)
        new_slots, skipped = [], 0
        for week in range(repeat_weeks + 1):
            start = first_start + timedelta(weeks=week)
            range_end = first_end + timedelta(weeks=week)
            while start < range_end:
                slot_start = start.strftime(TIME_FORMAT)
                slot_end = (start + self.SLOT_LENGTH).strftime(TIME_FORMAT)
                if any(slot_start < r["end_time"] and r["start_time"] < slot_end for r in existing):
                    skipped += 1
                else:
                    new_slots.append((slot_start, slot_end))
                start += self.SLOT_LENGTH

        if not new_slots:
            return False, "You already have availability for all of those times."
        ConsultationAvailability.addSlots(designer_user_id, new_slots)

        msg = f"Added {len(new_slots)} consultation slot{'s' if len(new_slots) != 1 else ''}"
        if repeat_weeks:
            last_day = first_start + timedelta(weeks=repeat_weeks)
            msg += f" every {first_start:%A} from {first_start:%d %b} to {last_day:%d %b %Y}."
        else:
            msg += f" on {first_start:%a %d %b %Y}."
        if skipped:
            msg += f" Skipped {skipped} that overlapped slots you already have."
        return True, msg

    def removeConsultationSlot(self, actor_role: str, designer_user_id: str, slot_id: str):
        """Removes one of the designer's free upcoming slots so customers can no longer book it."""
        if not self._checkDesignerPermissions(actor_role):
            raise PermissionError("Unauthorised: Only Interior Designers may set consultation availability.")
        slot = ConsultationAvailability.findById(slot_id)
        if not slot:
            raise LookupError(f"Availability slot #{slot_id} was not found.")
        if str(slot["designer_user_id"]) != str(designer_user_id):
            raise PermissionError("Unauthorised: This availability slot belongs to another designer.")
        if slot["is_available"] != "True":
            return False, "This slot is booked for a consultation and cannot be removed."
        if slot["start_time"] <= datetime.now().strftime(TIME_FORMAT):
            return False, "This slot has already started and cannot be removed."

        ConsultationAvailability.removeSlot(slot["slot_id"])
        return True, f"Removed the slot on {slot['start_time'][:16]}."
