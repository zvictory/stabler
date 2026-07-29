# ruff: noqa
"""MSA vendor payment history import — real dates, running supplier ledger.

Source: «Оплаты заводам HMA, FAIR, MIRHA, IFF _ PI» — normalized to
IMPORT_msa_vendor_payments.csv (394 rows, 2025-01-05 → 2026-07-23, Bank+Cash).

Design decisions (approved by the owner, 2026-07-29):
- ONE company (MSA). The two buyer entities in the workbook are ours; the
  separation lives in the CoA (channel/bank accounts), not in companies.
- Vendor-focused, PI labels ride along as remarks only.
- EVERY payment is entered on its REAL date (CBU rate of that day) — the
  Vendor Center supplier_ledger then shows debit/credit/running balance.
- Credit side: historical CIs become Purchase Invoices dated ci_date, so the
  running balance nets to the true remainder.
- Container status is IGNORED (historical data entry).
- FY2025 must exist; ensure_fiscal_years() creates it if missing.

Usage (bench console on msa, run phases IN ORDER, each dry-run first):

    exec(open("/tmp/IMPORT_msa_vendor_history.py").read())
    audit()                      # read-only; fill SUPPLIER_MAP after
    ensure_fiscal_years()        # writes only if FY missing
    ensure_accounts(dry_run=1)   # CoA scan → plan → approval → dry_run=0
    import_payments(dry_run=1)   # plan → approval → dry_run=0
    convert_cis(dry_run=1)       # plan → approval → dry_run=0
    reconcile(dry_run=1)         # plan → approval → dry_run=0
    compare()                    # ledger vs Excel targets — the honest table

NOTE: each new console session resets the resolved ACCOUNTS globals — any
session that runs import_payments must call ensure_accounts(dry_run=0)
first (idempotent: it only re-finds, creates nothing the second time).

Idempotent: PEs are keyed by reference_no (XLS-…); re-running skips existing.
CI→PInv reuses the WP-I5 endpoint (already idempotent per CI).
"""

import csv
import os
from collections import defaultdict

import frappe
from frappe.utils import flt, getdate

# ---------------------------------------------------------------- CONFIG ----
COMPANY = "MSA"
CSV_PATH = "/tmp/IMPORT_msa_vendor_payments.csv"

# Excel name -> Supplier docname on msa. audit() prints candidates; FILL THESE
# before any write phase (None aborts).
SUPPLIER_MAP = {
	"HMA AGRO INDUSTRIES LIMITED": None,
	"FAIR EXPORTS (INDIA) PVT. LTD.": None,
	"Mirha Exports Private limited": None,
	"IFF India Frozen Foods Private Limited": None,
	"AL-SUPER FROZEN FOODS PVT. LTD": None,
	"AL-DUA": None,
}

# paid_from account per channel. DO NOT hand-fill: ensure_accounts() resolves
# these from the company's existing CoA (and creates USD accounts only when
# nothing suitable exists), then prints the resolution for approval.
ACCOUNTS = {"Bank": None, "Cash": None}
BANK_OVERRIDES = {}  # bank_label → account, resolved by ensure_accounts()

# What ensure_accounts() looks for / creates. Matching is by token in the
# existing account name (case-insensitive), USD accounts preferred.
ACCOUNT_RULES = [
	# (slot, token, account_type, create_name if nothing matches)
	("BANK_OVERRIDES:NBU BANK", "NBU", "Bank", "NBU USD"),
	("BANK_OVERRIDES:ALOQA BANK", "ALOQA", "Bank", "Aloqa USD"),
	("ACCOUNTS:Bank", "BANK", "Bank", "Bank USD"),
	("ACCOUNTS:Cash", "KASSA", "Cash", "Kassa USD"),
]

