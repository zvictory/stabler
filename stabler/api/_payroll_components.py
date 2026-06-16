"""Pure payroll component-mapping helpers for Stabler HR.

No Frappe dependency — runs under plain ``python -m unittest``.

Bridges the Stabler Payroll Attendance Summary (PAS) to ERPNext
Additional Salary rows.  The caller (service layer) is responsible
for hydrating a PAS dict from the doctype and persisting the returned
rows to ``frappe.get_doc("Additional Salary", ...)``.

Rounding rule: whole UZS, round-half-up, applied ONCE at the point
the PAS amount is emitted.  Never round per-component twice.
"""

from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# 1. Canonical quantity keys + default sign map
# ---------------------------------------------------------------------------

#: Ordered list of quantity keys this module understands.
QUANTITY_KEYS: list[str] = [
	"late_deduction",
	"overtime",
	"night_premium",
	"duty_supplement",
	"kpi",
	"region_rate",
]

#: Default component_type for each key.
#: "kpi" is sign-dependent — the helper overrides it at runtime.
DEFAULT_SIGN_MAP: dict[str, str] = {
	"late_deduction":  "Deduction",
	"overtime":        "Earning",
	"night_premium":   "Earning",
	"duty_supplement": "Earning",
	"kpi":             "Earning",   # overridden when kpi_adjustment < 0
	"region_rate":     "Earning",
}

# Maps each QUANTITY_KEY → the PAS field that carries its currency amount.
_AMOUNT_FIELD: dict[str, str] = {
	"late_deduction":  "late_deduction_amount",
	"overtime":        "overtime_amount",
	"night_premium":   "night_premium_amount",
	"duty_supplement": "duty_supplement",
	"kpi":             "kpi_adjustment",
	"region_rate":     "region_rate",
}


# ---------------------------------------------------------------------------
# 2. summary_to_components
# ---------------------------------------------------------------------------

def summary_to_components(
	summary: dict,
	component_map: dict,
) -> list[dict]:
	"""Map a Payroll Attendance Summary dict to Additional Salary line dicts.

	Args:
		summary:
			Dict matching the ``Stabler Payroll Attendance Summary`` fields.
			The following amount fields are read:
			  ``late_deduction_amount``, ``overtime_amount``,
			  ``night_premium_amount``, ``duty_supplement``,
			  ``kpi_adjustment``, ``region_rate``.
		component_map:
			Maps each quantity key → ``{"salary_component": str,
			"component_type": "Earning"|"Deduction"}``.
			An unmapped key is skipped with a ``"warning"`` in the output.

	Returns:
		A list of dicts, one per non-zero quantity, deterministically ordered
		by ``QUANTITY_KEYS``::

			{
			    "quantity":         str,          # e.g. "overtime"
			    "salary_component": str | None,   # None when unmapped
			    "amount":           float,         # signed (Deduction is negative)
			    "abs_amount":       float,         # always positive, whole UZS
			    "component_type":   str | None,    # "Earning" | "Deduction" | None
			    "warning":          str | None,    # set when salary_component is None
			}

	KPI sign rule:
		If ``kpi_adjustment`` < 0 → component_type = "Deduction", abs_amount is
		the absolute value.  If ≥ 0 → component_type = "Earning".
		The caller's ``component_map`` entry for "kpi" may specify the type, but
		the sign derived from the PAS value always takes precedence.

	Zero amounts (including None) are silently skipped.
	"""
	if not isinstance(summary, dict):
		summary = {}
	if not isinstance(component_map, dict):
		component_map = {}

	lines: list[dict] = []

	for key in QUANTITY_KEYS:
		field = _AMOUNT_FIELD[key]
		raw = summary.get(field)
		if raw is None:
			continue

		raw_float = float(raw)
		if raw_float == 0.0:
			continue

		# Determine component_type, honouring KPI sign rule
		if key == "kpi":
			component_type_resolved = "Deduction" if raw_float < 0 else "Earning"
		else:
			component_type_resolved = DEFAULT_SIGN_MAP[key]

		# Round to whole UZS (round-half-up)
		abs_amount = float(math.floor(abs(raw_float) + 0.5))

		# Lookup in caller-supplied map
		mapping = component_map.get(key)
		if mapping and isinstance(mapping, dict):
			salary_component = mapping.get("salary_component")
			# Allow caller to override component_type (except KPI sign rule)
			if key != "kpi":
				component_type_resolved = mapping.get("component_type", component_type_resolved)
			warning = None
		else:
			salary_component = None
			warning = (
				f"No salary component mapped for '{key}'. "
				"Add an entry to the component map before generating Additional Salaries."
			)

		lines.append({
			"quantity":         key,
			"salary_component": salary_component,
			"amount":           raw_float,
			"abs_amount":       abs_amount,
			"component_type":   component_type_resolved if salary_component is not None else None,
			"warning":          warning,
		})

	return lines


