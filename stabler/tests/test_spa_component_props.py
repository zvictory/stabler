"""Bir çağıranın geçirdiği her prop, hedef bileşende gerçekten tanımlı mı?

Neden bu testin bir maliyeti hak ettiği: Vue'da bildirilmemiş bir öznitelik
**hata değildir**. `defineProps` içinde yoksa, öznitelik kök elemana düşen bir
fallthrough HTML özniteliği olur; bileşen kendi varsayılanını (`0`, `false`,
`""`) görür ve sessizce yanlış çalışır. Derleme geçer, konsol sessizdir, prod
sessizdir. Yalnız kullanıcı fark eder — ve genelde geç.

Ölçülmüş iki vaka, ikisi de bu daldan çıktı:

* `MoneyInput.vue`'nun `hideCurrency` prop'u `maxFractionDigits` eklenirken
  silindi, ama beş çağıran hâlâ `hide-currency` geçiriyordu. Sonuç: msa'nın
  ithalat formlarında yoğun tablo hücrelerine para birimi rozeti geri geldi.
* `TransporterCenter.vue` `Pagination`'a `:total-rows` / `v-model:page`
  geçiriyordu; bileşen `total` / `limitStart` tanımlar. Sayfalama `total=0`
  görüp ileri düğmesini kalıcı olarak kapalı tutuyordu.

İkisi de derlendi. İkisi de canlıya çıktı. Tek bir dosyayı okuyan hiçbir test
göremezdi — kırık olan ilişkinin kendisi.

Frappe önyüklemesi yok: yalnız kaynak okur ve ayrıştırır.
"""

import os
import re
import unittest
from pathlib import Path

SPA = Path(__file__).parents[1] / "public" / "js"

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_SCRIPT = re.compile(r"<script[^>]*>(.*?)</script>", re.S)
_TEMPLATE = re.compile(r"<template>(.*)</template>", re.S)
# Yalnız göreli `.vue` import'ları: kütüphane bileşenlerinin (vue-flow gibi)
# prop'ları bu depoda değil, okunamaz.
_LOCAL_IMPORT = re.compile(r'^\s*import\s+([A-Z][\w$]*)\s+from\s+["\'](\.[^"\']+\.vue)["\']', re.M)
# Etiket gövdesi tırnak farkındadır: `v-if="!error && total > 0"` içindeki `>`
# etiketi kapatmaz. Naif `[^>]*` orada durur ve etiketin geri kalan
# özniteliklerini sessizce kaçırırdı (ölçüldü: çapa kenarı böyle kayboldu).
_TAG = re.compile(r"""<([A-Z][\w]*)\b((?:"[^"]*"|'[^']*'|[^>"'])*)>""", re.S)
_DEFINE_PROPS_OBJ = re.compile(r"defineProps\s*\(\s*\{(.*?)\n\}\s*\)", re.S)
_DEFINE_PROPS_ARR = re.compile(r"defineProps\s*\(\s*\[([^\]]*)\]")
_KEY = re.compile(r"^\s*([\w$]+)\s*:", re.M)
# Öznitelik *adları* — değerler önce sıyrılır, yoksa `class="border-0 py-4"`
# içindeki `border-0` bir prop sanılır (ölçüldü: 11 yanlış pozitif).
_ATTR_NAME = re.compile(r'(?:^|\s):?([a-z][\w]*(?:-[\w]+)+)(?==|\s|$)')
_ATTR_VALUE = (re.compile(r'=\s*"[^"]*"'), re.compile(r"=\s*'[^']*'"))
_VMODEL_ARG = re.compile(r"\sv-model:([a-zA-Z][\w-]*)")

# Vue'nun kendi öznitelikleri ve HTML global'leri prop değildir.
_SKIP_PREFIX = ("data-", "aria-", "v-", "xmlns")
_SKIP = {"active-class", "exact-active-class"}

# Taramanın gerçekten kenar okuduğunun kanıtı. Regex bozulsa ya da SPA yolu
# kaysa "eksik yok" iddiası boş kümeyi doğrular ve sessizce yeşil kalırdı.
_ANCHOR = ("pages/imports/ImportContainers.vue", "pageCount", "components/Pagination.vue")