# Vendor summary blocks from the workbook — compare() prints ledger vs these.
# paid_* are the itemized sums (ground truth we import); summary_* are the
# sheet's own header figures; ostatok_* are the sheet's stated remainders.
TARGETS = {
	"HMA AGRO INDUSTRIES LIMITED": {
		"pi_total": 87_051_408.40 + 4_288_200.00,  # main + PBW
		"paid_bank": 72_992_318.81 + 4_120_200.00,
		"paid_cash": 4_916_834.04,
		"ostatok": 9_142_255.54 + 168_000.00,
	},
	"FAIR EXPORTS (INDIA) PVT. LTD.": {
		"pi_total": 12_442_643.99, "paid_bank": 9_360_541.00,
		"paid_cash": 0.0, "ostatok": 3_082_102.99,
	},
	"Mirha Exports Private limited": {
		"pi_total": 16_563_686.80, "paid_bank": 13_859_075.88,
		"paid_cash": 1_236_661.00, "ostatok": 1_467_949.92,
	},
	"IFF India Frozen Foods Private Limited": {
		"pi_total": 2_430_400.00, "paid_bank": 1_944_320.00,
		"paid_cash": 486_296.70,  # itemized; sheet header says 486_079.70 (+217 drift)
		"ostatok": 0.30,
	},
	"AL-SUPER FROZEN FOODS PVT. LTD": {
		"pi_total": 11_037_600.00, "paid_bank": 8_338_400.00,
		# itemized bank is 63 988 BELOW the sheet header (8 402 388) and total
		# 32 612 ABOVE header N — the workbook disagrees with itself; we import
		# the itemized rows and compare() shows both.
		"paid_cash": 197_680.00, "ostatok": 2_437_532.00,
	},
	"AL-DUA": {
		"pi_total": 1_264_230.00, "paid_bank": 242_000.00,
		"paid_cash": 0.0, "ostatok": 1_022_230.00,
	},
}


def _rows():
	if not os.path.exists(CSV_PATH):
		raise SystemExit(f"CSV not found: {CSV_PATH} — scp it to the server first")
	with open(CSV_PATH, encoding="utf-8") as fh:
		return list(csv.DictReader(fh))


def _require_map():
	missing = [k for k, v in SUPPLIER_MAP.items() if not v]
	if missing:
		raise SystemExit(f"SUPPLIER_MAP has unfilled entries: {missing} — run audit() and fill.")
	bad = [v for v in SUPPLIER_MAP.values() if not frappe.db.exists("Supplier", v)]
	if bad:
		raise SystemExit(f"Suppliers not found on this site: {bad}")
	if not ACCOUNTS.get("Bank") or not ACCOUNTS.get("Cash"):
		raise SystemExit("ACCOUNTS Bank/Cash unresolved — run ensure_accounts() first.")


