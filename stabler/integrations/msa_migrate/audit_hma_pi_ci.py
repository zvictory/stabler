"""Detailed line-by-line audit of all HMA AGRO INDUSTRIES LIMITED PIs and CIs vs Google Sheet references."""

import json
import os

import frappe

from .ci_backfill import _load_rows as load_ci_rows
from .pi_ref_backfill import PI_ROWS


def run():
	ci_ref_rows = load_ci_rows()
	pi_ref_rows = PI_ROWS

	# 1. HMA Proforma Invoices
	hma_pi_refs = [
		r
		for r in pi_ref_rows
		if "HMA" in (r.get("vendor") or "").upper() or "HMA" in (r.get("ref") or "").upper()
	]

	db_pis = frappe.get_all(
		"Proforma Invoice",
		filters={"supplier": ["like", "%HMA%"]},
		fields=["name", "supplier", "supplier_pi_ref", "pi_date", "agreed_total", "docs_total", "status"],
	)
	if not db_pis:
		db_pis = frappe.get_all(
			"Proforma Invoice",
			fields=["name", "supplier", "supplier_pi_ref", "pi_date", "agreed_total", "docs_total", "status"],
		)
		db_pis = [
			p
			for p in db_pis
			if "HMA" in (p.supplier or "").upper() or "HMA" in (p.supplier_pi_ref or "").upper()
		]

	db_pi_by_ref = {p.supplier_pi_ref: p for p in db_pis if p.supplier_pi_ref}
	db_pi_by_tot = {round(float(p.agreed_total or 0), 2): p for p in db_pis}

	pi_audit = []
	for ref_pi in hma_pi_refs:
		ref_num = ref_pi["ref"]
		ref_ag = round(float(ref_pi["agreed_total"]), 2)
		ref_dc = round(float(ref_pi["docs_total"]), 2)

		matched = db_pi_by_ref.get(ref_num) or db_pi_by_tot.get(ref_ag)

		db_name = matched.name if matched else "❌ NOT IN DB"
		db_orig_ref = matched.supplier_pi_ref if matched else "—"
		db_ag = float(matched.agreed_total or 0) if matched else 0.0
		db_dc = float(matched.docs_total or 0) if matched else 0.0

		is_ok = (
			matched and abs(db_ag - ref_ag) <= 0.01 and abs(db_dc - ref_dc) <= 0.01 and db_orig_ref == ref_num
		)

		pi_audit.append(
			{
				"ref_num": ref_num,
				"date": ref_pi["date"],
				"db_name": db_name,
				"db_orig_ref": db_orig_ref,
				"ref_ag": ref_ag,
				"db_ag": db_ag,
				"ref_dc": ref_dc,
				"db_dc": db_dc,
				"is_ok": is_ok,
			}
		)

	# 2. HMA Commercial Invoices
	hma_ci_refs = [
		r
		for r in ci_ref_rows
		if "HMA" in (r.get("vendor") or "").upper() or "HMA" in (r.get("ci_number") or "").upper()
	]

	db_cis = frappe.get_all(
		"Commercial Invoice",
		filters={"supplier": ["like", "%HMA%"]},
		fields=[
			"name",
			"ci_number",
			"supplier",
			"ci_date",
			"agreed_total",
			"docs_total",
			"cash_difference",
			"status",
		],
	)

	db_ci_by_cin = {c.ci_number: c for c in db_cis if c.ci_number}

	ci_audit = []
	discrepant_cis = []

	for ref_ci in hma_ci_refs:
		cin = ref_ci["ci_number"]
		ref_ag = round(float(ref_ci.get("agreed_total") or 0), 2)
		ref_dc = round(float(ref_ci.get("docs_total") or 0), 2)
		ref_cd = round(float(ref_ci.get("cash_difference") or 0), 2)

		matched = db_ci_by_cin.get(cin)

		db_name = matched.name if matched else "❌ NOT IN DB"
		db_ag = float(matched.agreed_total or 0) if matched else 0.0
		db_dc = float(matched.docs_total or 0) if matched else 0.0
		db_cd = float(matched.cash_difference or 0) if matched else 0.0

		is_ok = matched and abs(db_ag - ref_ag) <= 0.01 and abs(db_dc - ref_dc) <= 0.01

		item = {
			"ci_number": cin,
			"date": ref_ci.get("ci_date"),
			"db_name": db_name,
			"ref_ag": ref_ag,
			"db_ag": db_ag,
			"diff_ag": db_ag - ref_ag,
			"ref_dc": ref_dc,
			"db_dc": db_dc,
			"ref_cd": ref_cd,
			"db_cd": db_cd,
			"is_ok": is_ok,
		}
		ci_audit.append(item)
		if not is_ok:
			discrepant_cis.append(item)

	print("\n=========================================================================")
	print("  HMA AGRO INDUSTRIES LIMITED - FULL PI & CI AUDIT REPORT")
	print("=========================================================================")
	print(
		f"HMA Proforma Invoices (PI): Total Ref = {len(hma_pi_refs)} | 100% OK = {len([p for p in pi_audit if p['is_ok']])}"
	)
	print(
		f"HMA Commercial Invoices (CI): Total Ref = {len(hma_ci_refs)} | 100% OK = {len([c for c in ci_audit if c['is_ok']])} | Discrepancies = {len(discrepant_cis)}\n"
	)

	return {"pi_audit": pi_audit, "ci_audit": ci_audit, "discrepant_cis": discrepant_cis}
