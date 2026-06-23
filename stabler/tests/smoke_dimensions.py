"""Live smoke test for dimensional-pricing (Sales).

Run on a local bench WITHOUT leaving any data behind (everything is rolled back):

    bench --site <your-local-site> execute stabler.tests.smoke_dimensions.run

It proves, against the real DB + the real before_validate hook:
  1. A dimensional item (Area) computes qty = length × width × pieces (m²),
     overriding whatever qty was sent.
  2. A normal item (blank dimension mode = ice-cream Korobka/adet) is left
     completely untouched — qty stays exactly as entered.
  3. Both can live on the SAME order, each behaving on its own.

Safe to run repeatedly: it creates throwaway items, asserts, then rolls back.
"""

import frappe

from stabler.api.dimensions_hook import apply_dimensional_qty
from stabler.patches.v23_item_dimension_fields import execute as ensure_fields


def _pick_item_group():
	return (
		frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		or frappe.db.get_value("Item Group", {}, "name")
		or "All Item Groups"
	)


def _pick_uom():
	# Prefer standard ERPNext "Nos"; fall back to whatever the bench has.
	for candidate in ("Nos", "Dona", "Unit", "No", "Piece"):
		if frappe.db.exists("UOM", candidate):
			return candidate
	first = frappe.db.get_value("UOM", {}, "name")
	return first or "Nos"


def _make_item(code, mode):
	if frappe.db.exists("Item", code):
		frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
	doc = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_name": code,
			"item_group": _pick_item_group(),
			"stock_uom": _pick_uom(),
			"is_stock_item": 0,
			"custom_dimension_mode": mode,
		}
	).insert(ignore_permissions=True)
	return doc.name


def run():
	results = []

	def check(label, got, exp):
		ok = abs(float(got) - float(exp)) < 1e-9
		results.append((ok, label, got, exp))

	# Make sure the custom fields exist (no-op if migrate already ran).
	ensure_fields()

	belt = _make_item("ZZ-SMOKE-BELT", "Area")
	cream = _make_item("ZZ-SMOKE-CREAM", "")  # blank = normal ice-cream item

	# Build an in-memory Sales Order with BOTH kinds of line. We never insert it
	# (no customer/warehouse needed) — we call the hook directly, as ERPNext does
	# on before_validate.
	so = frappe.new_doc("Sales Order")
	so.append(
		"items",
		{
			"item_code": belt,
			"custom_length": 2.5,
			"custom_width": 0.3,
			"custom_pieces": 10,
			"qty": 999,  # deliberately wrong — hook must override to 7.5
		},
	)
	so.append(
		"items",
		{
			"item_code": cream,
			"qty": 5,  # ice-cream: must stay 5, untouched
		},
	)

	apply_dimensional_qty(so)

	check("belt qty = 2.5 x 0.3 x 10 (m2)", so.items[0].qty, 7.5)
	check("ice-cream qty untouched", so.items[1].qty, 5)

	# A dimensional line with NO measurements entered must also be left alone.
	so2 = frappe.new_doc("Sales Order")
	so2.append("items", {"item_code": belt, "qty": 42})  # no length/width
	apply_dimensional_qty(so2)
	check("belt w/o measurements untouched", so2.items[0].qty, 42)

	frappe.db.rollback()  # leave the DB exactly as we found it

	print("\n=== dimensional-pricing smoke ===")
	all_ok = True
	for ok, label, got, exp in results:
		all_ok = all_ok and ok
		print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got} expected={exp}")
	print(f"=== {'ALL PASS' if all_ok else 'FAILURES PRESENT'} ===\n")
	return all_ok