# ---------------------------------------------------------------- PHASE A ----
def audit():
	"""Read-only. Everything the write phases need decided, in one screen."""
	frappe.set_user("Administrator")
	rows = _rows()
	print(f"CSV: {len(rows)} rows, {min(r['posting_date'] for r in rows)} → {max(r['posting_date'] for r in rows)}")

	# fiscal years
	fys = frappe.get_all("Fiscal Year", fields=["name", "year_start_date", "year_end_date", "disabled"])
	print("\n— Fiscal Years:", [(f.name, str(f.year_start_date), str(f.year_end_date), f.disabled) for f in fys])
	for y in ("2025", "2026"):
		if not any(str(f.year_start_date) <= f"{y}-06-01" <= str(f.year_end_date) and not f.disabled for f in fys):
			print(f"  !! no open Fiscal Year covering {y} — ensure_fiscal_years() will create it")

	# supplier candidates
	print("\n— Supplier candidates (fill SUPPLIER_MAP):")
	all_sup = frappe.get_all("Supplier", fields=["name", "supplier_name"], limit_page_length=0)
	for excel in SUPPLIER_MAP:
		toks = [t for t in excel.upper().replace(".", " ").split() if len(t) > 2][:2]
		hits = [s.name for s in all_sup if all(t in (s.supplier_name or s.name).upper() for t in toks)]
		print(f"  {excel!r}: {hits or 'NO MATCH — create the Supplier or map manually'}")

	# candidate USD bank/cash accounts
	accs = frappe.get_all(
		"Account",
		filters={"company": COMPANY, "is_group": 0, "account_type": ["in", ["Bank", "Cash"]]},
		fields=["name", "account_type", "account_currency"],
	)
	print("\n— Bank/Cash accounts (fill ACCOUNTS, USD preferred):")
	for a in accs:
		print(f"  [{a.account_type:4}] {a.name}  ({a.account_currency})")

	# duplicates: our keys + any同-amount-same-day PEs already on the book
	existing = set(
		frappe.get_all(
			"Payment Entry",
			filters={"company": COMPANY, "reference_no": ["like", "XLS-%"], "docstatus": ["<", 2]},
			pluck="reference_no",
		)
	)
	print(f"\n— Existing XLS-keyed PEs: {len(existing)} (these will be skipped)")
	sup_names = [v for v in SUPPLIER_MAP.values() if v]
	if sup_names:
		other = frappe.get_all(
			"Payment Entry",
			filters={"company": COMPANY, "party": ["in", sup_names], "docstatus": ["<", 2]},
			fields=["name", "posting_date", "paid_amount", "reference_no"],
		)
		print(f"— Other PEs already on these suppliers: {len(other)}")
		for pe in other[:20]:
			print(f"    {pe.name} {pe.posting_date} {flt(pe.paid_amount):,.2f} ref={pe.reference_no}")

	# CI side per supplier
	print("\n— Commercial Invoices per supplier (credit side):")
	for excel, sup in SUPPLIER_MAP.items():
		if not sup:
			continue
		cis = frappe.get_all(
			"Commercial Invoice",
			filters={"company": COMPANY, "supplier": sup, "status": ["!=", "Cancelled"]},
			fields=["name", "ci_date", "agreed_total"],
		)
		tot = sum(flt(c.agreed_total) for c in cis)
		no_date = [c.name for c in cis if not c.ci_date]
		tgt = TARGETS.get(excel, {})
		print(
			f"  {sup}: {len(cis)} CI, agreed Σ {tot:,.2f}"
			f"  | Excel PI total {tgt.get('pi_total', 0):,.2f}"
			+ (f"  !! {len(no_date)} CI without ci_date: {no_date[:5]}" if no_date else "")
		)
	print("\naudit done — fill SUPPLIER_MAP + ACCOUNTS, then ensure_fiscal_years().")


def ensure_fiscal_years():
	"""Create missing calendar fiscal years (2025/2026). Idempotent."""
	frappe.set_user("Administrator")
	for y in (2025, 2026):
		covering = frappe.get_all(
			"Fiscal Year",
			filters={"year_start_date": ["<=", f"{y}-06-01"], "year_end_date": [">=", f"{y}-06-01"]},
			pluck="name",
		)
		if covering:
			print(f"FY covering {y}: {covering} — ok")
			continue
		fy = frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": str(y),
				"year_start_date": f"{y}-01-01",
				"year_end_date": f"{y}-12-31",
			}
		)
		fy.insert(ignore_permissions=True)
		print(f"created Fiscal Year {y}")
	frappe.db.commit()


