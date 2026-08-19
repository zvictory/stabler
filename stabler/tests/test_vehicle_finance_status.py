"""Vehicle Agreement durum makinesi — sekiz durum ilan edildi, üçünün yazanı yoktu.

`stabler-cibo` sekiz durumluk enum'u ve `Rescheduled` (tahsil edilebilir) ile
`Restructured` (terminal) ayrımını doğru biçimde getirdi. Ama yalnızca bazı
durumlar yazan kazandı: `v1.py` `agreement_status`ı tam iki yerde yazıyordu —
:470 `Active` ve :929 `Rescheduled`. `Completed`, `Terminated` ve `Restructured`
hiçbir yerde yazılmıyordu.

Sonuçları ölçülmüş hâliyle:

  1. TAMAMEN ÖDENMİŞ BİR SÖZLEŞME `Active` KALIYOR. Faturanın `outstanding`ı sıfıra
     inse bile durum değişmiyor; sözleşme sonsuza dek tahsilat kuyruğunda duruyor.
  2. `settlement_writeoff` yetkisinin tüketicisi yok. `permissions.py:42` onu
     tanımlayıp Manager'a veriyor, ama hiçbir uç onu istemiyor — yani bir
     sözleşmeyi zarar yazarak kapatmanın yolu yok.
  3. `approve_reschedule` hiçbir durum kapısı taşımıyordu: kapanmış bir sözleşme
     bile yeniden planlanabiliyordu.

Şema ve OKUMA yolu zaten vardı (`STATUS_MAP` rozet renkleri, `chain.py` zincir
matematiği, `restructured_from` kolonu). Eksik olan tek şey YAZANDI.

Bu dosya makineyi frappe'siz yargılıyor — `chain.py`nin sözleşmesiyle aynı: her
fonksiyon argümanlarının total fonksiyonu, dolayısıyla bench, site ve veritabanı
olmadan ölçülebilir. Yazanların gerçekten makineden geçtiği ise `v1.py` üzerinde
AST ile ölçülüyor; tek bir kaçak atama, "tek makine" güvencesini yok eder.

`Restructured` bilerek DIŞARIDA: ADR (docs/decisions/2026-08-16-restructure-closes-
and-reopens.md) restructure'ın orijinali kapatıp bir ARDIL yarattığını söylüyor,
yani o bir durum yazımı değil belge yaratma akışı. Tablo geçişi tanır, yazanı
ayrı iş. Backlog `stabler-2671` bunu tek ebeveyn altında bölmeye açıkça izin
veriyor — koşulu, paylaşılan tablonun ÖNCE gelmesi.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_vehicle_finance_status -v
"""

import ast
import json
import re
import unittest
from pathlib import Path

from stabler.api.vehicle_finance import status as S

ROOT = Path(__file__).resolve().parents[1]
DOCTYPE = ROOT / "stabler/doctype/vehicle_agreement/vehicle_agreement.json"
V1 = ROOT / "api/vehicle_finance/v1.py"
SETTER = "_set_status"
FIELD = "agreement_status"

#: Bilerek yazıcısız bırakılan durumlar. `Restructured` stabler-2671'e ertelendi;
#: `Review` ve `Approved` henüz var olmayan bir sözleşme onay akışına ait. Liste
#: `test_the_declared_gaps_really_have_no_writer` tarafından budanır.
DEFERRED_WRITERS = frozenset({"Restructured", "Review", "Approved"})


def _declared_states() -> list[str]:
	fields = json.loads(DOCTYPE.read_text(encoding="utf-8"))["fields"]
	options = next(f for f in fields if f["fieldname"] == "agreement_status")["options"]
	return [s for s in options.split("\n") if s]


def _code_only(src: str) -> str:
	"""Yorumları ve docstring'leri at.

	Testin sorusu "kod bu yetkiyi İSTİYOR mu"; onu ANLATAN bir docstring o isteğe
	ait değil. Ham metni taramak yorum yazmayı cezalandırır ve daha kötüsü, yetki
	çağrısı silindiğinde docstring testi yeşil tutar — bu tam olarak burada oldu ve
	bir mutasyon tarafından yakalandı.
	"""
	kept = []
	for line in src.split("\n"):
		if line.lstrip().startswith("#"):
			continue
		kept.append(line.split(" #")[0] if " #" in line else line)
	body = "\n".join(kept)
	while body.count('"""') >= 2:
		start = body.index('"""')
		end = body.index('"""', start + 3) + 3
		body = body[:start] + body[end:]
	return body