def _camel(kebab: str) -> str:
	head, *rest = kebab.split("-")
	return head + "".join(p[:1].upper() + p[1:] for p in rest)


def _vue_files():
	for dirpath, dirnames, filenames in os.walk(SPA):
		dirnames[:] = [d for d in dirnames if d not in ("node_modules", "dist")]
		for fn in sorted(filenames):
			if fn.endswith(".vue"):
				yield Path(dirpath) / fn


def _declared_props(path: Path) -> set:
	script = "\n".join(_SCRIPT.findall(path.read_text(encoding="utf-8")))
	names = set()
	obj = _DEFINE_PROPS_OBJ.search(script)
	if obj:
		names |= set(_KEY.findall(obj.group(1)))
	for arr in _DEFINE_PROPS_ARR.findall(script):
		names |= set(re.findall(r"[\"']([\w$]+)[\"']", arr))
	return names


def _passed_names(attrs: str):
	"""Bir açılış etiketinin geçirdiği prop adları (camelCase)."""
	for pat in _ATTR_VALUE:
		attrs = pat.sub("=", attrs)
	for name in _ATTR_NAME.findall(attrs):
		if name.startswith(_SKIP_PREFIX) or name in _SKIP:
			continue
		yield _camel(name)


def _scan():
	"""(eksik, görülen_kenarlar, dosya_sayısı, çözülen_bileşen_sayısı)."""
	missing, seen = [], set()
	props_of, files = {}, 0
	for src in _vue_files():
		files += 1
		text = _BLOCK_COMMENT.sub("", src.read_text(encoding="utf-8"))
		script = "\n".join(_SCRIPT.findall(text))
		imports = dict(_LOCAL_IMPORT.findall(script))
		tpl = _TEMPLATE.search(text)
		if not tpl or not imports:
			continue
		for tag, attrs in _TAG.findall(tpl.group(1)):
			rel = imports.get(tag)
			if not rel:
				continue
			target = (src.parent / rel).resolve()
			if not target.is_file():
				continue
			if target not in props_of:
				props_of[target] = _declared_props(target)
			# `v-model:limit-start` hedefte `limitStart` prop'u ister; `v-`
			# önekiyle elendiği için ayrıca toplanır.
			names = list(_passed_names(attrs)) + [_camel(a) for a in _VMODEL_ARG.findall(attrs)]
			for name in names:
				edge = (
					str(src.relative_to(SPA)),
					name,
					str(target.relative_to(SPA)),
				)
				if name in props_of[target]:
					seen.add(edge)
				else:
					missing.append(edge)
	return missing, seen, files, len(props_of)


class TestSpaComponentProps(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.missing, cls.seen, cls.files, cls.components = _scan()

	def test_the_scan_actually_read_the_spa(self):
		"""Çapa: bu geçmezse aşağıdaki iddia boş kümeyi doğruluyor demektir."""
		self.assertGreater(self.files, 200, "SPA .vue dosyaları bulunamadı — yol kaymış olabilir")
		self.assertGreater(self.components, 40, "hiçbir göreli bileşen import'u çözülmedi")
		self.assertGreater(len(self.seen), 250, "prop kenarı okunamadı — öznitelik ayrıştırıcı bozuk")
		self.assertIn(
			_ANCHOR, self.seen,
			"çapa kenarı bulunamadı — tarayıcı ya şablonu ya defineProps'u okuyamıyor",
		)

	def test_every_passed_prop_is_declared_by_the_target_component(self):
		"""Bildirilmemiş prop hata vermez — fallthrough özniteliğe düşer ve
		bileşen kendi varsayılanıyla sessizce yanlış çalışır."""
		lines = [f"{src}: <{tgt.split('/')[-1][:-4]} {sym}> — hedefte tanımlı değil" for src, sym, tgt in self.missing]
		self.assertEqual(
			self.missing, [],
			"çağıran, hedefin tanımlamadığı bir prop geçiriyor:\n  " + "\n  ".join(lines),
		)


if __name__ == "__main__":
	unittest.main()