def ensure_accounts(dry_run=1):
	"""Resolve paid_from accounts from the EXISTING CoA; create only what's missing.

	Resolution per ACCOUNT_RULES, in order, against non-group Bank/Cash accounts
	of the company:
	1. name contains the token AND account_currency == USD  → use it
	2. name contains the token (any currency)               → use it (warns if not USD)
	3. nothing matches → CREATE a USD account (create_name) under the parent
	   group of the existing accounts of that type (or the first group account
	   of that type). dry_run=1 only prints the plan.

	Writes the winners into ACCOUNTS / BANK_OVERRIDES (module globals) and
	prints the full resolution table — approve it before import_payments().
	"""
	frappe.set_user("Administrator")
	accs = frappe.get_all(
		"Account",
		filters={"company": COMPANY, "is_group": 0, "account_type": ["in", ["Bank", "Cash"]]},
		fields=["name", "account_type", "account_currency", "parent_account"],
	)

	def find(token, acc_type):
		pool = [a for a in accs if a.account_type == acc_type and token in a.name.upper()]
		usd = [a for a in pool if (a.account_currency or "") == "USD"]
		return (usd or pool or [None])[0]

	def parent_for(acc_type):
		siblings = [a for a in accs if a.account_type == acc_type and a.parent_account]
		if siblings:
			return siblings[0].parent_account
		grp = frappe.get_all(
			"Account",
			filters={"company": COMPANY, "is_group": 1, "account_type": acc_type},
			pluck="name", limit=1,
		)
		return grp[0] if grp else None

	print(f"{'slot':28} {'resolution':44} note")
	for slot, token, acc_type, create_name in ACCOUNT_RULES:
		kind, key = slot.split(":")
		hit = find(token, acc_type)
		note = ""
		if hit:
			chosen = hit.name
			if (hit.account_currency or "") != "USD":
				note = f"!! currency={hit.account_currency or '?'} (not USD) — payments are USD, check"
		else:
			parent = parent_for(acc_type)
			if not parent:
				print(f"{slot:28} {'—':44} !! no {acc_type} group in CoA — STOP, decide manually")
				continue
			chosen = f"{create_name} - {frappe.db.get_value('Company', COMPANY, 'abbr')}"
			note = f"CREATE under {parent}" + (" (dry-run)" if dry_run else "")
			if not dry_run:
				doc = frappe.get_doc(
					{
						"doctype": "Account",
						"company": COMPANY,
						"account_name": create_name,
						"parent_account": parent,
						"account_type": acc_type,
						"account_currency": "USD",
						"is_group": 0,
					}
				)
				doc.insert(ignore_permissions=True)
				chosen = doc.name
				note = f"CREATED under {parent}"
		if kind == "ACCOUNTS":
			ACCOUNTS[key] = chosen
		else:
			BANK_OVERRIDES[key] = chosen
		print(f"{slot:28} {chosen:44} {note}")
	if not dry_run:
		frappe.db.commit()
	print("\nACCOUNTS =", ACCOUNTS)
	print("BANK_OVERRIDES =", BANK_OVERRIDES)
	print("Rule: paid_from = BANK_OVERRIDES[bank_label] or ACCOUNTS[channel]; "
		"paid_to (payable) always comes from the CoA defaults via _apply_pay_accounts.")


