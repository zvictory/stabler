"""Pure customer parent/child hierarchy logic — no frappe, unit-testable.

QuickBooks-style single-level hierarchy (migration plan §2 K2): transactions are
always recorded on the CHILD customer; the parent is a consolidation node whose
balance is the cumulative rollup of its own balance plus its children. Children
are locations / "jobs" of exactly one parent, and the tree is strictly one level
deep (a parent cannot itself have a parent, a child cannot have children).

The frappe layer (customer_hooks.py, api/sales.py) maps the returned error codes
to translated messages and feeds these functions rows fetched from the DB, so the
rules and the rollup math stay pure and testable.
"""

from __future__ import annotations

from typing import NamedTuple

# Error codes returned by check_parent_link — the frappe layer maps each to a
# translated, user-facing message. None means the link is valid.
ERR_SELF = "self"
ERR_PARENT_HAS_PARENT = "parent_has_parent"
ERR_HAS_CHILDREN = "has_children"

# Error codes for the parent bulk-payment allocation grid (phase 2, plan §2 K2).
ERR_ALLOC_EMPTY = "alloc_empty"
ERR_ALLOC_NONPOSITIVE = "alloc_nonpositive"
ERR_ALLOC_UNKNOWN_INVOICE = "alloc_unknown_invoice"
ERR_ALLOC_EXCEEDS = "alloc_exceeds_outstanding"

# Error codes for the legacy parent-PE reallocation tool (phase 2).
ERR_XFER_EMPTY = "xfer_empty"
ERR_XFER_NONPOSITIVE = "xfer_nonpositive"
ERR_XFER_UNKNOWN_CHILD = "xfer_unknown_child"
ERR_XFER_EXCEEDS = "xfer_exceeds_unallocated"


def check_parent_link(
	customer: str | None,
	parent: str | None,
	*,
	parent_has_own_parent: bool,
	customer_has_children: bool,
) -> str | None:
	"""Validate a proposed parent link for `customer`.

	Returns an error code (see ERR_* constants) or None when valid.

	- ERR_SELF: a customer cannot be its own parent.
	- ERR_PARENT_HAS_PARENT: the chosen parent already has a parent — allowing
	  this would create a two-level tree (single-level rule).
	- ERR_HAS_CHILDREN: `customer` already has children of its own, so it cannot
	  become a child (that would also create two levels).

	An empty/None `parent` clears the link and is always valid.
	"""
	if not parent:
		return None
	if customer and parent == customer:
		return ERR_SELF
	if parent_has_own_parent:
		return ERR_PARENT_HAS_PARENT
	if customer_has_children:
		return ERR_HAS_CHILDREN
	return None


def children_balance_map(
	child_rows,
	*,
	parent_key: str = "parent_customer",
	balance_key: str = "balance",
) -> dict[str, float]:
	"""Aggregate each child's balance under its parent.

	`child_rows` is an iterable of dicts, each carrying the child's parent name
	and the child's own balance. Rows with an empty parent are ignored. Returns
	{parent_name: summed_children_balance}. Balances are added in whatever single
	currency the caller passed (base or account currency) — mixing is the
	caller's responsibility.
	"""
	out: dict[str, float] = {}
	for row in child_rows:
		parent = row.get(parent_key)
		if not parent:
			continue
		out[parent] = out.get(parent, 0.0) + float(row.get(balance_key) or 0)
	return out


def cumulative_balance(own_balance, children_total) -> float:
	"""Parent's rollup = own balance + summed children balance, rounded to 2 dp."""
	return round(float(own_balance or 0) + float(children_total or 0), 2)


# ---------------------------------------------------------------------------
# Parent bulk payment (plan §2 K2): a parent's incoming cash is split across
# the CHILD invoices it settles. The allocation grid is validated and grouped
# here (pure); the frappe layer creates one Payment Entry per child party.
# ---------------------------------------------------------------------------