#: Alana yazabilen çağrı biçimleri. `get_value` kasten yok — okumak yazmak değil.
_WRITE_CALLS = ("set_value", "db_set", "set", "update")

#: Paketteki her modül. Tarama önce yalnızca v1.py'yi geziyordu; aynı sütuna
#: read.py, work.py veya activation.py da yazabilir ve tarama bunu görmezdi.
_PACKAGE = V1.parent


def _vf_trees() -> list[tuple[str, ast.Module]]:
	return [
		(path.name, ast.parse(path.read_text(encoding="utf-8")))
		for path in sorted(_PACKAGE.glob("*.py"))
		if path.name != "__init__.py"
	]


def _v1_tree() -> ast.Module:
	return ast.parse(V1.read_text(encoding="utf-8"))


def _mentions_the_field(node: ast.AST) -> bool:
	return any(isinstance(child, ast.Constant) and child.value == FIELD for child in ast.walk(node))


def _status_writes() -> list[tuple[str, str, int]]:
	"""(modül, kapsayan fonksiyon, satır) — `agreement_status` alanına yazan her yer.

	Atama VE çağrı biçimleri. İlk hâli yalnızca `<bir şey>.agreement_status = ...`
	görüyordu, ama `_set_status`'ın kendisi `frappe.db.set_value(...)` ile
	kalıcılaştırıyor — yani tarama tam olarak kendi kapısının kullandığı biçime
	kördü. O kör noktada `v1.py` içine eklenecek doğrudan bir `db.set_value`,
	`test_no_endpoint_assigns_the_status_directly`'yi hiç kızartmadan geçerdi.
	"""
	found = []
	for module, tree in _vf_trees():
		for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
			for node in ast.walk(fn):
				if isinstance(node, ast.Assign):
					for target in node.targets:
						if isinstance(target, ast.Attribute) and target.attr == FIELD:
							found.append((module, fn.name, node.lineno))
				elif isinstance(node, ast.Call):
					name = node.func.attr if isinstance(node.func, ast.Attribute) else ""
					if name in _WRITE_CALLS and _mentions_the_field(node):
						found.append((module, fn.name, node.lineno))
	return found


def _set_status_targets() -> set[str]:
	"""`_set_status(..., "<durum>")` çağrılarındaki sabit hedefler — yani kim yazılıyor."""
	targets = set()
	for _module, tree in _vf_trees():
		for node in ast.walk(tree):
			if not isinstance(node, ast.Call):
				continue
			name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
			if name != SETTER:
				continue
			for arg in node.args[1:]:
				if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
					targets.add(arg.value)
	return targets


class TestTheTableAndTheDoctypeAgree(unittest.TestCase):
	"""Tablo ile enum ayrışırsa makine, belgenin taşıyabildiği bir durumu reddeder."""

	def test_they_declare_the_same_states(self):
		self.assertEqual(
			sorted(S.ALLOWED),
			sorted(_declared_states()),
			"geçiş tablosu ile doctype enum'u ayrışmış",
		)

	def test_no_transition_targets_a_state_the_doctype_cannot_hold(self):
		declared = set(_declared_states())
		for current, targets in S.ALLOWED.items():
			for target in targets:
				self.assertIn(target, declared, f"{current} -> {target}: hedef enum'da yok")


