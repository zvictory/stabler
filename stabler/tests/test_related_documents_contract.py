"""Bağlantılı belgeler paneli: bağlandığı her doctype'ta gerçekten çalışmalı.

RelatedDocuments.vue yedi forma bağlı. Panelin işe yaraması iki ayrı şeyin
tutmasına bağlı ve ikisi de sessizce bozulabiliyordu:

1. Backend, konu doctype'ını kabul etmeli. `get_linked_documents` iki ayrı
   liste taşıyordu — sonucu süzen küme Payment Entry'yi içeriyor ama konuyu
   kapayan guard yalnız Sales Order / Sales Invoice'a izin veriyordu. Yedi
   bağlanma noktasının beşi HTTP 417 alıyor, bileşen `catch`'te yutup boş
   panel çiziyordu. Hata mesajı yok, log yok, yalnız kalıcı bir "—".

2. Tıklanabilir görünen bir rozet bir yere GİTMELİ. Rozet, doctype ROUTE_MAP'te
   varsa tıklanabilir çiziliyor; ama hedef ya `${base}/${name}` ya da
   `${base}?open=${name}` oluyor. Payment Entry routed forma geçtiği halde
   drawer dalında kalmıştı ve Payments.vue `?open=` okumuyordu — rozet listeye
   gidip hiçbir şey yapmıyordu.

Bu yüzden testler kaynağı okuyor, tek tek davranış değil sözleşme kilitliyor:
bağlanma noktaları ⊆ kabul edilen küme, ve gezilebilir her doctype'ın gidiş
yolu karşı tarafta gerçekten karşılanıyor.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public/js"
COMPONENT = (JS / "components/RelatedDocuments.vue").read_text(encoding="utf-8")
SALES = (ROOT / "api/sales.py").read_text(encoding="utf-8")


def _mounted_doctypes() -> set[str]:
	"""`<RelatedDocuments ... doctype="X" ...>` geçen her sayfadan X'i topla."""
	found = set()
	for path in JS.rglob("*.vue"):
		if path.name == "RelatedDocuments.vue":
			continue
		src = path.read_text(encoding="utf-8")
		for tag in re.findall(r"<RelatedDocuments\b[^>]*>", src):
			m = re.search(r'doctype="([^"]+)"', tag)
			if m:
				found.add(m.group(1))
	return found


def _js_set(name: str) -> set[str]:
	"""`const NAME = new Set([...])` içindeki string literalleri çıkar."""
	m = re.search(re.escape(name) + r"\s*=\s*new Set\(\[(.*?)\]\)", COMPONENT, re.S)
	assert m, f"{name} kaynakta bulunamadı"
	return set(re.findall(r'"([^"]+)"', m.group(1)))


def _route_map() -> dict[str, str | None]:
	m = re.search(r"const ROUTE_MAP\s*=\s*\{(.*?)\n\};", COMPONENT, re.S)
	assert m, "ROUTE_MAP kaynakta bulunamadı"
	out: dict[str, str | None] = {}
	for line in m.group(1).split("\n"):
		entry = re.match(r'\s*"?([A-Za-z ]+?)"?\s*:\s*(null|"([^"]*)")', line.strip())
		if entry:
			out[entry.group(1)] = None if entry.group(2) == "null" else entry.group(3)
	return out


def _linked_doctypes() -> set[str]:
	m = re.search(r"_LINKED_DOCTYPES\s*=\s*frozenset\(\s*\{(.*?)\}\s*\)", SALES, re.S)
	assert m, "_LINKED_DOCTYPES api/sales.py'de bulunamadı"
	return set(re.findall(r'"([^"]+)"', m.group(1)))


def _list_page_for(router: str, base: str) -> Path | None:
	"""`/purchasing/receipts` → o rotanın component'ini karşılayan .vue dosyası."""
	leaf = base.rsplit("/", 1)[-1]
	route = re.search(rf'path:\s*"{re.escape(leaf)}",[^}}]*?component:\s*(\w+)', router)
	if not route:
		return None
	imp = re.search(rf'import {route.group(1)} from "\./([^"]+)"', router)
	if not imp:
		return None
	path = JS / imp.group(1)
	return path if path.exists() else None


class RelatedDocumentsContract(unittest.TestCase):
	def test_every_mount_site_is_accepted_by_the_endpoint(self):
		"""Bileşenin bağlandığı bir doctype endpoint'te kapalıysa panel ölüdür."""
		mounted = _mounted_doctypes()
		self.assertTrue(mounted, "hiç bağlanma noktası bulunamadı — regex bozulmuş olabilir")
		missing = sorted(mounted - _linked_doctypes())
		self.assertEqual(
			missing,
			[],
			f"RelatedDocuments şu doctype'lara bağlı ama get_linked_documents kabul etmiyor: {missing}",
		)

	def test_subject_and_result_filters_are_one_set(self):
		"""İki ayrı liste kaçınılmaz olarak birbirinden ayrılır — asıl hata buydu."""
		body = SALES[SALES.index("def get_linked_documents") :][:2000]
		self.assertNotIn(
			"allowed_doctypes",
			body,
			"sonuç süzgeci için ayrı bir küme geri gelmiş; konu guard'ı ile aynı kümeyi kullanmalı",
		)
		self.assertEqual(
			body.count("_LINKED_DOCTYPES"),
			2,
			"tek küme hem konu guard'ında hem sonuç süzgecinde kullanılmalı",
		)

	def test_navigable_badges_land_somewhere(self):
		"""Tıklanabilir çizilen her rozetin hedefi karşı tarafta karşılanmalı.

		ROUTE_MAP'te yolu olan doctype tıklanabilir görünür. PATH_DETAIL'deyse
		`${base}/${name}`'e gider — o zaman router'da `:name` rotası olmalı.
		Değilse `${base}?open=${name}`'e gider — o zaman liste sayfası
		`route.query.open` okumalı. İkisi de yoksa rozet hiçbir şey yapmaz.
		"""
		router = (JS / "router.js").read_text(encoding="utf-8")
		path_detail = _js_set("PATH_DETAIL")
		for doctype, base in _route_map().items():
			if not base:
				continue  # SPA'da yok — zaten tıklanamaz çiziliyor
			with self.subTest(doctype=doctype):
				if doctype in path_detail:
					leaf = base.rsplit("/", 1)[-1]
					self.assertRegex(
						router,
						rf'path:\s*"{re.escape(leaf)}/:name"',
						f"{doctype} için {base}/:name rotası yok",
					)
				else:
					page = _list_page_for(router, base)
					self.assertIsNotNone(page, f"{doctype} için {base} liste rotası yok")
					self.assertRegex(
						page.read_text(encoding="utf-8"),
						r"query\??\.open",
						f"{doctype} drawer dalında ama {page.name} `?open=` okumuyor — "
						"rozet listeye gidip hiçbir şey yapmaz",
					)


if __name__ == "__main__":
	unittest.main()
