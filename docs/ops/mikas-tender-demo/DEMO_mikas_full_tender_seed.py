"""Mikas tender demo — FULL lifecycle seed + verify.

THE BUSINESS ORDER (this is the whole point — do not reorder):
you cannot price a bid without knowing your cost. Sourcing comes FIRST.

  1. lot spotted     CRM Deal + intake (lot, buyer, deadlines) + go decision
                     ("worth sourcing" — NOT a bid yet)
  2. sourcing        5 Supplier Quotations from Russia + China, deal-tagged:
                     "what can we buy this for?"
  3. evaluation      comparison (5/5 + 3-country policy, Cheapest row) feeds
                     bid pricing: landed_goods = cheapest sourced cost,
                     mode=margin -> the engine BACK-SOLVES our bid price
  4. bid submitted   mark_tender_submitted (server-audited, from the price
                     the sourcing produced)
  5. won             intake result=won + won_price (audit-stamped)
                     + contract Sales Order on the board (stage: Procurement)
  6. execution       draft PO to the vendor the comparison selected
                     (submit it live on stage)

Everything carries the ZDEMO mark; cleanup() removes all of it.
verify() calls THE SAME whitelisted endpoints the demo screens call, in the
same business order, and asserts what the audience will see. If verify prints
all PASS, no screen in the demo can open empty.

USAGE (prod, mikas):
    scp DEMO_mikas_full_tender_seed.py \
      ice-production:/home/frappe/frappe-bench/apps/stabler/stabler/tmp_demo.py

    bench --site mikas.erpstable.com execute stabler.tmp_demo.seed
    bench --site mikas.erpstable.com execute stabler.tmp_demo.verify
    # ... after the presentation:
    bench --site mikas.erpstable.com execute stabler.tmp_demo.cleanup
    rm .../apps/stabler/stabler/tmp_demo.py
"""

import json
import os

import frappe
from frappe.utils import add_days, flt, today

MARK = "ZDEMO"
REGISTRY = "/tmp/stabler_demo_mikas_registry.json"

#: supplier, country, currency, unit rate — cheapest is Ningbo (China).
#: Mikas sources from Russia and China; USD is the settlement currency both ways.
QUOTES = [
    ("Ningbo Heavy Machinery", "China", "USD", 104.0),
    ("Harbin Electric Co", "China", "USD", 112.5),
    ("Ural Promsnab", "Russia", "USD", 118.0),
    ("Guangzhou Industrial Group", "China", "USD", 116.0),
    ("Novosibirsk TechExport", "Russia", "USD", 121.0),
]
QTY = 40.0
MARGIN_PCT = 15.0  # target margin — the engine back-solves the bid price


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #

def _register(doctype, name):
    data = _read()
    data.append({"doctype": doctype, "name": name})
    with open(REGISTRY, "w") as fh:
        json.dump(data, fh, indent=1)


def _read():
    if not os.path.exists(REGISTRY):
        return []
    try:
        with open(REGISTRY) as fh:
            return json.load(fh)
    except Exception:
        return []


#: Frappe ships ISO country names — "Russia" is stored as "Russian Federation".
#: A demo must not die on a label, so resolve to whatever the site actually has
#: and drop the field rather than fail if nothing matches.
_COUNTRY_ALIASES = {"Russia": "Russian Federation"}


def _country(label):
    for candidate in (label, _COUNTRY_ALIASES.get(label)):
        if candidate and frappe.db.exists("Country", candidate):
            return candidate
    hit = frappe.get_all("Country", filters={"name": ["like", f"%{label}%"]}, pluck="name", limit=1)
    return hit[0] if hit else None


#: CRM Deal.organization is a Link to CRM Organization, not free text — assigning
#: a raw string raises LinkValidationError. Create the org first, and register it
#: so cleanup() takes it back out with the rest of the demo.
def _org(label):
    name = label[:140]
    if not frappe.db.exists("CRM Organization", name):
        org = frappe.new_doc("CRM Organization")
        org.organization_name = name
        org.insert(ignore_permissions=True)
        _register("CRM Organization", org.name)
    return name


