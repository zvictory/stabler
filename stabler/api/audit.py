"""Audit trail API for Stabler.

A read-only window onto "who changed what, and when" — the question an auditor
asks and the one the SPA could not previously answer without the Frappe Desk.

It stitches a single timeline from four sources that already exist in the
platform, so there is no new write path and nothing to keep in sync:

  1. The document itself — creation (owner) and the current docstatus.
  2. `Version` rows — field-level diffs ERPNext records for tracked doctypes,
     including submit/cancel (a docstatus change) and edits.
  3. `Comment` rows — notes, info and workflow comments against the document.
  4. `Stabler Approval Request` — the maker-checker record (requested / reviewed).

Two entrypoints:
  * `document_history(doctype, name)` — one document's timeline. Gated by the
    caller's read permission on that document (no privilege escalation).
  * `recent_activity(...)` — a global feed across financial doctypes for
    managers/admins (the compliance "audit log").
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import get_fullname

from stabler.api._approval_rules import IGNORE_FIELDS, summarize_version

# Doctypes surfaced in the global audit feed. Version rows only exist for
# doctypes with track_changes, so listing one that isn't tracked is harmless.
FINANCIAL_DOCTYPES = (
	"Payment Entry",
	"Journal Entry",
	"Sales Invoice",
	"Purchase Invoice",
	"Sales Order",
	"Purchase Order",
	"Delivery Note",
	"Purchase Receipt",
	"Stock Entry",
)

# Reviewers/managers who may see the cross-document feed.
_AUDIT_ROLES = (
	"System Manager",
	"Stabler Admin",
	"Accounts Manager",
	"Auditor",
)


def _can_audit() -> bool:
	return bool(set(frappe.get_roles()) & set(_AUDIT_ROLES))


def _require_audit() -> None:
	if not _can_audit():
		frappe.throw(_("You are not permitted to view the audit log."), frappe.PermissionError)


def _fullname(user: str | None) -> str:
	if not user:
		return ""
	try:
		return get_fullname(user) or user
	except Exception:
		return user


def _field_label(meta, fieldname: str) -> str:
	try:
		df = meta.get_field(fieldname)
		if df and df.label:
			return _(df.label)
	except Exception:
		pass
	return fieldname


def _short(value) -> str:
	"""Render an old/new value compactly for display."""
	if value is None or value == "":
		return "—"
	if isinstance(value, (dict, list)):
		try:
			return json.dumps(value, ensure_ascii=False)[:120]
		except Exception:
			return str(value)[:120]
	return str(value)[:160]


_VERB = {
	"submit": lambda: _("Submitted"),
	"cancel": lambda: _("Cancelled"),
}


def _parse_version(row, meta) -> dict | None:
	"""Turn one Version row into a timeline event (None = only-noise, skip)."""
	try:
		data = json.loads(row.data or "{}")
	except Exception:
		data = {}

	# All the pure rules (kind, which fields changed, meaningfulness) live in
	# the frappe-free _approval_rules module so they can be unit tested.
	summary = summarize_version(data, IGNORE_FIELDS)
	if not summary["meaningful"]:
		return None

	kind = summary["kind"]
	if kind in _VERB:
		verb = _VERB[kind]()
	else:
		n = len(summary["field_changes"]) + summary["child_changes"]
		verb = _("Edited 1 field") if n == 1 else _("Edited {0} field(s)").format(n)

	changes = [
		{
			"field": c["field"],
			"label": _field_label(meta, c["field"]),
			"from": _short(c["old"]),
			"to": _short(c["new"]),
		}
		for c in summary["field_changes"]
	]

	return {
		"type": kind,
		"user": row.owner,
		"user_name": _fullname(row.owner),
		"timestamp": str(row.creation),
		"summary": verb,
		"changes": changes,
		"child_changes": summary["child_changes"],
	}


@frappe.whitelist()
def document_history(doctype: str, name: str) -> dict:
	"""Full timeline for one document. Requires read permission on that document."""
	if not doctype or not name:
		frappe.throw(_("Document type and name are required."))
	if not frappe.db.exists(doctype, name):
		frappe.throw(_("Document not found."), frappe.DoesNotExistError)
	if not frappe.has_permission(doctype, "read", name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	meta = frappe.get_meta(doctype)
	events: list[dict] = []

	# 1. Creation event from the document itself.
	core = frappe.db.get_value(doctype, name, ["owner", "creation", "docstatus"], as_dict=True) or {}
	if core:
		events.append(
			{
				"type": "create",
				"user": core.owner,
				"user_name": _fullname(core.owner),
				"timestamp": str(core.creation),
				"summary": _("Created"),
				"changes": [],
				"child_changes": 0,
			}
		)

	# 2. Version diffs (edits + submit/cancel).
	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": doctype, "docname": name},
		fields=["name", "owner", "creation", "data"],
		order_by="creation asc",
		limit=500,
	)
	for v in versions:
		ev = _parse_version(v, meta)
		if ev:
			events.append(ev)

	# 3. Comments (notes / info / workflow).
	comments = frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": doctype,
			"reference_name": name,
			"comment_type": ["in", ("Comment", "Info", "Workflow", "Label")],
		},
		fields=["owner", "creation", "content", "comment_type"],
		order_by="creation asc",
		limit=200,
	)
	for c in comments:
		events.append(
			{
				"type": "comment",
				"user": c.owner,
				"user_name": _fullname(c.owner),
				"timestamp": str(c.creation),
				"summary": frappe.utils.strip_html(c.content or "")[:200] or _("Comment"),
				"changes": [],
				"child_changes": 0,
			}
		)

	# 4. Approval records tied to this document.
	if frappe.db.exists("DocType", "Stabler Approval Request"):
		reqs = frappe.get_all(
			"Stabler Approval Request",
			filters={"reference_doctype": doctype, "reference_name": name},
			fields=[
				"name",
				"status",
				"requested_by",
				"requested_at",
				"reviewed_by",
				"reviewed_at",
				"review_note",
			],
			order_by="requested_at asc",
		)
		for r in reqs:
			if r.requested_at:
				events.append(
					{
						"type": "approval_requested",
						"user": r.requested_by,
						"user_name": _fullname(r.requested_by),
						"timestamp": str(r.requested_at),
						"summary": _("Submitted for approval"),
						"changes": [],
						"child_changes": 0,
					}
				)
			if r.reviewed_at and r.status in ("Approved", "Rejected"):
				events.append(
					{
						"type": "approved" if r.status == "Approved" else "rejected",
						"user": r.reviewed_by,
						"user_name": _fullname(r.reviewed_by),
						"timestamp": str(r.reviewed_at),
						"summary": (_("Approved") if r.status == "Approved" else _("Rejected"))
						+ ((" · " + r.review_note) if r.review_note else ""),
						"changes": [],
						"child_changes": 0,
					}
				)

	events.sort(key=lambda e: e["timestamp"])
	return {
		"doctype": doctype,
		"name": name,
		"docstatus": core.get("docstatus") if core else None,
		"events": events,
		"count": len(events),
	}


@frappe.whitelist()
def recent_activity(
	company: str | None = None,
	doctype: str | None = None,
	user: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 100,
	start: int = 0,
) -> dict:
	"""Cross-document audit feed for managers/admins (the compliance audit log)."""
	_require_audit()

	# Multi-tenant scoping: validate a passed company against the caller's
	# allowed set; when omitted, a non-admin auditor is restricted to their
	# allowed companies (never "all companies"). Admins / unrestricted users
	# (empty allowed list) are unaffected.
	from stabler.api.organization import _ADMIN_ROLES, _user_allowed_companies

	is_admin = any(r in frappe.get_roles() for r in _ADMIN_ROLES)
	allowed = [] if is_admin else _user_allowed_companies(frappe.session.user)
	if company and allowed and company not in allowed:
		frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)

	limit = min(int(limit or 100), 500)
	start = int(start or 0)

	doctypes = [doctype] if doctype else list(FINANCIAL_DOCTYPES)

	conds = ["v.ref_doctype IN %(doctypes)s"]
	params: dict = {"doctypes": tuple(doctypes), "limit": limit, "start": start}
	if user:
		conds.append("v.owner = %(user)s")
		params["user"] = user
	if from_date:
		conds.append("v.creation >= %(from_date)s")
		params["from_date"] = from_date
	if to_date:
		conds.append("v.creation <= %(to_date)s")
		params["to_date"] = to_date + " 23:59:59"
	where = " AND ".join(conds)

	rows = frappe.db.sql(
		f"""
		SELECT v.name, v.ref_doctype, v.docname, v.owner, v.creation, v.data
		FROM `tabVersion` v
		WHERE {where}
		ORDER BY v.creation DESC
		LIMIT %(limit)s OFFSET %(start)s
		""",
		params,
		as_dict=True,
	)

	# Optional company filter — resolved per source doctype (best effort; a row
	# whose document was deleted is simply dropped).
	out: list[dict] = []
	meta_cache: dict = {}
	for r in rows:
		if r.ref_doctype not in meta_cache:
			meta_cache[r.ref_doctype] = frappe.get_meta(r.ref_doctype)
		ev = _parse_version(r, meta_cache[r.ref_doctype])
		if not ev:
			continue
		if company or allowed:
			row_company = frappe.db.get_value(r.ref_doctype, r.docname, "company")
			if company:
				if row_company and row_company != company:
					continue
			elif allowed and row_company and row_company not in allowed:
				# No explicit company arg, but a scoped non-admin auditor: hide
				# rows belonging to companies outside their allowed set.
				continue
		ev["doctype"] = r.ref_doctype
		ev["name"] = r.docname
		out.append(ev)

	return {"events": out, "count": len(out), "can_audit": True}


@frappe.whitelist()
def audit_meta() -> dict:
	"""Filter options for the audit log UI."""
	return {
		"doctypes": list(FINANCIAL_DOCTYPES),
		"can_audit": _can_audit(),
	}


# =========================================================================== #
# Gap-42: Tamper-evidence — seal_audit_log / verify_audit_integrity           #
# =========================================================================== #


def _require_admin() -> None:
	"""Require System Manager or Stabler Admin role."""
	if not {"System Manager", "Stabler Admin"} & set(frappe.get_roles()):
		frappe.throw(_("Not permitted — admins only."), frappe.PermissionError)


def _last_seal(for_update: bool = False) -> dict | None:
	"""Return the most recent Stabler Audit Seal row (seq, hash, sealed_at), or None.

	`for_update` takes a row lock, and only the write path asks for it. Sealing
	reads this row to learn `prev_seq`/`prev_hash`, hashes every Version row
	since then, and inserts the next seal — a window wide enough for the nightly
	tick and a hand-run `bench execute` to overlap. `seq` carries no unique flag
	in the doctype JSON, so nothing below refuses the second seal claiming the
	same number, and a tamper-evident chain that forks proves nothing from that
	point on. The lock holds until the transaction commits, which is exactly as
	long as it needs to.

	Raw SQL because `frappe.get_all` has no `for_update`: `db_query` does not
	support it, only `frappe.db.get_value`/`get_values` do, and neither takes an
	`order_by`+`limit` over a doctype the way this needs.

	This is the cheap half of the fix. The complete one is a unique index on
	`seq`, which is a doctype change and per-site DDL across seven tenants, and
	is deliberately still owed. On an empty table there is no row to lock; the
	scan is a full one (`seq` is not indexed) so InnoDB's next-key locking does
	hold the gap under REPEATABLE READ, but that follows from the isolation
	level and from an index NOT existing, so it is not something to rely on.
	"""
	rows = frappe.db.sql(
		"SELECT `name`, `seq`, `hash`, `sealed_at` FROM `tabStabler Audit Seal` "
		"ORDER BY `seq` DESC LIMIT 1" + (" FOR UPDATE" if for_update else ""),
		as_dict=True,
	)
	return rows[0] if rows else None


@frappe.whitelist()
def seal_audit_log() -> dict:
	"""Compute and store a hash-chain seal over unseen Version rows.

	Admin-gated (System Manager / Stabler Admin).  Finds all Version rows for
	the financial doctypes that were created *after* the last seal (or since the
	beginning of time if none exists), builds the chain anchored at the previous
	seal hash, and writes a new ``Stabler Audit Seal`` document.

	Returns a summary dict::

	    {
	        "seal_name": "SEAL-2026-000001",
	        "seq": 1,
	        "hash": "<64-char hex>",
	        "sealed_at": "2026-06-16 12:00:00",
	        "version_count": 42,
	        "period": "2026-01-01 00:00:00 / 2026-06-16 12:00:00",
	    }
	"""
	_require_admin()
	_require_audit()

	from stabler.api._audit_chain import build_chain

	# Locked: everything from here to the insert is the fork window.
	last = _last_seal(for_update=True)
	prev_seq = last["seq"] if last else 0
	prev_hash = last["hash"] if last else "0" * 64
	after_dt = last["sealed_at"] if last else None

	# Fetch Version rows for financial doctypes since the last seal.
	conds = ["v.ref_doctype IN %(doctypes)s"]
	params: dict = {"doctypes": tuple(FINANCIAL_DOCTYPES)}
	if after_dt:
		conds.append("v.creation > %(after_dt)s")
		params["after_dt"] = str(after_dt)
	where = " AND ".join(conds)

	rows = frappe.db.sql(
		f"""
		SELECT v.name, v.ref_doctype, v.docname, v.owner, v.creation
		FROM `tabVersion` v
		WHERE {where}
		ORDER BY v.creation ASC, v.name ASC
		""",
		params,
		as_dict=True,
	)

	if not rows:
		return {
			"seal_name": None,
			"seq": prev_seq,
			"hash": prev_hash,
			"sealed_at": None,
			"version_count": 0,
			"period": None,
			"message": _("No new Version rows since the last seal."),
		}

	# Convert Frappe row dicts to plain serialisable dicts (dates → str).
	payload_rows = [
		{
			"name": str(r.name),
			"ref_doctype": str(r.ref_doctype),
			"docname": str(r.docname),
			"owner": str(r.owner),
			"creation": str(r.creation),
		}
		for r in rows
	]

	# Build chain anchored at the previous seal hash.
	# We build from a single "anchor" seed so the chain continues across seals:
	# insert a synthetic genesis row carrying prev_hash as its content, then
	# build the real rows on top. This ensures cross-seal continuity without
	# needing to re-process all historical rows.
	seed = [{"_anchor": prev_hash, "_prev_seq": prev_seq}]
	full_chain = build_chain(seed + payload_rows)

	# The terminal hash is the last entry in the chain.
	terminal_hash = full_chain[-1]["hash"]
	new_seq = prev_seq + 1

	period_from = str(rows[0].creation)
	period_to = str(rows[-1].creation)
	period_str = f"{period_from} / {period_to}"
	sealed_at = frappe.utils.now_datetime()

	seal_doc = frappe.get_doc(
		{
			"doctype": "Stabler Audit Seal",
			"seq": new_seq,
			"period": period_str,
			"hash": terminal_hash,
			"sealed_at": sealed_at,
			"version_count": len(rows),
			"sealed_by": frappe.session.user,
		}
	)
	seal_doc.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"seal_name": seal_doc.name,
		"seq": new_seq,
		"hash": terminal_hash,
		"sealed_at": str(sealed_at),
		"version_count": len(rows),
		"period": period_str,
	}


@frappe.whitelist()
def verify_audit_integrity() -> dict:
	"""Re-build and verify the hash chain for the most recent seal window.

	Admin/auditor-gated (same roles as ``recent_activity``).  Fetches the last
	seal record, re-fetches the same Version rows it covered, rebuilds the chain
	from scratch, and compares the terminal hash to the stored seal hash.

	Returns::

	    {
	        "ok": True | False,
	        "first_broken_seq": None | int,
	        "seal_name": "SEAL-...",
	        "seal_seq": 1,
	        "stored_hash": "<hex>",
	        "computed_hash": "<hex>",
	        "version_count": 42,
	    }
	"""
	_require_audit()

	from stabler.api._audit_chain import build_chain, verify_chain

	last = _last_seal()
	if not last:
		return {
			"ok": True,
			"first_broken_seq": None,
			"seal_name": None,
			"seal_seq": 0,
			"stored_hash": None,
			"computed_hash": None,
			"version_count": 0,
			"message": _("No seal has been created yet."),
		}

	# Determine the window: rows up to and including the seal's sealed_at.
	# We look one seal back to find the anchor point.
	seals = frappe.get_all(
		"Stabler Audit Seal",
		fields=["name", "seq", "hash", "sealed_at"],
		order_by="seq desc",
		limit=2,
	)
	current_seal = seals[0]
	prev_seal = seals[1] if len(seals) > 1 else None

	prev_hash = prev_seal["hash"] if prev_seal else "0" * 64
	prev_seq = prev_seal["seq"] if prev_seal else 0
	after_dt = prev_seal["sealed_at"] if prev_seal else None

	conds = [
		"v.ref_doctype IN %(doctypes)s",
		"v.creation <= %(up_to)s",
	]
	params: dict = {
		"doctypes": tuple(FINANCIAL_DOCTYPES),
		"up_to": str(current_seal["sealed_at"]),
	}
	if after_dt:
		conds.append("v.creation > %(after_dt)s")
		params["after_dt"] = str(after_dt)
	where = " AND ".join(conds)

	rows = frappe.db.sql(
		f"""
		SELECT v.name, v.ref_doctype, v.docname, v.owner, v.creation
		FROM `tabVersion` v
		WHERE {where}
		ORDER BY v.creation ASC, v.name ASC
		""",
		params,
		as_dict=True,
	)

	payload_rows = [
		{
			"name": str(r.name),
			"ref_doctype": str(r.ref_doctype),
			"docname": str(r.docname),
			"owner": str(r.owner),
			"creation": str(r.creation),
		}
		for r in rows
	]

	seed = [{"_anchor": prev_hash, "_prev_seq": prev_seq}]
	full_chain = build_chain(seed + payload_rows)
	computed_hash = full_chain[-1]["hash"]

	ok, first_broken = verify_chain(full_chain)
	hash_match = computed_hash == current_seal["hash"]
	overall_ok = ok and hash_match

	return {
		"ok": overall_ok,
		"first_broken_seq": first_broken if not ok else (None if hash_match else "terminal"),
		"seal_name": current_seal["name"],
		"seal_seq": current_seal["seq"],
		"stored_hash": current_seal["hash"],
		"computed_hash": computed_hash,
		"version_count": len(rows),
	}
