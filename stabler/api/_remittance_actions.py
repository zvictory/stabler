"""Which remittance actions a caller may take on a transfer right now — no Frappe, no DB.

One table, consulted by every read path, so the answer a screen renders and the
answer the server would give are the same object. A hidden button is a UX
affordance, not a permission; this module exists so the *server* is the thing that
decided, and the frontend only draws the result.

Two independent gates, and an action is offered only when BOTH open:

* **State.** Derived from the four axes on ``remittance_transfer.json`` —
  ``operational_status``, ``accounting_status``, ``verification_status``,
  ``refund_status`` — plus ``code_locked``. Each predicate below mirrors the
  refusal its endpoint already raises; where the two could drift, the test suite
  reads both and compares.
* **Role.** The four roles ``patches/v87_remittance_roles.py`` creates, plus the
  app's pre-existing money-control manager set. A Remittance Cashier is never
  offered Approve refund, Reject refund or Unlock, and a Viewer or Auditor is
  never offered anything at all — those two roles hold ``read`` and nothing else.

The invariant that gets its own early return
--------------------------------------------
``Registered`` + anything other than ``Posted`` yields the empty list for every
role. The obligation was never posted, so a payout would debit something that
does not exist. The module already refuses this in three places
(``payout_queue``'s inclusion filter, ``_assert_payable``, and the queue's own
field list); this is the fourth, and it is the only one stated as "no action at
all" rather than "not this action".

Action names are STABLE MACHINE IDENTIFIERS, deliberately not translated. They
are wire values a client matches on; a translated action name would mean a
Russian browser and a Turkish browser disagree about what the server offered.
The human label belongs to the frontend, keyed off these.

Pure on purpose, exactly like ``_remittance_pricing``: no ``import frappe``, so
the caller passes the role list it already fetched and the whole table is
testable without a bench. Callers fetch ``frappe.get_roles()`` ONCE per request
and hand the same list to every row — the role set cannot change mid-response,
and a per-row lookup would be N queries to answer one question.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #
PAYOUT = "payout"
UNLOCK_PICKUP_CODE = "unlock_pickup_code"
REQUEST_REFUND = "request_refund"
APPROVE_REFUND = "approve_refund"
REJECT_REFUND = "reject_refund"
COMPLETE_REFUND = "complete_refund"

VIEWER = "Remittance Viewer"
CASHIER = "Remittance Cashier"
FINANCE_MANAGER = "Remittance Finance Manager"
AUDITOR = "Remittance Auditor"

# The app's pre-existing money-control manager set — `approvals._APPROVER_ROLES`.
# Copied rather than imported so this module stays Frappe-free; the copy is not
# allowed to drift, and `test_remittance_actions` reads the real tuple out of
# `approvals.py` and compares. It is retained alongside the remittance Finance
# Manager because `unlock_pickup_code` shipped gated on it (stabler-j81g, when no
# remittance role existed) and an Accounts Manager who could unlock yesterday
# must still be able to today.
_LEGACY_APPROVER_ROLES = ("Accounts Manager", "System Manager", "Stabler Admin")

#: Who signs off. Approve, Reject and Unlock live here and nowhere else.
MANAGER_ROLES = (FINANCE_MANAGER, *_LEGACY_APPROVER_ROLES)

#: Who works a counter — hands over cash, takes a refund request. A superset of
#: the managers: a manager standing at the desk is still allowed to serve.
DESK_ROLES = (CASHIER, *MANAGER_ROLES)

#: The columns a caller must select for this module to answer. Nothing else is
#: read, and nothing here is a secret.
STATE_FIELDS = (
	"operational_status",
	"accounting_status",
	"verification_status",
	"refund_status",
	"code_locked",
)

#: Never on a read path, in a field list or in a response body — in any shape.
#: `pickup_code` is the secret itself; `pickup_code_hash` is a salted digest over
#: a 32-glyph, 8-character alphabet, which is a few core-seconds away from being
#: the secret itself. `stabler_pickup_code` is the third name for the same
#: secret: the v33 Journal Entry custom field, which v86 rewrote in place as a
#: digest. The remittance reads are JE-shaped as well as transfer-shaped, so
#: leaving it out would guard one shape of the response and not the other.
FORBIDDEN_READ_FIELDS = ("pickup_code", "pickup_code_hash", "stabler_pickup_code")


class PickupCodeLeak(RuntimeError):
	"""A read path was about to hand out the pickup code, or its digest.

	Deliberately not a `frappe.throw`: this is a programming error in our own
	read path, not something a user did wrong, and it carries no translated
	message because no user should ever be in a position to read one.
	"""


# --------------------------------------------------------------------------- #
# Reading one transfer's state
# --------------------------------------------------------------------------- #
def _field(state, name: str):
	"""One field off a dict, a `frappe._dict`, or a Document — whichever arrived."""
	if isinstance(state, dict):
		return state.get(name)
	getter = getattr(state, "get", None)
	if callable(getter):
		return getter(name)
	return getattr(state, name, None)


def _truthy(value) -> bool:
	"""`code_locked` is a Check: 1, "1", True and None all have to mean something."""
	if value in (None, "", "0", 0, False):
		return False
	return True


def _refund_state(state) -> str:
	"""`refund_status` as a comparable string. Empty and "None" are the same state."""
	value = _field(state, "refund_status")
	return "None" if value in (None, "") else str(value)


def _obligation_exists(state) -> bool:
	"""Registered + not-Posted is a transfer whose obligation was never created.

	Nothing may be done to it — not paid out, not refunded, not even unlocked.
	Offering any action there is offering to move money against a ledger entry
	that does not exist.
	"""
	if _field(state, "operational_status") != "Registered":
		return True
	return _field(state, "accounting_status") == "Posted"


def _payable(state) -> bool:
	"""Mirrors `remittance_commands._assert_payable`, refusal for refusal."""
	return (
		_field(state, "operational_status") == "Registered"
		and _field(state, "accounting_status") == "Posted"
		and _refund_state(state) not in ("Approved", "Completed")
		and not _truthy(_field(state, "code_locked"))
	)


def _unlockable(state) -> bool:
	"""Mirrors `remittance_commands.unlock_pickup_code`: still Registered, still locked."""
	return _field(state, "operational_status") == "Registered" and _truthy(_field(state, "code_locked"))


def _refund_requestable(state) -> bool:
	"""A refund can only be asked for on a posted obligation nobody has claimed yet.

	Once the receiver has been paid the cash is gone, and once a refund is in
	flight a second request is not a request, it is a duplicate.
	"""
	return (
		_field(state, "operational_status") == "Registered"
		and _field(state, "accounting_status") == "Posted"
		and _refund_state(state) == "None"
	)


def _refund_decidable(state) -> bool:
	"""Approve and Reject are the same gate: an open request on a live transfer."""
	return _field(state, "operational_status") == "Registered" and _refund_state(state) == "Requested"


def _refund_completable(state) -> bool:
	"""Only Completed moves cash, and only an approved refund reaches Completed."""
	return (
		_field(state, "operational_status") == "Registered"
		and _field(state, "accounting_status") == "Posted"
		and _refund_state(state) == "Approved"
	)


#: (action, roles that hold it, state that permits it). Ordered, so the list a
#: caller receives is stable across requests and diffable in a test.
_TABLE = (
	(PAYOUT, DESK_ROLES, _payable),
	(UNLOCK_PICKUP_CODE, MANAGER_ROLES, _unlockable),
	(REQUEST_REFUND, DESK_ROLES, _refund_requestable),
	(APPROVE_REFUND, MANAGER_ROLES, _refund_decidable),
	(REJECT_REFUND, MANAGER_ROLES, _refund_decidable),
	(COMPLETE_REFUND, DESK_ROLES, _refund_completable),
)

#: Every action this module knows how to offer, in table order.
ACTIONS = tuple(action for action, _roles, _permits in _TABLE)

_ROLES_BY_ACTION = {action: roles for action, roles, _permits in _TABLE}


# --------------------------------------------------------------------------- #
# The answer
# --------------------------------------------------------------------------- #
def holds(action: str, roles) -> bool:
	"""Does this role list hold `action` at all, ignoring the transfer's state?

	The role half of the gate on its own — what an enforcement point asks before
	it has a row in front of it.
	"""
	return bool(set(roles or ()) & set(_ROLES_BY_ACTION.get(action, ())))


def allowed_actions(state, roles) -> list[str]:
	"""What this caller may do to this transfer, right now.

	`state` is anything carrying `STATE_FIELDS`; `roles` is the caller's role
	list, fetched once by the caller.
	"""
	held = set(roles or ())
	if not held or not _obligation_exists(state):
		return []
	return [action for action, holders, permits in _TABLE if held & set(holders) and permits(state)]


def annotate(rows, roles) -> list:
	"""Stamp `allowed_actions` onto every row of a read response, in place.

	One role list for the whole page — see the module docstring.
	"""
	for row in rows:
		row["allowed_actions"] = allowed_actions(row, roles)
	return rows


# --------------------------------------------------------------------------- #
# The code never leaves
# --------------------------------------------------------------------------- #
def assert_safe_fields(fields) -> tuple:
	"""Refuse a read-path field list that selects the pickup code or its digest.

	Called with the constant itself, so a future edit that adds the hash to a
	queue or list projection fails at the read rather than shipping a digest to
	a browser. Returns the fields so it can wrap a call argument.
	"""
	leaked = sorted(set(FORBIDDEN_READ_FIELDS) & {str(field) for field in fields})
	if leaked:
		raise PickupCodeLeak(f"read-path field list selects {', '.join(leaked)}")
	return tuple(fields)


def assert_no_pickup_code(payload):
	"""Refuse a read-path response that carries the pickup code in any shape.

	Walks dicts and sequences, because a leak arrives nested — inside a `stages`
	list or a detail sub-dict — at least as easily as at the top level. The check
	is on KEYS: a value that merely looks like a code is a receiver's name, and
	refusing those would be a denial of service with no security story.

	Returns the payload so it can wrap a `return`.
	"""
	_walk(payload, 0)
	return payload


def _walk(node, depth: int) -> None:
	# A response is a projection of table rows, so it is shallow by construction.
	# The bound is a stop against a cycle, not a policy about nesting.
	if depth > 8:
		return
	if isinstance(node, dict):
		leaked = sorted(set(FORBIDDEN_READ_FIELDS) & {str(key) for key in node})
		if leaked:
			raise PickupCodeLeak(f"read-path response carries {', '.join(leaked)}")
		for value in node.values():
			_walk(value, depth + 1)
		return
	if isinstance(node, (list, tuple)):
		for value in node:
			_walk(value, depth + 1)


__all__ = [
	"ACTIONS",
	"APPROVE_REFUND",
	"AUDITOR",
	"CASHIER",
	"COMPLETE_REFUND",
	"DESK_ROLES",
	"FINANCE_MANAGER",
	"FORBIDDEN_READ_FIELDS",
	"MANAGER_ROLES",
	"PAYOUT",
	"REJECT_REFUND",
	"REQUEST_REFUND",
	"STATE_FIELDS",
	"UNLOCK_PICKUP_CODE",
	"VIEWER",
	"PickupCodeLeak",
	"allowed_actions",
	"annotate",
	"assert_no_pickup_code",
	"assert_safe_fields",
	"holds",
]
