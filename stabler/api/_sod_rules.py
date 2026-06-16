"""Segregation-of-duties (SoD) policy + evaluation — no Frappe, no I/O.

This is the classic IT general control auditors ask for: *no single person
should be able to both create and conceal a fraudulent transaction.* We express
that as a matrix of toxic capability pairs. A user violates a rule when they
hold at least one role from each side of the pair.

The policy is data (``SOD_CONFLICTS`` / ``CAPABILITIES``) and the evaluation is
pure, so both are unit tested without a bench. The Frappe layer
(``stabler.api.access_review``) just feeds in users and their roles.

Important: an SoD finding is **advisory** — in a small business one person
often wears several hats. The point is to *surface* the concentration so it can
be accepted with eyes open or mitigated by a compensating control (e.g. the
payment maker-checker already blocks self-approval at transaction time).
"""
from __future__ import annotations

SEVERITY_ORDER = {"critical": 3, "high": 2, "medium": 1, "info": 0}

# Capability → the roles that grant it. Used for the access-review grid and as
# the building blocks of the conflict matrix below.
CAPABILITIES: dict[str, dict] = {
	"make_payments": {
		"label": "Create payments / journals",
		"roles": ["Accounts User", "Accounts Manager"],
	},
	"approve_payments": {
		"label": "Approve payments",
		"roles": ["Accounts Manager", "Stabler Admin", "System Manager"],
	},
	"manage_suppliers": {
		"label": "Create / edit suppliers",
		"roles": ["Purchase User", "Purchase Manager", "Purchase Master Manager"],
	},
	"manage_customers": {
		"label": "Create / edit customers",
		"roles": ["Sales User", "Sales Manager", "Sales Master Manager"],
	},
	"collect_receivables": {
		"label": "Receive payments / issue credit notes",
		"roles": ["Accounts User", "Accounts Manager"],
	},
	"move_stock": {
		"label": "Record stock movements",
		"roles": ["Stock User", "Stock Manager"],
	},
	"reconcile_stock": {
		"label": "Reconcile / revalue stock",
		"roles": ["Stock Manager"],
	},
	"administer_users": {
		"label": "Administer users & roles",
		"roles": ["System Manager", "Stabler Admin"],
	},
	"view_audit": {
		"label": "View audit log",
		"roles": ["System Manager", "Stabler Admin", "Accounts Manager", "Auditor"],
	},
}

# Toxic pairs. A user violates when they hold >=1 role from group_a AND >=1 from
# group_b. Roles are kept explicit (not via CAPABILITIES) so a reviewer can read
# the policy without cross-referencing.
SOD_CONFLICTS: list[dict] = [
	{
		"id": "vendor_and_pay",
		"label": "Creates suppliers AND makes payments",
		"severity": "high",
		"group_a": {"label": "Manage suppliers", "roles": ["Purchase User", "Purchase Manager", "Purchase Master Manager"]},
		"group_b": {"label": "Make payments", "roles": ["Accounts User", "Accounts Manager"]},
		"rationale": "Could set up a fictitious supplier and pay it.",
		"mitigation": "Payment maker-checker blocks self-approval, partially mitigating the pay side.",
	},
	{
		"id": "customer_and_collect",
		"label": "Manages customers AND posts receipts / credit notes",
		"severity": "high",
		"group_a": {"label": "Manage customers", "roles": ["Sales User", "Sales Master Manager"]},
		"group_b": {"label": "Post receipts / credit notes", "roles": ["Accounts User", "Accounts Manager"]},
		"rationale": "Could divert customer receipts or issue unauthorised credit notes.",
		"mitigation": "Audit trail records credit-note issuance; review periodically.",
	},
	{
		"id": "superadmin_and_operator",
		"label": "Holds System Manager AND operates a finance/stock module",
		"severity": "critical",
		"group_a": {"label": "User administration", "roles": ["System Manager"]},
		"group_b": {"label": "Operates finance/stock", "roles": ["Accounts User", "Accounts Manager", "Stock User", "Stock Manager", "Purchase User"]},
		"rationale": "A super-admin who also transacts can grant themselves rights and erase the evidence. Violates least privilege.",
		"mitigation": "Give day-to-day operators scoped roles; reserve System Manager for a separate break-glass account.",
	},
	{
		"id": "stock_move_and_reconcile",
		"label": "Records stock movements AND reconciles stock",
		"severity": "medium",
		"group_a": {"label": "Move stock", "roles": ["Stock User"]},
		"group_b": {"label": "Reconcile / revalue", "roles": ["Stock Manager"]},
		"rationale": "Could hide shrinkage by adjusting counts to match movements.",
		"mitigation": "Independent cycle counts; review stock reconciliations.",
	},
]


