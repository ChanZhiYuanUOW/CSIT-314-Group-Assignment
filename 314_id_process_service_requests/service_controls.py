from datetime import datetime
from help_page_bridge import RegisteredUser
from service_entities import ServiceRequest, Quotation, Consultation, ConsultationAvailability


class ServiceRequestControl:
    """<<control>> :ServiceRequestControl"""

    REQUEST_STATUSES = ("Pending", "In Progress", "Responded")
    CONSULTATION_DECISIONS = ("accept", "decline", "propose")

    @staticmethod
    def _checkDesignerPermissions(actor_role: str) -> bool:
        return actor_role == "Interior Designer"

    @staticmethod
    def _getOwnedRequest(designer_user_id: str, request_id: str):
        request = ServiceRequest.findById(request_id)
        if not request:
            raise LookupError(f"Service request #{request_id} was not found.")
        if str(request["designer_user_id"]) != str(designer_user_id):
            raise PermissionError("Unauthorised: This service request was sent to another designer.")
        return request

    @staticmethod
    def _wantsQuotation(request) -> bool:
        return "Quotation" in request["request_type"]

    @staticmethod
    def _wantsConsultation(request) -> bool:
        return "Consultation" in request["request_type"]

    def _refreshRequestStatus(self, request):
        """Responded once every requested part is answered, In Progress if only some are."""
        parts_answered = []
        if self._wantsQuotation(request):
            parts_answered.append(Quotation.findByRequest(request["request_id"]) is not None)
        if self._wantsConsultation(request):
            consultation = Consultation.findByRequest(request["request_id"])
            parts_answered.append(consultation is not None and consultation["status"] != "Requested")

        if parts_answered and all(parts_answered):
            new_status = "Responded"
        elif any(parts_answered):
            new_status = "In Progress"
        else:
            new_status = "Pending"
        if new_status != request["status"]:
            ServiceRequest.changeStatus(request["request_id"], new_status)
        return new_status

    def processServiceRequest(self, actor_role: str, designer_user_id: str, status_filter="", selected_request_id=None):
        """Returns the designer's incoming requests and the full details of the selected one."""
        if not self._checkDesignerPermissions(actor_role):
            raise PermissionError("Unauthorised: Only Interior Designers may process service requests.")

        request_list = ServiceRequest.getRequestsForDesigner(designer_user_id, status_filter)
        for r in request_list:
            customer = RegisteredUser.findById(r["customer_user_id"])
            r["customer_name"] = customer["full_name"] if customer else f"Customer #{r['customer_user_id']}"

        selected = None
        if selected_request_id:
            selected = self._getOwnedRequest(designer_user_id, selected_request_id)
        elif request_list:
            selected = request_list[0]

        selected_details = None
        if selected:
            customer = RegisteredUser.findById(selected["customer_user_id"])
            consultation = Consultation.findByRequest(selected["request_id"])
            selected_details = {
                "request": selected,
                "customer": customer,
                "wants_quotation": self._wantsQuotation(selected),
                "wants_consultation": self._wantsConsultation(selected),
                "quotation": Quotation.findByRequest(selected["request_id"]),
                "consultation": consultation,
                "requested_time_is_free": bool(consultation) and ConsultationAvailability.findFreeSlotAt(
                    designer_user_id, consultation["proposed_time"]) is not None,
                "available_slots": ConsultationAvailability.getAvailableSlots(designer_user_id)
            }
        return request_list, selected_details

    def generateItemisedCostEstimate(self, actor_role: str, designer_user_id: str, request_id: str,
                                     items, scope: str, exclusions: str = ""):
        """<<extend>> Validates the line items and saves the itemised quotation for the request."""
        if not self._checkDesignerPermissions(actor_role):
            raise PermissionError("Unauthorised: Only Interior Designers may generate cost estimates.")
        request = self._getOwnedRequest(designer_user_id, request_id)
        if not self._wantsQuotation(request):
            return False, "This customer did not request a quotation."

        cleaned_items = []
        for item in items:
            description = str(item.get("description", "")).strip()
            amount_text = str(item.get("amount", "")).strip()
            if not description and not amount_text:
                continue  # blank form row
            if not description:
                return False, "Every line item needs a description."
            try:
                amount = float(amount_text)
            except ValueError:
                return False, f"Amount for '{description}' must be a number."
            if amount <= 0:
                return False, f"Amount for '{description}' must be greater than 0."
            cleaned_items.append({"description": description, "amount": round(amount, 2)})

        if not cleaned_items:
            return False, "Add at least one line item to the estimate."
        if not scope.strip():
            return False, "Please describe the scope of works."

        quotation = Quotation.saveQuotation(request["request_id"], cleaned_items, scope, exclusions)
        self._refreshRequestStatus(request)

        total = float(quotation["total_amount"])
        budget = float(request["budget"])
        msg = f"Itemised quotation of S${total:,.2f} sent to the customer."
        if total > budget:
            msg += f" Note: this is S${total - budget:,.2f} over the customer's budget of S${budget:,.2f}."
        return True, msg

    def acceptDeclineOrProposeTime(self, actor_role: str, designer_user_id: str, request_id: str,
                                   decision: str, slot_id: str = None, note: str = ""):
        """<<extend>> Accepts, declines or proposes a new time for the requested consultation."""
        if not self._checkDesignerPermissions(actor_role):
            raise PermissionError("Unauthorised: Only Interior Designers may respond to consultations.")
        request = self._getOwnedRequest(designer_user_id, request_id)
        consultation = Consultation.findByRequest(request["request_id"])
        if not self._wantsConsultation(request) or not consultation:
            return False, "This customer did not request a consultation."
        if consultation["status"] != "Requested":
            return False, f"This consultation has already been answered ({consultation['status']})."
        if decision not in self.CONSULTATION_DECISIONS:
            return False, "Choose to accept, decline or propose a new time."

        if decision == "accept":
            slot = ConsultationAvailability.findFreeSlotAt(designer_user_id, consultation["proposed_time"])
            if not slot:
                return False, "You have no free availability slot at the requested time. Propose a new time instead."
            Consultation.respondToProposedTime(consultation["consultation_id"], "Accepted",
                                               confirmed_time=slot["start_time"], designer_note=note)
            ConsultationAvailability.updateSlot(slot["slot_id"], False)
            msg = f"Consultation confirmed for {slot['start_time'][:16]}."

        elif decision == "decline":
            if not note.strip():
                return False, "Please give the customer a reason for declining."
            Consultation.respondToProposedTime(consultation["consultation_id"], "Declined", designer_note=note)
            msg = "Consultation declined."

        else:
            slot = ConsultationAvailability.findById(slot_id) if slot_id else None
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if (not slot or str(slot["designer_user_id"]) != str(designer_user_id)
                    or slot["is_available"] != "True" or slot["start_time"] <= now):
                return False, "Choose one of your free upcoming availability slots to propose."
            Consultation.respondToProposedTime(consultation["consultation_id"], "Time Proposed",
                                               proposed_time=slot["start_time"], designer_note=note)
            msg = f"New time {slot['start_time'][:16]} proposed to the customer."

        self._refreshRequestStatus(request)
        return True, msg
