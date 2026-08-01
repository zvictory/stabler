"""Hareket kaydının iki ekseni: statü hattı ve tender kulvarı.

Süreç akışı ekranının asıl sorusu "nereden geldik ve nerede oyalandık". Bunun
tek kaynağı geçmiş; v66'nın damgası geçmiş tutmuyor çünkü her hareket bir
öncekinin üzerine yazıyor. `CRM Stage Event` zaten değişmez bir log ve
şirket kapsamı + izin kancaları oradaydı, o yüzden tender hareketleri de
oraya yazılıyor.

TEK LOG, AYRI SÜTUNLAR — ve bu bir uzlaşma değil, bir kısıt:
`from_stage`/`to_stage` birer Link ve hedefleri CRM Deal Status. Bir statü
yeniden adlandırıldığında Frappe geçmişi de günceller; test_crm_company_scope
o zinciri kilitliyor. Tender aşamaları ise kodda sabit, tabloda satırları yok.
Link'e yazmak kırık bağlantı üretirdi; sütunu Data'ya çevirmek statü tarafının
yeniden adlandırma zincirini kırardı.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCTYPE = json.loads(
	(ROOT / "stabler/doctype/crm_stage_event/crm_stage_event.json").read_text(encoding="utf-8")
)
CONTROLLER = (ROOT / "stabler/doctype/crm_stage_event/crm_stage_event.py").read_text(encoding="utf-8")
TENDER = (ROOT / "api/tender.py").read_text(encoding="utf-8")
CRM = (ROOT / "api/crm.py").read_text(encoding="utf-8")
PATCH = (ROOT / "patches/v67_stage_event_axis.py").read_text(encoding="utf-8")
PATCHES = (ROOT / "patches.txt").read_text(encoding="utf-8")

FIELDS = {f["fieldname"]: f for f in DOCTYPE["fields"]}


def _sql_text(src: str) -> str:
	"""Kaynaktaki SQL'i satır kırılmasından bağımsız oku.

	Eski hâli `'status' " "WHERE` dikişine, yani SQL'in İKİ satıra bölünmüş
	olmasına çakılıydı. Biçimlendirici o örtük string birleşimini tek satıra
	toplayınca (110 karaktere sığıyor) test kırmızıya döndü — oysa yamanın
	davranışı zerre değişmemişti. Testin sorusu "hangi SQL yazılıyor", "kaç
	satıra bölünmüş" değil; o yüzden boşlukları ve birleşim dikişlerini eleyip
	iki biçimi de aynı metne indiriyoruz.
	"""
	return re.sub(r'"\s*"', "", re.sub(r"\s+", " ", src))


class TestTheAxisIsRecorded(unittest.TestCase):
	def test_the_field_exists_and_is_required(self):
		self.assertIn("axis", FIELDS)
		self.assertEqual(FIELDS["axis"]["reqd"], 1)

	def test_it_defaults_to_the_axis_that_already_existed(self):
		"""Yeni alan, eski yazıcıyı bozmadan devreye girmeli."""
		self.assertEqual(FIELDS["axis"]["default"], "status")

	def test_both_axes_are_offered_and_nothing_else(self):
		self.assertEqual(set(FIELDS["axis"]["options"].split("\n")), {"status", "tender_stage"})

	def test_the_existing_writer_names_its_axis_explicitly(self):
		"""Varsayılana güvenmek, bir gün varsayılan değişince statü geçmişini
		sessizce yanlış eksene yazardı."""
		self.assertIn('"axis": "status"', CRM)


class TestTheTwoAxesDoNotShareColumns(unittest.TestCase):
	def test_the_status_columns_are_still_links_to_the_status_table(self):
		"""Yeniden adlandırma zinciri buna bağlı; test_crm_company_scope onu
		ayrıca kilitliyor."""
		for field in ("from_stage", "to_stage"):
			with self.subTest(field=field):
				self.assertEqual(FIELDS[field]["fieldtype"], "Link")
				self.assertEqual(FIELDS[field]["options"], "CRM Deal Status")

	def test_the_tender_columns_are_plain_data(self):
		"""Tender aşamaları kodda sabit; Link'e yazmak kırık bağlantı üretir."""
		for field in ("from_tender_stage", "to_tender_stage"):
			with self.subTest(field=field):
				self.assertIn(field, FIELDS)
				self.assertEqual(FIELDS[field]["fieldtype"], "Data")

	def test_each_pair_is_shown_only_on_its_own_axis(self):
		for field, axis in (
			("from_stage", "status"),
			("to_stage", "status"),
			("from_tender_stage", "tender_stage"),
			("to_tender_stage", "tender_stage"),
		):
			with self.subTest(field=field):
				self.assertEqual(FIELDS[field].get("depends_on"), f"eval:doc.axis === '{axis}'")

	def test_the_controller_clears_the_other_axis_columns(self):
		"""İki sütun çifti de doluysa okuyan taraf hangisinin geçerli olduğunu
		bilemez — ve bir kayıt iki kez sayılır."""
		self.assertRegex(CONTROLLER, r"_validate_tender_axis[\s\S]*self\.from_stage = None")
		self.assertRegex(CONTROLLER, r"_validate_status_axis[\s\S]*self\.from_tender_stage = None")


