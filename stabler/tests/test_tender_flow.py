"""Süreç akışı — adım performansı toplaması.

Ekranın tek işi "nerede takıldık" sorusuna cevap vermek, ve bu cevabın iki
yanlış yolu var: bilmediğini biliyormuş gibi sunmak, ya da boş bir adımı
tıkanmış (veya tersi) göstermek. Bu dosya ikisini de kapatıyor.
"""

import unittest

from stabler.api import _tender_flow as flow
from stabler.api import _tender_sla as sla

TODAY = "2026-08-01"


def rows_for(deals, today=TODAY, overrides=None):
	return {r["stage"]: r for r in flow.step_rows(deals, today, overrides)}


class TestUnknownIsNotZero(unittest.TestCase):
	"""v66 öncesi taşınmış her anlaşmanın damgası yok. Onları ortalamaya 0 gün
	diye katmak ortalamayı aşağı çeker ve tıkanmış adımı sağlıklı gösterir."""

	def test_an_unstamped_deal_is_counted_as_open_but_not_averaged(self):
		row = rows_for(
			[
				{"stage": "sourcing", "entered_at": "2026-07-18"},
				{"stage": "sourcing", "entered_at": None},
			]
		)["sourcing"]
		self.assertEqual(row["open"], 2)
		self.assertEqual(row["unmeasured"], 1)
		self.assertEqual(row["avg_days"], 14.0)

	def test_a_stage_where_nothing_can_be_measured_says_so(self):
		row = rows_for([{"stage": "priced", "entered_at": None}])["priced"]
		self.assertEqual(row["state"], "unknown")
		self.assertIsNone(row["avg_days"])
		self.assertEqual(row["open"], 1)

	def test_unknown_is_not_reported_as_within_the_limit(self):
		"""Ekranın en dürüst olması gereken yerinde iyimser bir yalan."""
		self.assertNotEqual(rows_for([{"stage": "priced", "entered_at": None}])["priced"]["state"], "in")


class TestEmptyIsNotUnknown(unittest.TestCase):
	"""Boş adımda bekleyen iş YOK; ölçülemeyen adımda bekleyen iş VAR ama ne
	kadar beklediğini bilmiyoruz. İkisini tek kelimeye toplamak, tıkanmış
	olabilecek bir adımı boş göstermek demek."""

	def test_a_stage_with_no_deals_is_empty(self):
		row = rows_for([{"stage": "seen", "entered_at": "2026-08-01"}])["go"]
		self.assertEqual(row["open"], 0)
		self.assertEqual(row["state"], "empty")

	def test_a_stage_with_deals_but_no_stamps_is_unknown(self):
		self.assertEqual(rows_for([{"stage": "go", "entered_at": None}])["go"]["state"], "unknown")


class TestTheStateFollowsTheThreshold(unittest.TestCase):
	def test_well_inside_the_limit(self):
		self.assertEqual(
			rows_for([{"stage": "sourcing", "entered_at": "2026-07-29"}])["sourcing"]["state"], "in"
		)

	def test_the_last_quarter_is_the_edge(self):
		self.assertEqual(
			rows_for([{"stage": "sourcing", "entered_at": "2026-07-21"}])["sourcing"]["state"], "edge"
		)

	def test_past_the_limit_is_out(self):
		self.assertEqual(
			rows_for([{"stage": "sourcing", "entered_at": "2026-07-15"}])["sourcing"]["state"], "out"
		)

	def test_a_short_threshold_still_gets_an_edge(self):
		"""3 günlük eşikte tam çeyrek 0 gün eder; taban olmasa kısa adımlar
		hiç uyarmadan kırmızıya atlardı — `_tender_sla` ile aynı taban."""
		self.assertEqual(
			rows_for([{"stage": "priced", "entered_at": "2026-07-30"}])["priced"]["state"], "edge"
		)

	def test_a_tenant_override_moves_the_line(self):
		deals = [{"stage": "sourcing", "entered_at": "2026-07-15"}]
		self.assertEqual(rows_for(deals)["sourcing"]["state"], "out")
		self.assertEqual(rows_for(deals, overrides={"sourcing": 30})["sourcing"]["state"], "in")

	def test_a_switched_off_stage_is_never_out(self):
		row = rows_for([{"stage": "seen", "entered_at": "2020-01-01"}], overrides={"seen": 0})["seen"]
		self.assertIsNone(row["sla_days"])
		self.assertEqual(row["state"], "unknown")


