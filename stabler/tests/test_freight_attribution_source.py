"""Navlun parası hangi konteynere yazılıyor?

Konteyner listesi ve konteyner formu, navlunu `Freight Booking` üzerinden
okuyor. Bir booking konteyneri adıyla gösterebilir ya da yalnız Ticari
Faturaya (CI) düşülmüş olabilir. Aynı CI altında beş konteyner varsa, "CI'si
tutan her booking" kuralı beşinin de birbirinin navlununu göstermesine yol
açar — `LIMIT 1` sessizce **en yeni** kaydı seçer. Ekranda tutar olduğu sürece
bu yalnız yanlış bir taşıyıcı adıydı; tutar geldiğinden beri yanlış paradır.

Bu modül üç şeyi çiviliyor:

1. eşleşme kuralı **tek yerde** yazılı — liste 4.200 $ derken form 3.100 $
   diyemesin;
2. CI bacağı yalnız **hiçbir konteyner adı taşımayan** bookingleri kapsıyor;
3. navlun tutarı ve ödemeleri, kendi doctype'ında permlevel 1 oldukları için,
   ham SQL ile çekilip maskesiz çıkmıyor.

Frappe önyüklemesi yok: (3) gerçek davranış testi, diğerleri kaynak okur.
"""

from __future__ import annotations

import csv
import os
import re
import unittest

from stabler.api import _imports_rules as rules

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
API = os.path.join(_ROOT, "api", "imports.py")
VUE = os.path.join(_ROOT, "public", "js", "pages", "imports", "ImportContainers.vue")


def read(path):
	with open(path, encoding="utf-8") as fh:
		return fh.read()


def body(src, name):
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"{name} not found"
	tail = src[m.start():]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class FreightMatchTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.src = read(API)

	def test_the_match_rule_is_written_exactly_once(self):
		"""İki kopya kaçınılmaz olarak ayrışır ve ayrıştığı gün liste ile form
		aynı konteyner için farklı navlun gösterir."""
		self.assertEqual(
			self.src.count("fb.container = "), 2,
			"eşleşme kuralı _FREIGHT_MATCH dışında da yazılmış",
		)
		self.assertIn('"fb.container = {name}"', self.src)
		self.assertIn('" OR fb.container = {number}"', self.src)

	def test_the_ci_leg_only_catches_bookings_that_name_no_container(self):
		"""Kuralın parayı taşıyan bacağı. Kaldırılırsa aynı CI'deki kardeş
		konteynerlerden birinin navlunu diğerine yazılır."""
		self.assertIn("COALESCE(fb.container, '') = ''", self.src)

	def test_both_endpoints_read_the_same_rule(self):
		self.assertIn("{_FREIGHT_FOR_CONTAINER}", body(self.src, "list_import_containers"))
		self.assertIn("{_FREIGHT_FOR_ONE}", body(self.src, "get_import_container"))

	def test_one_booking_answers_every_column_of_a_row(self):
		"""Sütun başına ayrı `LIMIT 1` alt sorgusu, aynı saniyede yaratılmış iki
		bookingde farklı kayıtlara düşebiliyordu: bir taşıyıcının adı, bir
		başkasının nakit tutarıyla yan yana basılıyordu."""
		listing = body(self.src, "list_import_containers")
		self.assertEqual(
			listing.count("ORDER BY fb.creation DESC LIMIT 1"), 1,
			"satır alanları birden çok bağımsız alt sorgudan geliyor",
		)
		self.assertIn("_freight_bookings(", listing)

	def test_the_batched_fetch_is_one_query_for_the_whole_page(self):
		"""50 satırlık sayfa 50 sorgu etmesin."""
		fetch = body(self.src, "_freight_bookings")
		self.assertEqual(fetch.count("frappe.db.sql("), 1)
		self.assertIn("WHERE fb.name IN %(names)s", fetch)

	def test_the_shared_projection_carries_the_money_and_its_currency(self):
		"""Freight Booking'in kendi `currency` alanı var; sorgudan düşerse
		Python tarafı anahtarı yine yazar ama boş — ekran da tutarı sabit bir
		sembolle etiketlemek zorunda kalır. Bu yüzden iddia SQL'e bakıyor."""
		for alias in (
			"COALESCE(fb.amount, 0) AS transport_cost",
			"COALESCE(fb.cash_payment, 0) AS paid_cash",
			"COALESCE(fb.bank_payment, 0) AS paid_bank",
			"fb.currency AS transport_currency",
		):
			with self.subTest(alias):
				self.assertIn(alias, self.src)
		for fn in ("list_import_containers", "get_import_container"):
			with self.subTest(fn):
				self.assertIn("transport_currency", body(self.src, fn))