#: Backdated documents cannot look up a rate: mikas holds a single USD->UZS
#: Currency Exchange row and ERPNext only accepts one dated on or before the
#: document. Rather than write fake-dated rows into the tenant's real FX table,
#: the demo pins the site's newest known rate onto each foreign-currency doc.
def _fx_rate(company, currency):
    base = frappe.db.get_value("Company", company, "default_currency")
    if not base or base == currency:
        return 1.0
    rate = frappe.get_all(
        "Currency Exchange",
        filters={"from_currency": currency, "to_currency": base},
        fields=["exchange_rate"], order_by="date desc", limit=1,
    )
    if not rate:
        frappe.throw(f"No Currency Exchange row for {currency}->{base} — cannot seed")
    return flt(rate[0]["exchange_rate"])


def _company():
    c = frappe.defaults.get_global_default("company") or (
        frappe.get_all("Company", pluck="name", limit=1) or [None]
    )[0]
    if not c:
        frappe.throw("No company on this site")
    return c


# --------------------------------------------------------------------------- #
# seed — in the business order
# --------------------------------------------------------------------------- #

def seed():
    company = _company()
    for col, patch in (
        (("Supplier Quotation", "custom_crm_deal"), "v30"),
        (("CRM Deal", "custom_tender_intake"), "v37"),
        (("CRM Deal", "custom_bid_pricing"), "v36"),
        (("Sales Order", "custom_crm_deal"), "v28"),
        (("Purchase Order", "custom_crm_deal"), "v34"),
    ):
        if not frappe.db.has_column(*col):
            frappe.throw(f"{col[0]}.{col[1]} missing — run migrate (patch {patch})")
    if _read():
        print(f"ABORT: {REGISTRY} not empty — run cleanup() first.")
        return

    from stabler.api import purchasing as purchasing_api
    from stabler.api import tender as tender_api

    # --- shared masters -----------------------------------------------------
    item_code = f"{MARK}-TENDER-ITEM"
    if not frappe.db.exists("Item", item_code):
        it = frappe.new_doc("Item")
        it.update({
            "item_code": item_code, "item_name": "Vagon buksa podshipnigi (demo lot)",
            "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
            "stock_uom": frappe.db.get_value("UOM", {}, "name") or "Nos",
            "is_stock_item": 0,
        })
        it.insert(ignore_permissions=True)
        _register("Item", item_code)

    customer_name = f"{MARK} O'zbekiston temir yo'llari AJ"
    if not frappe.db.exists("Customer", customer_name):
        cu = frappe.new_doc("Customer")
        cu.update({"customer_name": customer_name,
                   "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
                   "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name")})
        cu.insert(ignore_permissions=True)
        _register("Customer", cu.name)

    # --- 1 · LOT SPOTTED — intake + GO (no bid yet) -------------------------
    deal = frappe.new_doc("CRM Deal")
    deal.update({"organization": _org(f"{MARK} UTY lot 2026-4417 — vagon buksa podshipniklari"),
                 "company": company})
    deal.insert(ignore_permissions=True)
    frappe.db.commit()
    _register("CRM Deal", deal.name)

    intake = {
        "lot_no": "UZEX-2026-4417",
        "buyer": "O'zbekiston temir yo'llari AJ (UTY)",
        "unit": "dona",
        "volume": QTY,
        "bid_deadline": add_days(today(), 2),
        "delivery_deadline": add_days(today(), 45),
        "guarantee_amount": 12_000_000,
        "guarantee_return": add_days(today(), 75),
        "penalty_pct_per_day": 0.1,
        "purchase_method": "tender",
        "go_no_go": "go",          # decision: worth SOURCING — not a bid
        "result": "",              # no result: we have not even bid yet
        "notes": "Demo — UTY vagon deposi uchun sentetik tender.",
    }
    tender_api.save_deal_intake(deal.name, json.dumps(intake))
    frappe.db.commit()
    print(f"1. lot spotted: {deal.name}  (intake saved, go_no_go=go — bid NOT submitted)")

    # --- 2 · SOURCING — what can we buy it for? -----------------------------
    print("2. sourcing — supplier quotations:")
    cheapest_rate = min(q[3] for q in QUOTES)
    cheapest_supplier = None
    for supplier_name, country, ccy, rate in QUOTES:
        sname = f"{MARK} {supplier_name}"
        if not frappe.db.exists("Supplier", sname):
            s = frappe.new_doc("Supplier")
            s.update({"supplier_name": sname, "country": _country(country),
                      "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")})
            s.insert(ignore_permissions=True)
            _register("Supplier", s.name)
        sq = frappe.new_doc("Supplier Quotation")
        sq.update({"company": company, "supplier": sname, "currency": ccy,
                   "transaction_date": today(), "valid_till": add_days(today(), 30),
                   "custom_crm_deal": deal.name})
        sq.append("items", {"item_code": item_code, "qty": QTY, "rate": rate})
        sq.insert(ignore_permissions=True)
        sq.submit()
        frappe.db.commit()
        _register("Supplier Quotation", sq.name)
        if rate == cheapest_rate:
            cheapest_supplier = sname
        print(f"   SQ {sq.name}  {sname:36} {country:11} {rate:>7.1f} {ccy}")

    # --- 3 · EVALUATION — sourcing cost -> bid price ------------------------
    sourced_cost = cheapest_rate * QTY
    pricing = tender_api.save_deal_bid_pricing(deal.name, json.dumps({
        "mode": "margin",              # back-solve the bid from a target margin
        "margin_pct": MARGIN_PCT,
        "landed_goods": sourced_cost,  # THE sourcing number — cost drives the bid
    }))
    bid_price = flt((pricing.get("pnl") or {}).get("bid_price")) or round(
        sourced_cost * (1 + MARGIN_PCT / 100), 2
    )
    frappe.db.commit()
    print(f"3. evaluation: cheapest sourced cost {sourced_cost:.2f} "
          f"+ {MARGIN_PCT}% margin -> bid price {bid_price:.2f} (engine back-solved)")

    # --- 4 · BID SUBMITTED — only now, priced from sourcing -----------------
    tender_api.mark_tender_submitted(deal.name, "UZEX-SUB-778812")
    frappe.db.commit()
    print("4. bid submitted (server-audited: submitted_at/by + reference)")

    # --- 5 · WON — result + contract SO on the board ------------------------
    intake["result"] = "won"
    intake["won_price"] = bid_price
    tender_api.save_deal_intake(deal.name, json.dumps(intake))
    frappe.db.commit()
    print(f"5. result=won @ {bid_price:.2f} (result_at/result_by server-stamped)")

    tender_api.so_board(company)  # idempotent: seeds default stages if absent
    so = frappe.new_doc("Sales Order")
    so.update({"company": company, "customer": customer_name,
               "transaction_date": today(), "delivery_date": add_days(today(), 45),
               "custom_crm_deal": deal.name, "custom_board_stage": "Procurement"})
    so.append("items", {"item_code": item_code, "qty": QTY, "rate": bid_price / QTY,
                        "delivery_date": add_days(today(), 45)})
    so.insert(ignore_permissions=True)
    so.submit()
    frappe.db.commit()
    _register("Sales Order", so.name)
    print(f"   contract SO on the board: {so.name} (stage: Procurement)")

    # --- 6 · EXECUTION — PO to the vendor the comparison selected -----------
    po_res = purchasing_api.create_purchase_order(
        company=company, supplier=cheapest_supplier,
        items=json.dumps([{"item_code": item_code, "qty": QTY, "rate": cheapest_rate}]),
        schedule_date=add_days(today(), 30),
        auto_submit=0,  # draft on purpose: submit it live on stage
        currency="USD",
        deal=deal.name,
    )
    po_name = po_res.get("name") if isinstance(po_res, dict) else str(po_res)
    _register("Purchase Order", po_name)
    frappe.db.commit()
    print(f"6. draft PO to {cheapest_supplier}: {po_name}  [submit LIVE on stage]")

    print("\nDONE. Demo URLs (in presentation order):")
    print(f"   #/tender/my-tenders")
    print(f"   #/tender/sourcing?deal={deal.name}")
    print(f"   #/tender/po-control?deal={deal.name}   (bid pricing + PO + landed)")
    print(f"   #/tender/board")
    print(f"   #/tender/director")
    print("\nNow run verify:")
    print("   bench --site mikas.erpstable.com execute stabler.tmp_demo.verify")


