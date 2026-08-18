"""Vehicle Agreement status machine — the one gate every status change goes through.

Frappe-free by construction, the same contract as `chain.py` and `work_policy`:
every function here is a total function of its arguments, so the machine is
testable without a bench, a site or a database.

WHY THIS EXISTS. `stabler-cibo` shipped the eight-state enum and correctly split
`Rescheduled` (collectible) from `Restructured` (terminal). Only some states got
writers. `v1.py` assigned `agreement_status` in exactly two places — `Active` on
activation and `Rescheduled` on reschedule approval — so three declared states
were unreachable, and the consequences were not cosmetic:

  - A fully paid agreement could never leave `Active`. Its invoice outstanding
    fell to zero and it stayed in the collection queue for ever.
  - The `settlement_writeoff` capability had no consumer at all: it was defined
    and granted to Vehicle Finance Manager, but no endpoint asked for it, so
    closing an agreement by writing off the balance was not expressible.
  - `approve_reschedule` carried no status guard, so a closed agreement could be
    rescheduled.

The schema and the read path already existed — badge colours, chain maths, the
`restructured_from` column. Only the writer was missing.

WHY A TABLE AND NOT AN `if`. The backlog entry that filed this defect
(`stabler-2671`) is explicit that the transition table must land FIRST, so that
both halves of the fix write through the same machine. Two endpoints each
deciding for themselves what a legal status change is, is how the enum grew three
unreachable states in the first place.

`Restructured` is a target here but has no writer yet, and that is deliberate
rather than an oversight: the ADR
(`docs/decisions/2026-08-16-restructure-closes-and-reopens.md`) settles that a
restructure CLOSES the original and OPENS a successor, which is a document-creation
flow rather than a status write. The table recognises the transition so the writer,
when it lands, goes through this gate like everything else.
"""

from __future__ import annotations

#: The status every agreement starts in. It is the one state no transition needs
#: to target, because the doctype default puts a document there.
INITIAL = "Draft"

#: Statuses money may still be collected against. `work.py` imports this through
#: `v1.py`; it is defined here so the queue and the machine cannot disagree.
COLLECTIBLE = ("Active", "Rescheduled")

#: Closed for good. A terminal agreement is not collectible, cannot be
#: rescheduled, and has no way back — reopening one would silently rewrite
#: history that the chain (`chain.py`) exists to keep readable.
TERMINAL = frozenset({"Restructured", "Completed", "Terminated"})

#: The whole machine. Keys are every state `vehicle_agreement.json` declares, in
#: the order it declares them; values are the states each may move to.
ALLOWED: dict[str, frozenset[str]] = {
	"Draft": frozenset({"Review", "Approved", "Active"}),
	"Review": frozenset({"Draft", "Approved"}),
	"Approved": frozenset({"Active"}),
	# A live agreement may be renegotiated (Rescheduled keeps the same record,
	# Restructured opens a successor), paid off, or written off.
	"Active": frozenset({"Rescheduled", "Restructured", "Completed", "Terminated"}),
	# Rescheduled -> Rescheduled is legal on purpose: an agreement can be
	# rescheduled more than once, and each approval supersedes the last version.
	"Rescheduled": frozenset({"Rescheduled", "Restructured", "Completed", "Terminated"}),
	"Restructured": frozenset(),
	"Completed": frozenset(),
	"Terminated": frozenset(),
}


class IllegalTransition(ValueError):
	"""A status change the machine refuses. Names both ends, because a refusal
	that does not say what it refused is a bug report nobody can act on."""

	def __init__(self, current: str, target: str) -> None:
		self.current = current
		self.target = target
		super().__init__(f"Cannot move a Vehicle Agreement from {current} to {target}.")


def is_terminal(status: str) -> bool:
	return status in TERMINAL


def is_collectible(status: str) -> bool:
	return status in COLLECTIBLE


def can_move(current: str, target: str) -> bool:
	"""True only when the move is declared.

	An unknown state on either end is refused rather than assumed legal — a typo
	that passed silently would make the machine guard nothing. Both directions
	fall out of the table lookup itself: an unknown `current` has no entry, and an
	unknown `target` is in nobody's set. An explicit `target not in ALLOWED` guard
	stood here until a mutation proved it could not change any answer.
	"""
	return target in ALLOWED.get(current, frozenset())


def assert_can_move(current: str, target: str) -> None:
	if not can_move(current, target):
		raise IllegalTransition(current, target)
