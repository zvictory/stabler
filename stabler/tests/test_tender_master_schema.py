"""Contract guards for the Tender Master schema and CRM Deal lot link."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
TENDER_MASTER_JSON = _ROOT / "stabler" / "doctype" / "tender_master" / "tender_master.json"
PATCH = _ROOT / "patches" / "v61_tender_master_link.py"
PATCHES = _ROOT / "patches.txt"


class TestTenderMasterSchema(unittest.TestCase):
	def test_parent_schema_and_lot_link_patch_are_registered(self):
		schema = json.loads(TENDER_MASTER_JSON.read_text())
		fields = {field["fieldname"]: field for field in schema["fields"]}
		self.assertEqual(fields["company"]["options"], "Company")
		self.assertEqual(fields["company"]["reqd"], 1)
		self.assertEqual(fields["status"]["options"], "New\nSourcing\nBid Preparation\nSubmitted\nWon\nLost\nCancelled")
		patch_source = PATCH.read_text()
		self.assertIn('"custom_parent_tender"', patch_source)
		self.assertIn('"options": "Tender Master"', patch_source)
		self.assertIn("stabler.patches.v61_tender_master_link.execute", PATCHES.read_text())


if __name__ == "__main__":
	unittest.main()
