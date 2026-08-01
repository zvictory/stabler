"""Tender aşamasının kaydedilmesi ve o aşamaya giriş anı.

Tender CRM'de bir kartı sürüklemek çalışıyor GÖRÜNÜYORDU: iyimser güncelleme
kartı taşıyor, sunucu 200 dönüyor, başarı bildirimi çıkıyor. Ama yazma
`frappe.db.has_column("CRM Deal", "custom_tender_stage")` ile korunuyordu ve o
sütunu yaratan bir yama depoda YOKTU — ne v36'da, ne v37'de, hiçbir yerde. Yani
koşul her sitede False dönüyor, aşama hiçbir yere yazılmıyor ve sayfa
yenilenince kart türetilmiş kulvarına geri düşüyordu.

Sessiz olan her şey gibi bu da kendini göstermiyordu: türetilmiş aşama çoğu
zaman doğru kulvarı seçiyor, o yüzden kayıp yalnız kullanıcı olguların
söylediğinden BAŞKA bir yere taşımak istediğinde ortaya çıkıyordu.

İkinci alan (`custom_tender_stage_entered_at`) süreç akışı ekranının veri
temeli: "bu anlaşma bu aşamada kaç gündür bekliyor". Bugün bu veri hiçbir
yerde yok.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "patches/v66_deal_tender_stage.py").read_text(encoding="utf-8")
PATCHES = (ROOT / "patches.txt").read_text(encoding="utf-8")
TENDER = (ROOT / "api/tender.py").read_text(encoding="utf-8")
FUNNEL = (ROOT / "api/_funnel.py").read_text(encoding="utf-8")

MOVE = TENDER[TENDER.index("def move_deal_stage") :]
MOVE = MOVE[: MOVE.index("\n# ---")]


class TestTheStageColumnIsActuallyCreated(unittest.TestCase):
	def test_the_patch_is_registered(self):
		self.assertIn("stabler.patches.v66_deal_tender_stage", PATCHES)

	def test_it_creates_both_fields(self):
		for field in ("custom_tender_stage", "custom_tender_stage_entered_at"):
			with self.subTest(field=field):
				self.assertIn(f'"fieldname": "{field}"', PATCH)

	def test_each_field_is_guarded_separately(self):
		"""Tek bir varlık kontrolü ikisini birden korusa, alanlardan biri elle
		yaratılmış bir sitede diğeri hiç oluşmazdı."""
		guards = re.findall(r'frappe\.db\.exists\(\s*"Custom Field",\s*\{[^}]*"fieldname": "(\w+)"', PATCH)
		self.assertEqual(sorted(guards), ["custom_tender_stage", "custom_tender_stage_entered_at"])

	def test_the_patch_is_pre_sync_safe(self):
		self.assertRegex(PATCH, r'if not frappe\.db\.exists\("DocType", "CRM Deal"\):\s*\n\s*return')

	def test_the_stage_field_has_no_default(self):
		"""Boş = "elle taşınmadı, aşama olgulardan türetilsin". Varsayılan bir
		aşama koymak her anlaşmayı elle taşınmış gibi gösterirdi ve türetme
		yolunu ölü koda çevirirdi."""
		# Alan adı dosyada iki kez geçiyor: biri varlık KONTROLÜNDE, biri
		# tanımda. İlkine göre kesmek kontrol sözlüğünü okurdu — tanımı
		# etiketinden bul.
		start = PATCH.index('"label": "Tender Stage"')
		block = PATCH[start : PATCH.index("},", start)]
		self.assertNotIn('"default"', block)
		self.assertIn('"options": "\\n"', block)


class TestTheStageIsValidatedBeforeItIsStored(unittest.TestCase):
	def test_an_unknown_stage_is_rejected(self):
		"""Doğrulama olmadan istemci ne gönderirse Select'e o giriyordu. Yazım
		hatası taşıyan kart hiçbir kulvara düşmez — ekrandan kaybolur."""
		self.assertIn("if stage not in _funnel.STAGES:", MOVE)
		self.assertRegex(MOVE, r'frappe\.throw\(_\("Unknown stage: \{0\}"\)')

	def test_the_valid_set_lives_in_one_place(self):
		self.assertIn('STAGES = frozenset(ORDER) | {"lost"}', FUNNEL)

	def test_lost_is_a_stage_but_not_a_step_forward(self):
		"""ORDER ilerlemeyi anlatıyor ve `lost`u dışarıda bırakıyor; STAGES
		"bu geçerli bir aşama mı" sorusuna cevap veriyor ve içeriyor. İkisini
		birleştirmek funnel'ı kayıplarla şişirirdi."""
		from stabler.api import _funnel

		self.assertIn("lost", _funnel.STAGES)
		self.assertNotIn("lost", _funnel.ORDER)
		self.assertNotIn("lost", _funnel.FUNNEL_STEPS)

	def test_every_lane_the_board_draws_is_a_valid_stage(self):
		"""Kulvar kimlikleri ile kabul edilen aşamalar ayrışırsa, kullanıcının
		sürükleyebildiği bir kulvar sunucuda reddedilir."""
		from stabler.api import _funnel

		board = TENDER[TENDER.index("def crm_board") :]
		board = board[: board.index("deal_names =")]
		lanes = set(re.findall(r'\{"id": "(\w+)", "label"', board))
		self.assertTrue(lanes, "kulvar listesi bulunamadı")
		self.assertEqual(lanes - set(_funnel.STAGES), set())


