import os
import unittest

API_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "api", "tender_desk.py")

class TestTenderDeskApiSource(unittest.TestCase):
    def setUp(self):
        with open(API_FILE, encoding="utf-8") as f:
            self.source = f.read()

    def test_no_app_routes_in_source(self):
        self.assertNotIn("/app/", self.source, "tender_desk.py must not contain /app/ links")

    def test_list_pending_unwraps_requests(self):
        # list_pending returns {"requests": [...], "total": n, "can_approve": bool}.
        # Passing that envelope on as if it were the row list makes _desk_rules
        # iterate its three KEYS: measured 2026-08-01 on mikas, the desk showed
        # "Approval required: Document requests / total / can_approve", counted them
        # in due_today, and every real pending approval vanished. Both halves fail
        # silently -- no exception, no empty list, just wrong work on a work board --
        # so the call site is pinned here rather than left to review.
        for idx, line in enumerate(self.source.splitlines(), 1):
            if "list_pending(" in line and not line.lstrip().startswith(("#", "from ", "import ")):
                self.assertIn("requests", line,
                              f"Line {idx}: list_pending() returns an envelope; unwrap ['requests']")

    def test_no_sql_aggregation_functions_in_select(self):
        lines = self.source.splitlines()
        for idx, line in enumerate(lines, 1):
            if "frappe.db.sql" in line or "SELECT" in line.upper():
                lower_line = line.lower()
                if "select" in lower_line:
                    self.assertNotIn("count(", lower_line, f"Line {idx}: SQL count() in string SELECT is forbidden")
                    self.assertNotIn("sum(", lower_line, f"Line {idx}: SQL sum() in string SELECT is forbidden")

    def test_no_queries_in_loops(self):
        lines = self.source.splitlines()
        in_loop = False
        loop_indent = 0
        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            indent = len(line) - len(line.lstrip())
            if stripped.startswith(("for ", "while ")) and not stripped.endswith(":"):
                pass
            elif stripped.startswith(("for ", "while ")) and stripped.endswith(":"):
                in_loop = True
                loop_indent = indent
            elif in_loop and indent <= loop_indent and stripped:
                in_loop = False

            if in_loop:
                self.assertNotIn("frappe.get_all(", stripped, f"Line {idx}: DB query in loop")
                self.assertNotIn("frappe.db.sql(", stripped, f"Line {idx}: DB query in loop")
                self.assertNotIn("frappe.get_doc(", stripped, f"Line {idx}: DB query in loop")

if __name__ == "__main__":
    unittest.main()
