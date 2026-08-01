"""Demo tohumlayıcının güvenlik ve dürüstlük sözleşmesi.

Bu betik CANLI bir siteye yazıyor. İki şeyi yanlış yapması hâlinde zarar
geri alınamaz: işaretsiz kayda dokunmak, ya da demo'yu gerçekten ayırt
edilemez hâle getirmek. Üçüncü bir risk daha var ve o sessiz: demo veriyi
"güzel" kurmak — her adımı eşiğin içinde, her damgayı dolu — ki o zaman
ekranların dürüstlüğü hiç sınanmamış olur.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = (ROOT / "maintenance/seed_tender_demo.py").read_text(encoding="utf-8")


def _fn(name: str) -> str:
	block = SEED[SEED.index(f"def {name}("):]
	nxt = re.search(r"\n(?:def |\Z)", block[1:])
	return block[: nxt.start() + 1] if nxt else block


class TestItCannotTouchRealData(unittest.TestCase):
	def test_every_record_carries_the_marker(self):
		self.assertIn('DEMO_SUFFIX = " [DEMO]"', SEED)
		self.assertIn('f"{name}{DEMO_SUFFIX}"', SEED)   # kurum
		self.assertIn('f"{lot_no}{DEMO_SUFFIX}"', SEED)  # lot

	def test_unseed_filters_on_the_marker_everywhere(self):
		"""İşaretsiz bir kaydı silen tek bir sorgu, geri alınamaz veri kaybı.

		Teklif belgeleri işareti TAŞIYAMIYOR: Supplier Quotation'ın demo diye
		damgalanabilecek bir başlık alanı yok. O yüzden tek meşru ikinci yol,
		`deal_names` üzerinden daralmak — ve o liste zaten işaretle süzülmüş
		anlaşmalardan geliyor. Bu gevşetme ancak `deal_names`'in kendisi
		işarete bağlı kaldığı sürece güvenli; aşağıdaki ikinci iddia tam olarak
		onu çiviliyor, yoksa "deal_names" adında bir değişken tanımlamak
		filtresiz silmenin serbest kapısı olurdu."""
		unseed = _fn("unseed")
		# Doctype'ı değişken olan sorgular da taransın: `for doctype, field in ...`
		# döngüsündeki get_all yalnız string doctype arayan bir desenden kaçardı.
		deletes = re.findall(r"frappe\.get_all\(\s*([^,]+),\s*filters=\{([^}]*)\}", unseed)
		self.assertEqual(
			len(deletes), unseed.count("frappe.get_all("),
			"desen bazı get_all çağrılarını kaçırıyor — taranmayan sorgu, sınanmamış silme",
		)
		for doctype, filters in deletes:
			with self.subTest(doctype=doctype.strip()):
				self.assertTrue(
					"DEMO_SUFFIX" in filters or "deal_names" in filters,
					f"{doctype.strip()} filtresi ne işarete ne de demo anlaşma listesine bakıyor",
				)

		self.assertRegex(
			unseed,
			r'filters=\{[^}]*"custom_tender_intake":\s*\["like",\s*f"%\{DEMO_SUFFIX\}%"\][^}]*\}'
			r"[\s\S]{0,300}deal_names\s*=\s*\[row\[\"name\"\] for row in deals\]",
			"deal_names, işaretle süzülmüş anlaşma sorgusundan türemek zorunda",
		)

	def test_the_raw_delete_is_scoped_to_one_deal(self):
		"""Olay kayıtları doğrudan SQL ile siliniyor (doctype değişmez);
		WHERE olmadan bu, sitenin tüm aşama geçmişini silerdi."""
		unseed = _fn("unseed")
		self.assertRegex(unseed, r"DELETE FROM `tabCRM Stage Event` WHERE deal = %\(deal\)s")

	def test_seeding_twice_does_nothing(self):
		seed = _fn("seed")
		self.assertIn("if _demo_exists():", seed)
		self.assertRegex(seed, r"if _demo_exists\(\):[\s\S]{0,200}return")

	def test_it_fails_loudly_on_a_missing_prerequisite(self):
		"""Eksik alanla yarım veri bırakmak, hiç veri bırakmamaktan kötü."""
		guard = _fn("_guard")
		self.assertIn("frappe.throw", guard)
		self.assertIn("custom_tender_intake", guard)
		self.assertIn('frappe.db.exists("Company", company)', guard)


class TestTheDataExercisesEveryScreenState(unittest.TestCase):
	"""Demo'nun işi ekranı doldurmak değil, ekranın gösterdiği AYRIMLARI
	üretmek. Hepsi yeşil bir demo, hiçbir şeyi kanıtlamaz."""

	LOTS = [
		line for line in SEED[SEED.index("DEMO_LOTS = ["):SEED.index("#: Son tarihler")].splitlines()
		if line.strip().startswith("(")
	]

	def test_every_pipeline_stage_has_a_deal(self):
		from stabler.api._funnel import STAGES

		staged = {re.search(r'"(\w+)", -?\d|"(\w+)", None', line) for line in self.LOTS}
		present = set(re.findall(r'",\s*"(\w+)",\s*(?:None|\d+),', "\n".join(self.LOTS)))
		self.assertEqual(STAGES - present, set(), f"aşamasız kalan: {STAGES - present}")

	def test_some_deals_deliberately_have_no_stage_stamp(self):
		"""Süreç akışının "ölçülemiyor" satırı gerçek sitede de olacak (v66
		öncesi her kayıt). Demo onu saklarsa ekranın en dürüst parçası hiç
		görülmez."""
		self.assertGreaterEqual(sum(1 for line in self.LOTS if ", None," in line), 2)

	def test_the_thresholds_are_crossed_in_both_directions(self):
		"""Eşik içinde, sınırda ve aşmış adımlar birlikte olmalı; hepsi yeşil
		bir demo SLA renklerini hiç göstermez."""
		from stabler.api._tender_sla import DEFAULT_STAGE_SLA_DAYS

		ages: dict[str, list[int]] = {}
		for line in self.LOTS:
			m = re.search(r'",\s*"(\w+)",\s*(\d+),', line)
			if m:
				ages.setdefault(m.group(1), []).append(int(m.group(2)))
		over = [s for s, days in ages.items() if s in DEFAULT_STAGE_SLA_DAYS
		        and sum(days) / len(days) > DEFAULT_STAGE_SLA_DAYS[s]]
		inside = [s for s, days in ages.items() if s in DEFAULT_STAGE_SLA_DAYS
		          and sum(days) / len(days) < DEFAULT_STAGE_SLA_DAYS[s]]
		self.assertTrue(over, "hiçbir adım eşiği aşmıyor — 'SLA dışı' hiç görünmez")
		self.assertTrue(inside, "hiçbir adım eşiğin içinde değil — 'içinde' hiç görünmez")

	def test_deadlines_cover_past_today_and_soon(self):
		"""Operasyon masasının severity dili bunlardan çıkıyor."""
		offsets = set(int(v) for v in re.findall(r':\s*(-?\d+),', SEED[SEED.index("DEADLINE_OFFSETS"):SEED.index("def _guard")]))
		self.assertTrue(any(o < 0 for o in offsets), "geçmiş son tarih yok")
		self.assertIn(0, offsets, "bugün biten yok")
		self.assertTrue(any(0 < o <= 2 for o in offsets), "48 saat içinde biten yok")

	def test_finished_deals_exist_on_both_sides(self):
		"""Direktör panosunun kazanma oranı tek taraflı veriyle anlamsız."""
		joined = "\n".join(self.LOTS)
		self.assertIn('"won"', joined)
		self.assertIn('"lost"', joined)


class TestTheEvidenceMatchesTheStage(unittest.TestCase):
	"""`_funnel.classify` aşamayı OLGULARDAN türetiyor. Damgalı aşama ile
	türetilen aşama ayrışırsa iki ekran aynı anlaşmayı farklı kulvarda
	gösterir — demo'nun yaratacağı en sinsi hata bu."""

	def test_submission_writes_both_audit_fields(self):
		"""`_has_submission_evidence` sonucu değil KATILIMI kanıt sayıyor:
		ikisi birden olmalı."""
		intake = _fn("_intake")
		self.assertIn('intake["submitted_at"]', intake)
		self.assertIn('intake["submitted_by"]', intake)

	def test_a_result_is_only_set_for_finished_deals(self):
		intake = _fn("_intake")
		self.assertRegex(intake, r'if stage in \("won", "lost"\):[\s\S]{0,120}intake\["result"\] = stage')

	def test_go_evidence_is_written_for_every_stage_past_intake(self):
		intake = _fn("_intake")
		self.assertRegex(intake, r'if stage != "seen":[\s\S]{0,160}intake\["go_no_go"\] = "go"')

	def test_history_walks_the_pipeline_instead_of_jumping(self):
		"""Yalnız son damgayı yazmak, her anlaşmayı bugünkü kulvarına doğmuş
		gösterir; süreç akışı "nerede oyalandık"ı geçmişten okuyor."""
		hist = _fn("_stage_history")
		self.assertIn("ORDER[: ORDER.index(stage) + 1]", hist)
		self.assertIn('"axis": "tender_stage"', hist)
		self.assertIn('"from_tender_stage": previous', hist)