# --------------------------------------------------------------------------- #
# verify — same endpoints the screens call, same business order
# --------------------------------------------------------------------------- #

def verify():
    """Prove each demo screen will render, in the order the story is told."""
    company = _company()
    entries = _read()
    deal = next((e["name"] for e in entries if e["doctype"] == "CRM Deal"), None)
    if not deal:
        print("FAIL: no seeded deal in the registry — run seed() first.")
        return
    R = []

    def check(name, ok, detail=""):
        R.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -> {detail}" if detail else ""))

    from stabler.api import purchasing as purchasing_api
    from stabler.api import tender as tender_api

    # act 1: lot + go decision (intake)
    r = tender_api.deal_intake(deal)
    ik = r.get("intake") or {}
    check("1  intake carries the lot + go decision",
          ik.get("lot_no") == "UZEX-2026-4417" and ik.get("go_no_go") == "go")

    # act 2: sourcing (comparison screen)
    q = purchasing_api.tender_quotations(deal)
    check("2a five quotations collected", q["count"] == 5, f"count={q['count']}")
    check("2b two countries — RU+CN (policy >= 2)", q["countries"] >= 2 and q["has_2_countries"],
          f"countries={q['countries']}")
    check("2c policy badge 5/5 green", q["has_min_5"] is True)
    cheapest = [r_ for r_ in q["rows"] if r_.get("cheapest")]
    check("2d exactly one Cheapest row, and it is Ningbo (CN)",
          len(cheapest) == 1 and "Ningbo" in (cheapest[0].get("supplier_name") or ""),
          cheapest[0].get("supplier_name") if cheapest else "none")

    # act 3: evaluation -> bid price derived FROM sourcing
    bp = tender_api.deal_bid_pricing(deal)
    pnl = bp.get("pnl") or {}
    sourced = 104.0 * 40.0
    check("3a bid pricing anchored on the sourced cost (landed_goods = cheapest)",
          abs(flt(pnl.get("landed_goods")) - sourced) < 0.01,
          f"landed_goods={pnl.get('landed_goods')} (sourced {sourced})")
    check("3b engine back-solved a bid price above cost",
          flt(pnl.get("bid_price")) > sourced,
          f"bid_price={pnl.get('bid_price')}")

    # act 4: bid submitted — audit stamped, AFTER pricing existed
    check("4  submission audit is server-stamped",
          bool(ik.get("submitted_at")) and bool(ik.get("submitted_by"))
          and ik.get("submission_reference") == "UZEX-SUB-778812",
          f"at={ik.get('submitted_at')} by={ik.get('submitted_by')}")

    # act 5: won + contract board
    check("5a result=won with audit trail, at the price sourcing produced",
          ik.get("result") == "won" and bool(ik.get("result_at"))
          and abs(flt(ik.get("won_price")) - flt(pnl.get("bid_price"))) < 0.01,
          f"won @ {ik.get('won_price')} by {ik.get('result_by')}")
    b = tender_api.so_board(company)
    so_rows = [c for c in (b.get("cards") or []) if c.get("deal") == deal]
    check("5b contract SO visible on the board (stage Procurement)",
          bool(so_rows) and so_rows[0].get("stage") == "Procurement",
          so_rows[0].get("name") if so_rows else "not found")

    # act 6: execution — PO control board
    pb = tender_api.po_control_board(deal)
    check("6a deal-tagged PO on the control board", pb["kpi"]["po_count"] >= 1,
          f"po_count={pb['kpi']['po_count']}")
    check("6b vendor comparison (compare) rows present", len(pb.get("compare") or []) >= 1,
          f"{len(pb.get('compare') or [])} vendor(s), kpi.vendors={pb['kpi']['vendors']}")

    # finale: director board sees it all
    d = tender_api.tender_director_board(company)
    blob = json.dumps(d, default=str)
    check("7  director board sees the demo deal", deal in blob or "ZDEMO" in blob)

    print(f"\n{sum(R)}/{len(R)} checks passed" + ("  — DEMO HAZIR ✓" if all(R) else "  — FAIL'leri incele"))


