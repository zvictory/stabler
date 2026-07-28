"""Structural guards for the imports workflow flow-board (msa)."""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
API = os.path.join(_ROOT, "api", "imports.py")
VUE = os.path.join(_ROOT, "public", "js", "pages", "imports", "ImportsFlow.vue")
DASH = os.path.join(_ROOT, "public", "js", "pages", "imports", "ImportsDashboard.vue")


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def body(src, name):
    m = re.search(rf"^def {name}\(", src, re.M)
    assert m, f"{name} not found"
    tail = src[m.start():]
    nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
    return tail[: nxt.start() + 1] if nxt else tail


class EndpointTest(unittest.TestCase):
    def setUp(self):
        self.src = read(API)
        self.body = body(self.src, "imports_flow")

    def test_whitelisted_and_gated(self):
        self.assertRegex(self.src, r"@frappe\.whitelist\(\)\ndef imports_flow\(")
        self.assertIn("_assert_imports_access(company)", self.body)

    def test_read_only(self):
        for token in (".save(", ".insert(", "db_set(", "db.set_value(", "db.commit("):
            with self.subTest(token=token):
                self.assertNotIn(token, self.body)

    def test_one_query_per_doctype(self):
        # The rule is N+1 avoidance: ONE query per doctype, never one per status.
        # How the rows are tallied (SQL GROUP BY vs. Python) is an implementation
        # detail — pinning the "how" is what let a query Frappe rejects at runtime
        # ship green once already.
        helper = body(self.src, "_status_counts")
        self.assertEqual(helper.count("frappe.get_all("), 1)
        self.assertEqual(helper.count("frappe.db.count("), 0)
        for doctype in ("Proforma Invoice", "Commercial Invoice", "Import Container", "Import Truck"):
            with self.subTest(doctype=doctype):
                self.assertIn(f'_status_counts("{doctype}", company)', self.body)

    def test_no_sql_function_in_a_string_select(self):
        # Frappe v16 throws "SQL functions are not allowed as strings in SELECT"
        # — a fields=["count(name) as n"] parses fine and passes every source
        # check, then 500s on the live site. Caught in prod on msa, 2026-07-28.
        offenders = re.findall(r'"\s*(?:count|sum|avg|min|max)\s*\([^"]*"', self.src, re.I)
        self.assertEqual(offenders, [], f"SQL function in a string SELECT: {offenders}")

    def test_drift_reuses_the_sea_lifecycle_rule(self):
        # One drift rule in the whole app: the CI panel's. No re-derivation.
        self.assertIn("sea_lifecycle.summarise(", self.body)

    def test_gate_reuses_departure_math(self):
        self.assertIn("departure_math.may_depart(", self.body)
        self.assertIn("has_valid_vet_cert(", self.body)

    def test_gate_tolerates_pre_v55_sites(self):
        self.assertIn("required_for_departure", self.body)
        self.assertIn("has_required_flag", self.body)


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.vue = read(VUE)

    def test_calls_the_endpoint(self):
        self.assertIn('call("stabler.api.imports.imports_flow"', self.vue)

    def test_chips_deep_link_to_the_original_list_with_status(self):
        # A count must open exactly those records — its own list, filtered.
        self.assertIn("query: { status: chip.key }", self.vue)
        for base in ("/imports/proformas", "/imports/commercial-invoices",
                     "/imports/containers", "/imports/trucks",
                     "/imports/grn-checklists", "/imports/landed-cost-bills",
                     "/imports/customs"):
            with self.subTest(base=base):
                self.assertIn(base, self.vue)

    def test_no_desk_links_and_graphics_only(self):
        self.assertNotIn('"/app', self.vue)
        self.assertNotIn("'/app", self.vue)
        self.assertNotIn("<table", self.vue)

    def test_all_user_facing_strings_are_translated(self):
        tpl = self.vue[self.vue.index("<template>"):]
        bare = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][^<{}]{3,40})\s*<", tpl)
        offenders = [b.strip() for b in bare if b.strip()]
        self.assertEqual(offenders, [], f"untranslated template text: {offenders}")

    def test_mounted_on_the_imports_dashboard(self):
        dash = read(DASH)
        self.assertIn("ImportsFlow", dash)
        self.assertIn("<ImportsFlow />", dash)


class ListDeepLinkTest(unittest.TestCase):
    def test_target_lists_read_status_from_the_route(self):
        # The deep link only works if the list initialises its filter from
        # ?status= — all chip targets must do so.
        for page in ("ProformaInvoices", "CommercialInvoices", "ImportContainers",
                     "ImportTrucks", "GRNChecklists", "LandedCostBills"):
            with self.subTest(page=page):
                src = read(os.path.join(_ROOT, "public", "js", "pages", "imports", f"{page}.vue"))
                self.assertIn("route.query.status", src, f"{page} ignores ?status=")


class RouteIsDeclaredTest(unittest.TestCase):
    """No .vue may read `route.` without calling useRoute().

    Reading ?status= was shipped into two list pages that imported only
    useRouter — `route` was never bound, so setup() threw
    "ReferenceError: route is not defined" and the whole page went blank.
    Every source check passed: the string "route.query.status" was right
    there. Caught in the browser on msa, 2026-07-28. Pin the binding, not
    the token.
    """

    USES = re.compile(r"(?<![\w.$])route\s*\.\s*(?:query|params|path|name|fullPath|hash|meta)\b")
    DECLARES = re.compile(r"(?:const|let)\s+route\s*=|(?:const|let)\s*\{[^}]*\broute\b[^}]*\}\s*=")

    def test_every_vue_that_reads_route_binds_it(self):
        root = os.path.join(_ROOT, "public", "js")
        offenders = []
        for base, _dirs, files in os.walk(root):
            for fn in files:
                if not fn.endswith(".vue"):
                    continue
                path = os.path.join(base, fn)
                src = read(path)
                if self.USES.search(src) and not self.DECLARES.search(src):
                    offenders.append(os.path.relpath(path, root))
        self.assertEqual(sorted(offenders), [], f"`route` used but never bound: {sorted(offenders)}")


if __name__ == "__main__":
    unittest.main()