class TestEveryStateIsReachable(unittest.TestCase):
	"""Bu dosyanın var olma sebebi: ilan edilip ulaşılamayan durum, yalan şemadır."""

	def test_every_state_except_the_initial_one_is_some_transitions_target(self):
		reachable = {t for targets in S.ALLOWED.values() for t in targets}
		unreachable = sorted(set(S.ALLOWED) - reachable - {S.INITIAL})
		self.assertEqual(
			unreachable,
			[],
			f"ilan edilmiş ama hiçbir geçişin hedefi olmayan durum(lar): {unreachable}",
		)

	def test_the_five_that_had_no_writer_are_reachable_by_name(self):
		# Adlarıyla: bulgunun kendisi bunlardı, bir sonraki yeniden düzenlemede
		# genel bir iddianın arkasına saklanmasınlar. Beş, üç değil — ilk sayım
		# `Review` ve `Approved`'ı atlıyordu.
		reachable = {t for targets in S.ALLOWED.values() for t in targets}
		for state in ("Completed", "Terminated", "Restructured", "Review", "Approved"):
			self.assertIn(state, reachable, f"{state} hâlâ ulaşılamaz")

	def test_the_table_has_no_self_transition(self):
		# `_set_status` `current == target` üzerinde erken dönüyor, yani kendine
		# giden hiçbir girdi hiç okunmaz. Okunamayan girdi, koda benzeyen yorumdur:
		# tabloyu bakan biri ona güvenir, oysa davranışı üreten kısa devredir.
		selfies = sorted(state for state, targets in S.ALLOWED.items() if state in targets)
		self.assertEqual(selfies, [], f"tabloda hiç okunmayan kendine-geçiş: {selfies}")

	def test_the_gate_really_short_circuits_on_no_change(self):
		# Yukarıdaki test ancak bu doğruysa haklı. Kısa devre kalkarsa tablo yeniden
		# karar verir ve kendine-geçişlerin yokluğu bir hataya dönüşür.
		setter = next(n for n in ast.walk(_v1_tree()) if isinstance(n, ast.FunctionDef) and n.name == SETTER)
		self.assertTrue(
			any(
				isinstance(node, ast.If)
				and isinstance(node.test, ast.Compare)
				and isinstance(node.test.ops[0], ast.Eq)
				and any(isinstance(b, ast.Return) for b in node.body)
				for node in ast.walk(setter)
			),
			f"{SETTER} artık değişimsiz çağrıda erken dönmüyor — kendine-geçişler tabloya geri gerekli",
		)

	def test_every_state_has_a_writer_or_is_a_declared_gap(self):
		# Ulaşılabilirlik tabloda ispatlanır; YAZILABİLİRLİK ancak kodda. İlk hâli
		# yalnızca tabloya bakıyordu — yani aynı commit'in yazdığı tablonun kendi
		# kendini onaylamasıydı ve bir durum yazıcısını kaybettiğinde kızarmazdı.
		missing = sorted(set(S.ALLOWED) - _set_status_targets() - {S.INITIAL} - DEFERRED_WRITERS)
		self.assertEqual(missing, [], f"hiçbir yerde yazılmayan, bildirilmemiş durum(lar): {missing}")

	def test_the_declared_gaps_really_have_no_writer(self):
		# Cırcır: kapanan bir boşluk listede kalırsa liste bir mazerete dönüşür ve
		# yukarıdaki test o durumu sonsuza dek muaf tutar.
		closed = sorted(DEFERRED_WRITERS & _set_status_targets())
		self.assertEqual(closed, [], f"artık yazıcısı var, listeden silin: {closed}")


class TestClosedIsNotTheSameAsFinal(unittest.TestCase):
	"""`Completed` kapalıdır ama nihai DEĞİLDİR — ve bu ayrım akademik değil.

	Son ödemenin aynı gün iptali faturadaki alacağı geri açar. Son ödemesi iptal
	edilmiş bir sözleşme hiç tamamlanmamıştır: durum bir olgu değil, bir yanlış
	kayıttı. `Completed`ı nihai saymak o sözleşmeyi kalıcı olarak tahsil edilemez
	yapıyordu — alacak açık, iş kuyruğu göremiyor, tahsilat/yeniden planlama/kapatma
	üçü birden reddediyor. `Restructured` ve `Terminated` farklıdır: onları geri
	açmak `chain.py`nin okunur tuttuğu geçmişi yeniden yazmak olurdu.
	"""

	def test_the_final_states_have_no_way_out(self):
		for state in S.FINAL:
			self.assertEqual(S.ALLOWED[state], frozenset(), f"{state} nihai değil")

	def test_completed_is_closed_but_not_final(self):
		self.assertTrue(S.is_closed("Completed"))
		self.assertFalse(S.is_final("Completed"))

	def test_completed_can_only_reopen_into_a_collectible_state(self):
		self.assertEqual(S.ALLOWED["Completed"], frozenset(S.COLLECTIBLE))

	def test_no_closed_agreement_is_collectible(self):
		for state in S.CLOSED:
			self.assertFalse(S.is_collectible(state), f"{state} hâlâ tahsil edilebilir sayılıyor")

	def test_collectible_is_exactly_the_two_live_states(self):
		self.assertEqual(tuple(S.COLLECTIBLE), ("Active", "Rescheduled"))

	def test_closed_and_collectible_never_overlap(self):
		self.assertEqual(set(S.COLLECTIBLE) & set(S.CLOSED), set())

	def test_final_is_a_subset_of_closed(self):
		self.assertTrue(S.FINAL <= S.CLOSED)