def _load_seed():
	"""Seed modülünü, yalnız içe aktarma için gereken Frappe yüzeyiyle yükle."""
	import importlib
	import sys
	import types

	sys.modules.pop("stabler.maintenance.seed_tender_demo", None)
	frappe = types.ModuleType("frappe")
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	utils = types.ModuleType("frappe.utils")
	utils.add_days = lambda value, days: value
	utils.now = lambda: "2026-08-01 09:00:00"
	utils.nowdate = lambda: "2026-08-01"
	frappe.utils = utils
	sys.modules["frappe"] = frappe
	sys.modules["frappe.utils"] = utils
	try:
		return importlib.import_module("stabler.maintenance.seed_tender_demo")
	finally:
		# Sahte frappe'yi bırakma: aynı dosyadaki diğer testler `_funnel` gibi
		# gerçek modülleri içe aktarıyor, sızan bir stub onları sessizce bozar.
		sys.modules.pop("frappe", None)
		sys.modules.pop("frappe.utils", None)


class TestTheQuotationsMakeTheBoardsTellTheTruth(unittest.TestCase):
	"""Teklifler demo'nun süsü değil, iki panonun tek veri kaynağı.

	`sq_count` Supplier Quotation satırları SAYILARAK, `country_count` ise o
	tekliflerin tedarikçilerinin `Supplier.country` alanından türetiliyor —
	ikisi de anlaşmanın üzerinde yazan bir sayı değil. Tohumlayıcı 2026-08-01'e
	kadar hiç teklif YARATMIYORDU: `_intake` `sq_count`'u parametre olarak alıp
	çöpe atıyor, `countries` hiçbir yere gitmiyordu. Sonuç, canlı mikas'ta her
	demo kartın `sq_count: 0` / `has_min_5: false` göstermesi — yani "5 teklif
	toplandı mı" politikasının demo üzerinde HİÇ sınanamaması."""

	seed = _load_seed()

	def test_it_produces_exactly_as_many_quotations_as_the_lot_asks_for(self):
		self.assertEqual(len(self.seed._pick_suppliers(5, 3)), 5)
		self.assertEqual(len(self.seed._pick_suppliers(1, 1)), 1)

	def test_zero_quotations_is_a_state_the_boards_must_show(self):
		# Politika boşluğu satırı ("3/5 quotes collected") ancak eksik teklifli
		# lotlar varsa görünür; sıfır, susturulacak bir uç durum değil.
		self.assertEqual(self.seed._pick_suppliers(0, 3), [])

	def test_the_quotations_really_span_the_requested_countries(self):
		"""Hepsi tek ülkeden gelseydi `country_count` yalan söylerdi."""
		picked = self.seed._pick_suppliers(5, 3)
		self.assertEqual(len({country for _name, country in picked}), 3)

	def test_no_supplier_is_used_twice(self):
		"""`_supplier` idempotent: aynı ad iki kez seçilirse iki teklif TEK
		tedarikçiye bağlanır ve ülke kümesi sessizce daralır."""
		picked = self.seed._pick_suppliers(6, 3)
		self.assertEqual(len({name for name, _country in picked}), 6)

	def test_an_impossible_ask_fails_loudly_instead_of_seeding_less(self):
		"""Havuz yetmediğinde sessizce az teklif üretmek, demo'yu sahte bir
		"politika boşluğu" ile doldurur — hata sanılacak şey verinin kendisi olur."""
		with self.assertRaises(Exception) as caught:
			self.seed._pick_suppliers(10, 3)
		self.assertIn("pool too small", str(caught.exception))

	def test_the_seeded_counts_can_actually_cross_the_five_quote_threshold(self):
		"""Demo lotlarının hiçbiri 5'e ulaşmasaydı, `has_min_5` panoda hep
		kırmızı kalır ve eşiğin doğru tarafı hiç görülmezdi."""
		counts = [
			int(m.group(1))
			for m in re.finditer(r",\s*(\d+),\s*\d+,\s*\d+\)", SEED[SEED.index("DEMO_LOTS = ["):SEED.index("#: Son tarihler")])
		]
		self.assertTrue(counts, "DEMO_LOTS'tan teklif sayıları okunamadı")
		self.assertTrue(any(c >= 5 for c in counts), "hiçbir demo lot 5 teklif eşiğini geçmiyor")
		self.assertTrue(any(0 < c < 5 for c in counts), "eşiğin altında kalan bir lot yok")

	def test_every_seeded_lot_is_actually_satisfiable(self):
		"""`_pick_suppliers` havuz yetmezse `frappe.throw` ediyor — doğru davranış,
		ama o patlama TOHUMLAMA SIRASINDA olursa demo yarım kalır: bir kısım
		anlaşma yazılmış, teklifleri yazılmamış. DEMO_LOTS ile tedarikçi havuzu
		arasındaki bu bağ kodun hiçbir yerinde görünmüyor; yeni bir lot eklemek
		onu sessizce koparabilir. Testin işi, kopmayı canlı siteden önce görmek."""
		block = SEED[SEED.index("DEMO_LOTS = ["):SEED.index("#: Son tarihler")]
		lots = re.findall(r",\s*(\d+),\s*(\d+),\s*\d+\)", block)
		self.assertEqual(len(lots), 13, "DEMO_LOTS satır sayısı değişti — desen güncellensin")
		for sq_count, countries in ((int(a), int(b)) for a, b in lots):
			with self.subTest(sq_count=sq_count, countries=countries):
				picked = self.seed._pick_suppliers(sq_count, countries)
				self.assertEqual(len(picked), sq_count)
				if sq_count:
					self.assertEqual(len({c for _n, c in picked}), max(1, countries))

	def test_deal_linked_documents_go_before_the_deals(self):
		"""Teklif ve sipariş `custom_crm_deal` ile bağlı, kendi başlıklarında
		` [DEMO]` taşımıyorlar. Anlaşma önce silinirse hangi belgelerin demo
		olduğu bir daha bilinemez ve sitede sahipsiz kalırlar.

		İddia iki belge tipini de kapsıyor: sipariş sonradan eklendi ve aynı
		tuzağa aynı şekilde düşebilirdi.
		"""
		unseed = _fn("unseed")
		deals_gone = unseed.index('frappe.delete_doc("CRM Deal"')
		for doctype in ("Supplier Quotation", "Purchase Order"):
			with self.subTest(doctype=doctype):
				self.assertIn(f'"{doctype}"', unseed, f"{doctype} unseed'de hiç geçmiyor")
				self.assertLess(
					unseed.index(f'"{doctype}"'),
					deals_gone,
					f"{doctype} anlaşmalardan ÖNCE silinmeli",
				)

	def test_the_boards_that_read_orders_actually_get_orders(self):
		"""Gümrük kuyruğu ve lojistik panosu yalnız Purchase Order okuyor.

		Betiğin ilk hâli hiç sipariş üretmiyordu, o yüzden iki pano da seed'den
		sonra boş açılıyordu — ve çıktı satırı dört pano sayıp o ikisini hiç
		anmayarak durumu itiraf ediyordu. Burada üç şey birden tutuluyor: hat
		var, kazanılmış lotlara bağlı, ve çıktı satırı artık altı panoyu sayıyor.
		"""
		self.assertIn("DEMO_PURCHASE_ORDERS = [", SEED)
		block = SEED[SEED.index("DEMO_PURCHASE_ORDERS = ["):SEED.index("#: Demo tedarikçileri")]
		lots = set(re.findall(r'\("(UTY-\d{4}-\d{4})"', block))
		self.assertTrue(lots, "sipariş hattı boş")
		won = {lot for lot, *_rest in self.seed.DEMO_LOTS if _rest[1] == "won"}
		self.assertTrue(
			lots.issubset(won),
			f"sipariş yalnız kazanılmış lota bağlanmalı; {sorted(lots - won)} kazanılmamış",
		)
		for board in ("/tender/customs", "/tender/logistics"):
			with self.subTest(board=board):
				self.assertIn(board, SEED, f"çıktı satırı {board} panosunu saymıyor")

	def test_the_order_line_covers_every_state_both_boards_can_show(self):
		"""Tek durumlu bir hat, iki panoyu da tek satır göstererek 'çalışıyor'
		izlenimi verir. Kuyruk boşsa fark edilir; hepsi aynıysa fark edilmez.

		Gümrük: ETA'sı geçmiş (risk) · ≤7 gün (uyarı) · uzak (sakin), ve masrafsız
		(pending) · masraflı (in_progress) · alınmış (cleared).
		Lojistik: teslim tarihini aşan ETA (geciken) · alınmış (teslim).
		"""
		rows = self.seed.DEMO_PURCHASE_ORDERS
		etas = [r[3] for r in rows]
		received = [r[4] for r in rows]
		customs = [r[6] for r in rows]
		self.assertTrue(any(e < 0 for e in etas), "ETA'sı geçmiş satır yok — gümrük 'risk' üretmez")
		self.assertTrue(any(0 <= e <= 7 for e in etas), "yakın ETA yok — gümrük 'uyarı' üretmez")
		self.assertTrue(any(e > 30 for e in etas), "uzak ETA yok")
		self.assertTrue(any(p >= 100 for p in received), "tam alınmış satır yok — 'cleared'/'teslim' üretmez")
		self.assertTrue(any(p == 0 for p in received), "hiç alınmamış satır yok")
		self.assertTrue(any(c > 0 for c in customs), "gümrük masrafı olan satır yok — 'in_progress' üretmez")
		self.assertTrue(any(c == 0 for c in customs), "masrafsız satır yok — 'pending' üretmez")
		# Lojistiğin "geciken" kuralı ETA ile TESLİM tarihini karşılaştırıyor,
		# bugünle değil. Kazanılmış lotların teslim tarihi bu yüzden 90 günden
		# yakın; hepsi 90 olsaydı hiçbir sevkiyat gecikmiş çıkmazdı.
		for lot in {r[0] for r in rows}:
			with self.subTest(lot=lot):
				self.assertIn(lot, self.seed.DELIVERY_OFFSETS, f"{lot} için teslim tarihi kısaltılmamış")
		late = [
			r for r in rows
			if r[4] < 100 and r[3] > self.seed.DELIVERY_OFFSETS.get(r[0], 90)
		]
		self.assertTrue(late, "hiçbir sevkiyat teslim tarihini aşmıyor — lojistik 'geciken' üretmez")

	def test_the_working_lots_are_assigned_and_the_new_ones_are_not(self):
		"""Atama tedarik penceresinin görünürlük sınırı: `/tender/my-tenders`,
		masanın sourcing süzgeci ve ekip yükü kırılımı bu alandan okuyor.
		Atamasız demo'da üçü de belge sahibine çöküyordu — tek satır, hep aynı
		isim. Yeni gelen ilan (`seen`) ise bilerek atamasız: panonun 'sahipsiz'
		hâlini de birinin göstermesi lazım.
		"""
		seed_fn = _fn("seed")
		self.assertIn('stage != "seen"', seed_fn, "seen lotları atama dışında tutulmalı")
		intake = _fn("_intake")
		for key in ("assigned_to", "assigned_to_name", "assigned_at", "assigned_by"):
			with self.subTest(key=key):
				self.assertIn(f'intake["{key}"]', intake, f"{key} intake'e yazılmıyor")

	def test_the_order_column_is_checked_before_anything_is_created(self):
		"""Eksik kolonda durmak doğru; ON ÜÇ anlaşma ve teklif setleri
		yaratıldıktan SONRA durmak yarım demo bırakmak demek — betiğin `_guard`
		docstring'inin baştan uyardığı hâl. Kontrol `_orders()` içinde değil,
		`_guard()` içinde olmalı."""
		guard = _fn("_guard")
		self.assertIn('has_column("Purchase Order", "custom_crm_deal")', guard,
		              "sipariş kolonu kontrolü _guard'da değil")
		orders = _fn("_orders")
		self.assertNotIn('has_column("Purchase Order", "custom_crm_deal")', orders,
		                 "kontrol _orders'ta kalırsa 13 anlaşma yaratıldıktan sonra durur")

	def test_a_draft_quotation_still_counts_on_the_board(self):
		"""Pano `docstatus < 2` sayıyor. Teklifleri submit etmek demo'yu
		gerçekte olmadığı kadar ilerlemiş gösterir; taslak doğru durum."""
		quotations = _fn("_quotations")
		self.assertNotIn(".submit()", quotations)
		self.assertIn(".insert(", quotations)

	def _make_supplier(self, known_countries):
		"""`_supplier`'ı, yalnız ülke kararını görecek kadar sahte yüzeyle çalıştır."""
		import types as _types

		created = _types.SimpleNamespace(country=None, insert=lambda **kw: None, name="SUP-1")
		fr = self.seed.frappe
		fr.db = _types.SimpleNamespace(
			exists=lambda doctype, filt=None: (
				filt in known_countries if doctype == "Country" else None
			),
			get_value=lambda *a, **kw: "Demo Group",
		)
		fr.new_doc = lambda doctype: created
		return created

	def test_a_country_the_site_does_not_know_stops_the_seed(self):
		"""Ülke adı yazılamazsa pano ülke sayısını SESSİZCE eksik gösterir.

		`country_count` doğrudan `Supplier.country`'den türüyor. Eski kod
		`if frappe.db.exists("Country", country)` deyip yoksa atlıyordu; atlamak
		alanı boş bırakmıyor, Supplier'ı sistem varsayılanına düşürüyor. Ölçüldü
		2026-08-01, canlı mikas: Country listesinde "Russia" yok ("Russian
		Federation" var), UralVagonSnab ve SibTransDetal Uzbekistan'a düştü, üç
		ülkelik demo panoda iki ülke olarak göründü — hatasız, sorunsuz, yanlış."""
		created = self._make_supplier({"Uzbekistan"})
		with self.assertRaises(Exception):
			self.seed._supplier("UralVagonSnab", "Russia")
		self.assertIsNone(created.country, "yanlış ülke yazılmamalı — ne varsayılan ne boş")

	def test_a_known_country_is_actually_written_to_the_supplier(self):
		"""Patlamak tek başına yetmez: alan gerçekten yazılmazsa sayı yine düşer."""
		created = self._make_supplier({"Russian Federation"})
		self.seed._supplier("UralVagonSnab", "Russian Federation")
		self.assertEqual(created.country, "Russian Federation")

	def test_the_demo_pool_uses_names_the_country_doctype_actually_has(self):
		"""Frappe'nin Country kayıtları ISO adlarıdır. "Russia" tam da bu yüzden
		düştü; kısaltmayı geri getiren bir düzenleme burada yakalanır."""
		countries = re.findall(r'^\t\("([^"]+)", \[', SEED, re.M)
		self.assertTrue(countries, "DEMO_SUPPLIERS deseni artık tutmuyor")
		for bad in ("Russia", "USA", "UK", "South Korea"):
			self.assertNotIn(bad, countries, f"{bad!r} Country doctype'ında yok — ISO adını kullan")


if __name__ == "__main__":
	unittest.main()