def validate_bulk_allocations(
	allocations,
	invoice_party_map: dict,
	outstanding_map: dict,
	*,
	epsilon: float = 0.01,
) -> str | None:
	"""Validate the parent bulk-payment allocation grid.

	`allocations` is an iterable of {invoice, amount}. `invoice_party_map` maps
	each open invoice to its actual party (the child customer, or the legacy
	parent-booked reference). `outstanding_map` maps each invoice to its current
	outstanding amount. Returns an ERR_ALLOC_* code or None when every row is
	valid. Rows targeting the same invoice are summed before the outstanding
	check so two partial rows can't quietly overpay one invoice.
	"""
	rows = [r for r in allocations if float(r.get("amount") or 0) != 0]
	if not rows:
		return ERR_ALLOC_EMPTY
	per_invoice: dict[str, float] = {}
	for row in rows:
		inv = row.get("invoice")
		amt = float(row.get("amount") or 0)
		if inv not in invoice_party_map:
			return ERR_ALLOC_UNKNOWN_INVOICE
		if amt <= 0:
			return ERR_ALLOC_NONPOSITIVE
		per_invoice[inv] = per_invoice.get(inv, 0.0) + amt
	for inv, total in per_invoice.items():
		if total > float(outstanding_map.get(inv, 0) or 0) + epsilon:
			return ERR_ALLOC_EXCEEDS
	return None


def group_allocations_by_party(allocations, invoice_party_map: dict) -> dict[str, list[dict]]:
	"""Group allocation rows by the invoice's actual party (child customer).

	Returns {party: [{"invoice": name, "amount": float}, ...]} preserving the
	input order (callers pass oldest-first). Rows with a non-positive amount or
	an unknown invoice are skipped — call `validate_bulk_allocations` first to
	surface those to the user.
	"""
	out: dict[str, list[dict]] = {}
	for row in allocations:
		inv = row.get("invoice")
		amt = round(float(row.get("amount") or 0), 2)
		party = invoice_party_map.get(inv)
		if party is None or amt <= 0:
			continue
		out.setdefault(party, []).append({"invoice": inv, "amount": amt})
	return out


# ---------------------------------------------------------------------------
# Parent-chain credit limit (plan §2 K2): the limit lives on the chain root
# and is checked against the whole chain's outstanding plus the invoice being
# posted. Pure decision so the hook stays a thin, testable wrapper.
# ---------------------------------------------------------------------------


class CreditDecision(NamedTuple):
	exceeded: bool
	projected: float
	limit: float
	unlimited: bool


def credit_limit_decision(
	limit,
	chain_outstanding,
	new_amount,
	prev_outstanding=0.0,
	*,
	epsilon: float = 0.01,
) -> CreditDecision:
	"""Decide whether posting `new_amount` breaches the chain credit limit.

	- `limit` <= 0 (or falsy) means unlimited → never exceeded.
	- `chain_outstanding` is the current GL outstanding for the whole chain
	  (root + children), already summed by the caller.
	- `prev_outstanding` is this invoice's own outstanding BEFORE the change,
	  subtracted so amending an existing invoice only counts its delta (a fresh
	  invoice passes 0).
	- Exactly hitting the limit passes; only strictly exceeding (beyond a small
	  epsilon for float noise) is flagged.
	"""
	lim = float(limit or 0)
	projected = round(
		float(chain_outstanding or 0) - float(prev_outstanding or 0) + float(new_amount or 0), 2
	)
	if lim <= 0:
		return CreditDecision(False, projected, lim, True)
	return CreditDecision(projected > lim + epsilon, projected, lim, False)


def validate_transfers(
	transfers,
	unallocated,
	valid_children,
	*,
	epsilon: float = 0.01,
) -> str | None:
	"""Validate a legacy parent-PE reallocation.

	`transfers` is an iterable of {child, amount}; `unallocated` is the source
	Payment Entry's unallocated amount; `valid_children` is the set of names in
	the parent's chain that may receive credit. Returns an ERR_XFER_* code or
	None. Amounts are summed across rows (two rows to the same child are added).
	"""
	rows = [r for r in transfers if float(r.get("amount") or 0) != 0]
	if not rows:
		return ERR_XFER_EMPTY
	total = 0.0
	for row in rows:
		child = row.get("child")
		amt = float(row.get("amount") or 0)
		if child not in valid_children:
			return ERR_XFER_UNKNOWN_CHILD
		if amt <= 0:
			return ERR_XFER_NONPOSITIVE
		total += amt
	if total > float(unallocated or 0) + epsilon:
		return ERR_XFER_EXCEEDS
	return None
