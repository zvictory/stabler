"""Pure geo helpers for outlet GPS entry — no frappe, no DB (unit-testable).

Used by stabler.api.sfa to validate single coordinate writes and to resolve a
pasted/CSV bulk batch of (identifier, lat, lng) rows against the company's
outlets before writing.
"""

from __future__ import annotations


class GeoError(ValueError):
	"""Raised for an invalid coordinate, carrying a human-readable message."""


def to_number(value) -> float:
	"""Parse a coordinate that may arrive as float, int, or string. Accepts a
	comma decimal separator ("41,3111") since field users paste localized values."""
	if value is None or value == "":
		raise GeoError("empty value")
	if isinstance(value, (int, float)):
		return float(value)
	s = str(value).strip().replace(" ", "")
	# Only treat comma as a decimal separator when there's no dot already.
	if "," in s and "." not in s:
		s = s.replace(",", ".")
	try:
		return float(s)
	except ValueError:
		raise GeoError(f"not a number: {value!r}")


def parse_coord_pair(lat_raw, lng_raw) -> tuple[float, float]:
	"""Return (lat, lng) as floats rounded to 7 dp, or raise GeoError.

	Rejects out-of-range values and the null-island (0, 0) point, which is almost
	always an empty/placeholder coordinate rather than a real venue.
	"""
	lat = to_number(lat_raw)
	lng = to_number(lng_raw)
	if not (-90.0 <= lat <= 90.0):
		raise GeoError(f"latitude out of range: {lat}")
	if not (-180.0 <= lng <= 180.0):
		raise GeoError(f"longitude out of range: {lng}")
	if lat == 0.0 and lng == 0.0:
		raise GeoError("zero coordinates (0, 0)")
	return round(lat, 7), round(lng, 7)


def norm_key(value) -> str:
	return str(value or "").strip().casefold()


def _identifier(row: dict):
	for field in ("outlet", "name", "outlet_code", "code", "outlet_name"):
		val = row.get(field)
		if val not in (None, ""):
			return val
	return None


def resolve_bulk(rows, by_name: dict, by_code: dict, by_oname: dict):
	"""Match each row to an outlet and validate its coordinates.

	`by_name`/`by_code`/`by_oname` map norm_key(value) → outlet docname. An
	identifier is tried against docname, then outlet_code, then outlet_name.

	Returns (updates, errors):
	  updates: [{"outlet": <docname>, "lat": float, "lng": float}]
	  errors:  [{"row": <1-based idx>, "identifier": <raw>, "reason": <str>}]
	Duplicate identifiers within the batch keep the LAST occurrence (later rows
	win) and are not reported as errors.
	"""
	updates_by_outlet: dict[str, dict] = {}
	errors: list[dict] = []
	for idx, row in enumerate(rows or [], start=1):
		if not isinstance(row, dict):
			errors.append({"row": idx, "identifier": None, "reason": "row is not an object"})
			continue
		ident = _identifier(row)
		if ident is None:
			errors.append({"row": idx, "identifier": None, "reason": "missing outlet identifier"})
			continue
		key = norm_key(ident)
		outlet = by_name.get(key) or by_code.get(key) or by_oname.get(key)
		if not outlet:
			errors.append({"row": idx, "identifier": ident, "reason": "outlet not found in company"})
			continue
		try:
			lat, lng = parse_coord_pair(
				row.get("lat", row.get("latitude")), row.get("lng", row.get("longitude"))
			)
		except GeoError as exc:
			errors.append({"row": idx, "identifier": ident, "reason": str(exc)})
			continue
		updates_by_outlet[outlet] = {"outlet": outlet, "lat": lat, "lng": lng}
	return list(updates_by_outlet.values()), errors