class TestTheMachineRefusesClearly(unittest.TestCase):
	def test_a_legal_move_is_allowed(self):
		self.assertTrue(S.can_move("Active", "Completed"))

	def test_an_illegal_move_is_refused(self):
		self.assertFalse(S.can_move("Terminated", "Active"))

	def test_an_unknown_state_is_refused_rather_than_assumed_legal(self):
		# Yazım hatası taşıyan bir durum sessizce geçerli sayılırsa makine hiçbir
		# şey korumaz.
		self.assertFalse(S.can_move("Aktif", "Completed"))
		self.assertFalse(S.can_move("Active", "Kapandi"))

	def test_the_refusal_names_both_ends(self):
		with self.assertRaises(S.IllegalTransition) as caught:
			S.assert_can_move("Terminated", "Active")
		message = str(caught.exception)
		self.assertIn("Terminated", message)
		self.assertIn("Active", message)


class TestEveryWriteGoesThroughTheMachine(unittest.TestCase):
	"""Tek bir kaçak atama, tablonun sağladığı her güvenceyi yok eder."""

	def test_the_setter_exists(self):
		names = {n.name for n in ast.walk(_v1_tree()) if isinstance(n, ast.FunctionDef)}
		self.assertIn(SETTER, names, f"{SETTER} yok — makinenin tek kapısı olmalı")

	def test_no_endpoint_writes_the_status_directly(self):
		strays = [(mod, fn, line) for mod, fn, line in _status_writes() if fn != SETTER]
		self.assertEqual(
			strays,
			[],
			f"makineyi atlayan doğrudan yazma(lar): {strays}",
		)

	def test_the_setter_actually_consults_the_machine(self):
		# Aksi hâlde yukarıdaki test yalnızca bir ada bakmış olur.
		setter = next(n for n in ast.walk(_v1_tree()) if isinstance(n, ast.FunctionDef) and n.name == SETTER)
		called = {
			node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
			for node in ast.walk(setter)
			if isinstance(node, ast.Call)
		}
		self.assertTrue(
			{"can_move", "assert_can_move"} & called,
			f"{SETTER} makineye hiç sormuyor — yukarıdaki tarama yalnızca bir ada bakmış olur",
		)

	def test_the_sweep_is_not_vacuous(self):
		self.assertGreaterEqual(len(_status_writes()), 1, "hiç durum yazması bulunamadı")

	def test_the_sweep_sees_the_call_form_its_own_gate_uses(self):
		# Tarama önce yalnızca `x.agreement_status = ...` görüyordu, oysa kapının
		# kendisi `frappe.db.set_value(...)` ile yazıyor. Kör noktanın kapandığını
		# adıyla iddia et: aksi hâlde yukarıdaki testler, kaçırdıkları tek biçimi
		# kaçırmaya devam ederken yeşil kalır.
		setter_src = ast.get_source_segment(
			V1.read_text(encoding="utf-8"),
			next(n for n in ast.walk(_v1_tree()) if isinstance(n, ast.FunctionDef) and n.name == SETTER),
		)
		self.assertIn(
			"set_value", setter_src, "kapı artık çağrı biçimini kullanmıyor — bu test amacını yitirdi"
		)
		# O ÇAĞRININ satırı taramada görünmeli. "SETTER bir yerde geçiyor" yetmez:
		# `_set_status` alana ayrıca atamayla da yazıyor, yani çağrı dalı tümden
		# silinse bile atama dalı SETTER'ı bulmaya devam ederdi.
		setter = next(n for n in ast.walk(_v1_tree()) if isinstance(n, ast.FunctionDef) and n.name == SETTER)
		call_lines = {
			node.lineno
			for node in ast.walk(setter)
			if isinstance(node, ast.Call)
			and isinstance(node.func, ast.Attribute)
			and node.func.attr in _WRITE_CALLS
			and _mentions_the_field(node)
		}
		self.assertTrue(call_lines, "kapıda alana yazan çağrı yok — bu test amacını yitirdi")
		seen = {line for _mod, fn, line in _status_writes() if fn == SETTER}
		self.assertTrue(
			call_lines <= seen,
			f"tarama çağrı biçimine kör: {sorted(call_lines - seen)}",
		)


