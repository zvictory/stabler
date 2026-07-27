import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENT_PATH = ROOT / "stabler/public/js/pages/imports/CiLogisticsOverview.vue"
CI_FORM_PATH = ROOT / "stabler/public/js/pages/imports/CommercialInvoiceForm.vue"
SOURCE = COMPONENT_PATH.read_text() if COMPONENT_PATH.exists() else ""
CI_FORM = CI_FORM_PATH.read_text()


class TestCiLogisticsWorkspaceSource(unittest.TestCase):
	def test_component_has_no_desk_redirect_or_manual_striping(self):
		self.assertNotIn("/app/", SOURCE)
		self.assertNotIn("table-striped", SOURCE)

	def test_component_exposes_packing_and_grn_actions(self):
		self.assertIn("packingSummary.reconciliation", SOURCE)
		self.assertIn("createGrnForCi", SOURCE)
		self.assertIn("refreshGrnExpectedQuantities", SOURCE)
		self.assertIn("/imports/grn-checklists/", SOURCE)

	def test_component_covers_operational_states_and_feedback(self):
		for invariant in (
			"loading",
			"busy",
			"Incomplete",
			"Mismatch",
			"Ready",
			"expected_snapshot_locked",
			"actionError",
			"toast.error",
		):
			with self.subTest(invariant=invariant):
				self.assertIn(invariant, SOURCE)

	def test_reconciliation_numbers_are_monospace(self):
		self.assertGreaterEqual(SOURCE.count("font-monospace"), 4)

	def test_refresh_is_available_only_for_an_unlocked_draft_grn(self):
		self.assertRegex(
			SOURCE,
			r"(?s)const canRefreshExpected = computed\(.*Boolean\(props\.grn\?\.name\).*"
			r"Number\(props\.grn\.docstatus\) === 0.*!props\.grn\.expected_snapshot_locked",
		)
		self.assertRegex(
			SOURCE,
			r'(?s)<button\s+v-if="canRefreshExpected".*?@click="refreshExpected"',
		)
		self.assertRegex(
			SOURCE,
			r"async function refreshExpected\(\) \{\s*if \(!canRefreshExpected\.value\) return;",
		)

	def test_actions_require_a_loaded_commercial_invoice_identity(self):
		self.assertRegex(
			SOURCE,
			r"(?s)async function createOrOpenGrn\(\) \{\s*if \(!props\.commercialInvoice\) \{.*?return;",
		)
		self.assertEqual(
			SOURCE.count(':disabled="busy || loading || !commercialInvoice"'),
			2,
		)
		self.assertRegex(
			CI_FORM,
			r'(?s)<CiLogisticsOverview\s+v-if="!isCreate && form\.name"\s+'
			r':commercial-invoice="form\.name"',
		)

	def test_ci_form_mounts_focused_component_with_payload_and_reload(self):
		self.assertIn("import CiLogisticsOverview", CI_FORM)
		self.assertIn("<CiLogisticsOverview", CI_FORM)
		self.assertIn(':packing-summary="form.packing_summary"', CI_FORM)
		self.assertIn(':grn="form.grn"', CI_FORM)
		self.assertIn(':loading="loading"', CI_FORM)
		self.assertIn('@reload="loadDoc"', CI_FORM)


if __name__ == "__main__":
	unittest.main()