def _held(roles: set, group_roles) -> list:
	"""Roles from group_roles the user actually holds (sorted, for stable output)."""
	return sorted(roles.intersection(group_roles))


def evaluate_user(user_roles, conflicts=SOD_CONFLICTS) -> list[dict]:
	"""Return the conflicts a single user violates.

	Each result: {id, label, severity, matched_a:[...], matched_b:[...],
	rationale, mitigation}. A role appearing on both sides still needs a *second*
	distinct role on the other side to violate — holding one role never conflicts
	with itself.
	"""
	roles = set(user_roles or [])
	out = []
	for c in conflicts:
		a = _held(roles, set(c["group_a"]["roles"]))
		b = _held(roles, set(c["group_b"]["roles"]))
		if not a or not b:
			continue
		# Require the violation to rest on at least two distinct roles, so a
		# single role that happens to sit in both groups isn't self-flagged.
		if set(a) == set(b) and len(set(a) | set(b)) < 2:
			continue
		out.append(
			{
				"id": c["id"],
				"label": c["label"],
				"severity": c["severity"],
				"matched_a": a,
				"matched_b": b,
				"rationale": c["rationale"],
				"mitigation": c.get("mitigation", ""),
			}
		)
	return out


def scan_users(users, conflicts=SOD_CONFLICTS) -> dict:
	"""Evaluate a list of users.

	``users``: [{"user": str, "full_name": str, "roles": [..]}, ...].
	Returns per-user violations + a severity summary.
	"""
	violations = []
	flagged = set()
	summary = {"critical": 0, "high": 0, "medium": 0, "info": 0}
	for u in users:
		ev = evaluate_user(u.get("roles") or [], conflicts)
		for v in ev:
			row = dict(v)
			row["user"] = u.get("user")
			row["full_name"] = u.get("full_name") or u.get("user")
			violations.append(row)
			summary[v["severity"]] = summary.get(v["severity"], 0) + 1
			flagged.add(u.get("user"))
	violations.sort(key=lambda r: (-SEVERITY_ORDER.get(r["severity"], 0), r["user"] or ""))
	summary["users_flagged"] = len(flagged)
	summary["total"] = len(violations)
	return {"violations": violations, "summary": summary}


def would_conflict(existing_roles, new_role, conflicts=SOD_CONFLICTS) -> list[dict]:
	"""Conflicts that adding ``new_role`` would newly introduce.

	Used to warn at role-assignment time. Returns only conflicts that are NOT
	already present with the existing roles (so we don't nag about pre-existing
	concentration when changing something unrelated).
	"""
	existing = set(existing_roles or [])
	before = {c["id"] for c in evaluate_user(existing, conflicts)}
	after = evaluate_user(existing | {new_role}, conflicts)
	return [c for c in after if c["id"] not in before]


def capabilities_for(user_roles, capabilities=CAPABILITIES) -> dict:
	"""Which sensitive capabilities a user holds (for the access-review grid)."""
	roles = set(user_roles or [])
	return {key: bool(roles.intersection(cap["roles"])) for key, cap in capabilities.items()}


# ---------------------------------------------------------------------------
# Enforcement decision engine (per-document, per-action)
# ---------------------------------------------------------------------------

# Each entry defines a conflict between two *lifecycle actions* on a document.
# If the same actor performed `action_a` at some prior step, they may not
# perform `action_b`. The rule is symmetric only when listed both ways.
#
# Keys:
#   id       – stable string identifier
#   doctypes – frozenset of doctypes this rule governs; empty frozenset = all
#   action_a – prior lifecycle action (e.g. "create", "submit", "request")
#   action_b – blocked lifecycle action (e.g. "approve", "receive", "pay")
#   severity – "critical" | "high" | "medium" | "info"
#   message  – human-readable block reason (no Frappe _ here; translated by wrapper)
#
# "create"  = owner / first-save actor
# "submit"  = the user who submitted (docstatus → 1)
# "request" = the user who originated a purchase request / material request
# "approve" = the user granting approval / releasing for payment
# "receive" = the user who posts a Purchase Receipt / Delivery Note
# "pay"     = the user who posts a Payment Entry or Journal Entry against the doc
# "amend"   = the user who amended (created an amendment from) a cancelled doc

