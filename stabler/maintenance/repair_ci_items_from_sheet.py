"""Rebuild Commercial Invoice line items from the MSA operational workbook.

WHY THIS EXISTS
---------------
``migrate_msaerp_imports.py`` rebuilt CI line items from the legacy MSAERP
sqlite. Where that source had no product reference it wrote the placeholder
item ``ITEM-GENERIC`` and a NULL category, and it did so with
``ignore_validate``, so nothing complained. A CI line with no category cannot
match any PI line at all — the PI<->CI match key is ``(PI, category)``, not the
item (see ``stabler/api/_imports_rules.py``) — which is why those invoices show
up as "Not on any PI" with every line flagged as a deviation.

This script restores those lines from the operational book
(``CI MSA.xlsx`` -> ``Sheet1``): 7 400 lines / 387 invoices / 90 PIs /
31 830 861 kg. It is the same book the matching rules in ``_imports_rules.py``
were validated against, one export newer, and it cross-checks against the
``MSA Fresh MEAT`` workbook's own control totals (31 830 861,44 kg and
127 032 500,02 declared).

DIFFERENCES FROM THE SCRIPT THAT CAUSED THE DAMAGE
--------------------------------------------------
* Dry run is the default. Nothing is written unless ``dry_run=0``.
* Every CI it is about to touch is dumped to a JSON backup first.
* No ``ignore_validate`` / ``ignore_links``. The controller runs.
* An item it cannot resolve is never replaced by a placeholder: the line — and
  by default the whole invoice — is skipped and reported.
* Re-running it is safe: same input, same result.

USAGE
-----
    bench --site <site> execute stabler.maintenance.repair_ci_items_from_sheet.run \
        --kwargs "{'csv_path': '/home/frappe/msa_ci_lines.csv', 'company': 'MSA'}"

    # after reading the dry-run report, apply:
    ... --kwargs "{'csv_path': '...', 'company': 'MSA', 'dry_run': 0}"

    # one invoice only, to prove the shape first:
    ... --kwargs "{'csv_path': '...', 'invoices': ['MH/104/202526'], 'dry_run': 0}"

CSV CONTRACT
------------
Header (extracted from ``CI MSA.xlsx`` / sheet ``Sheet1``, one row per invoice
line):
    contract, pi_ref, ci_number, ci_date, container, supplier, category,
    article, jargon, product_name, boxes, box_weight_kg, qty_kg,
    docs_price, docs_amount, agreed_price, agreed_amount, row_no, flags

The book keeps the two prices apart and they genuinely differ: on 5 520 of
7 269 priced lines the declared (docs) price is a flat per-invoice figure while
the agreed price is per product. Whole book: docs 127 032 500, agreed
128 438 240. So ``docs_price`` <- docs price, ``rate`` <- agreed price, and the
CI's cash_difference falls out of the two. Where a line carries only one of the
two, the other is filled from it and the line is flagged.
"""

import csv
import json
import os
import re
from collections import defaultdict

import frappe
from frappe.utils import cint, flt

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_WS = re.compile(r"\s+")


def _norm_ref(value) -> str:
	"""Document-reference key: upper-case, strip everything but A-Z0-9.

	``MH/104/202526`` and ``MH-104-202526`` are the same invoice. Same rule the
	legacy migration used, so both sides land on the same key.
	"""
	return _NON_ALNUM.sub("", str(value or "").upper())


def _norm_text(value) -> str:
	"""Display-text key: collapse whitespace, upper-case. Never used for output."""
	return _WS.sub(" ", str(value or "")).strip().upper()


def _f(value) -> float:
	try:
		return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
	except (TypeError, ValueError):
		return 0.0


def _numeric_variants(article: str) -> list[str]:
	"""Zero-padding variants of a purely numeric article code.

	``5`` -> ``05``, ``005``; ``019`` -> ``19``. Anything that is not all
	digits (``15-17``, ``105/106``, ``UKR/frozen``) returns nothing, because
	padding those would invent a different product.
	"""
	raw = (article or "").strip()
	if not raw.isdigit():
		return []
	bare = raw.lstrip("0") or "0"
	out = {bare, bare.zfill(2), bare.zfill(3), bare.zfill(4)}
	out.discard(raw)
	return [_norm_text(v) for v in sorted(out)]


