"""Origin marking for a Work Order's consumed inputs. No frappe import.

`wo_genealogy` reads what an order consumed. What it cannot read is which
earlier order produced each input, because at anjan no batch has ever been
recorded: 0 of 23 851 material-transfer rows carry a `batch_no`, and 0 of 3 789
submitted orders carry a `custom_batch_no` (measured 2026-08-28).

The structure is nonetheless real — 23 848 of those rows are sourced from a
warehouse some order produces into — so the panel can say *that* an input was
made in-house, and how many orders could have made it, without ever naming one.
Naming one would take a mean of 14.9 candidates (max 171) and pick by date; the
result would look identical to a resolved chain and would be read during a
recall.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def annotate_consumed_origin(
	consumed: list[dict[str, Any]],
	production_warehouses: Iterable[str],
	producer_candidates: dict[str, int],
) -> list[dict[str, Any]]:
	"""Add ``from_production`` and ``producer_candidates`` to each consumed row.

	Never adds a parent order — see the module docstring, and
	``test_a_single_candidate_is_still_not_named``.
	"""
	produced_in = {w for w in production_warehouses if w}
	out = []
	for row in consumed:
		warehouse = row.get("warehouse")
		out.append(
			{
				**row,
				"from_production": bool(warehouse) and warehouse in produced_in,
				"producer_candidates": int(producer_candidates.get(row.get("item_code"), 0)),
			}
		)
	return out