# ---------------------------------------------------------------------------
# 3. components_total
# ---------------------------------------------------------------------------

def components_total(lines: list[dict]) -> dict:
	"""Aggregate a list of component lines into earnings / deductions / net.

	Args:
		lines: as returned by ``summary_to_components``.

	Returns::

		{"earnings": float, "deductions": float, "net": float}

	All values are whole UZS.  Net = earnings − deductions.
	Warning-only lines (``salary_component`` is None) are still counted so the
	caller can compute a tentative total even before the map is complete.
	"""
	earnings: float = 0.0
	deductions: float = 0.0

	for line in lines:
		ctype = line.get("component_type")
		abs_amount = float(line.get("abs_amount") or 0)
		if ctype == "Earning":
			earnings += abs_amount
		elif ctype == "Deduction":
			deductions += abs_amount

	return {
		"earnings":   float(math.floor(earnings + 0.5)),
		"deductions": float(math.floor(deductions + 0.5)),
		"net":        float(math.floor((earnings - deductions) + 0.5)),
	}


# ---------------------------------------------------------------------------
# 4. slip_variance
# ---------------------------------------------------------------------------

_VARIANCE_TOLERANCE_UZS: float = 1000.0  # D12 parallel-run gate


def slip_variance(summary_net: float, slip_net: float) -> dict:
	"""Compare a PAS-derived net against an ERPNext Salary Slip net.

	Args:
		summary_net: net computed from the PAS (earnings − deductions), UZS.
		slip_net:    net from the ERPNext Salary Slip, UZS.

	Returns::

		{
		    "variance":         float,  # slip_net − summary_net
		    "within_tolerance": bool,   # abs(variance) <= 1000 UZS
		}

	Tolerance is ±1 000 UZS per decision D12.
	"""
	variance = float(slip_net) - float(summary_net)
	return {
		"variance":         variance,
		"within_tolerance": abs(variance) <= _VARIANCE_TOLERANCE_UZS,
	}


# ---------------------------------------------------------------------------
# 5. mapping_complete
# ---------------------------------------------------------------------------

def mapping_complete(summary: dict, component_map: dict) -> list[str]:
	"""Return quantity keys that are non-zero on the summary but have no mapping.

	The API layer can call this before allowing slip generation; if the list is
	non-empty it should surface an error and block until every key is mapped.

	Args:
		summary:       PAS dict (same as ``summary_to_components``).
		component_map: same as ``summary_to_components``.

	Returns:
		List of quantity key strings (subset of ``QUANTITY_KEYS``) that are
		non-zero in the summary but absent (or invalid) in ``component_map``.
		An empty list means the map is complete for this summary.
	"""
	if not isinstance(summary, dict):
		summary = {}
	if not isinstance(component_map, dict):
		component_map = {}

	missing: list[str] = []
	for key in QUANTITY_KEYS:
		field = _AMOUNT_FIELD[key]
		raw = summary.get(field)
		if raw is None:
			continue
		if float(raw) == 0.0:
			continue
		mapping = component_map.get(key)
		if not (mapping and isinstance(mapping, dict) and mapping.get("salary_component")):
			missing.append(key)

	return missing