def _load_csv(csv_path: str) -> list[dict]:
	if not os.path.exists(csv_path):
		frappe.throw(f"CSV not found: {csv_path}")
	with open(csv_path, encoding="utf-8-sig", newline="") as fh:
		return list(csv.DictReader(fh))


# --------------------------------------------------------------------------
# resolvers
# --------------------------------------------------------------------------


def _ci_index(company: str) -> dict[str, str]:
	"""Every Commercial Invoice of the company, keyed by normalised ci_number
	AND by normalised name — the workbook sometimes carries one, sometimes the
	other."""
	index: dict[str, str] = {}
	for row in frappe.get_all(
		"Commercial Invoice", filters={"company": company}, fields=["name", "ci_number"]
	):
		if row.ci_number:
			index.setdefault(_norm_ref(row.ci_number), row.name)
		index.setdefault(_norm_ref(row.name), row.name)
	return index


def _pi_index(company: str) -> dict[str, str]:
	index: dict[str, str] = {}
	for row in frappe.get_all(
		"Proforma Invoice", filters={"company": company}, fields=["name", "supplier_pi_ref"]
	):
		if row.supplier_pi_ref:
			index.setdefault(_norm_ref(row.supplier_pi_ref), row.name)
		index.setdefault(_norm_ref(row.name), row.name)
	return index


def _item_index() -> tuple[dict[str, str], dict[str, str]]:
	"""Two lookups over the Item master: by code and by name.

	Both are normalised text keys. The value is always the real ``item_code``.
	"""
	by_code: dict[str, str] = {}
	by_name: dict[str, str] = {}
	for row in frappe.get_all("Item", fields=["name", "item_code", "item_name"], limit_page_length=0):
		code = row.item_code or row.name
		by_code.setdefault(_norm_text(code), code)
		by_code.setdefault(_norm_ref(code), code)
		if row.item_name:
			by_name.setdefault(_norm_text(row.item_name), code)
	return by_code, by_name


def _resolve_item(line: dict, by_code: dict, by_name: dict, aliases: dict) -> tuple[str | None, str]:
	"""Find the Stabler Item for one workbook line.

	Returns ``(item_code, strategy)``. ``item_code`` is None when nothing
	matched — the caller reports it, it is never replaced by a placeholder.

	Order matters: an explicit alias beats an exact code, an exact code beats a
	name, and a name beats the "article + name" composite that most of the MSA
	item master is written in (``41 TOPSIDE``, ``TOPSIDE 41``).
	"""
	article = (line.get("article") or "").strip()
	pname = (line.get("product_name") or "").strip()

	alias_key = f"{_norm_text(article)}|{_norm_text(pname)}"
	if alias_key in aliases:
		return aliases[alias_key], "alias"

	if article and _norm_text(article) in by_code:
		return by_code[_norm_text(article)], "code"

	# The book writes an offal cut as ``5``; the item master writes it as
	# ``005``. Only pure-digit articles get this — ``15-17``, ``60/60A`` and
	# ``UKR/frozen`` must never be zero-padded into something else.
	for variant in _numeric_variants(article):
		if variant in by_code:
			return by_code[variant], "code(padded)"
	if pname and _norm_text(pname) in by_code:
		return by_code[_norm_text(pname)], "code"
	if pname and _norm_text(pname) in by_name:
		return by_name[_norm_text(pname)], "name"

	for joined in (f"{article} {pname}", f"{pname} {article}"):
		key = _norm_text(joined)
		if key in by_code:
			return by_code[key], "code+name"
		if key in by_name:
			return by_name[key], "code+name"

	return None, "unresolved"


def _load_aliases(alias_path: str | None) -> dict[str, str]:
	"""Optional manual map for lines the automatic resolver cannot place.

	CSV with columns ``article, product_name, item_code``. Produced by reading
	the dry-run's ``unresolved`` report and deciding each pair once.
	"""
	if not alias_path:
		return {}
	out: dict[str, str] = {}
	for row in _load_csv(alias_path):
		key = f"{_norm_text(row.get('article'))}|{_norm_text(row.get('product_name'))}"
		if row.get("item_code"):
			out[key] = row["item_code"].strip()
	return out


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