# ---------------------------------------------------------------- PHASE B ----
def import_payments(dry_run=1):
	"""394 Payment Entries on their real dates. Idempotent by reference_no."""
	frappe.set_user("Administrator")
	_require_map()
	from stabler.api.money import setup_payment_entry_exchange_rates
	from stabler.stabler.imports_module.hooks import _apply_pay_accounts

	rows = _rows()
	existing = set(
		frappe.get_all(
			"Payment Entry",
			filters={"company": COMPANY, "reference_no": ["like", "XLS-%"], "docstatus": ["<", 2]},
			pluck="reference_no",
		)
	)
	has_stream = frappe.db.has_column("Payment Entry", "custom_payment_stream")

	plan = defaultdict(lambda: [0, 0.0])
	skipped = 0
	created = failed = 0
	for r in rows:
		if r["key"] in existing:
			skipped += 1
			continue
		sup = SUPPLIER_MAP[r["supplier_excel"]]
		amount = flt(r["amount_usd"])
		plan[sup][0] += 1
		plan[sup][1] += amount
		if dry_run:
			continue
		try:
			pe = frappe.new_doc("Payment Entry")
			pe.payment_type = "Pay"
			pe.company = COMPANY
			pe.party_type = "Supplier"
			pe.party = sup
			pe.posting_date = getdate(r["posting_date"])  # REAL date
			pe.paid_amount = amount
			pe.received_amount = amount
			pe.reference_no = r["key"]
			pe.reference_date = getdate(r["posting_date"])
			pe.remarks = f"{r['sheet']} · {r['pi_label']} · {r['bank_label']} · {r['kind']}"
			if has_stream:
				pe.custom_payment_stream = r["channel"]
			_apply_pay_accounts(pe, COMPANY, sup)
			pe.paid_from = BANK_OVERRIDES.get(r["bank_label"]) or ACCOUNTS[r["channel"]]
			setup_payment_entry_exchange_rates(pe)  # CBU rate of the REAL date
			pe.insert(ignore_permissions=True)
			pe.submit()
			created += 1
			if created % 50 == 0:
				print(f"  … {created} submitted")
		except Exception as e:
			failed += 1
			print(f"  FAIL {r['key']}: {e}")
			frappe.db.rollback()

	print(("PLAN (dry-run)" if dry_run else "DONE") + f" — skipped(existing)={skipped}")
	for sup, (n, tot) in sorted(plan.items()):
		print(f"  {sup}: {n} PE, Σ {tot:,.2f} USD")
	if not dry_run:
		print(f"created+submitted={created} failed={failed}")
		frappe.db.commit()


# ---------------------------------------------------------------- PHASE C ----
def convert_cis(dry_run=1):
	"""Historical CIs → submitted Purchase Invoices dated ci_date.

	Reuses convert_ci_to_purchase_invoice (idempotent, agreed_total guard),
	then re-dates the draft to ci_date and submits. CIs whose lines don't
	reconcile to agreed_total are LISTED, not forced."""
	frappe.set_user("Administrator")
	_require_map()
	from stabler.api.imports import convert_ci_to_purchase_invoice

	exceptions = []
	done = already = 0
	for excel, sup in SUPPLIER_MAP.items():
		cis = frappe.get_all(
			"Commercial Invoice",
			filters={"company": COMPANY, "supplier": sup, "status": ["!=", "Cancelled"]},
			fields=["name", "ci_date", "agreed_total"],
			order_by="ci_date asc",
		)
		print(f"\n{sup}: {len(cis)} CI")
		for c in cis:
			try:
				prev = convert_ci_to_purchase_invoice(c.name, COMPANY, dry_run=1)
				if prev.get("already_linked"):
					already += 1
					continue
				if not prev.get("reconciles_agreed"):
					exceptions.append((c.name, "lines != agreed_total", prev.get("lines_total"), c.agreed_total))
					continue
				if not c.ci_date:
					exceptions.append((c.name, "no ci_date", None, None))
					continue
				if dry_run:
					done += 1
					continue
				res = convert_ci_to_purchase_invoice(c.name, COMPANY, dry_run=0)
				pinv = frappe.get_doc("Purchase Invoice", res["purchase_invoice"])
				pinv.set_posting_time = 1
				pinv.posting_date = getdate(c.ci_date)  # REAL date
				pinv.bill_date = getdate(c.ci_date)
				pinv.bill_no = pinv.bill_no or c.name
				pinv.save(ignore_permissions=True)
				pinv.submit()
				done += 1
				if done % 25 == 0:
					print(f"  … {done} submitted")
			except Exception as e:
				exceptions.append((c.name, str(e)[:120], None, None))
				frappe.db.rollback()
	print(f"\n{'PLAN convertible' if dry_run else 'converted+submitted'}={done} already_linked={already}")
	if exceptions:
		print(f"EXCEPTIONS ({len(exceptions)}) — resolve manually, NOT forced:")
		for x in exceptions:
			print("  ", x)
	if not dry_run:
		frappe.db.commit()