class TestValidationMovedIntoTheController(unittest.TestCase):
	"""Link'in bedavaya verdiği "bu değer var mı" güvencesinin tender
	tarafındaki karşılığı `_funnel.STAGES` üyeliği."""

	def test_an_unknown_tender_stage_is_rejected(self):
		self.assertIn("if value and value not in STAGES:", CONTROLLER)
		self.assertRegex(CONTROLLER, r'_\("Unknown tender stage: \{0\}"\)')

	def test_an_unknown_axis_is_rejected(self):
		self.assertRegex(CONTROLLER, r'_\("Unknown stage axis: \{0\}"\)')

	def test_each_axis_requires_a_destination(self):
		self.assertIn("A tender stage event needs a destination stage.", CONTROLLER)
		self.assertIn("A status event needs a destination status.", CONTROLLER)

	def test_a_blank_origin_is_allowed(self):
		"""İlk hareketin bir öncesi yok; boşu reddetmek anlaşmanın ilk
		kaydını imkânsız kılardı."""
		self.assertIn("if value and value not in STAGES:", CONTROLLER)

	def test_the_records_are_still_immutable(self):
		self.assertIn("CRM Stage Event records are immutable.", CONTROLLER)
		self.assertRegex(CONTROLLER, r"def on_trash\(self\):")


class TestTheTenderMoveWritesHistory(unittest.TestCase):
	MOVE = TENDER[TENDER.index("def _record_tender_stage_event") :]
	MOVE = MOVE[: MOVE.index("\n# ---")]

	def test_the_event_is_written_on_a_real_move_only(self):
		block = TENDER[TENDER.index("def move_deal_stage") :]
		block = block[: block.index("\n# ---")]
		self.assertIn("if previous != stage:", block)
		self.assertIn("_record_tender_stage_event(name, company, previous, stage, moved_at)", block)

	def test_the_stamp_and_the_event_share_one_timestamp(self):
		"""İki ayrı `now()` çağrısı, damga ile geçmişi milisaniyelerle
		ayrıştırır ve "aşamaya girdiği an" iki farklı değer olur."""
		block = TENDER[TENDER.index("def move_deal_stage") :]
		block = block[: block.index("\n# ---")]
		self.assertEqual(block.count("frappe.utils.now()"), 1)
		self.assertIn("moved_at = frappe.utils.now()", block)

	def test_it_writes_the_tender_axis_into_the_tender_columns(self):
		self.assertIn('"axis": "tender_stage"', self.MOVE)
		self.assertIn('"from_tender_stage": from_stage or ""', self.MOVE)
		self.assertIn('"to_tender_stage": to_stage', self.MOVE)

	def test_it_never_touches_the_status_columns(self):
		self.assertNotIn('"to_stage"', self.MOVE)
		self.assertNotIn('"from_stage"', self.MOVE)

	def test_a_failed_write_does_not_undo_the_users_move(self):
		"""Log yazılamadı diye aşama hareketini geri almak, kullanıcının
		yaptığı işi tarihçe uğruna iptal etmektir. Yutuluyor ama sessiz
		değil."""
		self.assertRegex(self.MOVE, r"except Exception:\s*\n\s*frappe\.log_error\(")


class TestExistingHistoryIsClaimedByTheStatusAxis(unittest.TestCase):
	def test_the_patch_is_registered(self):
		self.assertIn("stabler.patches.v67_stage_event_axis", PATCHES)

	def test_it_backfills_null_rows_as_status(self):
		"""Bu yamadan önce o logu yazan tek yer statü hattıydı. NULL bırakmak,
		eksene göre filtreleyen bir ekranda geçmişin tamamını sessizce
		kaybettirirdi — hata değil, boş bir zaman çizelgesi."""
		self.assertIn("SET axis = 'status' WHERE axis IS NULL OR axis = ''", _sql_text(PATCH))

	def test_it_is_pre_sync_safe(self):
		self.assertIn('has_column("CRM Stage Event", "axis")', PATCH)
		self.assertIn('table_exists("CRM Stage Event")', PATCH)


if __name__ == "__main__":
	unittest.main()
