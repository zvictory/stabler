NEW_TESTS = '''

class TestSavingTheAward(unittest.TestCase):
	"""Sourcing writes the award; the numbers behind it are taken server-side.

	A payload that carries its own comparison is a payload that can carry a
	flattering one, and the snapshot is the whole point of the record: it is what
	the decision was made against, not what the totals happen to be today.
	"""

	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def _save(self, **overrides):
		payload = {
			"deal": "LOT-A",
			"selected_quotation": "SQ-SUBMITTED",
			"selection_reason": "Delivery window fits the tender deadline.",
			"policy_exception": 1,
			"exception_reason": "Only two suppliers hold the certificate.",
			"company": "ACME",
		}
		payload.update(overrides)
		return self.api.save_sourcing_decision(**payload)

	def test_cheapest_and_selected_are_recorded_as_two_facts(self):
		"""The interesting award is the one where they differ; a record that only
		keeps the choice cannot show that it was a choice."""
		result = self._save()
		doc = self.fake.created[-1]
		self.assertEqual(doc["selected_quotation"], "SQ-SUBMITTED")
		self.assertEqual(doc["cheapest_quotation"], "SQ-DRAFT")
		self.assertEqual(result["cheapest_quotation"], "SQ-DRAFT")

	def test_the_snapshot_is_computed_here_not_posted(self):
		self._save()
		snapshot = json.loads(self.fake.created[-1]["comparison_snapshot"])
		self.assertEqual(snapshot["base_currency"], "UZS")
		self.assertEqual([r["quotation"] for r in snapshot["rows"]], ["SQ-DRAFT", "SQ-SUBMITTED"])
		self.assertEqual(snapshot["taken_at"], "2026-08-02 10:00:00")

	def test_the_policy_counts_travel_with_the_decision(self):
		"""The controller enforces the exception rule from these two numbers, so
		they have to be on the document, not only in the endpoint that wrote it."""
		self._save()
		doc = self.fake.created[-1]
		self.assertEqual(doc["quotation_count"], 2)
		self.assertEqual(doc["country_count"], 2)

	def test_a_quotation_from_another_lot_cannot_be_awarded(self):
		with self.assertRaises(ValueError):
			self._save(selected_quotation="SQ-OTHER-LOT")
		self.assertEqual(self.fake.created, [])

	def test_a_reason_is_required(self):
		"""An award with no reason is a click, not a decision."""
		with self.assertRaises(ValueError):
			self._save(selection_reason="   ")

	def test_a_lot_gets_one_open_award_at_a_time(self):
		"""Two drafts are two answers to "who won", and nothing in the record
		says which one the buyer acted on. LOT-A already carries TSD-DRAFT."""
		fake = _FakeFrappe()
		api = _load_api(fake)
		with self.assertRaises(ValueError):
			api.save_sourcing_decision(
				deal="LOT-A", selected_quotation="SQ-SUBMITTED", selection_reason="Second opinion.",
				policy_exception=1, exception_reason="…", company="ACME",
			)

	def test_only_the_sourcing_window_may_write_one(self):
		"""Separation of duties: the same person must not both pick and approve."""
		api = _load_api(self.fake, views=("director",))
		with self.assertRaises(PermissionError):
			api.save_sourcing_decision(
				deal="LOT-A", selected_quotation="SQ-SUBMITTED", selection_reason="x",
				policy_exception=1, exception_reason="y", company="ACME",
			)

	def test_the_usual_three_gates_still_apply(self):
		api = _load_api(self.fake, tender_allowed=False)
		with self.assertRaises(PermissionError):
			api.save_sourcing_decision(
				deal="LOT-A", selected_quotation="SQ-SUBMITTED", selection_reason="x", company="ACME"
			)
		with self.assertRaises(PermissionError):
			self._save(deal="LOT-OTHER")
		with self.assertRaises(PermissionError):
			self._save(company="Other Co")


class TestApprovingTheAward(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_the_stamp_is_written_by_the_server(self):
		result = self.api.approve_sourcing_decision("TSD-DRAFT", company="ACME")
		doc = self.fake.docs[("Tender Sourcing Decision", "TSD-DRAFT")]
		self.assertEqual(doc["status"], "Approved")
		self.assertEqual(doc["approved_by"], "sourcing@example.com")
		self.assertEqual(doc["approved_at"], "2026-08-02 10:00:00")
		self.assertEqual(result["status"], "Approved")

	def test_the_controller_is_told_this_is_the_approval_path(self):
		"""Without the flag the controller refuses the transition — which is what
		stops an ordinary save from approving a decision."""
		self.api.approve_sourcing_decision("TSD-DRAFT", company="ACME")
		doc = self.fake.docs[("Tender Sourcing Decision", "TSD-DRAFT")]
		self.assertTrue(doc.flags.stabler_approving)

	def test_only_a_director_may_approve(self):
		api = _load_api(self.fake, views=("sourcing",))
		with self.assertRaises(PermissionError):
			api.approve_sourcing_decision("TSD-DRAFT", company="ACME")

	def test_an_approved_decision_cannot_be_approved_again(self):
		with self.assertRaises(ValueError):
			self.api.approve_sourcing_decision("TSD-APPROVED", company="ACME")

	def test_a_decision_from_another_company_is_refused(self):
		with self.assertRaises(PermissionError):
			self.api.approve_sourcing_decision("TSD-OTHER-COMPANY", company="ACME")

	def test_the_module_gate_still_applies(self):
		api = _load_api(self.fake, tender_allowed=False)
		with self.assertRaises(PermissionError):
			api.approve_sourcing_decision("TSD-DRAFT", company="ACME")


class TestReadingTheAward(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_the_open_decision_comes_back_with_its_comparison(self):
		"""One call, because the screen shows them together and two calls can
		disagree about what "now" was."""
		result = self.api.get_sourcing_decision("LOT-A", company="ACME")
		self.assertEqual(result["decision"]["name"], "TSD-DRAFT")
		self.assertEqual(result["comparison"]["count"], 2)

	def test_a_lot_without_an_award_reads_as_none_not_an_error(self):
		result = self.api.get_sourcing_decision("LOT-B", company="ACME")
		self.assertIsNone(result["decision"])

	def test_reading_is_gated_like_everything_else(self):
		with self.assertRaises(PermissionError):
			self.api.get_sourcing_decision("LOT-DENIED", company="ACME")
'''