class TestTheClockOnlyRestartsOnARealMove(unittest.TestCase):
	"""Sayaç yanlış sıfırlanırsa süreç akışı bekleyen işi genç gösterir — en
	çok bakılması gereken anlaşma en az dikkat çeker."""

	def test_the_previous_stage_is_read_before_it_is_overwritten(self):
		read = MOVE.index('previous = frappe.db.get_value("CRM Deal", name, "custom_tender_stage")')
		write = MOVE.index('frappe.db.set_value("CRM Deal", name, "custom_tender_stage", stage)')
		self.assertLess(read, write, "eski aşama üzerine yazıldıktan sonra okunuyor")

	def test_the_timestamp_is_gated_on_an_actual_change(self):
		self.assertIn("if previous != stage", MOVE)

	def test_the_timestamp_write_is_guarded_on_its_own_column(self):
		"""Yama uygulanmamış bir sitede bu yazma hata verirdi."""
		# Biçime değil İFADEYE bak: bu iddia bir satır sonu yüzünden düşerse,
		# test kodun ne yaptığını değil nasıl sarıldığını ölçüyor demektir.
		flat = re.sub(r"\s+", " ", MOVE)
		self.assertIn(
			'has_column( "CRM Deal", "custom_tender_stage_entered_at" )'.replace("( ", "(").replace(
				" )", ")"
			),
			flat.replace("( ", "(").replace(" )", ")"),
		)

	def test_the_timestamp_does_not_touch_the_modified_stamp(self):
		"""`modified` eşzamanlılık kontrolü için kullanılıyor; damgayı yazarken
		onu ilerletmek, açık duran bir formu sahte "başkası değiştirdi"
		çakışmasına düşürür."""
		block = MOVE[MOVE.index("custom_tender_stage_entered_at") :]
		self.assertIn("update_modified=False", block[:400])


class TestTheTwoTimestampsStayOnSeparateAxes(unittest.TestCase):
	"""CRM Deal'de zaten `stage_entered_at` var (v60) ama o `status` ekseninin
	damgası ve `api/crm.py` onu yazıyor. Aynı alanı iki eksenden yazmak, bir
	alanın hangi hareketi kaydettiğini belirsiz yapar — üzerine kurulan hiçbir
	süre güvenilir olmaz."""

	def test_the_tender_move_does_not_write_the_crm_status_stamp(self):
		self.assertNotIn('stage_entered_at"', MOVE.replace('custom_tender_stage_entered_at"', ""))

	def test_the_patch_explains_why_a_second_field_exists(self):
		self.assertIn("stage_entered_at", PATCH)
		self.assertIn("status", PATCH)


if __name__ == "__main__":
	unittest.main()