# --------------------------------------------------------------------------- #
# cleanup
# --------------------------------------------------------------------------- #

ORDER = ["Purchase Order", "Supplier Quotation", "Sales Order",
         "CRM Deal", "CRM Organization", "Supplier", "Customer", "Item"]


def cleanup():
    entries = _read()
    if not entries:
        print("registry empty — nothing to clean")
        return
    by = {}
    for e in entries:
        by.setdefault(e["doctype"], []).append(e["name"])
    failed = []
    for dt in ORDER:
        for name in by.get(dt, []):
            if not frappe.db.exists(dt, name):
                print(f"  gone     {dt} {name}")
                continue
            try:
                d = frappe.get_doc(dt, name)
                if getattr(d, "docstatus", 0) == 1:
                    d.cancel()
                frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
                frappe.db.commit()
                print(f"  removed  {dt} {name}")
            except Exception as e:
                failed.append((dt, name))
                print(f"  FAILED   {dt} {name} -> {str(e)[:120]}")
    if not failed:
        os.remove(REGISTRY)
        print("registry cleared — zero residue")


# --------------------------------------------------------------------------- #
# PORTFOLIO seed — 2025-2026 history so the funnel/board reads like real life
# --------------------------------------------------------------------------- #
#
# ~27 UTY tenders spread across every stage. Recent activity (last 90 days)
# fills the funnel and the win-rate; 2025 wins sit in Paid/Closed so the
# "Completed" bucket has history without inflating the period win-rate —
# exactly the window rule the funnel enforces.
#
#     bench --site mikas.erpstable.com execute stabler.tmp_demo.seed_portfolio
#     bench --site mikas.erpstable.com execute stabler.tmp_demo.verify_portfolio
#     ... cleanup() removes this together with the single-cycle seed.

