"""Maker-checker approvals for Stabler money movement.

This is the segregation-of-duties control: a user who *creates* a payment or
journal entry cannot also *approve* (submit) it. The flow:

  1. Maker creates a Payment Entry / Journal Entry. If it requires approval it
     stays Draft (docstatus=0) and a Stabler Approval Request (Pending) is
     created instead of submitting.
  2. An approver (Accounts Manager / admin, a *different* user) reviews the
     queue and calls `approve` — which flips the request to Approved and
     submits the underlying document atomically.
  3. `before_submit` (wired in hooks.py) is the backstop: it refuses to submit
     a controlled document unless an Approved request by a different user
     exists. This blocks the Frappe Desk and any other submit path too, so the
     control is a real boundary, not just SPA UX.

Config lives on Stabler Settings:
  enable_payment_approvals  (Check, default 1)
  approval_threshold_base   (Currency, base currency; 0 = every payment)
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from stabler.api._approval_rules import (
	approval_is_in_sequence,
	is_fully_approved,
	is_self_approval,
	next_required_level,
	resolve_required_tiers,
	threshold_requires,
	would_be_double_approve,
)
from stabler.api._common import _require_company
from stabler.api.organization import _ADMIN_ROLES, _user_allowed_companies


def _is_admin() -> bool:
	return any(r in frappe.get_roles() for r in _ADMIN_ROLES)


# Doctypes governed by maker-checker.
CONTROLLED_DOCTYPES = ("Payment Entry", "Journal Entry", "Purchase Order", "Purchase Invoice")

# Per-doctype config keys on Stabler Settings. Payments and journals share the
# "payment approvals" switch (money leaving the books); Purchase Order and
# Purchase Invoice each have their own switch because committing to spend /
# accepting a supplier liability is a different control with its own rollout.
#
# Tuple: (enable_field, threshold_field, default_on, tiers_field)
# ``tiers_field`` is a JSON Text field on Stabler Settings that stores a list
# of {"threshold": N, "approver_role": "...", "level": N} dicts. When present
# and non-empty, multi-level resolution is used; otherwise single-level applies.
_CONFIG_KEYS = {
	"Payment Entry": ("enable_payment_approvals", "approval_threshold_base", True, None),
	"Journal Entry": ("enable_payment_approvals", "approval_threshold_base", True, None),
	"Purchase Order": ("enable_po_approvals", "po_approval_threshold_base", False, None),
	"Purchase Invoice": ("enable_pi_approvals", "pi_approval_threshold_base", False, "pi_approval_tiers"),
}

# Who may approve. Admins included so a fresh tenant is never fully blocked, but
# SoD (reviewer != requester) still applies to them — an admin cannot approve
# their own request.
_APPROVER_ROLES = ("Accounts Manager", "System Manager", "Stabler Admin")


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def _config_for(doctype: str) -> dict:
	"""Read the approval config for a specific controlled doctype.

	Each doctype maps to its own enable + threshold settings fields and a
	secure-by-default fallback (payments default ON; Purchase Order and Purchase
	Invoice default OFF so an upgrade doesn't suddenly block every document —
	they are opt-in per org).

	Returns:
	  {
	    "enabled": bool,
	    "threshold": float,          # single-level threshold (0 = all docs)
	    "tiers": list | None,        # multi-level tier config or None
	  }
	"""
	keys = _CONFIG_KEYS.get(doctype)
	if not keys:
		return {"enabled": False, "threshold": 0.0, "tiers": None}
	enable_field, threshold_field, default_on, tiers_field = keys
	enabled = default_on
	threshold = 0.0
	tiers = None
	if frappe.db.exists("DocType", "Stabler Settings"):
		val = frappe.db.get_single_value("Stabler Settings", enable_field)
		enabled = default_on if val is None else bool(int(val or 0))
		threshold = flt(frappe.db.get_single_value("Stabler Settings", threshold_field) or 0)
		if tiers_field:
			raw = frappe.db.get_single_value("Stabler Settings", tiers_field)
			if raw:
				try:
					import json

					tiers = json.loads(raw)
				except (ValueError, TypeError):
					tiers = None
	return {"enabled": enabled, "threshold": threshold, "tiers": tiers}


def is_approver(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	roles = frappe.get_roles(user)
	return any(r in roles for r in _APPROVER_ROLES)


def _require_approver() -> None:
	if not is_approver():
		frappe.throw(_("You are not permitted to review approval requests."), frappe.PermissionError)


def _assert_company_scope(company: str | None) -> None:
	"""Multi-tenant hygiene: an approver may only act on companies they belong
	to. Admins and users with no explicit Allowed Companies see all."""
	if not company:
		return
	from stabler.api.organization import _ADMIN_ROLES, _user_allowed_companies

	if any(r in frappe.get_roles() for r in _ADMIN_ROLES):
		return
	allowed = _user_allowed_companies(frappe.session.user)
	if allowed and company not in allowed:
		frappe.throw(_("This request belongs to a company you cannot access."), frappe.PermissionError)


# --------------------------------------------------------------------------- #
# Requirement test + context extraction
# --------------------------------------------------------------------------- #
def _doc_context(doc) -> dict:
	"""Pull amount / currency / base_amount / label off a controlled doc."""
	dt = doc.doctype
	if dt == "Payment Entry":
		base = flt(doc.get("base_paid_amount") or doc.get("base_received_amount") or 0)
		amount = flt(doc.get("paid_amount") or 0)
		# Currency of the money leaving/entering the company-side account.
		currency = doc.get("paid_to_account_currency") or doc.get("paid_from_account_currency") or ""
		party = doc.get("party_name") or doc.get("party") or ""
		title = "{0} · {1}".format(doc.get("payment_type") or "Payment", party or doc.name)
		return {
			"company": doc.company,
			"amount": amount,
			"currency": currency,
			"base_amount": base or amount,
			"party_label": party,
			"title": title,
		}
	if dt == "Journal Entry":
		base = flt(doc.get("total_debit") or 0)
		return {
			"company": doc.company,
			"amount": base,
			"currency": frappe.get_cached_value("Company", doc.company, "default_currency") or "",
			"base_amount": base,
			"party_label": "",
			"title": doc.get("user_remark") or doc.get("voucher_type") or doc.name,
		}
	if dt == "Purchase Order":
		# base_grand_total is in company currency; grand_total is in the PO
		# (supplier) currency. Anchor the threshold on the base amount.
		base = flt(doc.get("base_grand_total") or doc.get("grand_total") or 0)
		supplier = doc.get("supplier_name") or doc.get("supplier") or ""
		return {
			"company": doc.company,
			"amount": flt(doc.get("grand_total") or 0),
			"currency": doc.get("currency") or "",
			"base_amount": base,
			"party_label": supplier,
			"title": "{0} · {1}".format(_("Purchase Order"), supplier or doc.name),
		}
	if dt == "Purchase Invoice":
		# base_grand_total is in company currency; grand_total is in the supplier
		# (invoice) currency. Anchor threshold on the base amount.
		base = flt(doc.get("base_grand_total") or doc.get("grand_total") or 0)
		supplier = doc.get("supplier_name") or doc.get("supplier") or ""
		return {
			"company": doc.company,
			"amount": flt(doc.get("grand_total") or 0),
			"currency": doc.get("currency") or "",
			"base_amount": base,
			"party_label": supplier,
			"title": "{0} · {1}".format(_("Purchase Invoice"), supplier or doc.name),
		}
	return {
		"company": doc.get("company"),
		"amount": 0.0,
		"currency": "",
		"base_amount": 0.0,
		"party_label": "",
		"title": doc.name,
	}


def requires_approval(doc) -> bool:
	"""True when this document must be approved before it can be submitted."""
	if doc.doctype not in CONTROLLED_DOCTYPES:
		return False
	cfg = _config_for(doc.doctype)
	ctx = _doc_context(doc)
	return threshold_requires(ctx["base_amount"], enabled=cfg["enabled"], threshold=cfg["threshold"])


# --------------------------------------------------------------------------- #
# Request lifecycle
# --------------------------------------------------------------------------- #
def _open_request_for(reference_doctype: str, reference_name: str) -> str | None:
	"""Name of an existing Pending/Approved request for this document, if any."""
	return frappe.db.get_value(
		"Stabler Approval Request",
		{
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"status": ["in", ("Pending", "Approved")],
		},
		"name",
	)


def _load_tier_approvals(request_name: str) -> list:
	"""Load recorded tier approvals for a multi-level request.

	Returns a list of ``{"level": int, "approver": str}`` dicts from the
	``Stabler Approval Tier`` child table on the request. Returns [] when the
	child table does not exist (single-level flow or table not yet created).
	"""
	if not frappe.db.exists("DocType", "Stabler Approval Tier"):
		return []
	rows = frappe.get_all(
		"Stabler Approval Tier",
		filters={"parent": request_name, "parenttype": "Stabler Approval Request"},
		fields=["approval_level", "approver"],
		order_by="approval_level asc",
	)
	return [{"level": int(r.approval_level), "approver": r.approver} for r in rows]


def _record_tier_approval(request_name: str, level: int, approver: str) -> None:
	"""Append one tier-approval row to the request child table.

	No-op when the child table does not exist (single-level flow).
	"""
	if not frappe.db.exists("DocType", "Stabler Approval Tier"):
		return
	row = frappe.new_doc("Stabler Approval Tier")
	row.parent = request_name
	row.parenttype = "Stabler Approval Request"
	row.parentfield = "tier_approvals"
	row.approval_level = level
	row.approver = approver
	row.approved_at = frappe.utils.now_datetime()
	row.insert(ignore_permissions=True)


def ensure_request_for_doc(doc) -> str | None:
	"""Create (or reuse) a Pending approval request for a draft controlled doc.

	Returns the request name, or None if the doc does not require approval.
	"""
	if not requires_approval(doc):
		return None
	existing = _open_request_for(doc.doctype, doc.name)
	if existing:
		return existing
	ctx = _doc_context(doc)
	req = frappe.new_doc("Stabler Approval Request")
	req.reference_doctype = doc.doctype
	req.reference_name = doc.name
	req.company = ctx["company"]
	req.amount = ctx["amount"]
	req.currency = ctx["currency"]
	req.base_amount = ctx["base_amount"]
	req.party_label = ctx["party_label"]
	req.title = ctx["title"]
	req.requested_by = frappe.session.user
	req.requested_at = now_datetime()
	req.status = "Pending"
	req.insert(ignore_permissions=True)
	return req.name


def assert_submit_allowed(doc) -> None:
	"""before_submit gate. Raise unless a fully approved request by another user exists.

	For single-level flow: an Approved request by a different user is required.
	For multi-level flow: every required tier must have been recorded before
	  the request may flip to Approved and trigger submit.

	Secure-by-default: this runs for *every* submit path (SPA, Desk, scripts),
	so any new code that posts a controlled document is gated unless it opts out.

	Exemptions (no human maker is in the loop):
	  * doc.flags.ignore_approval_gate — set by trusted system flows that
	    auto-post (bank/ARCA webhooks, installment auto-collect, remittance,
	    marketing payouts). These are automated postings, not discretionary
	    clerk actions, so maker-checker does not apply.
	  * install / migrate / patch / test contexts — so deploys never deadlock.
	"""
	if getattr(doc, "flags", None) is not None and doc.flags.get("ignore_approval_gate"):
		return
	if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch or frappe.flags.in_test:
		return
	if not requires_approval(doc):
		return
	row = frappe.db.get_value(
		"Stabler Approval Request",
		{"reference_doctype": doc.doctype, "reference_name": doc.name, "status": "Approved"},
		["name", "requested_by", "reviewed_by"],
		as_dict=True,
	)
	if not row:
		frappe.throw(
			_(
				"This {0} needs an approval before it can be posted. It has been routed to the approvals queue."
			).format(_(doc.doctype)),
			title=_("Approval required"),
		)
	if is_self_approval(row.requested_by, row.reviewed_by):
		frappe.throw(
			_("Segregation of duties: the approver must be a different user from the requester."),
			title=_("Self-approval blocked"),
		)
	# Multi-level check: verify all required tiers were satisfied.
	cfg = _config_for(doc.doctype)
	if cfg.get("tiers"):
		ctx = _doc_context(doc)
		required_tiers = resolve_required_tiers(ctx["base_amount"], cfg["tiers"])
		if required_tiers:
			tier_approvals = _load_tier_approvals(row.name)
			if not is_fully_approved(required_tiers, tier_approvals):
				nxt = next_required_level(required_tiers, tier_approvals)
				frappe.throw(
					_("Approval level {0} has not been completed yet.").format(nxt),
					title=_("Multi-level approval incomplete"),
				)


def before_submit_gate(doc, method=None) -> None:
	"""doc_event entrypoint (hooks.py). Refuses submit without a valid approval."""
	assert_submit_allowed(doc)


def submit_or_route(doc) -> dict:
	"""Submit an already-inserted draft, OR — when it needs maker-checker
	approval — leave it as a Draft and open a Pending request instead.

	`doc` must already be inserted (have a name and computed base totals).
	Returns the standard create/submit result dict with a `pending_approval`
	flag the SPA uses to tell the maker their entry is awaiting review.
	"""
	if requires_approval(doc):
		req = ensure_request_for_doc(doc)
		return {
			"name": doc.name,
			"docstatus": doc.docstatus,
			"pending_approval": True,
			"approval_request": req,
		}
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "pending_approval": False}


# --------------------------------------------------------------------------- #
# Whitelisted API — the SPA approvals queue
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def list_pending(company: str | None = None, limit: int = 100, start: int = 0) -> dict:
	"""Approval queue for reviewers: Pending requests, newest first."""
	_require_approver()
	_assert_company_scope(company)
	limit = min(int(limit or 100), 500)
	start = int(start or 0)
	filters: dict = {"status": "Pending"}
	if company:
		filters["company"] = company
	else:
		allowed = _user_allowed_companies(frappe.session.user)
		if allowed and not _is_admin():
			filters["company"] = ["in", allowed]
	rows = frappe.get_all(
		"Stabler Approval Request",
		filters=filters,
		fields=[
			"name",
			"reference_doctype",
			"reference_name",
			"company",
			"amount",
			"currency",
			"base_amount",
			"party_label",
			"title",
			"requested_by",
			"requested_at",
			"status",
		],
		order_by="requested_at desc",
		limit=limit,
		start=start,
	)
	me = frappe.session.user
	for r in rows:
		# Flag rows this user cannot approve (they raised them) so the UI can
		# disable the button rather than fail on submit.
		r["self_made"] = r.get("requested_by") == me
		# Attach multi-level tier state so the queue shows per-level progress on a
		# fresh load (not just within the session that performed an approval).
		r["multi_level"] = False
		r["required_tiers"] = []
		r["tier_approvals"] = []
		r["next_required_level"] = None
		try:
			cfg = _config_for(r.get("reference_doctype") or "")
			if cfg.get("tiers"):
				required_tiers = resolve_required_tiers(r.get("base_amount") or 0, cfg["tiers"])
				if required_tiers:
					tier_approvals = _load_tier_approvals(r["name"])
					r["multi_level"] = True
					r["required_tiers"] = required_tiers
					r["tier_approvals"] = tier_approvals
					r["next_required_level"] = next_required_level(required_tiers, tier_approvals)
		except Exception:
			# A malformed tier config must never break the queue listing.
			pass
	total = frappe.db.count("Stabler Approval Request", filters)
	return {"requests": rows, "total": total, "can_approve": True}


@frappe.whitelist()
def my_requests(
	company: str | None = None, status: str | None = None, limit: int = 100, start: int = 0
) -> dict:
	"""Requests raised by the current user — the maker's view of their queue."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	limit = min(int(limit or 100), 500)
	start = int(start or 0)
	filters: dict = {"requested_by": frappe.session.user}
	if company:
		filters["company"] = company
	if status:
		filters["status"] = status
	rows = frappe.get_all(
		"Stabler Approval Request",
		filters=filters,
		fields=[
			"name",
			"reference_doctype",
			"reference_name",
			"company",
			"amount",
			"currency",
			"base_amount",
			"party_label",
			"title",
			"status",
			"requested_at",
			"reviewed_by",
			"reviewed_at",
			"review_note",
		],
		order_by="requested_at desc",
		limit=limit,
		start=start,
	)
	total = frappe.db.count("Stabler Approval Request", filters)
	return {"requests": rows, "total": total}