class TestTheBottleneckIsTheWorstRatioNotTheWorstGap(unittest.TestCase):
	"""30 günlük eşiği 3 gün aşan adım ile 3 günlük eşiği 3 gün aşan adım aynı
	değil — ikincisi iki katına çıkmış demektir."""

	def test_the_proportionally_worst_step_wins(self):
		# Vaka AYIRT EDİCİ olmalı: ilk yazdığımda fark da oran da aynı adımı
		# seçiyordu, dolayısıyla "fark kullan" mutasyonu testten sağ çıktı.
		#   sourcing 20/14 → oran 1.43 · fark 6
		#   priced    7/3  → oran 2.33 · fark 4
		# Oran priced der, fark sourcing. İkisi ayrışmazsa iddia bir şey
		# kanıtlamaz.
		rows = flow.step_rows(
			[
				{"stage": "sourcing", "entered_at": "2026-07-12"},
				{"stage": "priced", "entered_at": "2026-07-25"},
			],
			"2026-08-01",
		)
		self.assertEqual(flow.bottleneck(rows), "priced")

	def test_no_bottleneck_when_everything_is_inside(self):
		rows = flow.step_rows([{"stage": "sourcing", "entered_at": "2026-07-30"}], "2026-08-01")
		self.assertIsNone(flow.bottleneck(rows))

	def test_a_stage_without_a_threshold_can_never_be_the_bottleneck(self):
		rows = flow.step_rows([{"stage": "seen", "entered_at": "2020-01-01"}], "2026-08-01", {"seen": 0})
		self.assertIsNone(flow.bottleneck(rows))


class TestTheTableShape(unittest.TestCase):
	def test_every_working_stage_gets_a_row_even_when_empty(self):
		"""Adım tablosundan bir satırın kaybolması, o adımın var olmadığı
		izlenimi verir — oysa yalnızca boştur."""
		rows = flow.step_rows([], "2026-08-01")
		self.assertEqual([r["stage"] for r in rows], list(flow.WORKING_STAGES))

	def test_finished_stages_are_not_in_the_table(self):
		"""Tablo BEKLEYEN işi anlatıyor; kazanılmış bir anlaşma beklemiyor."""
		for stage in ("won", "lost"):
			with self.subTest(stage=stage):
				self.assertNotIn(stage, flow.WORKING_STAGES)

	def test_an_unknown_stage_is_ignored_not_invented(self):
		rows = rows_for([{"stage": "bilinmeyen", "entered_at": "2026-08-01"}])
		self.assertNotIn("bilinmeyen", rows)
		self.assertEqual(sum(r["open"] for r in rows.values()), 0)

	def test_the_worst_case_is_reported_beside_the_average(self):
		"""Ortalama tek başına saklar: 1 ve 29 günün ortalaması 15, ama 29
		günlük iş bugün müdahale ister."""
		row = rows_for(
			[
				{"stage": "submitted", "entered_at": "2026-07-31"},
				{"stage": "submitted", "entered_at": "2026-07-03"},
			]
		)["submitted"]
		self.assertEqual(row["avg_days"], 15.0)
		self.assertEqual(row["worst_days"], 29)

	def test_the_stages_match_the_thresholds_that_exist(self):
		"""Eşiksiz bir çalışma adımı ya da adımsız bir eşik, ikisi de sessiz
		bir boşluk."""
		from stabler.api._tender_sla import DEFAULT_STAGE_SLA_DAYS

		self.assertEqual(set(flow.WORKING_STAGES), set(DEFAULT_STAGE_SLA_DAYS))


