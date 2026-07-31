"""Modernist Tabler tasarım katmanının sözleşmesi.

Katman kademeli göç için yazıldı: bir ekranı yeni dile taşımak = kök elemana
`class="stbl-ds"` eklemek. Bu ancak katmanın TAMAMI o sarmalayıcıya scope'lu
kalırsa güvenli olur — tek bir kapsam dışı kural, taşınmamış her ekranı
(Dashboard, POS, CRM, Purchasing) sessizce etkiler.

Buradaki testlerin hepsi geçmişte GERÇEKTEN yapılmış bir hatayı kilitliyor:
kapsam kaçağı, tarayıcı varsayılanı kenar, dış font CDN'i, Kiril kaybı.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS_PATH = ROOT / "stabler/public/css/stabler-modernist.css"
HTML_PATH = ROOT / "stabler/www/stabler.html"
FONT_DIR = ROOT / "stabler/public/fonts"

CSS = CSS_PATH.read_text(encoding="utf-8")
HTML = HTML_PATH.read_text(encoding="utf-8")

# Yorumları at — içlerinde örnek seçici ve URL geçiyor, tarama onları
# gerçek kural sanmasın.
CSS_NO_COMMENTS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)


def _rule_selectors(src=None):
	"""Stil bloğu olan her seçiciyi tek tek döndür.

	Düz regex yetmiyor: `@keyframes` içindeki `from`/`to` adımları da `X { }`
	şeklinde görünüyor ve seçici sanılıyor; `@media` blokları ise İÇİNE
	inilmesi gereken sarmalayıcılar. Bu yüzden dengeli parantez yürüyüşü —
	font-face/keyframes atlanır, media/supports'a girilir.
	"""
	if src is None:
		src = CSS_NO_COMMENTS
	i, n = 0, len(src)
	while i < n:
		brace = src.find("{", i)
		if brace == -1:
			return
		head = src[i:brace].replace("}", " ").strip()
		depth, j = 1, brace + 1
		while j < n and depth:
			if src[j] == "{":
				depth += 1
			elif src[j] == "}":
				depth -= 1
			j += 1
		if head.startswith(("@media", "@supports")):
			yield from _rule_selectors(src[brace + 1 : j - 1])
		elif head.startswith("@"):
			pass  # @font-face, @keyframes — seçici içermez
		elif head:
			for sel in head.split(","):
				sel = sel.strip()
				if sel:
					yield sel
		i = j


class TestScopeIsolation(unittest.TestCase):
	def test_every_rule_lives_under_the_stbl_ds_wrapper(self):
		"""Yayılma yarıçapı sıfır olmalı. Bir kural sarmalayıcının dışına
		çıkarsa taşınmamış ekranlar da onu görür — göçün tüm güvenliği bu
		tek değişmezde."""
		escaped = [s for s in _rule_selectors() if ".stbl-ds" not in s and s != ":root"]
		self.assertEqual(escaped, [], f"kapsam dışı kural: {escaped}")

	def test_root_block_only_declares_variables(self):
		""":root tek istisna; orada da yalnız token tanımı olabilir, görsel
		kural olamaz."""
		for block in re.finditer(r":root\s*\{([^}]*)\}", CSS_NO_COMMENTS):
			for decl in block.group(1).split(";"):
				decl = decl.strip()
				if decl:
					self.assertTrue(
						decl.startswith("--"),
						f":root içinde token olmayan bildirim: {decl}",
					)


class TestUserAgentBorderReset(unittest.TestCase):
	"""Bu bileşenler <button> olarak render ediliyor. Tarayıcı butona
	varsayılan `2px outset` kenar verir; Tabler'ın .btn reset'i bu sınıflara
	uygulanmıyor. Reset olmadan kutular kalın gri çerçeveyle çıkıyor —
	tasarımda bir kez böyle kırıldı."""

	BUTTON_COMPONENTS = ("ds-kpi", "ds-stage", "ds-row", "ds-band")

	def test_button_components_reset_the_default_border(self):
		for cls in self.BUTTON_COMPONENTS:
			with self.subTest(component=cls):
				block = re.search(
					r"\.stbl-ds \.%s\s*\{([^}]*)\}" % cls, CSS_NO_COMMENTS
				)
				self.assertIsNotNone(block, f".{cls} temel kuralı yok")
				self.assertRegex(
					block.group(1),
					r"border:\s*0",
					f".{cls} kuralı `border: 0` reset'i taşımıyor",
				)

	def test_border_style_is_declared_where_borders_are_drawn(self):
		"""`border: 0` sonrası yalnız genişlik/renk vermek yetmez — stil de
		açıkça `solid` olmalı, yoksa kenar hiç çizilmez."""
		self.assertIn("border-style: solid", CSS_NO_COMMENTS)


class TestSelfSufficiency(unittest.TestCase):
	def test_layer_sets_its_own_box_sizing(self):
		"""Üretimde Tabler zaten border-box veriyor; ama katman referans
		sayfalarında Tabler'sız da doğru ölçmeli. Bu olmadan çekmece 2px
		kaydı."""
		self.assertRegex(CSS_NO_COMMENTS, r"\.stbl-ds\s*,\s*\.stbl-ds \*[^{]*\{[^}]*box-sizing:\s*border-box")


class TestFontsAreSelfHosted(unittest.TestCase):
	"""Kiracı ağları dış CDN'e çıkamıyor. Google Fonts'a link vermek ekranı
	sistem fontuna düşürür ve tasarımın tipografisi tamamen kaybolur."""

	def test_no_external_font_cdn_in_css_or_shell(self):
		for needle in ("fonts.googleapis.com", "fonts.gstatic.com", "//fonts."):
			with self.subTest(needle=needle):
				self.assertNotIn(needle, CSS)
				self.assertNotIn(needle, HTML)

	def test_every_referenced_font_file_exists_in_the_repo(self):
		refs = set(re.findall(r'url\("\.\./fonts/([^"]+)"\)', CSS))
		self.assertTrue(refs, "katman hiç font referansı içermiyor")
		for name in sorted(refs):
			with self.subTest(font=name):
				self.assertTrue(
					(FONT_DIR / name).is_file(),
					f"{name} CSS'te referanslı ama stabler/public/fonts/ altında yok",
				)


class TestCyrillicCoverage(unittest.TestCase):
	"""Archivo'da Kiril YOK — doğrulandı. Stabler ru ve uzc servis ediyor.
	Bölme kaldırılırsa Kiril metin sessizce sistem fontuna düşer."""

	def test_cyrillic_range_is_split_onto_a_font_that_has_it(self):
		self.assertIn("unicode-range", CSS)
		blocks = re.findall(r"@font-face\s*\{[^}]*\}", CSS, flags=re.S)
		cyrillic = [b for b in blocks if "U+04" in b or "U+0400" in b]
		self.assertTrue(cyrillic, "Kiril unicode-range bloğu yok")
		for block in cyrillic:
			with self.subTest(block=block[:60]):
				self.assertNotIn(
					"archivo", block.lower(),
					"Kiril aralığı Archivo'ya bağlanmış — o fontta Kiril yok",
				)


class TestTextEmphasisTokensAreLiteral(unittest.TestCase):
	"""Tasarım, KENAR için parlak Tabler tonunu, METİN için koyu varyantı
	kullanıyor. Tabler'ın kendi emphasis rampası bu iş için yanlış:
	--tblr-danger-text-emphasis = #561717 (uyarı kutusu zemini için),
	--tblr-orange-text-emphasis ise hiç tanımlı değil. Bu yüzden ikisi
	bilerek sabit — biri var() zincirine geri düşerse renk sessizce bozulur."""

	def test_tokens_do_not_fall_back_to_tabler_emphasis_ramp(self):
		for token in ("--ds-crit-tx", "--ds-today-tx"):
			with self.subTest(token=token):
				decl = re.search(rf"{token}:\s*([^;]+);", CSS_NO_COMMENTS)
				self.assertIsNotNone(decl, f"{token} tanımlı değil")
				self.assertNotIn(
					"text-emphasis", decl.group(1),
					f"{token} Tabler emphasis rampasına bağlanmış",
				)

	def test_bright_and_text_tones_are_not_the_same_value(self):
		"""Aynı olurlarsa ayrımın anlamı kalmaz ve kontrast düzeltmesi
		sessizce geri alınmış olur."""
		pairs = [("--ds-crit", "--ds-crit-tx"), ("--ds-today", "--ds-today-tx")]
		for bright, text in pairs:
			with self.subTest(pair=(bright, text)):
				b = re.search(rf"{bright}:\s*([^;]+);", CSS_NO_COMMENTS).group(1)
				t = re.search(rf"{text}:\s*([^;]+);", CSS_NO_COMMENTS).group(1)
				self.assertNotEqual(b.strip(), t.strip())


class TestShellWiring(unittest.TestCase):
	def test_layer_is_linked_after_the_base_stylesheet(self):
		"""Sıra önemli: katman token'ları stabler.css'in --tblr-primary
		override'ından sonra okumalı."""
		base = HTML.index("css/stabler.css")
		layer = HTML.index("css/stabler-modernist.css")
		self.assertLess(base, layer, "katman temel stylesheet'ten ÖNCE bağlanmış")

	def test_layer_link_is_cache_busted(self):
		self.assertRegex(
			HTML,
			r"css/stabler-modernist\.css\?v=\{\{\s*asset_version\s*\}\}",
			"katman linkinde cache-bust yok — deploy sonrası bayat CSS servis edilir",
		)


if __name__ == "__main__":
	unittest.main()