# ---------------------------------------------------------------- PHASE D ----
def reconcile(dry_run=1):
	"""FIFO: oldest unallocated PE ↔ oldest outstanding PInv, per supplier."""
	frappe.set_user("Administrator")
	_require_map()
	from erpnext.accounts.utils import reconcile_against_document

	for excel, sup in SUPPLIER_MAP.items():
		pes = frappe.get_all(
			"Payment Entry",
			filters={"company": COMPANY, "party": sup, "docstatus": 1, "unallocated_amount": [">", 0.005]},
			fields=["name", "posting_date", "unallocated_amount", "paid_from", "paid_to"],
			order_by="posting_date asc, name asc",
		)
		invs = frappe.get_all(
			"Purchase Invoice",
			filters={"company": COMPANY, "supplier": sup, "docstatus": 1, "outstanding_amount": [">", 0.005]},
			fields=["name", "posting_date", "outstanding_amount"],
			order_by="posting_date asc, name asc",
		)
		pairs = []
		i = 0
		for inv in invs:
			out = flt(inv.outstanding_amount)
			while out > 0.005 and i < len(pes):
				pe = pes[i]
				take = min(out, flt(pe.unallocated_amount))
				if take > 0.005:
					pairs.append((pe, inv, round(take, 2)))
					pe.unallocated_amount = flt(pe.unallocated_amount) - take
					out -= take
				if flt(pe.unallocated_amount) <= 0.005:
					i += 1
		tot = sum(p[2] for p in pairs)
		print(f"\n{sup}: {len(pairs)} allocations, Σ {tot:,.2f}")
		for pe, inv, amt in pairs[:8]:
			print(f"  {pe.name} ({pe.posting_date}) → {inv.name} ({inv.posting_date})  {amt:,.2f}")
		if len(pairs) > 8:
			print(f"  … +{len(pairs) - 8} more")
		if dry_run:
			continue
		ok = fail = 0
		for pe, inv, amt in pairs:
			try:
				pe_doc = frappe.get_doc("Payment Entry", pe.name)
				args = frappe._dict(
					{
						"company": COMPANY,
						"party_type": "Supplier",
						"party": sup,
						"voucher_type": "Payment Entry",
						"voucher_no": pe.name,
						"against_voucher_type": "Purchase Invoice",
						"against_voucher": inv.name,
						"account": pe_doc.paid_to,
						"allocated_amount": amt,
						"unadjusted_amount": amt,
						"unreconciled_amount": amt,
						"grand_total": amt,
						"dr_or_cr": "debit_in_account_currency",
					}
				)
				reconcile_against_document([args])
				ok += 1
			except Exception as e:
				fail += 1
				print(f"  FAIL {pe.name}→{inv.name}: {str(e)[:140]}")
				frappe.db.rollback()
		print(f"  reconciled={ok} failed={fail}")
		if not dry_run:
			frappe.db.commit()


# ---------------------------------------------------------------- PHASE E ----
def compare():
	"""The honest table: supplier_ledger closing vs the workbook's Остаток."""
	frappe.set_user("Administrator")
	_require_map()
	from stabler.api.purchasing import supplier_ledger

	print(f"{'supplier':40} {'ledger closing':>16} {'Excel остаток':>14} {'delta':>12}")
	for excel, sup in SUPPLIER_MAP.items():
		led = supplier_ledger(COMPANY, sup, limit=1)
		closing = flt(led["closing_acc"])  # +ve = we owe (USD)
		tgt = TARGETS.get(excel, {})
		ost = flt(tgt.get("ostatok"))
		print(f"{sup:40} {closing:>16,.2f} {ost:>14,.2f} {closing - ost:>12,.2f}")
	print(
		"\nNotes: delta ≠ 0 is INFORMATION, not failure — candidates: undelivered"
		" PI remainder (no CI yet → not on ledger), the workbook's own internal"
		" drifts (IFF +217; ALS −63 988 bank / +32 612 total), or CIs listed as"
		" convert exceptions. Investigate by supplier_ledger() row-by-row."
	)