RAIL_LOTS = [
    ("Rels mahkamlash elementlari · 12 t", "O'zbekiston temir yo'llari AJ"),
    ("Vagon buksa podshipniklari · 480 dona", "O'zbekiston temir yo'llari AJ"),
    ("Lokomotiv filtr to'plamlari", "Qo'qon lokomotiv deposi (UTY)"),
    ("Temir yo'l shpal boltlari · 60 t", "O'zbekiston temir yo'llari AJ"),
    ("Kontakt tarmoq izolyatorlari", "Toshkent vagon ta'mirlash zavodi (UTY)"),
    ("Signal kabel muftasi · 120 to'plam", "O'zbekiston temir yo'llari AJ"),
    ("G'ildirak jufti podshipniklari", "Toshkent vagon ta'mirlash zavodi (UTY)"),
    ("Tormoz havo klapani · 340 dona", "Qo'qon lokomotiv deposi (UTY)"),
    ("Lokomotiv kompressori 15 kVt", "O'zbekiston temir yo'llari AJ"),
    ("Ko'prik po'lat konstruksiyalari", "O'zbekiston temir yo'llari AJ"),
    ("Rels payvandlash elektrodi · 3 t", "Toshkent vagon ta'mirlash zavodi (UTY)"),
    ("Yo'l o'lchash asboblari", "O'zbekiston temir yo'llari AJ"),
    ("Strelka o'tkazgich qismlari", "O'zbekiston temir yo'llari AJ"),
    ("Vagon resslari · 220 dona", "Toshkent vagon ta'mirlash zavodi (UTY)"),
    ("Dizel dvigatel ehtiyot qismlari", "Qo'qon lokomotiv deposi (UTY)"),
    ("Platforma yuk mahkamlagichlari", "O'zbekiston temir yo'llari AJ"),
    ("Temir yo'l piktogramma-belgilari", "O'zbekiston temir yo'llari AJ"),
    ("Kupe vagon ichki jihozlari", "Toshkent vagon ta'mirlash zavodi (UTY)"),
    ("Lokomotiv fara bloklari", "Qo'qon lokomotiv deposi (UTY)"),
    ("Ballast shag'al elaklari", "O'zbekiston temir yo'llari AJ"),
    ("Vagon eshik mexanizmlari", "Toshkent vagon ta'mirlash zavodi (UTY)"),
    ("Rels tirgak plitalari · 30 t", "O'zbekiston temir yo'llari AJ"),
    ("Signal svetofor bloklari", "O'zbekiston temir yo'llari AJ"),
    ("Vagon tortish moslamalari", "Toshkent vagon ta'mirlash zavodi (UTY)"),
    ("Depo kran ehtiyot qismlari", "Qo'qon lokomotiv deposi (UTY)"),
    ("Yo'lovchi vagon o'rindiqlari", "Toshkent vagon ta'mirlash zavodi (UTY)"),
    ("Temir yo'l aloqa radiostansiyalari", "O'zbekiston temir yo'llari AJ"),
]

