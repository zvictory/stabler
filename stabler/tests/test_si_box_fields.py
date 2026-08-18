"""Koli sayısı fatura satırında kalmalı — hem yazılırken hem geri okunurken.

MSA donmuş et ithal edip kilo üzerinden satıyor. Kutu ağırlığı sabit değildir
(kemikli/kemiksiz fark eder), o yüzden faturanın parasal gerçeği kilodur. Ama
DEPONUN gerçeği kolidir: sevkiyattan kaç koli çıktığı, sayımda kaç koli
bulunduğu, eksik teslim ve iade tartışmasında kimin haklı olduğu koli
üzerinden konuşulur. İki sayı birbirinin yerine geçmez; ikisi de saklanmalı.

Ekran bunu zaten topluyor (`NewDirectInvoicePage.vue`, satır başına
`boxes` ve `box_kg`) ve payload'a koyuyor. Göç sırasında backend'in iki ucu
da bu alanları sessizce düşürmeye başladı: `create_direct_sales_invoice`
satır sözlüğüne yazmıyordu, `sales_invoice_detail` de geri okumuyordu. Eski
msaerp kodu (`msaerp/api/invoices.py`) ikisini de yazıyordu.

Sessiz olması işin kötü tarafı: fatura kesilir, toplam doğrudur, kimse bir
hata görmez — koli bilgisi yalnızca yoktur. 2026-08-18'de ölçüldüğünde
`Sales Invoice Item` tablosunda 21 141 satırın 21 129'u doluydu ve koli
verisi taşıyan SON satır 2026-07-28 tarihliydi; yani kayıp üç hafta boyunca
fark edilmemişti.

Bu yüzden test kaynağı okur: alanların iki uçta da adı geçmeli. Bir daha
düşürülürse `make check` kırmızı olur.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SALES = (ROOT / "api/sales.py").read_text(encoding="utf-8")

BOX_FIELDS = ("custom_boxes", "custom_box_kg")


def _function_body(src: str, name: str) -> str:
	"""`def <name>` ile bir sonraki üst seviye `def`/`@` arasını döndürür."""
	start = src.index(f"def {name}(")
	rest = src[start:]
	end = len(rest)
	for marker in ("\n@frappe.whitelist", "\ndef "):
		idx = rest.find(marker, 1)
		if idx != -1:
			end = min(end, idx)
	return rest[:end]


WRITE_PATH = _function_body(SALES, "create_direct_sales_invoice")
READ_PATH = _function_body(SALES, "sales_invoice_detail")


class TestTheWritePathKeepsBoxes(unittest.TestCase):
	"""Ekranın topladığı koli bilgisi belgeye ulaşmalı."""

	def test_the_row_dict_carries_both_box_fields(self):
		for field in BOX_FIELDS:
			self.assertIn(
				field,
				WRITE_PATH,
				f"create_direct_sales_invoice satırı {field} yazmıyor — ekran topluyor ama belge kaybediyor",
			)

	def test_the_row_is_assigned_not_merely_mentioned(self):
		"""Alanın adının geçmesi yetmez — satıra ATANDIĞINI görmeliyiz."""
		for field in BOX_FIELDS:
			self.assertIn(
				f'row["{field}"]',
				WRITE_PATH,
				f"{field} satır sözlüğüne atanmıyor",
			)

	def test_it_reads_the_keys_the_screen_actually_sends(self):
		"""SPA `boxes`/`box_kg` gönderiyor, doctype alanı `custom_boxes`.

		Backend doctype adını yazıp ekranın gönderdiği adı okumazsa alan
		her satırda boş kalır — ve bu, testin adının geçmesiyle gizlenir."""
		for sent in ("boxes", "box_kg"):
			self.assertRegex(
				WRITE_PATH,
				rf'it\.get\(\s*["\']{sent}["\']',
				f"ekranın gönderdiği {sent!r} anahtarı okunmuyor",
			)


class TestTheReadPathReturnsBoxes(unittest.TestCase):
	"""Yazmak yetmez: form kaydı geri açtığında koliyi görmeli.

	Okuma yolu düşürürse taslak düzenleme sessizce koliyi sıfırlar — yani
	yalnız görüntülemek bile veriyi bozar."""

	def test_the_item_projection_carries_both_box_fields(self):
		for field in BOX_FIELDS:
			self.assertIn(
				field,
				READ_PATH,
				f"sales_invoice_detail satır projeksiyonu {field} döndürmüyor",
			)


if __name__ == "__main__":
	unittest.main()
