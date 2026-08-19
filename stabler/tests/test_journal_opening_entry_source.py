"""`Opening Entry` bir etiket değil, bir bayraktır — kaynaktan okunur.

Neden: SPA'nın jurnal formu `voucher_type` listesinde "Opening Entry" sunuyor
(JournalEntries.vue), ama form `is_opening` göndermiyordu ve backend de hiç set
etmiyordu. Sonuç: kullanıcının açılış kaydı diye kaydettiği JE, ERPNext'in
açılış bakiyesi / dönem kapanışı raporlamasında sıradan bir kayıt sayılıyordu.
Aynı uygulamanın Hesap Planı yolu (`create_account`) ise açılış JE'sini
`is_opening = "Yes"` ile yazıyor — yani iki yol aynı belgeyi iki türlü
üretiyordu.

Bir Frappe belgesini bench olmadan kuramayız; test kaynağı okur. Bu zayıf bir
doğrulama ve davranışsal kanıtı `make test-bench` + canlı UAT verir; buradaki
iş, bayrağın sessizce geri düşmesini engellemek.
"""

import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "api" / "money.py"


def _body(src: str, name: str) -> str:
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"{name} bulunamadı — kaynak kaymış"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def )", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class TestOpeningEntryFlag(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.src = SOURCE.read_text(encoding="utf-8")

	def test_the_test_reads_the_module(self):
		"""Çapa: yol kayarsa aşağıdaki iddialar boş metni doğrularlardı."""
		self.assertIn("def create_journal_entry(", self.src)
		self.assertIn("def update_journal_entry(", self.src)

	def test_chart_of_accounts_path_still_flags_its_opening_entry(self):
		"""Karşılaştırma noktası: bozulursa aşağıdaki iki iddia anlamsızlaşır."""
		body = _body(self.src, "create_account")
		self.assertIn('je.is_opening = "Yes"', body)

	def test_the_label_is_what_decides_the_flag(self):
		body = _body(self.src, "_opening_flag")
		self.assertIn("Opening Entry", body)
		self.assertIn('"Yes"', body)
		self.assertIn('"No"', body)

	def test_created_entry_carries_the_flag_its_voucher_type_promises(self):
		body = _body(self.src, "create_journal_entry")
		self.assertIn("doc.is_opening = _opening_flag(voucher_type)", body)

	def test_editing_a_draft_keeps_the_flag_in_step_with_its_voucher_type(self):
		"""Taslağın türü düzenlemede değişebilir; bayrak da onunla dönmeli,
		yoksa 'Opening Entry' iken kaydedilen bir taslak, türü geri alındıktan
		sonra da açılış kaydı olarak kalır."""
		body = _body(self.src, "update_journal_entry")
		self.assertIn("doc.is_opening = _opening_flag(", body)


if __name__ == "__main__":
	unittest.main()
