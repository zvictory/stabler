"""Vehicle Agreement restructure chain — pure position maths (stabler-vjfd).

Frappe-free by construction, the same contract as `work_policy`: every function
here is a total function of its arguments, so the chain maths is testable
without a bench, a site or a database. The frappe-dependent half — reading
`restructured_from` out of the table — lives in `read.py`.

Why this exists at all: the ADR
`docs/decisions/2026-08-16-restructure-closes-and-reopens.md` settles that a
restructure CLOSES the original agreement and OPENS a successor. That keeps the
audit trail intact, but only if the history is visible where people work. The
condition of the owner's vote was that the work queue and the agreement list
show the chain position AT A GLANCE — `3/3 · restructured twice` — because
otherwise you still have to go hunting for the last closed agreement to learn
the history, which is the very problem the decision was chosen to solve.

The chain is a linked list stored backwards: each agreement carries a link to
its predecessor and nothing else. A stored successor field would need two
writes to stay consistent, and the pair would eventually disagree.

Two invariants this module protects:

1. **Every member of a chain reports the same length.** Position differs, length
   and restructure count do not. So the answer to "how many times was this
   restructured" is the same whether you are looking at the closed original or
   at the live successor — that is what makes the number objective rather than
   a tab nobody opens.
2. **Malformed data degrades, it does not hang.** A predecessor outside the
   input is read as a chain root, and a cycle terminates. Neither is expected;
   both are cheaper to absorb than to crash a work queue over.
"""

from __future__ import annotations

from collections.abc import Mapping

# What an agreement that was never restructured looks like. Also the honest
# fallback when a name is missing from the map: one agreement, no history.
SOLE_AGREEMENT = {"chain_position": 1, "chain_length": 1, "restructure_count": 0}


def positions(predecessor_by_name: Mapping[str, str | None]) -> dict[str, dict]:
	"""Chain position, length and restructure count for every named agreement.

	`predecessor_by_name` maps an agreement name to its `restructured_from`, or
	to `None` when it starts a chain. The caller is responsible for passing a
	CLOSED set — every agreement in the chains of interest, not just the page
	being rendered — otherwise a chain is silently reported as shorter than it
	is. `read._chain_positions` walks the table in both directions to guarantee
	that closure.

	A predecessor that is not itself a key is treated as a root: that is what a
	cancelled predecessor looks like once it is filtered out, and a cancelled
	agreement is not part of the history.
	"""
	known = set(predecessor_by_name)

	# Undirected adjacency: chain length is the size of the connected component,
	# which stays right even if bad data ever forks a chain into two successors.
	adjacent: dict[str, set[str]] = {name: set() for name in known}
	for name, predecessor in predecessor_by_name.items():
		if predecessor and predecessor in known:
			adjacent[name].add(predecessor)
			adjacent[predecessor].add(name)

	component_of: dict[str, int] = {}
	component_sizes: list[int] = []
	for name in sorted(known):
		if name in component_of:
			continue
		index = len(component_sizes)
		component_of[name] = index
		stack = [name]
		size = 0
		while stack:
			current = stack.pop()
			size += 1
			for neighbour in adjacent[current]:
				if neighbour not in component_of:
					component_of[neighbour] = index
					stack.append(neighbour)
		component_sizes.append(size)

	result: dict[str, dict] = {}
	for name in known:
		# Walk back to the root. `seen` is the cycle guard, not an optimisation.
		seen = {name}
		cursor = predecessor_by_name[name]
		depth = 0
		while cursor and cursor in known and cursor not in seen:
			seen.add(cursor)
			depth += 1
			cursor = predecessor_by_name[cursor]
		length = component_sizes[component_of[name]]
		result[name] = {
			"chain_position": depth + 1,
			"chain_length": length,
			"restructure_count": length - 1,
		}
	return result
