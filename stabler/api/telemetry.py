"""Activation telemetry — fire-and-forget, PII-free, company-anonymous.

`track()` records one activation-funnel event as a versioned JSON line in
`logs/stabler.telemetry.log` (mirrors the `_log_payment` diagnostic pattern in
api/money.py). It is deliberately minimal and defensive:

  * Fire-and-forget — it NEVER raises and NEVER blocks the caller. Any failure
    (bad payload, scope violation, log I/O) is swallowed so the front-end UX is
    never affected.
  * No PII — the company is reduced to a stable, non-reversible anonymous hash,
    and prop values are shallow-scrubbed to PII-free primitives.
  * Versioned schema — every line carries `"v": SCHEMA_VERSION` so the shape can
    evolve without breaking downstream parsing.

There is no backing doctype (write-only diagnostic stream), so the security
control here is tenant isolation via `_require_company` + `_assert_company_scope`
(reject events for a company the user cannot access). No SQL, no db.commit.

Tail it:  tail -f sites/<site>/logs/stabler.telemetry.log
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe.utils import now_datetime

from stabler.api._common import _require_company
from stabler.api.approvals import _assert_company_scope

# Bump when the emitted JSON shape changes. Downstream parsers branch on it.
SCHEMA_VERSION = 1

# The activation funnel + the empty-state CTA event. Anything else is dropped.
FUNNEL_EVENTS = ("signup", "wizard_done", "first_item", "first_sale", "first_payment")
CTA_EVENT = "empty_state_cta"
_ALLOWED_EVENTS = frozenset(FUNNEL_EVENTS) | {CTA_EVENT}

_MAX_PROPS = 20
_MAX_STR = 200
# Prop keys that could carry PII are dropped defensively even if a caller sends them.
_PII_KEYS = frozenset({
	"email", "phone", "mobile", "tel", "name", "full_name", "fio", "first_name",
	"last_name", "address", "tax_id", "tin", "inn", "password", "pwd", "token",
	"secret", "user", "user_id", "customer", "customer_name", "supplier",
	"supplier_name", "party", "party_name", "ip",
})


def _anon_company(company: str) -> str:
	"""Stable, non-reversible per-site hash of the company — company-anonymous.

	Salt is the site name (or a configured override) so the same company maps to
	the same hash within a deployment, but the raw company id never leaves the app.
	"""
	salt = (frappe.local.conf.get("stabler_telemetry_salt") if frappe.local.conf else None) or (
		getattr(frappe.local, "site", "") or ""
	)
	return hashlib.sha256(f"{salt}:{company}".encode()).hexdigest()[:16]


def _scrub_props(props) -> dict:
	"""Keep only PII-free primitive values; cap count + string length."""
	if not isinstance(props, dict):
		return {}
	out: dict = {}
	for key, value in list(props.items())[:_MAX_PROPS]:
		ks = str(key)
		if ks.lower() in _PII_KEYS:
			continue
		if isinstance(value, bool) or isinstance(value, (int, float)) or value is None:
			out[ks] = value
		elif isinstance(value, str):
			out[ks] = value[:_MAX_STR]
		# non-primitive (dict/list/obj) → dropped to avoid nested PII leakage
	return out


@frappe.whitelist()
def track(event: str, company: str, props: dict | str | None = None) -> dict:
	"""Record one activation-funnel event. Fire-and-forget.

	Always returns ``{"ok": True}`` and never raises — the caller must not depend
	on the result. Events for an out-of-scope company, unknown event names, or any
	internal error are silently dropped.
	"""
	try:
		if not event or event not in _ALLOWED_EVENTS:
			return {"ok": True}
		_require_company(company)
		_assert_company_scope(company)  # tenant isolation: reject a foreign company arg

		if isinstance(props, str):
			try:
				props = json.loads(props)
			except Exception:
				props = None

		payload = {
			"v": SCHEMA_VERSION,
			"event": event,
			"ts": now_datetime().isoformat(timespec="seconds"),
			"company_hash": _anon_company(company),
			"props": _scrub_props(props),
		}
		frappe.logger("stabler.telemetry", allow_site=True, file_count=10).info(
			json.dumps(payload, default=str, ensure_ascii=False)
		)
	except Exception:
		# Fire-and-forget: telemetry must never surface an error to the caller.
		pass
	return {"ok": True}
