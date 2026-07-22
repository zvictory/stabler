from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping


def aggregate_container_items(rows: Iterable[Mapping[str, object]]) -> list[dict]:
	agg: dict[str, dict] = defaultdict(lambda: {"item_name": "", "boxes": 0, "kg": 0.0})
	for row in rows:
		item = str(row.get("item_code") or "").strip()
		if not item:
			continue
		entry = agg[item]
		entry["item_name"] = entry["item_name"] or str(row.get("item_name") or item)
		entry["boxes"] += int(row.get("box_qty") or 0)
		entry["kg"] += float(row.get("total_kg") or 0)
	return [{
		"item_code": item,
		"item_name": values["item_name"],
		"expected_boxes": values["boxes"],
		"expected_box_kg": round(values["kg"] / values["boxes"], 3) if values["boxes"] else 0.0,
		"expected_total_kg": round(values["kg"], 3),
	} for item, values in sorted(agg.items())]


def reconcile_ci_items(ci_rows: Iterable[Mapping[str, object]], packed_rows: Iterable[Mapping[str, object]]) -> list[dict]:
	ci = {str(row.get("item_code") or row.get("item") or ""): float(row.get("qty") or 0) for row in ci_rows}
	packed = {str(row.get("item_code") or ""): float(row.get("expected_total_kg") or 0) for row in packed_rows}
	return [{"item_code": item, "ci_kg": round(ci.get(item, 0), 3), "packed_kg": round(packed.get(item, 0), 3), "difference_kg": round(packed.get(item, 0) - ci.get(item, 0), 3), "matches": abs(packed.get(item, 0) - ci.get(item, 0)) <= 0.01} for item in sorted(set(ci) | set(packed))]


def packing_readiness(container_names: Iterable[str], containers_with_rows: Iterable[str], reconciliation: Iterable[Mapping[str, object]]) -> str:
	names = set(container_names)
	if not names or not names.issubset(set(containers_with_rows)):
		return "Incomplete"
	return "Ready" if all(bool(row.get("matches")) for row in reconciliation) else "Mismatch"