ACTOR_CONFLICT_RULES: list[dict] = [
	{
		"id": "creator_cannot_approve",
		"doctypes": frozenset(),  # universal
		"action_a": "create",
		"action_b": "approve",
		"severity": "critical",
		"message": "The user who created this document cannot also approve it.",
	},
	{
		"id": "submitter_cannot_approve",
		"doctypes": frozenset(),  # universal
		"action_a": "submit",
		"action_b": "approve",
		"severity": "critical",
		"message": "The user who submitted this document cannot also approve it.",
	},
	{
		"id": "supplier_creator_cannot_pay",
		"doctypes": frozenset({"Payment Entry", "Purchase Invoice", "Journal Entry"}),
		"action_a": "create_supplier",
		"action_b": "pay",
		"severity": "high",
		"message": "The user who created the supplier cannot post a payment to that supplier.",
	},
	{
		"id": "po_creator_cannot_receive",
		"doctypes": frozenset({"Purchase Receipt"}),
		"action_a": "create",
		"action_b": "receive",
		"severity": "high",
		"message": "The user who created the Purchase Order cannot also receive the goods.",
	},
	{
		"id": "requester_cannot_approve",
		"doctypes": frozenset({"Material Request", "Purchase Order"}),
		"action_a": "request",
		"action_b": "approve",
		"severity": "high",
		"message": "The user who raised the request cannot also approve it.",
	},
	{
		"id": "requester_cannot_pay",
		"doctypes": frozenset({"Payment Entry", "Purchase Invoice", "Journal Entry"}),
		"action_a": "request",
		"action_b": "pay",
		"severity": "high",
		"message": "The user who originated the purchase request cannot also post the payment.",
	},
	{
		"id": "creator_cannot_pay",
		"doctypes": frozenset({"Payment Entry", "Journal Entry"}),
		"action_a": "create",
		"action_b": "pay",
		"severity": "high",
		"message": "The user who created this payment document cannot also submit/pay it (use maker-checker).",
	},
	{
		"id": "creator_cannot_amend",
		"doctypes": frozenset(),  # universal
		"action_a": "create",
		"action_b": "amend",
		"severity": "medium",
		"message": "The user who originally created this document should not be the sole actor in its amendment.",
	},
]


def conflicting_actor(
	action: str,
	doctype: str,
	actor: str,
	prior_actors_by_action: dict[str, list[str]],
	rules: list[dict] | None = None,
) -> list[dict]:
	"""Return all ACTOR_CONFLICT_RULES violated by ``actor`` performing ``action``
	on a document of type ``doctype``, given the prior actors already recorded.

	Parameters
	----------
	action:
	    The lifecycle action the current user is about to perform (e.g. "approve").
	doctype:
	    ERPNext doctype name (e.g. "Payment Entry").
	actor:
	    The user who is about to perform ``action`` (typically frappe.session.user).
	prior_actors_by_action:
	    Mapping of action → list of users who already performed that action on this
	    document. E.g. {"create": ["alice@x"], "submit": ["alice@x"]}.
	    An empty list or missing key means nobody has performed that action yet.
	rules:
	    Override the default ACTOR_CONFLICT_RULES (used in tests).

	Returns
	-------
	List of violation dicts, one per triggered rule::

	    {
	        "rule_id": str,
	        "action_a": str,        # prior action that was performed
	        "action_b": str,        # blocked action being attempted
	        "conflict_actor": str,  # the user who did action_a (== actor)
	        "severity": str,
	        "message": str,
	    }

	An empty list means no conflict — proceed.
	"""
	if not actor or not action:
		return []

	effective_rules = rules if rules is not None else ACTOR_CONFLICT_RULES
	violations = []

	for rule in effective_rules:
		if rule["action_b"] != action:
			continue
		# Doctype filter: empty frozenset = applies to all doctypes.
		doctypes = rule.get("doctypes") or frozenset()
		if doctypes and doctype not in doctypes:
			continue
		# Check whether actor appears in the prior-actors list for action_a.
		prior = prior_actors_by_action.get(rule["action_a"]) or []
		if actor in prior:
			violations.append(
				{
					"rule_id": rule["id"],
					"action_a": rule["action_a"],
					"action_b": rule["action_b"],
					"conflict_actor": actor,
					"severity": rule["severity"],
					"message": rule["message"],
				}
			)

	return violations