@frappe.whitelist()
def run(
	csv_path: str,
	company: str = "MSA",
	dry_run: int = 1,
	invoices=None,
	alias_path: str | None = None,
	allow_partial: int = 0,
	only_suppliers: str | None = None,
	skip_suppliers: str | None = None,
	require_pi: int = 1,
	include_service_lines: int = 0,
	service_item: str | None = None,
	report_dir: str | None = None,
):
	"""Rebuild CI items from the workbook CSV."""
	dry_run = cint(dry_run)
	allow_partial = cint(allow_partial)
	require_pi = cint(require_pi)
	include_service_lines = cint(include_service_lines)

	rows = _load_csv(csv_path)
	wanted = {_norm_ref(x) for x in (invoices or [])} or None
	only_terms = [t.strip().upper() for t in (only_suppliers or "").split(",") if t.strip()]
	skip_terms = [t.strip().upper() for t in (skip_suppliers or "").split(",") if t.strip()]

	ci_idx = _ci_index(company)
	pi_idx = _pi_index(company)
	by_code, by_name = _item_index()
	aliases = _load_aliases(alias_path)

	report_dir = report_dir or frappe.get_site_path("private", "files")
	os.makedirs(report_dir, exist_ok=True)
	stamp = frappe.utils.now_datetime().strftime("%Y%m%d-%H%M%S")

	# ---- group the workbook by invoice -----------------------------------
	grouped: dict[str, list[dict]] = defaultdict(list)
	for row in rows:
		key = _norm_ref(row.get("ci_number"))
		if not key or (wanted and key not in wanted):
			continue
		grouped[key].append(row)

	summary = {
		"site": frappe.local.site,
		"company": company,
		"dry_run": bool(dry_run),
		"csv_rows": len(rows),
		"invoices_in_csv": len(grouped),
		"matched": 0,
		"unknown_invoice": [],
		"skipped_supplier": [],
		"skipped_unresolved": [],
		"skipped_no_pi": [],
		"missing_pi_refs": defaultdict(int),
		"applied": [],
		"unresolved_items": defaultdict(int),
		"failed": [],
	}
	backup: dict[str, list[dict]] = {}
	details = []

	for key, lines in sorted(grouped.items()):
		ci_name = ci_idx.get(key)
		raw_number = lines[0].get("ci_number")

		suppliers = {(line.get("supplier") or "").strip() for line in lines}
		outside = {
			name
			for name in suppliers
			if (only_terms and not any(term in name.upper() for term in only_terms))
			or any(term in name.upper() for term in skip_terms)
		}
		if outside:
			summary["skipped_supplier"].append(
				{
					"ci_number": raw_number,
					"suppliers": sorted(outside),
					"mixed": len(outside) < len(suppliers),
				}
			)
			continue
		if not ci_name:
			summary["unknown_invoice"].append(raw_number)
			continue
		summary["matched"] += 1

		planned, unresolved, no_pi = [], [], []
		for line in lines:
			boxes = _f(line.get("boxes"))
			is_service = boxes == 0
			if is_service and not include_service_lines:
				continue

			item_code, strategy = _resolve_item(line, by_code, by_name, aliases)
			if is_service and service_item:
				item_code, strategy = service_item, "service"
			if not item_code:
				pair = f"{line.get('article')} | {line.get('product_name')}"
				summary["unresolved_items"][pair] += 1
				unresolved.append({"row_no": line.get("row_no"), "pair": pair})
				continue

			pi_ref = (line.get("pi_ref") or "").strip()
			pi_name = pi_idx.get(_norm_ref(pi_ref))
			if require_pi and not pi_name:
				summary["missing_pi_refs"][pi_ref or "(blank)"] += 1
				no_pi.append({"row_no": line.get("row_no"), "pi_ref": pi_ref})
				continue

			qty = _f(line.get("qty_kg"))
			docs_price = _f(line.get("docs_price"))
			agreed_price = _f(line.get("agreed_price"))
			# One-sided lines (freight, war risk, a product the book never priced
			# twice) carry the figure they do have into the field they do not, so a
			# missing price never silently becomes a zero-value invoice line.
			if not agreed_price:
				agreed_price = docs_price
			if not docs_price:
				docs_price = agreed_price
			docs_amount = _f(line.get("docs_amount")) or (qty * docs_price)
			agreed_amount = _f(line.get("agreed_amount")) or (qty * agreed_price)
			planned.append(
				{
					"custom_proforma_invoice": pi_name,
					"category": (line.get("category") or "").strip() or None,
					"item": item_code,
					"description": (line.get("product_name") or "").strip() or item_code,
					"boxes": cint(boxes),
					"box_weight_kg": _f(line.get("box_weight_kg")),
					"qty": qty,
					"uom": "Kg",
					"rate": agreed_price,
					"docs_price": docs_price,
					"amount": agreed_amount,
					"docs_amount": docs_amount,
					"_strategy": strategy,
				}
			)

		if no_pi and not allow_partial:
			summary["skipped_no_pi"].append(
				{"ci": ci_name, "ci_number": raw_number, "missing": sorted({r["pi_ref"] for r in no_pi})}
			)
			continue
		if unresolved and not allow_partial:
			summary["skipped_unresolved"].append(
				{"ci": ci_name, "ci_number": raw_number, "unresolved": unresolved}
			)
			continue
		if not planned:
			continue

		existing = frappe.get_all(
			"Commercial Invoice Item",
			filters={"parent": ci_name, "parenttype": "Commercial Invoice"},
			fields=[
				"name",
				"item",
				"category",
				"boxes",
				"box_weight_kg",
				"qty",
				"rate",
				"docs_price",
				"amount",
				"docs_amount",
				"custom_proforma_invoice",
			],
			order_by="idx asc",
		)
		backup[ci_name] = existing

		before = {
			"lines": len(existing),
			"boxes": sum(cint(r.boxes) for r in existing),
			"kg": sum(flt(r.qty) for r in existing),
			"amount": sum(flt(r.amount) for r in existing),
			"docs": sum(flt(r.docs_amount) for r in existing),
			"generic": sum(1 for r in existing if r.item == "ITEM-GENERIC"),
			"no_category": sum(1 for r in existing if not (r.category or "").strip()),
		}
		after = {
			"lines": len(planned),
			"boxes": sum(p["boxes"] for p in planned),
			"kg": sum(p["qty"] for p in planned),
			"amount": sum(p["amount"] for p in planned),
			"docs": sum(p["docs_amount"] for p in planned),
		}
		details.append(
			{
				"ci": ci_name,
				"ci_number": raw_number,
				"before": before,
				"after": after,
				"unresolved": unresolved,
			}
		)

		if dry_run:
			continue

		try:
			doc = frappe.get_doc("Commercial Invoice", ci_name)
			doc.set("items", [])
			for plan in planned:
				payload = {k: v for k, v in plan.items() if not k.startswith("_")}
				doc.append("items", payload)
			doc.total_boxes = after["boxes"]
			doc.total_kg = after["kg"]
			doc.agreed_total = after["amount"]
			doc.docs_total = sum(p["docs_amount"] for p in planned)
			doc.cash_difference = flt(doc.agreed_total) - flt(doc.docs_total)
			doc.flags.ignore_permissions = True
			doc.save()
			frappe.db.commit()
			summary["applied"].append(ci_name)
		except Exception as exc:
			frappe.db.rollback()
			summary["failed"].append({"ci": ci_name, "error": str(exc)[:400]})

	# ---- persist backup + report -----------------------------------------
	backup_path = os.path.join(report_dir, f"ci_items_backup_{stamp}.json")
	report_path = os.path.join(report_dir, f"ci_repair_report_{stamp}.json")
	with open(backup_path, "w", encoding="utf-8") as fh:
		json.dump(backup, fh, ensure_ascii=False, indent=1, default=str)
	summary["unresolved_items"] = dict(sorted(summary["unresolved_items"].items(), key=lambda kv: -kv[1]))
	summary["missing_pi_refs"] = dict(sorted(summary["missing_pi_refs"].items(), key=lambda kv: -kv[1]))
	with open(report_path, "w", encoding="utf-8") as fh:
		json.dump({"summary": summary, "details": details}, fh, ensure_ascii=False, indent=1, default=str)

	# The unresolved pairs come back out in exactly the shape ``alias_path``
	# expects, so closing the loop is filling one column in this file and
	# re-running — no hand-built CSV, no transcription slips.
	alias_out = os.path.join(report_dir, f"ci_repair_unresolved_{stamp}.csv")
	with open(alias_out, "w", encoding="utf-8", newline="") as fh:
		writer = csv.writer(fh)
		writer.writerow(["article", "product_name", "lines", "item_code"])
		for pair, count in summary["unresolved_items"].items():
			article, _, pname = pair.partition(" | ")
			writer.writerow([article, pname, count, ""])

	print(f"site               : {frappe.local.site}")
	print(f"mode               : {'DRY RUN — nothing written' if dry_run else 'APPLIED'}")
	print(f"csv rows           : {summary['csv_rows']}")
	print(f"invoices in csv    : {summary['invoices_in_csv']}")
	print(f"matched in Stabler : {summary['matched']}")
	print(f"unknown invoice    : {len(summary['unknown_invoice'])}")
	print(f"skipped (supplier) : {len(summary['skipped_supplier'])}")
	print(f"skipped (item?)    : {len(summary['skipped_unresolved'])}")
	print(f"skipped (no PI)    : {len(summary['skipped_no_pi'])}")
	print(f"would touch/applied: {len(details) if dry_run else len(summary['applied'])}")
	print(f"failed             : {len(summary['failed'])}")
	generic = sum(d["before"]["generic"] for d in details)
	nocat = sum(d["before"]["no_category"] for d in details)
	print(f"ITEM-GENERIC lines being replaced : {generic}")
	print(f"category-less lines being replaced: {nocat}")
	if summary["missing_pi_refs"]:
		print("\nPI references not found in Stabler (create these first):")
		for ref, count in summary["missing_pi_refs"].items():
			print(f"   {count:5d} lines  {ref}")
	if summary["unresolved_items"]:
		print("\nunresolved article | product  (top 20 — feed these to alias_path):")
		for pair, count in list(summary["unresolved_items"].items())[:20]:
			print(f"   {count:5d}  {pair}")
	print(f"\nbackup    : {backup_path}")
	print(f"report    : {report_path}")
	print(f"unresolved: {alias_out}   <- fill item_code, pass back as alias_path")
	return summary


