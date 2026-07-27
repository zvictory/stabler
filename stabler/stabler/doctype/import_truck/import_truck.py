"""Import Truck controller.

Non-submittable operational document (critique M5): the Iran -> Uzbekistan road
leg is enforced as a one-way status pipeline via the shared `assert_transition`
helper. A single-step backward correction is allowed for an Imports Manager who
supplies a `status_correction_reason`.

PENDING -> DEPARTED_IRAN is additionally gated on customs and veterinary
clearance for the whole commercial invoice — see `_check_departure_gate` and
imports_module/departure_math.py for why the gate cannot be per-truck.

The CROSSED_BORDER side effect (create the DRAFT cross-border transport Purchase
Invoice) is wired through `doc_events` on_update in the app hooks.py — see
stabler/stabler/imports_module/hooks.py:on_truck_update.
"""

import frappe
from frappe.model.document import Document

from stabler.stabler.doctype.vet_certificate.vet_certificate import has_valid_vet_cert
from stabler.stabler.imports_module import departure_math
from stabler.stabler.imports_module.status_pipeline import assert_transition

_ALLOWED_TRANSITIONS = {
	"PENDING": {"DEPARTED_IRAN", "Cancelled"},
	"DEPARTED_IRAN": {"AT_BORDER", "Cancelled"},
	"AT_BORDER": {"CROSSED_BORDER", "Cancelled"},
	"CROSSED_BORDER": {"IN_TRANSIT", "Cancelled"},
	"IN_TRANSIT": {"ARRIVED", "Cancelled"},
	"ARRIVED": {"UNLOADING", "Cancelled"},
	"UNLOADING": {"GRN_CREATED", "Cancelled"},
	"GRN_CREATED": {"COMPLETED", "Cancelled"},
	"COMPLETED": set(),
	"Cancelled": set(),
}


class ImportTruck(Document):
	def validate(self) -> None:
		if self.is_new():
			return
		previous_status = frappe.db.get_value("Import Truck", self.name, "status")
		assert_transition("Import Truck", previous_status, self.status, _ALLOWED_TRANSITIONS, self)
		self._check_departure_gate(previous_status)

	def _check_departure_gate(self, previous_status) -> None:
		"""Customs and veterinary clearance before the truck may leave Iran.

		Only PENDING -> DEPARTED_IRAN is gated. Because the model has no
		Truck-to-GTD allocation, partial clearance cannot authorise a subset of
		trucks, so the rule is all-or-nothing for the whole commercial invoice.
		"""
		if not departure_math.gates_this_transition(previous_status, self.status):
			return
		if not _imports_enabled(self.company):
			return

		declarations = frappe.get_all(
			"Customs Declaration",
			filters={"commercial_invoice": self.commercial_invoice},
			fields=["gtd_number", "status", "cleared_date"]
			+ (["required_for_departure"] if _has_required_flag() else []),
		)
		if not _has_required_flag():
			# Pre-v55 tenant: the flag does not exist yet, so treat every
			# declaration as required rather than silently passing them all.
			for d in declarations:
				d["required_for_departure"] = 1

		verdict = departure_math.may_depart(
			declarations,
			vet_valid=has_valid_vet_cert(self.commercial_invoice),
			override=bool(self.get("departure_override")),
			override_reason=self.get("departure_override_reason") or "",
		)
		if verdict["allowed"]:
			if verdict["via_override"]:
				_assert_override_role()
				self.add_comment(
					"Comment",
					frappe._("Departure released by override: {0}").format(self.departure_override_reason),
				)
			return

		frappe.throw(_blocker_message(verdict["blockers"]))


def _blocker_message(blockers) -> str:
	"""One readable sentence per blocker, so the driver knows what to chase."""
	lines = []
	for b in blockers:
		if b["code"] == "declaration_not_cleared":
			lines.append(frappe._("Customs declaration {0} is not cleared.").format(b["gtd_number"]))
		elif b["code"] == "no_required_declaration":
			lines.append(
				frappe._("No customs declaration on this invoice is marked as required for departure.")
			)
		elif b["code"] == "vet_certificate_missing":
			lines.append(frappe._("A valid veterinary certificate is required."))
	return frappe._("This truck cannot leave Iran yet:") + "\n- " + "\n- ".join(lines)


def _assert_override_role() -> None:
	if not set(frappe.get_roles()).intersection(("Imports Manager", "System Manager")):
		frappe.throw(frappe._("Only an Imports Manager can release a truck without customs clearance."))


def _has_required_flag() -> bool:
	return frappe.db.has_column("Customs Declaration", "required_for_departure")


def _imports_enabled(company) -> bool:
	from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

	return bool(module_map_for(company).get("imports"))
