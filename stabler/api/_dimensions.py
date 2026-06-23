"""Pure dimensional-quantity math for line items — no frappe, unit-testable.

Some items are sold/bought by measured size rather than a fixed UOM: industrial
belt/fabric by area (m²), pipe/profile by length (m), foam/timber by volume (m³).
The user enters length/width/height/pieces on the line and the BILLABLE stock
quantity (in the item's stock UOM = m / m² / m³) is computed here. Rate is per
that stock UOM, so amount = qty × rate and ERPNext's stock/valuation/GL stay
consistent — the dimensions are just a calculator that fills `qty`.

Item.custom_dimension_mode drives it:
  ""        → not dimensional (use the entered qty as-is; ice-cream-style items)
  "Linear"  → qty = length × pieces                  (UOM m)
  "Area"    → qty = length × width × pieces           (UOM m²)
  "Volume"  → qty = length × width × height × pieces  (UOM m³)
"""

from __future__ import annotations

DIMENSION_MODES = ("", "Linear", "Area", "Volume")


def is_dimensional(mode) -> bool:
	return mode in ("Linear", "Area", "Volume")


def _f(v, default=0.0) -> float:
	if v in (None, ""):
		return default
	try:
		return float(v)
	except (TypeError, ValueError):
		return default


def dimensional_qty(mode, length=None, width=None, height=None, pieces=None) -> float | None:
	"""Stock quantity from measurements. Returns None when the item is not
	dimensional (caller keeps the manually-entered qty). Rounds to 6 dp."""
	if not is_dimensional(mode):
		return None
	length_v = _f(length)
	width_v = _f(width)
	height_v = _f(height)
	# A blank pieces means a single piece; an explicit 0 means nothing.
	pieces_v = 1.0 if pieces in (None, "") else _f(pieces)

	if mode == "Linear":
		qty = length_v * pieces_v
	elif mode == "Area":
		qty = length_v * width_v * pieces_v
	else:  # Volume
		qty = length_v * width_v * height_v * pieces_v
	return round(qty, 6)


def dimension_summary(mode, length=None, width=None, height=None, pieces=None) -> str:
	"""Human-readable "2.5 × 0.3 × 10 pcs" string for prints/exports."""
	if not is_dimensional(mode):
		return ""
	parts = []
	if mode in ("Linear", "Area", "Volume"):
		parts.append(_trim(length))
	if mode in ("Area", "Volume"):
		parts.append(_trim(width))
	if mode == "Volume":
		parts.append(_trim(height))
	dims = " × ".join(p for p in parts if p)
	pcs = pieces if pieces not in (None, "") else 1
	return f"{dims} × {_trim(pcs)} pcs" if dims else ""


def _trim(v) -> str:
	f = _f(v)
	s = f"{f:.6f}".rstrip("0").rstrip(".")
	return s or "0"