@frappe.whitelist()
def approve(name: str, note: str | None = None, level: int | None = None) -> dict:
	"""Approve a request and (when fully approved) submit the underlying document.

	Single-level flow (``level`` is None / not provided):
	  Behaves identically to the previous implementation — flips the request to
	  Approved and submits the document atomically.

	Multi-level flow (``level`` is an integer):
	  Records the approval for the given tier level. When the last required tier
	  is satisfied, flips the request to Approved and submits. Otherwise leaves
	  the request in Pending so the next-level approver can act.

	In both flows, segregation of duties is enforced: the approver must differ
	from the maker. In multi-level flow, one user may satisfy multiple levels
	(each at a separate call) as long as they did not raise the request — but
	double-approving the same level is rejected.
	"""
	_require_approver()
	if not name:
		frappe.throw(_("Approval request name is required."))
	req = frappe.get_doc("Stabler Approval Request", name)
	_assert_company_scope(req.company)
	if req.status != "Pending":
		frappe.throw(_("This request is already {0}.").format(_(req.status)))
	if req.requested_by == frappe.session.user:
		frappe.throw(
			_("You raised this request — it must be approved by someone else."),
			title=_("Self-approval blocked"),
		)
	if not frappe.db.exists(req.reference_doctype, req.reference_name):
		frappe.throw(_("The referenced document no longer exists."))

	target = frappe.get_doc(req.reference_doctype, req.reference_name)
	if target.docstatus == 1:
		# Already posted somehow — record the decision but don't double-submit.
		_mark_reviewed(req, "Approved", note)
		return {"name": req.name, "status": req.status, "reference_docstatus": 1}
	if target.docstatus == 2:
		frappe.throw(_("The referenced document is cancelled and cannot be approved."))

	# Determine whether this is a multi-level flow.
	cfg = _config_for(req.reference_doctype)
	tiers_config = cfg.get("tiers")
	ctx_base_amount = flt(req.get("base_amount") or 0)
	required_tiers = resolve_required_tiers(ctx_base_amount, tiers_config) if tiers_config else []

	if required_tiers and level is not None:
		# --- Multi-level path ---
		level = int(level)
		tier_approvals = _load_tier_approvals(req.name)

		# Race-prevention: reload inside a DB check — pure guard first.
		if would_be_double_approve(level, frappe.session.user, tier_approvals):
			frappe.throw(
				_("You have already approved level {0} for this request.").format(level),
				title=_("Duplicate approval"),
			)

		# Sequence guard: prior levels must be satisfied.
		if not approval_is_in_sequence(level, required_tiers, tier_approvals):
			nxt = next_required_level(required_tiers, tier_approvals)
			frappe.throw(
				_("Level {0} cannot be approved yet — level {1} must be completed first.").format(level, nxt),
				title=_("Out-of-sequence approval"),
			)

		# Record this tier approval.
		_record_tier_approval(req.name, level, frappe.session.user)

		# Reload to pick up the row we just inserted.
		tier_approvals = _load_tier_approvals(req.name)

		if is_fully_approved(required_tiers, tier_approvals):
			# All tiers satisfied — flip to Approved and submit.
			_mark_reviewed(req, "Approved", note)
			target.submit()
			return {
				"name": req.name,
				"status": req.status,
				"reference": target.name,
				"reference_docstatus": target.docstatus,
				"multi_level": True,
				"fully_approved": True,
			}
		else:
			nxt = next_required_level(required_tiers, tier_approvals)
			return {
				"name": req.name,
				"status": "Pending",
				"multi_level": True,
				"fully_approved": False,
				"next_required_level": nxt,
			}
	else:
		# --- Single-level path (original behaviour, backward compatible) ---
		# Flip to Approved FIRST so the before_submit gate sees an Approved request
		# whose reviewer differs from the requester, then submit.
		_mark_reviewed(req, "Approved", note)
		target.submit()
		return {
			"name": req.name,
			"status": req.status,
			"reference": target.name,
			"reference_docstatus": target.docstatus,
		}


