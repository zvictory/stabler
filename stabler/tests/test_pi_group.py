"""Unit tests for stabler.api._proforma Import PI Group membership rules
(Frappe-free): eligible-set computation + bulk-assignment re-validation.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_pi_group -v

The Frappe-layer endpoints (imports.pi_group_detail / save_pi_group /
delete_pi_group / list_group_eligible_pis / assign_pis_to_group in
stabler/api/imports.py) need a live bench + site to exercise end-to-end
(DB reads/writes, company-scope gate, concurrency check) — those are covered
by manual/integration smoke, not this pure layer.
"""

from __future__ import annotations

import unittest

from stabler.api._proforma import is_group_eligible, validate_assignment

GROUP = "IPG-2026-00001"
OTHER_GROUP = "IPG-2026-00002"
VENDOR_A = "Supplier A"
VENDOR_B = "Supplier B"


class TestIsGroupEligible(unittest.TestCase):
    def test_already_a_member_is_eligible(self):
        # Re-submitting a selection that already includes this PI is a no-op,
        # regardless of supplier/vendor restriction.
        self.assertTrue(is_group_eligible(GROUP, VENDOR_B, GROUP, VENDOR_A))

    def test_unlinked_no_restriction_is_eligible(self):
        self.assertTrue(is_group_eligible(None, VENDOR_B, GROUP, None))
        self.assertTrue(is_group_eligible("", VENDOR_B, GROUP, None))

    def test_unlinked_matching_vendor_is_eligible(self):
        self.assertTrue(is_group_eligible(None, VENDOR_A, GROUP, VENDOR_A))

    def test_unlinked_non_matching_vendor_is_not_eligible(self):
        self.assertFalse(is_group_eligible(None, VENDOR_B, GROUP, VENDOR_A))

    def test_linked_to_a_different_group_is_not_eligible(self):
        # A PI belongs to <=1 group — already grouped elsewhere blocks reassignment
        # even when the supplier would otherwise match.
        self.assertFalse(is_group_eligible(OTHER_GROUP, VENDOR_A, GROUP, VENDOR_A))
        self.assertFalse(is_group_eligible(OTHER_GROUP, VENDOR_A, GROUP, None))

    def test_no_supplier_with_vendor_restriction_is_not_eligible(self):
        self.assertFalse(is_group_eligible(None, None, GROUP, VENDOR_A))


class TestValidateAssignment(unittest.TestCase):
    def test_all_eligible_returns_empty(self):
        rows = [
            {"name": "PI-1", "supplier": VENDOR_A, "import_pi_group": None},
            {"name": "PI-2", "supplier": VENDOR_A, "import_pi_group": GROUP},
        ]
        self.assertEqual(validate_assignment(rows, GROUP, VENDOR_A), [])

    def test_no_vendor_restriction_any_unlinked_pi_ok(self):
        rows = [
            {"name": "PI-1", "supplier": VENDOR_A, "import_pi_group": None},
            {"name": "PI-2", "supplier": VENDOR_B, "import_pi_group": None},
        ]
        self.assertEqual(validate_assignment(rows, GROUP, None), [])

    def test_wrong_vendor_flagged(self):
        rows = [
            {"name": "PI-1", "supplier": VENDOR_A, "import_pi_group": None},
            {"name": "PI-2", "supplier": VENDOR_B, "import_pi_group": None},
        ]
        self.assertEqual(validate_assignment(rows, GROUP, VENDOR_A), ["PI-2"])

    def test_linked_elsewhere_flagged(self):
        rows = [
            {"name": "PI-1", "supplier": VENDOR_A, "import_pi_group": OTHER_GROUP},
        ]
        self.assertEqual(validate_assignment(rows, GROUP, VENDOR_A), ["PI-1"])

    def test_empty_selection_returns_empty(self):
        self.assertEqual(validate_assignment([], GROUP, VENDOR_A), [])

    def test_none_rows_survive_without_crashing(self):
        # A malformed/None row must not raise — it's treated as an empty dict,
        # which (correctly) fails a vendor restriction since it has no supplier.
        rows = [None, {"name": "PI-1", "supplier": VENDOR_A, "import_pi_group": None}]
        self.assertEqual(validate_assignment(rows, GROUP, VENDOR_A), [None])


if __name__ == "__main__":
    unittest.main()
