"""Party Center'ın kayıt-başına yükleyicileri sıra dışı yanıtlara karşı korunmalı.

`PartyCenter.vue` Müşteri ve Tedarikçi merkezlerinin ORTAK kabuğu. Seçili kayıt
için dört uç nokta çağrılıyor (ekstre, siparişler, teklifler, detay) ve dördü de
`await`'ten sonra paylaşılan bir `ref`'e yazıyordu. A kaydına tıklayıp yanıt
dönmeden B'ye geçildiğinde A'nın geç dönen yanıtı B'nin adı altında boyanıyor:
ekranda B yazıyor, rakamlar A'nın. Kullanıcı için sessiz — hata yok, yalnızca
yanlış para.

Bu dosya `useLatestRequest` kablolamasını kaynaktan pinliyor. Frappe önyüklemesi
yok; SFC yalnız metin olarak okunuyor (repoda DOM'lu test altyapısı yok:
`vitest.config.mjs` → `environment: "node"`, `@vue/test-utils` kurulu değil).

En kritik pin `test_each_loader_owns_its_ticket`: dört yükleyici TEK bir ortak
sayaca bağlanırsa kod "sadeleşmiş" görünür ama bozulur — `selectRow` ve
`prefetchSelection` dördünü peş peşe çağırdığı için ortak sayaçta yalnız sonuncu
çağrı geçerli kalır, diğer üç panel hiç dolmaz.
"""

import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "public" / "js" / "components" / "party" / "PartyCenter.vue"

# (yükleyici, kendi bilet üreteci, await sonrası paylaşılan duruma ilk yazma)
LOADERS = (
	("loadLedger", "ledgerReq", "ledger.value = res;"),
	("loadOrders", "ordersReq", "orders.value = res;"),
	("loadQuotes", "quotesReq", "quotes.value = Array.isArray(res) ? res : res?.rows || [];"),
	("loadDetail", "detailReq", "recentInvoices.value = detail.recent_invoices || [];"),
)

# Yükleniyor bayrağı olan yükleyiciler: `finally` bileti sormak zorunda.
LOADERS_WITH_FLAG = (
	("loadLedger", "ledgerLoading"),
	("loadOrders", "ordersLoading"),
	("loadQuotes", "quotesLoading"),
)

GUARD = "if (!isCurrent()) return;"


def _src():
	return SOURCE.read_text(encoding="utf-8")


def _body(src, name):
	start = src.index(f"async function {name}(row) {{")
	# Gövde, kendi bildiriminden bir tab daha içeride; kapanışı tek başına duran
	# ilk süslü parantez satırı.
	return src[start : src.index("\n}\n", start)]


class PartyCenterRaceGuardTest(unittest.TestCase):
	def setUp(self):
		self.src = _src()

	def test_each_loader_owns_its_ticket(self):
		"""Ortak tek sayaç, `selectRow`'un dörtlü serisini kendi içinde iptal ederdi."""
		self.assertEqual(
			self.src.count("useLatestRequest()"),
			len(LOADERS),
			"her yükleyicinin kendi bilet üreteci olmalı — ortak sayaç dördünden üçünü iptal eder",
		)
		for loader, req, _ in LOADERS:
			with self.subTest(loader=loader):
				body = _body(self.src, loader)
				self.assertIn(f"{req}.take()", body)
				self.assertLess(
					body.index(f"{req}.take()"),
					body.index("await call("),
					"bilet `await`'ten ÖNCE alınmalı",
				)

	def test_the_ticket_is_checked_between_the_await_and_the_write(self):
		for loader, _, write in LOADERS:
			with self.subTest(loader=loader):
				body = _body(self.src, loader)
				# Pencere bilerek sınırlı: gövdenin sonuna kadar aramak `catch`
				# dalındaki aynı satırı da yakalar, o zaman bu guard silinse bile
				# test yeşil kalırdı.
				self.assertIn(GUARD, body[body.index("await call(") : body.index(write)])

	def test_a_stale_failure_does_not_blank_the_current_record(self):
		# `loadDetail`'in `catch`'i yalnız `console.error` — paylaşılan duruma
		# yazmadığı için bileti sormasına gerek yok, bu yüzden listede değil.
		for loader in ("loadLedger", "loadOrders", "loadQuotes"):
			with self.subTest(loader=loader):
				body = _body(self.src, loader)
				self.assertIn(GUARD, body[body.index("} catch") : body.index("} finally")])

	def test_a_stale_request_does_not_drop_the_skeleton(self):
		# `finally` erken `return`'den SONRA da koşar: emekli isteğin paylaşılan
		# duruma erişebildiği tek yer burası. Bayrağı korumasız indirirse iskelet
		# kalkar, tablo "yüklendi" görünür ama önceki kaydın satırlarını gösterir.
		for loader, flag in LOADERS_WITH_FLAG:
			with self.subTest(loader=loader):
				body = _body(self.src, loader)
				self.assertIn(f"if (isCurrent()) {flag}.value = false;", body[body.index("} finally") :])

	def test_every_deselect_path_retires_the_in_flight_requests(self):
		"""Üç yol da seçimi kaldırıyor; biri unutulursa o yolda panel kendiliğinden dolar."""
		# Pencereler bloğa göre kuruluyor: yalnız sayıya bakmak, üçünün de aynı
		# bloğa yazılmasıyla yeşil kalırdı.
		windows = (
			("ESC", "useEscapeBack(() => {", "return true;"),
			("liste yenilendi, kayıt düştü", "const fresh = rows.value.find(", "\n\t\t}"),
			("şirket değişimi", "watch(activeCompany, () => {", "\tloadList();"),
		)
		for label, opener, closer in windows:
			with self.subTest(path=label):
				start = self.src.index(opener)
				block = self.src[start : self.src.index(closer, start)]
				self.assertIn("invalidatePartyRequests();", block)
		self.assertEqual(
			self.src.count("invalidatePartyRequests();"),
			len(windows),
			"seçimi kaldıran yol sayısı değiştiyse pencereler de güncellenmeli",
		)

	def test_invalidate_retires_all_four_and_clears_the_flags(self):
		start = self.src.index("function invalidatePartyRequests() {")
		body = self.src[start : self.src.index("\n}\n", start)]
		for _, req, _ in LOADERS:
			with self.subTest(req=req):
				self.assertIn(f"{req}.invalidate();", body)
		for _, flag in LOADERS_WITH_FLAG:
			with self.subTest(flag=flag):
				# Emekli isteğin `finally`'si artık bayrağı temizlemiyor; burada
				# indirilmezse iskelet sonsuza kadar döner.
				self.assertIn(f"{flag}.value = false;", body)


if __name__ == "__main__":
	unittest.main()
