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

**Why the engine is written here and not "operationally".** `remittance_engine`
ships as `Legacy` on every company and v90 writes `Legacy` onto every existing row.
Every Transfer V1 screen is gated on it. Nothing in the SPA could set it, and
`CLAUDE.md` forbids sending a user to the Frappe Desk, so the entire V1 surface —
operations centre, payout desk, refund chain, reconciliation — was unreachable on
all seven tenants and would have stayed unreachable until somebody ran an UPDATE by
hand on a bench console. A rollout decision still has to be *taken* somewhere; this
is where it is *recorded*.

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

#: `remittance_engine` Select options, verbatim from the doctype JSON. A value
#: outside this pair is refused rather than stored: the SPA gate and the whole V1
#: route set branch on an exact string match against "V1", so a typo would not fail,
#: it would silently mean Legacy forever.
ENGINES = ("Legacy", "V1")

#: The parent fields this endpoint accepts. An allow-list, not a filter over the
#: request: an unlisted key is ignored, so a client cannot reach a field that is not
#: on the form — `company` and `remittance_engine` included, both of which are
#: handled explicitly below.
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

	if "remittance_engine" in data:
		doc.remittance_engine = _validated_engine(data["remittance_engine"])

	if "cash_desk_accounts" in data:
		doc.set("cash_desk_accounts", [])
		for row in data["cash_desk_accounts"] or []:
			doc.append("cash_desk_accounts", {f: (row or {}).get(f) for f in _DESK_FIELDS})

	# Checked before the save so the refusal names the missing piece, instead of the
	# first transfer of the day failing at the counter with the customer present.
	if doc.remittance_engine == "V1":
		_assert_ready_for_v1(doc)

	# Permissions deliberately NOT ignored: this is the whole role gate.
	doc.save()

	return {
		"company": doc.company,
		"remittance_engine": doc.remittance_engine,
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


def _validated_engine(value) -> str:
	engine = str(value or "").strip()
	if engine not in ENGINES:
		frappe.throw(
			_("{0} is not a remittance engine. Choose one of: {1}.").format(
				engine or _("(empty)"), ", ".join(ENGINES)
			)
		)
	return engine


def _assert_ready_for_v1(doc) -> None:
	"""Refuse to switch a company to V1 while V1 cannot register a transfer.

	The three accounts are `reqd` on the doctype, so Frappe already refuses those.
	The desk table is not: without a row, `get_desk_account` throws at register time
	— which is to say, at the counter, with the cash already counted. A rollout that
	cannot take a transfer is not a rollout, so it is refused at the moment it is
	requested instead.
	"""
	if not (doc.cash_desk_accounts or []):
		frappe.throw(
			_(
				"Add at least one cash desk before switching {0} to the V1 engine: "
				"V1 reads every cash account from this table and cannot register a "
				"transfer without one."
			).format(doc.company)
		)