@frappe.whitelist()
def reject(name: str, note: str | None = None) -> dict:
	"""Reject a request. The draft document is left untouched for the maker to fix or delete."""
	_require_approver()
	if not name:
		frappe.throw(_("Approval request name is required."))
	req = frappe.get_doc("Stabler Approval Request", name)
	_assert_company_scope(req.company)
	if req.status != "Pending":
		frappe.throw(_("This request is already {0}.").format(_(req.status)))
	if req.requested_by == frappe.session.user:
		frappe.throw(_("You raised this request — it must be reviewed by someone else."))
	_mark_reviewed(req, "Rejected", note)
	return {"name": req.name, "status": req.status}


def _mark_reviewed(req, status: str, note: str | None) -> None:
	req.status = status
	req.reviewed_by = frappe.session.user
	req.reviewed_at = now_datetime()
	if note:
		req.review_note = note
	req.save(ignore_permissions=True)


@frappe.whitelist()
def pending_count(company: str | None = None) -> dict:
	"""Badge count for the approvals queue (reviewers only; 0 otherwise)."""
	if not is_approver():
		return {"count": 0, "can_approve": False}
	_assert_company_scope(company)
	filters: dict = {"status": "Pending"}
	if company:
		filters["company"] = company
	else:
		allowed = _user_allowed_companies(frappe.session.user)
		if allowed and not _is_admin():
			filters["company"] = ["in", allowed]
	return {"count": frappe.db.count("Stabler Approval Request", filters), "can_approve": True}