#: (stage, count, days_ago_range) — recent stages first, then the archive.
PLAN = [
    ("seen",      4, (3, 20)),
    ("go",        3, (5, 25)),
    ("sourcing",  3, (10, 35)),
    ("priced",    2, (15, 40)),
    ("submitted", 4, (5, 30)),
    ("won",       4, (20, 80)),    # in-window wins -> funnel + win-rate
    ("lost",      3, (25, 85)),
    ("done",      4, (120, 400)),  # 2025/early-2026 -> Paid/Closed archive
]
#: board stages for the 4 recent wins, one each.
WON_SO_STAGES = ["New", "Procurement", "Delivery", "Invoicing"]


def _stamp_intake(deal_name, updates):
    """Backdate server stamps for HISTORICAL demo rows. Live flows must never
    do this — it exists so a 2025 result can look like 2025 in the demo."""
    raw = frappe.db.get_value("CRM Deal", deal_name, "custom_tender_intake")
    data = json.loads(raw) if raw else {}
    data.update(updates)
    frappe.db.set_value("CRM Deal", deal_name, "custom_tender_intake",
                        json.dumps(data, ensure_ascii=False), update_modified=False)


def seed_portfolio():
    import random

    from stabler.api import tender as tender_api

    random.seed(20262025)  # deterministic: re-runs plan the same portfolio
    #: This function commits per deal, so a mid-run failure leaves the deals it
    #: already wrote behind. Re-running then stacks a second portfolio on top and
    #: the early stages silently double — which is invisible to verify_portfolio,
    #: whose thresholds are all ">=". seed() creates exactly one deal, so more
    #: than one in the registry means a portfolio run already happened.
    if sum(1 for e in _read() if e["doctype"] == "CRM Deal") > 1:
        print(f"ABORT: {REGISTRY} already holds portfolio deals — run cleanup() first.")
        return
    company = _company()
    usd_rate = _fx_rate(company, "USD")
    tender_api.so_board(company)  # ensure default stages exist

    item_code = f"{MARK}-TENDER-ITEM"
    if not frappe.db.exists("Item", item_code):
        it = frappe.new_doc("Item")
        it.update({
            "item_code": item_code, "item_name": "Vagon buksa podshipnigi (demo lot)",
            "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
            "stock_uom": frappe.db.get_value("UOM", {}, "name") or "Nos",
            "is_stock_item": 0,
        })
        it.insert(ignore_permissions=True)
        _register("Item", item_code)

    suppliers = []
    for supplier_name, country, _ccy, _rate in QUOTES:
        sname = f"{MARK} {supplier_name}"
        if not frappe.db.exists("Supplier", sname):
            sup = frappe.new_doc("Supplier")
            sup.update({"supplier_name": sname, "country": _country(country),
                        "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")})
            sup.insert(ignore_permissions=True)
            _register("Supplier", sup.name)
        suppliers.append(sname)

    def customer_for(buyer):
        cname = f"{MARK} {buyer}"[:140]
        if not frappe.db.exists("Customer", cname):
            cu = frappe.new_doc("Customer")
            cu.update({"customer_name": cname,
                       "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
                       "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name")})
            cu.insert(ignore_permissions=True)
            _register("Customer", cu.name)
        return cname

    lots = iter(RAIL_LOTS)
    lot_no = 4300
    made = {k: 0 for k, _n, _r in PLAN}
    won_so_stage = iter(WON_SO_STAGES)

    for stage, count, (lo, hi) in PLAN:
        for _ in range(count):
            subject, buyer = next(lots)
            lot_no += 1
            age = random.randint(lo, hi)
            created = add_days(today(), -age)
            qty = float(random.choice([40, 120, 240, 480]))
            unit_cost = random.uniform(60, 300)

            deal = frappe.new_doc("CRM Deal")
            deal.update({"organization": _org(f"{MARK} UTY lot 2026-{lot_no} — {subject}"),
                         "company": company})
            deal.insert(ignore_permissions=True)
            frappe.db.set_value("CRM Deal", deal.name, "creation",
                                f"{created} 09:00:00", update_modified=False)
            _register("CRM Deal", deal.name)

            intake = {
                "lot_no": f"UZEX-2026-{lot_no}", "buyer": buyer, "unit": "dona",
                "volume": qty,
                "bid_deadline": add_days(created, 12),
                "delivery_deadline": add_days(created, 60),
                "guarantee_amount": random.choice([8, 12, 20]) * 1_000_000,
                "guarantee_return": add_days(created, 90),
                "penalty_pct_per_day": 0.1, "purchase_method": "tender",
                "go_no_go": "", "result": "",
                "notes": "Demo portfoy — UTY 2025-2026.",
            }
            if stage != "seen":
                intake["go_no_go"] = "go"
            tender_api.save_deal_intake(deal.name, json.dumps(intake))
            stamps = {}
            if stage != "seen":
                stamps["go_no_go_at"] = f"{add_days(created, 1)} 10:00:00"

            # quotations: sourcing 2-4 (policy gap), priced/submitted/won/lost/done 5
            sq_n = 0
            if stage == "sourcing":
                sq_n = random.randint(2, 4)
            elif stage in ("priced", "submitted", "won", "lost", "done"):
                sq_n = 5
            rates = sorted(random.uniform(0.82, 1.18) * unit_cost for _ in range(sq_n))
            for i in range(sq_n):
                sq = frappe.new_doc("Supplier Quotation")
                sq.update({"company": company, "supplier": suppliers[i % len(suppliers)],
                           "currency": "USD", "conversion_rate": usd_rate,
                           "transaction_date": add_days(created, 2 + i),
                           "valid_till": add_days(created, 45),
                           "custom_crm_deal": deal.name})
                sq.append("items", {"item_code": item_code, "qty": qty, "rate": round(rates[i], 2)})
                sq.insert(ignore_permissions=True)
                sq.submit()
                _register("Supplier Quotation", sq.name)

            bid_price = 0.0
            if stage in ("priced", "submitted", "won", "lost", "done"):
                pricing = tender_api.save_deal_bid_pricing(deal.name, json.dumps({
                    "mode": "margin", "margin_pct": random.choice([12.0, 15.0, 18.0]),
                    "landed_goods": round(rates[0] * qty, 2),
                }))
                bid_price = flt((pricing.get("pnl") or {}).get("bid_price")) or rates[0] * qty * 1.15

            if stage in ("submitted", "won", "lost", "done"):
                stamps.update({
                    "submitted_at": f"{add_days(created, 10)} 15:00:00",
                    "submitted_by": "demo@mikas.uz",
                    "submission_reference": f"UZEX-SUB-{lot_no}",
                })
            if stage in ("won", "lost", "done"):
                stamps.update({
                    "result": "won" if stage in ("won", "done") else "lost",
                    "result_at": f"{add_days(created, 14)} 11:00:00",
                    "result_by": "demo@mikas.uz",
                    "won_price": round(bid_price, 2) if stage in ("won", "done") else 0,
                })
            if stamps:
                _stamp_intake(deal.name, stamps)

            if stage in ("won", "done"):
                so = frappe.new_doc("Sales Order")
                so_stage = next(won_so_stage) if stage == "won" else random.choice(["Paid", "Closed"])
                so.update({"company": company, "customer": customer_for(buyer),
                           "transaction_date": add_days(created, 16),
                           "delivery_date": add_days(created, 60),
                           "custom_crm_deal": deal.name, "custom_board_stage": so_stage})
                so.append("items", {"item_code": item_code, "qty": qty,
                                    "rate": round(bid_price / qty, 2) if qty else 0,
                                    "delivery_date": add_days(created, 60)})
                so.insert(ignore_permissions=True)
                so.submit()
                _register("Sales Order", so.name)

            frappe.db.commit()
            made[stage] += 1
            print(f"  {stage:9} {deal.name}  {subject[:44]:46} -{age}d")

    print("\nDONE:", made)
    print("Simdi: bench --site mikas.erpstable.com execute stabler.tmp_demo.verify_portfolio")