@frappe.whitelist()
def restore(backup_path: str, dry_run: int = 1):
	"""Put back exactly what ``run`` replaced, from its JSON backup."""
	dry_run = cint(dry_run)
	with open(backup_path, encoding="utf-8") as fh:
		backup = json.load(fh)
	restored = []
	for ci_name, rows in backup.items():
		if not frappe.db.exists("Commercial Invoice", ci_name):
			continue
		if dry_run:
			restored.append({"ci": ci_name, "lines": len(rows)})
			continue
		doc = frappe.get_doc("Commercial Invoice", ci_name)
		doc.set("items", [])
		for row in rows:
			doc.append(
				"items",
				{
					k: v
					for k, v in row.items()
					if k not in ("name", "idx", "parent", "parenttype", "parentfield")
				},
			)
		doc.flags.ignore_permissions = True
		doc.save()
		frappe.db.commit()
		restored.append({"ci": ci_name, "lines": len(rows)})
	print(f"{'would restore' if dry_run else 'restored'}: {len(restored)} invoices")
	return restored


@frappe.whitelist()
def verify(csv_path: str, company: str = "MSA", tolerance: float = 1.0, only_suppliers: str | None = None):
	"""Prove, invoice by invoice, that Stabler reproduces the book."""
	rows = _load_csv(csv_path)
	ci_idx = _ci_index(company)
	pi_idx = _pi_index(company)
	only_terms = [t.strip().upper() for t in (only_suppliers or "").split(",") if t.strip()]

	expected: dict[str, dict] = {}
	for row in rows:
		if "SERVICE_LINE" in (row.get("flags") or ""):
			continue
		if only_terms and not any(term in (row.get("supplier") or "").upper() for term in only_terms):
			continue
		key = _norm_ref(row.get("ci_number"))
		if not key:
			continue
		exp = expected.setdefault(
			key,
			{
				"ci_number": row.get("ci_number"),
				"lines": 0,
				"boxes": 0,
				"kg": 0.0,
				"agreed": 0.0,
				"docs": 0.0,
				"split": defaultdict(int),
			},
		)
		# Mirror run()'s one-sided-price fallback exactly. Without this the
		# checker disagrees with the writer on the handful of lines the book
		# priced only once, and reports a difference the repair did not make.
		qty = _f(row.get("qty_kg"))
		docs_price = _f(row.get("docs_price"))
		agreed_price = _f(row.get("agreed_price")) or docs_price
		docs_price = docs_price or agreed_price

		exp["lines"] += 1
		exp["boxes"] += cint(_f(row.get("boxes")))
		exp["kg"] += qty
		exp["agreed"] += _f(row.get("agreed_amount")) or (qty * agreed_price)
		exp["docs"] += _f(row.get("docs_amount")) or (qty * docs_price)
		# The PI is part of the key, not decoration: 16 lines in this book carry
		# the SAME category on the SAME invoice from TWO different proformas.
		# Leave the PI out and a line booked against the wrong contract still
		# passes — which is the error this whole repair is about.
		exp["split"][
			(
				pi_idx.get(_norm_ref(row.get("pi_ref"))) or f"?{(row.get('pi_ref') or '').strip()}",
				_norm_text(row.get("category")),
				cint(_f(row.get("boxes"))),
				round(_f(row.get("qty_kg")), 2),
			)
		] += 1

	ok, mismatched, missing = 0, [], []
	for key, exp in sorted(expected.items()):
		ci_name = ci_idx.get(key)
		if not ci_name:
			missing.append(exp["ci_number"])
			continue

		lines = frappe.db.sql(
			"""SELECT i.item, i.category, i.boxes, i.qty, i.amount, i.docs_amount,
			          i.custom_proforma_invoice AS pi, p.name AS pi_exists
			     FROM `tabCommercial Invoice Item` i
			     LEFT JOIN `tabProforma Invoice` p ON p.name = i.custom_proforma_invoice
			    WHERE i.parent = %(ci)s AND i.parenttype = 'Commercial Invoice'""",
			{"ci": ci_name},
			as_dict=True,
		)
		actual_split = defaultdict(int)
		for row in lines:
			actual_split[
				(
					row.pi or "(no PI)",
					_norm_text(row.category),
					cint(row.boxes),
					round(flt(row.qty), 2),
				)
			] += 1

		problems = []
		if len(lines) != exp["lines"]:
			problems.append(f"lines {len(lines)} != {exp['lines']}")
		if sum(cint(r.boxes) for r in lines) != exp["boxes"]:
			problems.append(f"boxes {sum(cint(r.boxes) for r in lines)} != {exp['boxes']}")
		for field, label in (("qty", "kg"), ("amount", "agreed"), ("docs_amount", "docs")):
			got = sum(flt(r[field]) for r in lines)
			want = exp[{"qty": "kg", "amount": "agreed", "docs_amount": "docs"}[field]]
			if abs(got - want) > tolerance:
				problems.append(f"{label} {got:.2f} != {want:.2f}")

		# the split check — same totals, wrong product breakdown, still fails
		for combo, count in exp["split"].items():
			if actual_split.get(combo, 0) != count:
				problems.append(
					f"split {combo[0]}/{combo[1] or '(no category)'} {combo[2]}bx: {actual_split.get(combo, 0)} != {count}"
				)
		for combo, count in actual_split.items():
			if combo not in exp["split"]:
				problems.append(f"extra {combo[0]}/{combo[1] or '(no category)'} {combo[2]}bx x{count}")

		generic = sum(1 for r in lines if r.item == "ITEM-GENERIC")
		nocat = sum(1 for r in lines if not (r.category or "").strip())
		nopi = sum(1 for r in lines if not (r.pi or "").strip())
		deadpi = sum(1 for r in lines if (r.pi or "").strip() and not r.pi_exists)
		if generic:
			problems.append(f"{generic} ITEM-GENERIC lines")
		if nocat:
			problems.append(f"{nocat} lines without category")
		if nopi:
			problems.append(f"{nopi} lines without a PI reference")
		if deadpi:
			problems.append(f"{deadpi} lines pointing at a missing PI")

		if problems:
			mismatched.append({"ci": ci_name, "ci_number": exp["ci_number"], "problems": problems[:6]})
		else:
			ok += 1

	print(f"invoices in scope    : {len(expected)}")
	print(f"invoices verified OK : {ok}")
	print(f"mismatched           : {len(mismatched)}")
	print(f"not found in Stabler : {len(missing)}")
	if missing:
		print("   " + ", ".join(missing[:20]) + (" …" if len(missing) > 20 else ""))
	for row in mismatched:
		print(f"   {row['ci_number']:<22} {'; '.join(row['problems'])}")
	if not mismatched and not missing:
		print("\nEVERY invoice in scope reproduces the book: category, product split,")
		print("boxes, kg, both prices, and a live PI reference on every single line.")
	return {"ok": ok, "mismatched": mismatched, "missing": missing}


