"""The one writer for `Remittance Settings` — the row every transfer reads first.

Why this module exists at all. `remittance_settings.json` marks the three company
GL accounts `reqd: 1` and nothing — no patch, no fixture — creates the row, so on
every company the FIRST registration throws. `get_desk_account` says the same from
the other side. `RemittanceSettings.vue` is the screen that fixes it, and it was
shipped calling `stabler.api.remittance_settings.save_remittance_settings` before
that name existed anywhere on disk: the manager filled the form, pressed the only
primary button on the page, and got an honest sentence saying the endpoint had not
shipped. Honest, and useless — the state the screen exists to repair could not be
repaired from the screen.

**The engine flag this module used to write is gone.** `remittance_engine` chose
between the JE-only engine and Transfer V1, and every Transfer V1 screen was gated
on it. The JE-only engine was retired on 2026-08-20 with no tenant running it, so
the choice had one option left and the flag was removed with it. What survives is
the readiness check below, which was the more useful half all along: it never
answered "which engine", it answered "can this company take a transfer at all".

**One gate, and it is the doctype's.** No role list is written here. The parent doc
is saved with permissions ON, so `write` (and `create` on the first save) is what
Frappe checks, and `remittance_settings.json` grants both to Remittance Finance
Manager and System Manager and to nobody else. A second copy of that list in this
module would be a second answer to the same question.

**The child table is replaced, not merged.** The screen sends the desk grid it is
showing, whole. A merge would need identity for rows the form does not carry one
for, and "the rows I can see are the rows there are" is what a manager staring at
that grid already believes. `RemittanceSettings._dedupe_desk_currency` still runs
and still refuses two accounts for one (desk, currency).

Bench-dependent by nature: it saves a document. `make check` cannot prove it.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from stabler.api._common import _require_company
from stabler.api.approvals import _assert_company_scope

SETTINGS = "Remittance Settings"

#: The parent fields this endpoint accepts. An allow-list, not a filter over the
#: request: an unlisted key is ignored, so a client cannot reach a field that is not
#: on the form — `company` included, which is handled explicitly below.
_PARENT_FIELDS = (
	"receiver_obligation_account",
	"deferred_commission_account",
	"commission_income_account",
	"default_quote_expiry_hours",
	"max_code_attempts",
	"lockout_minutes",
	"require_refund_approval",
)

#: The desk-row fields. Same reasoning as above.
_DESK_FIELDS = ("branch", "city", "currency", "account", "evidence_type")


@frappe.whitelist()
def save_remittance_settings(company: str, payload: str | dict) -> dict:
	"""Create or update one company's remittance configuration.

	Returns the saved state — including the engine — so the SPA can re-gate itself
	without a reload. It does NOT return anything the caller did not just send,
	beyond the fields it stored.
	"""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)

	data = _as_dict(payload)
	doc = _settings_doc(company)

	for field in _PARENT_FIELDS:
		if field in data:
			doc.set(field, _blank_to_none(data[field]))

	if "cash_desk_accounts" in data:
		doc.set("cash_desk_accounts", [])
		for row in data["cash_desk_accounts"] or []:
			doc.append("cash_desk_accounts", {f: (row or {}).get(f) for f in _DESK_FIELDS})

	# Checked before the save so the refusal names the missing piece, instead of the
	# first transfer of the day failing at the counter with the customer present.
	# Unconditional since the engine flag was retired: it used to run only when a
	# company was being switched to V1, which was the only remaining engine, so on
	# the fleet as it stands this changed nothing — but the check outlived its
	# trigger and had to be given a new one or quietly stop running.
	_assert_ready_for_remittance(doc)

	# Permissions deliberately NOT ignored: this is the whole role gate.
	doc.save()

	return {
		"company": doc.company,
		"name": doc.name,
		"modified": doc.modified,
	}


def _settings_doc(company: str):
	"""The company's row, or a new one. `autoname: field:company` makes them equal."""
	if frappe.db.exists(SETTINGS, company):
		return frappe.get_doc(SETTINGS, company)
	doc = frappe.new_doc(SETTINGS)
	doc.company = company
	return doc


def _as_dict(payload: str | dict) -> dict:
	"""The SPA sends JSON; `client.js` stringifies every value it posts."""
	if isinstance(payload, dict):
		return payload
	try:
		data = json.loads(payload or "{}")
	except (TypeError, ValueError):
		frappe.throw(_("The settings payload could not be read."))
	if not isinstance(data, dict):
		frappe.throw(_("The settings payload could not be read."))
	return data


def _blank_to_none(value):
	"""An empty box is "unset", not zero.

	The three Int policy fields carry doctype defaults. Storing 0 for a field the
	manager left blank would mean "zero attempts allowed" and "expires in zero
	hours" — both of which are policy this screen has no authority to invent.
	"""
	if value == "" or value is None:
		return None
	return value


#: The Journal Entry fields `remittance_cancel_guard` reads to recognise one of its
#: own vouchers. Created by `v33_remittance_stage_fields`, and by nothing else.
_GUARD_FIELDS = ("stabler_remittance_id", "stabler_remittance_stage")


def _assert_ready_for_remittance(doc) -> None:
	"""Refuse to save a configuration that cannot register a transfer, or that
	nothing can protect the vouchers of.

	This ran only on the switch to V1 until the engine flag was retired
	(2026-08-20). It was never really about the engine: both checks ask whether
	this company and this site can take a transfer at all, and the answer does not
	depend on which engine asked.

	The three accounts are `reqd` on the doctype, so Frappe already refuses those.
	The desk table is not: without a row, `get_desk_account` throws at register time
	— which is to say, at the counter, with the cash already counted. A configuration
	that cannot take a transfer is refused at the moment it is saved instead.

	The stage fields are the same rule one layer down, and their absence is SILENT
	on both sides. `_build_entry` sets `stabler_remittance_id` on every voucher it
	inserts and Frappe drops an unknown key without complaint; the cancel guard opens
	with `doc.get("stabler_remittance_id")` and returns when it is empty, which is the
	cheap exit an ordinary Journal Entry takes. Missing field, therefore, means every
	remittance voucher is cancellable from the Desk and nothing anywhere says so.
	Measured on zuma 2026-08-19: nine submitted vouchers, guard registered and inert,
	because a fresh site stamps every patch as applied and Custom Fields are created
	by patch code alone.
	"""
	if not (doc.cash_desk_accounts or []):
		frappe.throw(
			_(
				"Add at least one cash desk for {0}: every cash account comes from "
				"this table, and without a row the register desk cannot take a "
				"transfer."
			).format(doc.company)
		)

	meta = frappe.get_meta("Journal Entry")
	missing = [f for f in _GUARD_FIELDS if not meta.get_field(f)]
	if missing:
		frappe.throw(
			_(
				"Journal Entry is missing {1} on this site, so a remittance voucher "
				"cannot be told apart from any other and the cancel guard would let it "
				"be cancelled. Run `bench --site <site> migrate` to create the fields "
				"before configuring remittance for {0}."
			).format(doc.company, ", ".join(missing))
		)