class FreightMaskTest(unittest.TestCase):
	"""Gerçek davranış: `amount` / `cash_payment` / `bank_payment` kendi
	doctype'ında permlevel 1. Konteyner uçları bunları ham SQL ile okuyor ve
	ham SQL permlevel tanımaz — maskeleme adla yapılmazsa join, izin
	katmanının etrafından dolaşmanın yolu olur."""

	def _masked(self, fields):
		row = {"transport_cost": 4200.0, "paid_cash": 1000.0, "paid_bank": 3200.0, "status": "In Transit"}
		rules.mask_named(row, fields, visible=False)
		return row

	def test_list_hides_freight_money_from_users_without_cost_visibility(self):
		row = self._masked(rules.CONTAINER_LIST_MASK_FIELDS)
		for key in ("transport_cost", "paid_cash", "paid_bank"):
			with self.subTest(key):
				self.assertIsNone(row[key])
		self.assertEqual(row["status"], "In Transit", "maske para dışı alana dokunmamalı")

	def test_the_detail_form_hides_the_same_figures(self):
		row = self._masked(rules.CONTAINER_MASK_FIELDS)
		for key in ("transport_cost", "paid_cash", "paid_bank"):
			with self.subTest(key):
				self.assertIsNone(row[key])

	def test_a_cost_visible_user_still_sees_them(self):
		row = {"transport_cost": 4200.0, "paid_cash": 1000.0, "paid_bank": 3200.0}
		rules.mask_named(row, rules.CONTAINER_LIST_MASK_FIELDS, visible=True)
		self.assertEqual(row["transport_cost"], 4200.0)


class FreightCellTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.vue = read(VUE)

	def test_the_cell_labels_the_amount_with_the_booking_currency(self):
		"""Sabit `'USD'`, UZS kesilmiş bir navlunu dolar diye gösteriyordu."""
		hardcoded = [ln.strip() for ln in self.vue.splitlines() if "transport_cost" in ln and "formatMoney" in ln]
		self.assertEqual(hardcoded, [], "navlun tutarı sabit para birimiyle basılıyor")
		self.assertIn("fm(r.transport_cost, r.transport_currency)", self.vue)
		self.assertIn("fm(r.paid_cash + r.paid_bank, r.transport_currency)", self.vue)

	def test_a_masked_row_does_not_read_as_free_freight(self):
		"""Maskelenmiş satırda tutar `null`; şablon onu `$0.00` diye basarsa
		kullanıcı navlunun bedava olduğunu sanır."""
		self.assertNotIn("$0.00", self.vue)


class FreightCellTranslationTest(unittest.TestCase):
	"""Hücrenin bastığı üç dize beş dilde de dolu olmalı.

	Liste `t()` çağrılarıyla birlikte doğrulanıyor: proje kuralı çevrilmemiş
	dize bırakmayı yasaklıyor, ama tersi de bir arıza — bu oturumda CSV'lere
	hiçbir çağrı yeri olmayan dokuz anahtar eklenmişti. Çağrısı kalmayan
	anahtar burada da düşsün."""

	KEYS = ("Transporter & Freight Cost", "No Transporter", "Vehicle / Truck")
	LANGS = ("en", "ru", "uz", "uzc", "tr")

	@classmethod
	def setUpClass(cls):
		cls.vue = read(VUE)

	def test_every_listed_key_is_really_rendered_by_the_cell(self):
		for key in self.KEYS:
			with self.subTest(key):
				self.assertTrue(
					f't("{key}")' in self.vue or f"t('{key}')" in self.vue,
					f"{key!r} artık ekranda yok; çeviri satırları da düşürülmeli",
				)

	def test_the_cell_strings_are_translated_in_every_language(self):
		for lang in self.LANGS:
			path = os.path.join(_ROOT, "translations", f"{lang}.csv")
			with open(path, encoding="utf-8", newline="") as fh:
				table = {r[0]: r[1] for r in csv.reader(fh) if len(r) >= 2}
			missing = sorted(k for k in self.KEYS if not table.get(k, "").strip())
			with self.subTest(lang):
				self.assertEqual(missing, [], f"{lang}.csv eksik: {missing}")


if __name__ == "__main__":
	unittest.main()