@frappe.whitelist()
def key_ledger(csv_path: str | None = None, company: str = "MSA", only_suppliers: str | None = None):
	"""The contract ledger: one row per ``(PI, category)`` — ordered vs shipped."""
	only_terms = [t.strip().upper() for t in (only_suppliers or "").split(",") if t.strip()]

	pi_rows = frappe.db.sql(
		"""SELECT pi.name AS pi, pi.supplier, it.category,
		          COALESCE(SUM(it.boxes),0) AS boxes, COALESCE(SUM(it.qty),0) AS kg
		     FROM `tabProforma Invoice` pi
		     JOIN `tabProforma Invoice Item` it ON it.parent = pi.name
		    WHERE pi.company = %(company)s
		    GROUP BY pi.name, pi.supplier, it.category""",
		{"company": company},
		as_dict=True,
	)
	ci_rows = frappe.db.sql(
		"""SELECT it.custom_proforma_invoice AS pi, ci.supplier, it.category,
		          COALESCE(SUM(it.boxes),0) AS boxes, COALESCE(SUM(it.qty),0) AS kg,
		          COUNT(DISTINCT ci.name) AS cis
		     FROM `tabCommercial Invoice` ci
		     JOIN `tabCommercial Invoice Item` it ON it.parent = ci.name
		    WHERE ci.company = %(company)s AND ci.status != 'Cancelled'
		    GROUP BY it.custom_proforma_invoice, ci.supplier, it.category""",
		{"company": company},
		as_dict=True,
	)

	def wanted(supplier):
		return not only_terms or any(term in (supplier or "").upper() for term in only_terms)

	ordered, shipped = {}, {}
	for row in pi_rows:
		if wanted(row.supplier):
			ordered[(row.pi, _norm_text(row.category))] = row
	for row in ci_rows:
		if wanted(row.supplier) and row.pi:
			shipped[(row.pi, _norm_text(row.category))] = row

	unattributable = [r for r in ci_rows if wanted(r.supplier) and not r.pi]

	ledger, orphan_keys, over = [], [], []
	for key in sorted(set(ordered) | set(shipped)):
		o, s = ordered.get(key), shipped.get(key)
		row = {
			"pi": key[0],
			"category": (o or s).category,
			"ordered_boxes": cint(o.boxes) if o else 0,
			"shipped_boxes": cint(s.boxes) if s else 0,
			"ordered_kg": flt(o.kg) if o else 0.0,
			"shipped_kg": flt(s.kg) if s else 0.0,
			"cis": cint(s.cis) if s else 0,
		}
		row["remaining_boxes"] = row["ordered_boxes"] - row["shipped_boxes"]
		ledger.append(row)
		if not o:
			orphan_keys.append(row)
		elif row["remaining_boxes"] < 0:
			over.append(row)

	book_missing = []
	if csv_path:
		pi_idx = _pi_index(company)
		book = set()
		for line in _load_csv(csv_path):
			if "SERVICE_LINE" in (line.get("flags") or "") or not wanted(line.get("supplier")):
				continue
			name = pi_idx.get(_norm_ref(line.get("pi_ref")))
			book.add((name or f"?{line.get('pi_ref')}", _norm_text(line.get("category"))))
		book_missing = sorted(k for k in book if k not in ordered)

	print(f"contract keys (PI x category) : {len(ledger)}")
	print(f"  fully or partly shipped     : {sum(1 for r in ledger if r['shipped_boxes'])}")
	print(f"  shipped against no PI line  : {len(orphan_keys)}   <- these are the 'Not on any PI' rows")
	print(f"  over-shipped                : {len(over)}")
	print(f"CI lines with no PI reference : {len(unattributable)}")
	if book_missing:
		print(f"keys the book expects but no PI carries: {len(book_missing)}")
		for key in book_missing[:20]:
			print(f"   {key[0]:<24} {key[1]}")
	if orphan_keys:
		print("\nshipped against a category no PI of that vendor books:")
		for row in orphan_keys[:20]:
			print(f"   {row['pi'] or '(no PI)':<24} {row['category'][:28]:<28} {row['shipped_boxes']:>8} bx")
	if over:
		print("\nover-shipped keys (negative remaining is a finding, never clamped):")
		for row in over[:20]:
			print(f"   {row['pi']:<24} {row['category'][:28]:<28} {row['remaining_boxes']:>8} bx")
	if not orphan_keys and not over and not unattributable and not book_missing:
		print("\nEvery shipped box sits on a contract key its proforma booked.")
	return {
		"ledger": ledger,
		"orphan_keys": orphan_keys,
		"over_shipped": over,
		"unattributable_lines": len(unattributable),
		"book_missing_keys": book_missing,
	}