class TestTheTwoMissingWritersNowExist(unittest.TestCase):
	"""Bulgunun doğrudan geri-dönüş testi."""

	def setUp(self):
		self.src = V1.read_text(encoding="utf-8")

	def test_a_fully_paid_agreement_is_completed(self):
		# `_code_only`: aynı tuzak burada da var — modülün üst yorumları
		# "Completed" sözcüğünü zaten geçiriyor.
		collector = next(
			n for n in ast.walk(_v1_tree()) if isinstance(n, ast.FunctionDef) and n.name == "_collect_or_pay"
		)
		segment = _code_only(ast.get_source_segment(self.src, collector) or "")
		self.assertIn(
			'"Completed"',
			segment,
			"tamamen ödenmiş sözleşmeyi Completed yapan yazan tahsilat yolunda yok",
		)

	def test_terminating_is_an_endpoint_of_its_own(self):
		names = {n.name for n in ast.walk(_v1_tree()) if isinstance(n, ast.FunctionDef)}
		self.assertIn("terminate_agreement", names, "sözleşmeyi kapatan uç yok")

	def test_terminating_demands_the_capability_that_had_no_consumer(self):
		fn = next(
			n
			for n in ast.walk(_v1_tree())
			if isinstance(n, ast.FunctionDef) and n.name == "terminate_agreement"
		)
		segment = _code_only(ast.get_source_segment(self.src, fn) or "")
		self.assertIn(
			"settlement_writeoff",
			segment,
			"terminate ucu settlement_writeoff yetkisini istemiyor — yetkinin hâlâ tüketicisi yok",
		)

	def test_rescheduling_refuses_a_closed_agreement(self):
		fn = next(
			n
			for n in ast.walk(_v1_tree())
			if isinstance(n, ast.FunctionDef) and n.name == "approve_reschedule"
		)
		segment = _code_only(ast.get_source_segment(self.src, fn) or "")
		self.assertTrue(
			re.search(r"is_closed\(doc\.agreement_status\)", segment),
			"approve_reschedule kapanmış bir sözleşmeyi hâlâ yeniden planlar",
		)


class TestTheScreenCanSeeTheCapabilityItNowNeeds(unittest.TestCase):
	"""Bir yetkinin tüketicisi varsa ekran onu bilebilmeli.

	`agreement_detail` ekrana yalnızca `_DETAIL_CAPABILITIES` içindeki yetkileri
	bildiriyor. `settlement_writeoff` orada yoktu — ki tüketicisi de olmadığı için
	bu tutarlıydı. Artık `terminate_agreement` onu istiyor: listede olmazsa ekran
	kullanıcının bu yetkiyi taşıyıp taşımadığını hiç öğrenemez ve eylemi hiç
	sunamaz. Uç erişilebilir ama ürün içinde görünmez olur.
	"""

	READ = ROOT / "api/vehicle_finance/read.py"

	def _detail_capabilities(self) -> tuple[str, ...]:
		tree = ast.parse(self.READ.read_text(encoding="utf-8"))
		for node in ast.walk(tree):
			if isinstance(node, ast.Assign) and any(
				isinstance(t, ast.Name) and t.id == "_DETAIL_CAPABILITIES" for t in node.targets
			):
				return tuple(e.value for e in node.value.elts)
		raise AssertionError("_DETAIL_CAPABILITIES bulunamadı")

	def test_the_detail_surface_reports_the_writeoff_capability(self):
		self.assertIn(
			"settlement_writeoff",
			self._detail_capabilities(),
			"terminate ucu bu yetkiyi istiyor ama ekran kullanıcının onu taşıyıp taşımadığını göremiyor",
		)

	def test_every_reported_capability_is_a_real_one(self):
		# AST ile, import ile değil: `permissions.py` frappe'ye bağlı ve bu dosya
		# frappe'siz koşuyor.
		tree = ast.parse((ROOT / "api/vehicle_finance/permissions.py").read_text(encoding="utf-8"))
		declared = set()
		for node in ast.walk(tree):
			if isinstance(node, ast.AnnAssign | ast.Assign):
				targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
				if any(isinstance(t, ast.Name) and t.id == "CAPABILITY_ROLES" for t in targets):
					declared = {k.value for k in node.value.keys}
		self.assertTrue(declared, "CAPABILITY_ROLES okunamadı")
		for cap in self._detail_capabilities():
			self.assertIn(cap, declared, f"{cap} tanımlı bir yetki değil")


if __name__ == "__main__":
	unittest.main()