class TestTheWorstDealCarriesItsOwnVerdict(unittest.TestCase):
	"""A step's average being inside its threshold is not the same as no deal in
	that step being late — and finding late work is the only reason this screen
	exists. `worst_days` was the one number on the table with no verdict beside
	it, while the two functions that would judge it (`_tender_sla.severity` and
	`overdue_by`) were written, documented and called by nothing outside their
	own tests. Measured 2026-09-02: on seed data all four measurable worsts
	carry one — two `crit`, two exactly `today`.
	"""

	def test_a_step_whose_average_is_inside_can_hold_a_deal_that_is_over(self):
		# WHAT WOULD MAKE THIS FAIL: reusing the row's `state` for the worst
		# number. `state` is computed from the AVERAGE, so the reader would be
		# told this step is at the edge while one of its two deals is eight days
		# past the threshold. That deal is exactly what the screen is for.
		row = rows_for(
			[
				{"stage": "sourcing", "entered_at": "2026-07-30"},
				{"stage": "sourcing", "entered_at": "2026-07-10"},
			]
		)["sourcing"]
		self.assertEqual(row["avg_days"], 12.0)
		self.assertEqual(row["state"], "edge")
		self.assertEqual(row["worst_days"], 22)
		self.assertEqual(row["worst_state"], "crit")
		self.assertEqual(row["worst_over"], 8)

	def test_a_deal_sitting_exactly_on_its_threshold_is_not_yet_over_it(self):
		# WHAT WOULD MAKE THIS FAIL: `>=` where `>` belongs. Two of the five
		# seeded steps sit exactly on their limit (3 of 3, 5 of 5); calling
		# those `crit` would put two permanent red marks on a healthy pipeline
		# and teach the reader to ignore the colour.
		row = rows_for([{"stage": "seen", "entered_at": "2026-07-29"}])["seen"]
		self.assertEqual(row["worst_days"], 3)
		self.assertEqual(row["worst_state"], "today")
		self.assertEqual(row["worst_over"], 0)

	def test_the_verdict_follows_the_worst_deal_and_not_the_average(self):
		# WHAT WOULD MAKE THIS FAIL: judging the average and labelling it as the
		# worst. Here the average is comfortably `in` and the worst deal is
		# already `soon`; a verdict computed from the average would say nothing
		# is happening in a step where something is.
		row = rows_for(
			[
				{"stage": "priced", "entered_at": "2026-08-01"},
				{"stage": "priced", "entered_at": "2026-07-30"},
			]
		)["priced"]
		self.assertEqual(row["avg_days"], 1.0)
		self.assertEqual(row["state"], "in")
		self.assertEqual(row["worst_days"], 2)
		self.assertEqual(row["worst_state"], "soon")

	def test_a_step_with_nothing_measurable_invents_no_verdict(self):
		# WHAT WOULD MAKE THIS FAIL: treating a missing stamp as zero days and
		# calling it healthy — the exact lie this module exists to refuse. There
		# is no worst deal here because no deal in this step has a clock.
		row = rows_for([{"stage": "submitted", "entered_at": None}])["submitted"]
		self.assertIsNone(row["worst_days"])
		self.assertEqual(row["worst_state"], "info")
		self.assertEqual(row["worst_over"], 0)

	def test_a_switched_off_step_can_never_produce_a_late_verdict(self):
		# WHAT WOULD MAKE THIS FAIL: falling back to the built-in default when
		# an administrator clears the field. A step with no threshold has no
		# patience to exceed; marking a six-year-old deal `crit` there would
		# silently undo the decision to stop tracking it.
		row = rows_for([{"stage": "seen", "entered_at": "2020-01-01"}], overrides={"seen": 0})["seen"]
		self.assertIsNone(row["sla_days"])
		self.assertEqual(row["worst_state"], "info")
		self.assertEqual(row["worst_over"], 0)

	def test_the_verdict_is_the_one_the_sla_module_already_defines(self):
		# WHAT WOULD MAKE THIS FAIL: a second copy of the severity thresholds
		# living here. Two copies of "the last quarter, floored at one day"
		# drift, and the one nobody exercises is the one that rots — which is
		# how `severity` came to be dead in production in the first place.
		for stage, entered in (
			("seen", "2026-07-29"),
			("go", "2026-07-27"),
			("sourcing", "2026-07-01"),
			("priced", "2026-07-30"),
		):
			with self.subTest(stage=stage):
				row = rows_for([{"stage": stage, "entered_at": entered}])[stage]
				self.assertEqual(row["worst_state"], sla.severity(stage, entered, TODAY))
				self.assertEqual(row["worst_over"], sla.overdue_by(stage, entered, TODAY))


class TestAThresholdSaysWhereItCameFrom(unittest.TestCase):
	"""The panel foot promises *"Thresholds come from Stabler Settings, per
	company"* and nothing on screen distinguished a tenant's number from the
	built-in one.

	Measured 2026-09-02: the `stage_sla` key already on the wire CANNOT answer
	this. `stage_sla_for` returns `dict(DEFAULT_STAGE_SLA_DAYS)` verbatim when a
	company has no settings row (`stabler_settings.py:134-135`), so the payload
	is byte-identical whether the tenant configured nothing or configured the
	default numbers. What the data can honestly support is a statement about the
	VALUE, not about who typed it — and the words on screen say only that.
	"""

	def test_an_untouched_step_reads_as_the_built_in_number(self):
		self.assertEqual(rows_for([])["sourcing"]["sla_source"], "default")

	def test_a_number_the_tenant_changed_is_distinguishable_from_the_default(self):
		# WHAT WOULD MAKE THIS FAIL: shipping `stage_sla` alone and asking the
		# screen to work it out. A director reading `threshold 14 days` cannot
		# tell whether their company chose it, and the foot's promise makes them
		# assume it did.
		self.assertEqual(rows_for([], overrides={"sourcing": 21})["sourcing"]["sla_source"], "tenant")

	def test_a_step_switched_off_is_not_a_step_nobody_configured(self):
		# WHAT WOULD MAKE THIS FAIL: rendering both as *not tracked*. A
		# threshold of 0 is an administrator switching a step off; showing that
		# identically to an unconfigured step hides a deliberate decision.
		row = rows_for([], overrides={"seen": 0})["seen"]
		self.assertIsNone(row["sla_days"])
		self.assertEqual(row["sla_source"], "off")

	def test_a_tenant_number_equal_to_the_default_is_not_claimed_as_a_choice(self):
		# WHAT WOULD MAKE THIS FAIL: promising more than the wire can prove.
		# This case is INDISTINGUISHABLE from an unconfigured company, so the
		# row reports `default` and the screen's wording is a claim about the
		# value ("matches the built-in default"), never about provenance.
		self.assertEqual(rows_for([], overrides={"seen": 3})["seen"]["sla_source"], "default")

	def test_every_working_step_can_answer_the_question(self):
		# WHAT WOULD MAKE THIS FAIL: a stage reaching the table with no source
		# word, which would render as a blank line under one threshold and read
		# as a rendering bug rather than as missing information.
		for row in flow.step_rows([], TODAY):
			with self.subTest(stage=row["stage"]):
				self.assertIn(row["sla_source"], ("default", "tenant", "off"))


if __name__ == "__main__":
	unittest.main()
