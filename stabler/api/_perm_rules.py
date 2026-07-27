"""Pure permission-scoping rules — no Frappe, no DB.

The decision logic behind record-level company isolation: given the set of
companies a user is allowed to see, decide whether to restrict and whether a
specific record's company is allowed. The Frappe layer
(``stabler.api.permissions``) turns these into ``permission_query_conditions``
SQL and ``has_permission`` checks.

Convention (matches ``organization._user_allowed_companies``): an **empty/None**
allowed list means *no restriction* (the user sees all companies) — restriction
only kicks in when a user has an explicit Allowed Companies list.

Gap #46 — owner/territory scoping for company-agnostic masters (Customer /
Supplier). Same safe-by-default convention: empty/None allowed list = no
restriction; admins bypass via the Frappe layer, never here.

Gap #45 — cost/margin field masking. ``mask_fields`` strips valuation/cost/
margin fields from a payload dict (or list of dicts) when the caller's role set
lacks cost visibility. The set of masked field names is a module-level constant
so callers can also use it for SQL projection.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Gap #1 (existing) — company scoping
# ---------------------------------------------------------------------------


def needs_company_restriction(allowed) -> bool:
	"""True only when there is a non-empty explicit allow-list to enforce."""
	return bool(allowed)


def is_company_allowed(company, allowed) -> bool:
	"""Is `company` visible under `allowed`? No restriction ⇒ always True."""
	if not needs_company_restriction(allowed):
		return True
	if not company:
		# A record with no company can't be company-scoped; don't hide it.
		return True
	return company in set(allowed)


# ---------------------------------------------------------------------------
# Gap #46 — owner / territory scoping for masters (Customer, Supplier)
# ---------------------------------------------------------------------------


def needs_owner_restriction(allowed_owners) -> bool:
	"""True only when a non-empty owner allow-list is present."""
	return bool(allowed_owners)


def owner_allowed(owner, allowed_owners) -> bool:
	"""Is record `owner` visible?

	Parameters
	----------
	owner:
		The ``owner`` field value on the master record (ERPNext stores the
		creating user's email there).
	allowed_owners:
		Iterable of user emails the current user may see, or empty/None for
		no restriction.

	Safe-by-default: empty / None → always True.
	Records with a blank owner are never hidden (can't be scoped).
	"""
	if not needs_owner_restriction(allowed_owners):
		return True
	if not owner:
		return True
	return owner in set(allowed_owners)


def needs_territory_restriction(allowed_territories) -> bool:
	"""True only when a non-empty territory allow-list is present."""
	return bool(allowed_territories)


def territory_allowed(territory, allowed_territories) -> bool:
	"""Is record `territory` visible?

	Parameters
	----------
	territory:
		The ``territory`` field value on the Customer / Supplier.
	allowed_territories:
		Iterable of territory names the current user may see, or empty/None
		for no restriction.

	Safe-by-default: empty / None → always True.
	Records with a blank territory are never hidden.
	"""
	if not needs_territory_restriction(allowed_territories):
		return True
	if not territory:
		return True
	return territory in set(allowed_territories)


def master_allowed(owner, territory, allowed_owners, allowed_territories) -> bool:
	"""Combined owner + territory gate for a single master record.

	A record is visible only if it passes BOTH active restrictions
	independently. When a restriction list is empty/None that axis is not
	applied (safe-by-default on each axis).
	"""
	return owner_allowed(owner, allowed_owners) and territory_allowed(territory, allowed_territories)


# ---------------------------------------------------------------------------
# Gap #45 — cost / margin field masking
# ---------------------------------------------------------------------------

#: Fields that expose cost or margin data.  The Frappe layer may use this
#: constant to build SQL projections that never fetch these columns at all.
COST_FIELDS: frozenset[str] = frozenset(
	(
		"valuation_rate",
		"last_purchase_rate",
		"standard_rate",
		"incoming_rate",
		"avg_rate",
		"cost",
		"landed_cost",
		"base_rate",
		"rate_of_valuation",
		"gross_profit",
		"gross_profit_percent",
		"margin_type",
		"margin_rate_or_amount",
		"discount_amount",
		"discount_percentage",
		"profit",
		"profit_percent",
	)
)


def mask_fields(payload, role_has_cost_visibility: bool):
	"""Strip cost/margin fields from *payload* when the user lacks visibility.

	Parameters
	----------
	payload:
		Either a single ``dict`` (one record) or a ``list`` of dicts (a
		list result). Modified **in-place**; the same object is returned.
	role_has_cost_visibility:
		Pass ``True`` when the user's role set grants cost visibility — in
		that case the function is a no-op and returns *payload* unchanged.

	Returns
	-------
	The (possibly mutated) payload.

	Safe: keys not present in a dict are silently ignored.  Handles None /
	non-dict items in a list gracefully.
	"""
	if role_has_cost_visibility:
		return payload
	if isinstance(payload, list):
		for item in payload:
			if isinstance(item, dict):
				_strip_cost_keys(item)
	elif isinstance(payload, dict):
		_strip_cost_keys(payload)
	return payload


def _strip_cost_keys(record: dict) -> None:
	"""Null-out every COST_FIELD present in *record* (in-place)."""
	for field in COST_FIELDS:
		if field in record:
			record[field] = None
