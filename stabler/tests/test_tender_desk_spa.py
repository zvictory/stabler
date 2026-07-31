import os
import unittest

SPA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "js", "pages", "tender", "OperationsDesk.vue")

class TestTenderDeskSpaSource(unittest.TestCase):
    def setUp(self):
        with open(SPA_FILE, encoding="utf-8") as f:
            self.source = f.read()

    def test_no_app_routes_in_vue_source(self):
        self.assertNotIn("/app/", self.source, "OperationsDesk.vue must not contain /app/ links")

    def test_no_table_striped_class(self):
        self.assertNotIn("table-striped", self.source, "OperationsDesk.vue must not add table-striped manually")

    def test_uses_skeleton_rows(self):
        self.assertIn("SkeletonRows", self.source, "OperationsDesk.vue must use SkeletonRows during loading")

    def test_uses_request_token_pattern(self):
        self.assertIn("reqToken", self.source, "OperationsDesk.vue must use request-token pattern for race safety")

if __name__ == "__main__":
    unittest.main()
