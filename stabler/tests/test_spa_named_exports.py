"""SPA'da göreli olarak import edilen her adlandırılmış simge gerçekten export ediliyor mu?

Neden bu testin bir maliyeti hak ettiği: esbuild eksik bir adlandırılmış export'u
uyarı değil **hard error** yapar ("No matching export"), ve prod'da `bench build`
rsync'ten SONRA koşar. Yani bu hata canlıya yarım güncellenmiş bir uygulama
olarak iner — dosyalar değişmiş, paket derlenmemiş, yedeği geri yüklemekten
başka çıkış yok.

Nasıl oluşuyor: çağıranı commit edip çağrılanı commit etmemek. Ölçülmüş vaka —
`fe25fec` `Suppliers.vue`'yu `formatTime` import'uyla birlikte commit etti, ama
`formatTime` `date.js`'te çalışma ağacında kaldı. Çalışan geliştirici makinesinde
her şey derleniyordu; kırık olan yalnızca HEAD'di, ve bunu ancak deploy'un
temiz export'u fark etti. Tek bir dosyayı okuyan hiçbir test bunu göremez —
kırık olan ilişkinin kendisi.

Frappe önyüklemesi yok: yalnız kaynak okur ve ayrıştırır.
"""

import os
import re
import unittest
from pathlib import Path

SPA = Path(__file__).parents[1] / "public" / "js"

# `[^}]*` satır sonlarını da yer, o yüzden çok satırlı import blokları da yakalanır
# (ölçüldü: 8 tane var).
_IMPORT = re.compile(r"""import\s*\{([^}]*)\}\s*from\s*["'](\.[^"']+)["']""")
_EXPORT_DECL = re.compile(r"^\s*export\s+(?:async\s+)?(?:function|const|let|var|class)\s+(\w+)", re.M)
_EXPORT_BLOCK = re.compile(r"^\s*export\s*\{([^}]*)\}", re.M)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.M)

# Taramanın gerçekten kenar okuduğunu kanıtlayan çapa. Regex bozulsa ya da
# SPA yolu kaysa aşağıdaki "eksik yok" iddiası boş kümeyle sessizce geçerdi —
# yeşil bir test hiçbir şey doğrulamamış olurdu.
_ANCHOR = ("pages/purchasing/Suppliers.vue", "formatDate", "composables/date.js")


def _strip_comments(text: str) -> str:
	"""Yorum içindeki örnek kullanımlar import değildir.

	`composables/i18n.js` başlığında `import { t } from "./composables/i18n.js";`
	yazan bir kullanım örneği var; yorumları atmazsak tarayıcı onu çözülemeyen
	bir kenar sanır."""
	return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _source_files():
	for dirpath, dirnames, filenames in os.walk(SPA):
		dirnames[:] = [d for d in dirnames if d not in ("node_modules", "dist")]
		for fn in sorted(filenames):
			if fn.endswith((".js", ".mjs", ".vue")):
				yield Path(dirpath) / fn


def _exports_of(path: Path) -> set:
	text = _strip_comments(path.read_text(encoding="utf-8"))
	names = set(_EXPORT_DECL.findall(text))
	for block in _EXPORT_BLOCK.findall(text):
		for part in block.split(","):
			part = part.strip()
			if part:
				# `export { a as b }` dışarıya `b` verir.
				names.add(part.split()[-1])
	return names


def _resolve(importer: Path, rel: str):
	base = (importer.parent / rel).resolve()
	for cand in (base, base.with_suffix(base.suffix + ".js"), base / "index.js"):
		if cand.is_file():
			return cand
	return None


def _scan():
	"""(eksik, çözülemeyen, çözülmüş_kenarlar, dosya_sayısı) döndürür.

	`seen` bilerek pozitif bir kayıt: çapayı "eksikler arasında değil" diye
	kontrol etmek hiçbir şey kanıtlamaz — var olmayan bir simge de eksikler
	arasında olmaz, çünkü onu import eden kimse yoktur."""
	missing, unresolved, seen, files = [], [], set(), 0
	cache = {}
	for src in _source_files():
		files += 1
		text = _strip_comments(src.read_text(encoding="utf-8"))
		for names, rel in _IMPORT.findall(text):
			target = _resolve(src, rel)
			if target is None:
				unresolved.append((str(src.relative_to(SPA)), rel))
				continue
			if target not in cache:
				cache[target] = _exports_of(target)
			for raw in names.split(","):
				raw = raw.strip()
				if not raw:
					continue
				# `import { a as b }` -> dışarıdan istenen ad `a`.
				symbol = raw.split()[0]
				if symbol == "default":
					continue
				edge = (str(src.relative_to(SPA)), symbol, str(target.relative_to(SPA)))
				if symbol in cache[target]:
					seen.add(edge)
				else:
					missing.append(edge)
	return missing, unresolved, seen, files


class TestSpaNamedExports(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.missing, cls.unresolved, cls.seen, cls.files = _scan()

	def test_the_scan_actually_read_the_spa(self):
		"""Çapa: bu geçmezse aşağıdaki iddialar boş kümeyi doğruluyor demektir."""
		self.assertGreater(self.files, 200, "SPA kaynak dosyaları bulunamadı — yol kaymış olabilir")
		self.assertGreater(len(self.seen), 800, "göreli adlandırılmış import kenarı çözülemedi")
		self.assertIn(
			_ANCHOR,
			self.seen,
			"çapa kenarı bulunamadı — tarayıcı ya dosyayı ya export'ları okuyamıyor",
		)

	def test_every_named_import_has_a_matching_export(self):
		"""esbuild bunu hard error yapar ve prod'da rsync'ten sonra koşar."""
		lines = [f"{src} -> {sym} ({tgt})" for src, sym, tgt in self.missing]
		self.assertEqual(
			self.missing,
			[],
			"eksik export — prod'da `bench build` bu yüzden patlar:\n  " + "\n  ".join(lines),
		)

	def test_every_relative_import_resolves_to_a_file(self):
		"""Çözülemeyen yol da aynı yerde patlar; ayrı tutuluyor çünkü nedeni
		farklı — silinmiş/taşınmış dosya, eksik export değil."""
		lines = [f"{src} -> {rel}" for src, rel in self.unresolved]
		self.assertEqual(
			self.unresolved,
			[],
			"göreli import bir dosyaya çözülmüyor:\n  " + "\n  ".join(lines),
		)


if __name__ == "__main__":
	unittest.main()