def verify_portfolio():
    """The funnel endpoint must see at least the planned portfolio."""
    from stabler.api.tender import tender_funnel

    company = _company()
    r = tender_funnel(company)
    plan = {k: n for k, n, _ in PLAN}
    R = []

    def check(name, ok, detail=""):
        R.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -> {detail}" if detail else ""))

    s = r["stages"]
    for k in ("seen", "go", "sourcing", "priced", "submitted"):
        check(f"stage {k} >= {plan[k]}", s.get(k, 0) >= plan[k], f"got {s.get(k, 0)}")
    check(f"won (window) >= {plan['won']}", s.get("won", 0) >= plan["won"], f"got {s.get('won', 0)}")
    check(f"lost (window) >= {plan['lost']}", s.get("lost", 0) >= plan["lost"], f"got {s.get('lost', 0)}")
    check("done bucket >= 4 (2025 archive)", r["so"]["done"] >= plan["done"], f"got {r['so']['done']}")
    check("active contracts >= 4", r["so"]["active"] >= 4, f"got {r['so']['active']}")
    check("policy-gap badge > 0", r["meta"]["sourcing_policy_gap"] >= 1,
          f"got {r['meta']['sourcing_policy_gap']}")
    check("funnel last rung == stages won (lost not counted)",
          r["funnel"][-1]["n"] == s.get("won", 0),
          f"funnel={r['funnel'][-1]['n']} stages.won={s.get('won', 0)}")
    check("win-rate computed", r["kpi"]["win_rate"] is not None, f"{r['kpi']['win_rate']}%")
    print(f"\n{sum(R)}/{len(R)} checks passed" + ("  — PORTFOY HAZIR" if all(R) else ""))
    print("funnel:", [(f["key"], f["n"]) for f in r["funnel"]])
