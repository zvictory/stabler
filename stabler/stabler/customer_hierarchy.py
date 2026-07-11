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

# Error codes returned by check_parent_link — the frappe layer maps each to a
# translated, user-facing message. None means the link is valid.
ERR_SELF = "self"
ERR_PARENT_HAS_PARENT = "parent_has_parent"
ERR_HAS_CHILDREN = "has_children"


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
