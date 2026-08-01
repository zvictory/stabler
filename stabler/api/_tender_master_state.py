"""Tender Master board lane — derived, never stored.

Frappe-free, so the rule that turns a set of child-lot funnel stages into one
parent-level lane can be tested exhaustively without a site.

WHY DERIVED, NOT STORED
------------------------
A Tender Master's board lane is a projection of its child CRM Deal lots, not
a fact of its own. If the lane were a hand-maintained `status` field on the
parent, someone would have to remember to flip it every time a lot moves —
and nobody does, reliably. Two lots win and three stay open, and the parent
still reads "Preparation" because the person who closed the last lot forgot
the checkbox. A derived lane can't drift: it is recomputed from the lots'
actual funnel stages (see `_funnel.classify`) every time it's read, so it is
always consistent with the source documents.
"""

from __future__ import annotations

#: Board lanes, in business order.
LANES = ["Preparation", "Active", "Awaiting Result", "Partial Result", "Completed"]

#: Stages that mean a lot's participation is finished, win or lose.
_TERMINAL = {"won", "lost"}

#: Stages that mean active sourcing/pricing work is underway.
_ACTIVE = {"sourcing", "priced"}


def derive(lot_stages: list[str]) -> str:
	"""Map a parent tender's child-lot funnel stages to one board lane.

	``lot_stages``: outputs of `_funnel.classify` for each child lot —
	seen|go|sourcing|priced|submitted|won|lost.

	Priority, first match wins:
	  1. no lots at all                          -> Preparation
	  2. every lot terminal (won/lost)            -> Completed
	  3. some terminal, some not                  -> Partial Result
	  4. no terminal but >=1 submitted            -> Awaiting Result
	  5. >=1 lot sourcing or priced                -> Active
	  6. otherwise (seen/go)                       -> Preparation

	An unknown/malformed stage is NOT ignored — it is treated as a
	non-terminal, non-submitted, non-active lot, i.e. it degrades toward
	Preparation rather than inventing progress. So ["won", "zzz"] is a
	Partial Result (one terminal, one not), while ["zzz"] alone is
	Preparation (nothing terminal, submitted, or active was recognised).
	This mirrors `_funnel.classify`'s own rule: when in doubt, undercount.
	"""
	if not lot_stages:
		return "Preparation"

	terminal_count = sum(1 for stage in lot_stages if stage in _TERMINAL)
	if terminal_count == len(lot_stages):
		return "Completed"
	if terminal_count > 0:
		return "Partial Result"
	if any(stage == "submitted" for stage in lot_stages):
		return "Awaiting Result"
	if any(stage in _ACTIVE for stage in lot_stages):
		return "Active"
	return "Preparation"
