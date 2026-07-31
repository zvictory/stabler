"""useDocumentForm bağlaması: watch() ondan ÖNCE gelemez.

`<script setup>` gövdesi yukarıdan aşağı bir kez koşar. `watch()` kaynak
getter'larını oluşturulduğu anda hemen çağırır; `computed()` ise tembeldir,
ilk okunana kadar gövdesi çalışmaz. Bu yüzden aynı değişkeni okuyan iki
sarmalayıcıdan yalnız biri patlar.

`const { model: form, ... } = useDocumentForm({...})` bu dosyalarda hep
aşağıda durur (toPayload/fromDetail'i argüman aldığı için). Yukarıda `form`
okuyan bir watch, TDZ yüzünden "Cannot access 'form' before initialization"
fırlatır. Kritik olan: bu hata watcher'ı kurulmadan öldürür, Vue onu yutar ve
geriye çalışmayan bir özellik kalır — ekranda hata yok, konsolda tek satır.

PaymentEntryForm.vue'de tam olarak bu olmuştu: CBU kur sapması uyarısı
(rateDeviation > %5) hiç tetiklenmiyordu. Test bu yüzden "uyarı görünüyor mu"
değil, sıralamayı kilitliyor — bozulan şey sıralamaydı ve sessizdi.
"""

import re
import unittest
from pathlib import Path

PAGES = Path(__file__).resolve().parents[1] / "public/js/pages"


def _first_argument(src: str, open_paren: int) -> str:
	"""`watch(` çağrısının yalnız ilk argümanını döndür.

	Sadece ilk argüman — çünkü tehlikeli olan o. Kaynak getter'lar oluşturma
	anında çağrılır; callback gövdesi ise tetiklenene kadar beklediği için
	orada `form` okumak serbesttir. Naif bir "ilk N karakter" penceresi ya
	callback'i içine alıp yanlış alarm verir ya da (ilk `=>`'de kesince)
	kaynakları tamamen kaçırır — ikinci hata testi sessizce kör etmişti.

	Bu yüzden parantez/köşeli/süslü derinliği sayılır ve derinlik 0'daki ilk
	virgülde ya da çağrıyı kapatan parantezde durulur.
	"""
	depth = 0
	i = open_paren
	while i < len(src):
		ch = src[i]
		if ch in "([{":
			depth += 1
		elif ch in ")]}":
			depth -= 1
			if depth == 0:
				return src[open_paren + 1 : i]
		elif ch == "," and depth == 1:
			return src[open_paren + 1 : i]
		i += 1
	return src[open_paren + 1 :]


def _engine_bindings(src: str) -> tuple[set[str], int]:
	"""useDocumentForm destructure'ından çıkan adlar ve o bağlamanın konumu.

	`[^{}]*` bilerek: `.*?` + DOTALL, dosyanın en başındaki herhangi bir
	`const {`'ten başlayıp aradaki her şeyi yutarak buraya kadar uzanabiliyor.
	O zaman konum 180 yerine 22 çıkıyor, taranan `head` neredeyse boş kalıyor
	ve test hiçbir watch görmeden yeşil yanıyordu.
	"""
	m = re.search(r"const\s*\{([^{}]*)\}\s*=\s*useDocumentForm\(", src)
	if not m:
		return set(), -1
	names = set()
	for part in m.group(1).split(","):
		part = part.strip()
		if not part:
			continue
		names.add(part.split(":")[-1].strip())
	return names, m.start()


class DocumentFormTemporalDeadZone(unittest.TestCase):
	def test_no_watch_reads_engine_bindings_before_they_exist(self):
		files = sorted(PAGES.rglob("*.vue"))
		checked = 0
		for path in files:
			src = path.read_text(encoding="utf-8")
			bindings, at = _engine_bindings(src)
			if at < 0:
				continue
			checked += 1
			head = src[:at]
			for call in re.finditer(r"\bwatch(?:Effect)?\s*\(", head):
				window = _first_argument(head, call.end() - 1)
				used = sorted(b for b in bindings if re.search(rf"\b{re.escape(b)}\b", window))
				self.assertEqual(
					used,
					[],
					f"{path.name}: satır {head[: call.start()].count(chr(10)) + 1} watch() "
					f"useDocumentForm bağlamasını {used} tanımlanmadan okuyor — "
					"watch kaynakları hemen değerlendirir, ReferenceError watcher'ı "
					"sessizce öldürür. Bloğu destructure'ın ALTINA taşı.",
				)
		self.assertGreaterEqual(checked, 7, "useDocumentForm sayfaları bulunamadı — tarama bozuk")


if __name__ == "__main__":
	unittest.main()
