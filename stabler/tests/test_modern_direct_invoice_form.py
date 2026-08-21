"""MSA'nın fatura ekranı: Modern deneyim, ama sipariş kavramı olmadan.

MSA sipariş kullanmıyor — ölçüldüğünde 0 Satış Siparişi, 4937 Satış Faturası
vardı. Bu yüzden `enable_modern_sales_order` bayrağını açmak onlara hiçbir şey
yapmaz: o bayrak yalnız Satış Siparişi rotasındaki formu seçer. İstenen,
Modern formun DENEYİMİNİN fatura yazarken de olması.

Bu dosya yeni formun üç sınırını kilitliyor.

**1. Belge Satış Faturası'dır, Satış Siparişi değil.** Form `useDocumentForm`'a
`Sales Invoice` doctype'ını ve fatura uçlarını vermeli. Sipariş uçlarından
birine bağlanırsa ekran sessizce yanlış belgeyi yazar.

**2. Taslak kaydetmek ile göndermek AYRI eylemlerdir.** Sipariş formunda tek
tuşla kaydet-ve-gönder doğrudur: yanlış bir sipariş bedavadır, silinir.
Fatura öyle değil — gönderilen fatura muhasebe kaydı (GL), stok kaydı (SLE)
ve e-fatura doğurur. Tek tuş, geri alınamaz bir işlemi kazayla tetiklemenin
en kısa yoludur.

**3. Koli sütunları kalır.** Paranın birimi kilo, deponun birimi koli. Ortak
`LineItemsEditor` bileşeninin sütunları Item/Qty/UOM/Rate/Amount — koli yok.
Onu satır ızgarası olarak kullanmak koli bilgisini düşürürdü; onu koli
taşıyacak şekilde DEĞİŞTİRMEK ise aynı bileşeni kullanan altı kiracının
sipariş ekranına dokunmak olurdu. Bu yüzden ızgara faturaya özel kalıyor ve
yalnız güvenli ortak parçalar (Typeahead, FormPage, MoneyInput, DateInput,
Select) yeniden kullanılıyor.

Ayrıca kapı: sayfa, backend'in ZORLADIĞI bayrakla kapılanmalı. Eski sayfa
`imports` modülüne bakıyordu, backend ise `direct_invoicing`'e — bir kiracıda
`imports` açık `direct_invoicing` kapalı olsaydı ekran açılır, kayıt backend'de
patlardı.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "public/js/pages/sales/SalesInvoiceFormModern.vue"
ROUTER = (ROOT / "public/js/router.js").read_text(encoding="utf-8")
SHARED_EDITOR = (ROOT / "public/js/components/LineItemsEditor.vue").read_text(encoding="utf-8")


class TestTheFormExists(unittest.TestCase):
	def test_the_component_file_is_present(self):
		self.assertTrue(FORM.exists(), f"{FORM.name} yok")


class TestItWritesAnInvoiceNotAnOrder(unittest.TestCase):
	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""

	def test_the_document_engine_is_pointed_at_sales_invoice(self):
		self.assertIn('doctype: "Sales Invoice"', self.src, "doctype Satış Faturası değil")

	#: Hangi ucun hangi `useDocumentForm` slotuna ait olduğu. Adın dosyada geçmesi
	#: değil, SLOTUN doğru olması iddia ediliyor; bütün mesele bu. Bu testin önceki
	#: hâli aynı beş adı `assertIn(api, self.src)` ile geziyordu — hangi anahtarın
	#: hangi ucu tuttuğundan bağımsız olarak doğru bir cümle. `detailApi` ile
	#: `updateApi` yer değiştirmişti (yazan uç okuma slotunda, okuyan uç yazma
	#: slotunda) ve bu daldaki 27 testin hepsi yeşil kaldı.
	BINDINGS = (
		("detailApi", "sales_invoice_detail"),
		("createApi", "create_direct_sales_invoice"),
		("updateApi", "update_sales_invoice"),
		("submitApi", "submit_sales_invoice"),
		("cancelApi", "cancel_sales_invoice"),
		("amendApi", "amend_sales_invoice"),
		("deleteApi", "delete_sales_invoice"),
	)

	def _bound(self, key: str) -> str | None:
		"""`key`e bağlı uç; anahtar yoksa None."""
		found = re.search(rf'\b{key}:\s*"([^"]+)"', self.src)
		return found.group(1) if found else None

	def test_every_endpoint_is_bound_to_the_slot_that_calls_it(self):
		for key, endpoint in self.BINDINGS:
			with self.subTest(slot=key):
				self.assertEqual(
					self._bound(key),
					f"stabler.api.sales.{endpoint}",
					f"{key} {endpoint} ucunu göstermiyor; form bu slot için yanlış ucu "
					f"çağırıyor ve bu daldaki başka hiçbir test bunu göremez",
				)

	def test_the_load_slot_never_names_a_writer(self):
		"""`detailApi` sayfa açılışında çağrılır; yalnızca bakmak güvenli olmalı.

		`useDocumentForm.js:60` onu `call(detailApi, { name })` diye çağırıyor —
		tek argüman, mount anında, kullanıcı hiçbir şey yapmadan önce. Oraya yazan
		bir uç koymak, belgeyi açmanın belgeyi değiştirmesi demektir.

		Bu yanlışken hasar yok değildi, örtülüydü: `update_sales_invoice` önce
		`check_concurrency` çalıştırıyor ve eksik `modified` yüzünden "Stale
		request" fırlatıyordu, yani ekran sadece açılmıyordu. O ret bir güvenlik
		özelliği değil — sırf önce çalışmış bir bayatlık kontrolü. Açılmayan bir
		sayfayı düzeltmenin bariz yolu `modified`ı geçirmektir, ki bu o kontrolü
		kaldırır ve her sayfa görüntülemesini bir kayda çevirir.

		Bu yüzden kural o uç hakkında değil, slot hakkında: adı yazdığını söyleyen
		hiçbir uç, görülür görülmez çağrılan slotta duramaz.
		"""
		loader = self._bound("detailApi")
		self.assertIsNotNone(loader, "detailApi hiç bağlanmamış")
		for verb in ("create_", "update_", "submit_", "cancel_", "amend_", "delete_"):
			self.assertNotIn(
				verb,
				loader.rsplit(".", 1)[-1],
				f"detailApi {loader} ucunu gösteriyor, o da yazıyor — formu açmak onu çağırırdı",
			)

	def test_no_endpoint_is_bound_to_two_slots(self):
		# Yer değiştirme iki ucu birbirinin slotuna koymuştu; aynı ucun iki slotta
		# olması ise aynı hatanın öbür biçimi ve zararsız görünüyor.
		bound = [self._bound(key) for key, _ in self.BINDINGS]
		present = [b for b in bound if b]
		self.assertEqual(
			len(present),
			len(set(present)),
			f"bir uç birden fazla slota bağlı: {present}",
		)

	def test_no_sales_order_endpoint_leaks_in(self):
		for leaked in (
			"create_sales_order",
			"update_sales_order",
			"submit_sales_order",
			"sales_order_detail",
			"close_sales_order",
		):
			self.assertNotIn(leaked, self.src, f"sipariş ucu sızmış: {leaked}")

	def test_order_only_concepts_are_absent(self):
		for concept in ("delivery_date", "reserved_qty", "reservation"):
			self.assertNotIn(concept, self.src, f"siparişe özgü kavram taşınmış: {concept}")


class TestSavingAndSubmittingAreSeparate(unittest.TestCase):
	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""

	def test_there_is_a_draft_save_action_and_a_separate_submit_action(self):
		self.assertIn("saveDraft", self.src, "taslak kaydetme eylemi yok")
		self.assertIn("submitInvoice", self.src, "ayrı gönderme eylemi yok")

	def test_submitting_asks_first(self):
		"""Geri alınamayan bir işlem onay istemeden çalışmamalı."""
		self.assertIn("confirm", self.src, "gönderme onay istemiyor")


class TestTheBoxColumnsSurvive(unittest.TestCase):
	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""

	def test_the_grid_still_carries_boxes_and_box_weight(self):
		for field in ("boxes", "box_kg"):
			self.assertIn(field, self.src, f"{field} sütunu düşmüş")

	def test_the_shared_editor_was_not_taught_about_boxes(self):
		"""Ortak bileşeni koli taşıyacak şekilde değiştirmek altı kiracının
		sipariş ekranına dokunmak olurdu — bu testin koruduğu sınır budur."""
		for field in ("boxes", "box_kg", "custom_boxes"):
			self.assertNotIn(
				field,
				SHARED_EDITOR,
				"LineItemsEditor değiştirilmiş — paylaşılan bileşen artık izole değil",
			)


class TestTheGateMatchesTheBackend(unittest.TestCase):
	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""

	def test_it_gates_on_the_flag_the_backend_enforces(self):
		self.assertIn(
			"direct_invoicing",
			self.src,
			"ekran backend'in zorladığı bayrağa bakmıyor — form açılır, kayıt patlar",
		)


class TestTheRouteUsesIt(unittest.TestCase):
	def test_the_new_invoice_route_renders_the_new_form(self):
		self.assertIn("SalesInvoiceFormModern", ROUTER, "rota yeni forma bağlanmamış")


if __name__ == "__main__":
	unittest.main()


class TestSubmittingAnExistingDraftSavesFirst(unittest.TestCase):
	""" "Kaydet ve Gönder" bir taslakta önce KAYDETMELİ.

	`update_sales_invoice` submit etmez — yalnızca alan düzenlemelerini kalıcı
	kılar. Dolayısıyla kaydedilmiş bir taslağı göndermek kendi save-then-submit
	adımını gerektirir. Eksikse buton, sunucunun DÜZENLEME ÖNCESİ kopyasını
	submit eder: `modified` değişmediği için eşzamanlılık kontrolü de geçer,
	kullanıcının yazdığı sessizce yok olur ve ekranda yeşil bir başarı bildirimi
	belirir. Gönderilen fatura GL, SLE ve e-fatura doğurduğu için bu geri
	alınamaz. Kardeş form `SalesOrderFormModern.vue` aynı sebeple `isDirty` →
	`save()` → `submit()` yapıyor ve gerekçesini yorumda taşıyor.

	Bu, dalın bitirmek için açıldığı sessiz kaybın ta kendisi — dalın kendi
	eklediği yazım yolunda.
	"""

	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""

	def test_the_existing_draft_branch_saves_before_it_submits(self):
		branch = self.src.index("if (!isCreate.value)")
		submit_at = self.src.index("doc.submit()", branch)
		save_at = self.src.find("doc.save()", branch, submit_at)
		self.assertNotEqual(
			save_at,
			-1,
			"mevcut taslak dalı kaydetmeden submit ediyor — sunucunun düzenleme öncesi kopyası gönderilir",
		)

	def test_it_only_saves_when_there_is_something_to_save(self):
		branch = self.src.index("if (!isCreate.value)")
		submit_at = self.src.index("doc.submit()", branch)
		self.assertIn(
			"isDirty",
			self.src[branch:submit_at],
			"temiz bir taslakta da gereksiz yazma yapılıyor",
		)


class TestReopeningADraftNeverRewritesItsRates(unittest.TestCase):
	"""Kayıtlı bir satırın fiyatı, kullanıcı istemeden yeniden çekilmemeli.

	`fromDetail` `d.price_list` okuyor. Uç bunu döndürmezse model alanı `""`
	olur; `loadPriceLists()` ise `doc.load()`tan ÖNCE koşup ilk listeyi seçtiği
	için değer "Standard Selling" → "" diye değişir. Fiyat listesine bağlı bir
	model izleyicisi o anda tetiklenir ve `fetchRate` her satırın pazarlıkla
	belirlenmiş `rate`'ini güncel liste fiyatıyla ezer. Taslağı yalnızca AÇMAK
	faturayı değiştirir; Kaydet ise değişikliği kalıcı kılar.

	İki koşul birden gerekiyor: uç belgenin fiyat listesini döndürmeli, ve
	oranların yenilenmesi kullanıcı eylemine bağlı olmalı — model değişimine
	değil, çünkü modeli yükleme de değiştirir.
	"""

	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""
		self.api = (ROOT / "api/sales.py").read_text(encoding="utf-8")

	def test_the_detail_endpoint_returns_the_documents_price_list(self):
		start = self.api.index("def sales_invoice_detail")
		end = self.api.index("\ndef ", start + 1)
		self.assertIn(
			'"price_list"',
			self.api[start:end],
			"uç belge düzeyinde price_list döndürmüyor — fromDetail boş okur ve izleyici tetiklenir",
		)

	def test_the_rate_refresh_is_not_wired_to_a_model_watcher(self):
		self.assertNotIn(
			"watch(() => model.value.price_list",
			self.src,
			"oranlar model izleyicisine bağlı — yükleme de modeli değiştirdiği için taslak açmak rate'leri ezer",
		)

	def test_the_price_list_control_refreshes_rates_on_user_change(self):
		# İzleyici kalkınca yenileme kaybolmamalı: kullanıcı listeyi gerçekten
		# değiştirdiğinde oranlar hâlâ tazelenmeli.
		select_at = self.src.index('v-model="model.price_list"')
		block = self.src[select_at : select_at + 400]
		self.assertIn(
			"refreshAllRates",
			block,
			"fiyat listesi kontrolü kullanıcı değişikliğinde oranları tazelemiyor",
		)


class TestTheDocumentsOwnCurrencyIsKept(unittest.TestCase):
	"""Fatura kendi para biriminde gösterilir ve kaydedilir, oturumunkinde değil.

	`sales_invoice_detail` `currency` döndürüyor. `fromDetail` onu okumazsa ekran
	tutarları yanlış birimde gösterir ve her güncelleme belgeyi şirket varsayılan
	birimine yeniden damgalar: satırlar eski birimin büyüklüğünde kalırken
	`grand_total`, `base_grand_total` ve alacak GL'i FX çarpanı kadar bozulur —
	hatasız.
	"""

	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""

	def test_the_loaded_document_currency_reaches_the_model(self):
		start = self.src.index("function fromDetail(")
		end = self.src.index("\n}", start)
		self.assertIn(
			"currency",
			self.src[start:end],
			"fromDetail belgenin para birimini okumuyor",
		)

	def test_display_and_payload_prefer_the_documents_currency(self):
		self.assertIn(
			"model.value?.currency",
			self.src,
			"para birimi oturumdan sabitlenmiş — belgenin kendi birimi yok sayılıyor",
		)


class TestNoTenantIsToldAnotherTenantsName(unittest.TestCase):
	"""Kapı mesajı bir kiracının adını anmaz.

	`make guards` bunu yakalayamaz: oradaki kiracı-adı denetimi koddaki kiracı-adı
	karşılaştırmalarını arar, kullanıcıya gösterilen düzyazıyı değil. Metin silinen
	sayfadan aynen taşındı, ama artık altı kiracının ulaşabildiği yeni bir dosyada.
	"""

	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""
		self.list_form = (ROOT / "public/js/pages/sales/SalesInvoiceForm.vue").read_text(encoding="utf-8")

	def test_the_restricted_banner_names_no_tenant(self):
		self.assertNotIn(
			"only enabled for MSA",
			self.src,
			"kapı mesajı başka bir kiracının adını söylüyor",
		)

	def test_the_edit_button_is_gated_on_the_same_flag_as_the_form(self):
		edit_at = self.list_form.index("/edit`)")
		block = self.list_form[max(0, edit_at - 400) : edit_at]
		self.assertIn(
			"canDirectInvoice",
			block,
			"Düzenle butonu modül bayrağına bakmıyor — özelliği olmayan kiracıyı kapı ekranına yollar",
		)
		# Ve o hesaplanan değer gerçekten backend'in zorladığı bayrağı okumalı,
		# yoksa yukarıdaki iddia yalnızca bir ada bakmış olur.
		gate_at = self.list_form.index("const canDirectInvoice")
		self.assertIn(
			"direct_invoicing",
			self.list_form[gate_at : gate_at + 300],
			"canDirectInvoice backend'in bayrağını okumuyor",
		)


class TestThePriceListsCurrencyIsNotIgnored(unittest.TestCase):
	"""A price list is quoted in its own currency; this invoice is written in another.

	(English, per CLAUDE.md's "implementation code is English-first". The rest of
	this file predates that reading and is left as it is — rewriting it would be
	a change nothing on this branch asked for.)

	`fetchRate` took `price_list_rate` off `stabler.api.sales.get_item_price` and
	wrote it straight into the line's rate field, never reading the `currency`
	that came back beside it and describes it. A price list quoted in USD, used
	on a so'm-denominated invoice, put `4.42` into a field meaning сўм: a ~12 000×
	error, in the customer's favour, on every line that takes a price-list rate.
	It did not even look wrong, because a rate of `4` is a plausible-looking
	number and nothing on the screen says which currency the list was quoted in.

	This is the same defect that was closed in both Sales Order forms, and it is
	worse here: `router.js` sends both `invoices/new` and `invoices/:name/edit` to
	this component with no feature flag, and the older `SalesInvoiceForm.vue`
	calls neither `create_direct_sales_invoice` nor `update_sales_invoice` — it
	views invoices derived from orders. This form is the only way any of the eight
	tenants creates a direct sales invoice, so there is no unaffected fallback.

	The arithmetic itself is asserted in `public/js/tests/fx.spec.js`, where
	`make test-js` runs it against the pure function. What is guarded HERE is that
	the component actually calls it — the one thing a unit test cannot reach,
	since `@vue/test-utils` is not a dependency and the component cannot be
	mounted. A second copy of the conversion is precisely how the two Sales Order
	forms drifted apart, one of them silently wrong.
	"""

	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""

	def _fetch_rate_body(self) -> str:
		"""The body of `fetchRate` — the function that decides what a line costs."""
		start = self.src.index("async function fetchRate(")
		return self.src[start : self.src.index("\n}", start)]

	def test_the_test_reads_the_pricing_path(self):
		"""Anchor: if the function is renamed, every assertion below reads empty text."""
		self.assertIn("async function fetchRate(", self.src)
		self.assertIn("get_item_price", self._fetch_rate_body())

	def test_the_raw_price_list_figure_never_reaches_the_rate_field(self):
		"""THE defect, in one line: `row.rate = Number(res.price_list_rate)`.

		A number is only meaningful together with the currency it is quoted in.
		Assigning the price list's figure to a field denominated in the invoice's
		currency asserts the two are the same currency — which nothing checked.
		"""
		for assigned in re.findall(r"row\.rate\s*=\s*([^;\n]+)", self._fetch_rate_body()):
			self.assertNotIn(
				"price_list_rate",
				assigned,
				f"`row.rate = {assigned.strip()}` writes the price list's own figure into a "
				"field denominated in the invoice's currency, without converting it",
			)

	def test_the_currency_that_came_back_with_the_price_is_read(self):
		"""The lookup returns `currency`, and it describes `price_list_rate` and
		nothing else. Not reading it is what made the wrong number look right."""
		self.assertRegex(
			self._fetch_rate_body(),
			r"\bpriced[?.]*\.currency\b|\bres[?.]*\.currency\b",
			"the price lookup's own currency is never read — the form cannot know "
			"what the number it is about to write actually means",
		)

	def test_the_conversion_comes_from_the_one_shared_helper(self):
		"""Two copies of a currency conversion is how one of them ends up wrong and
		nobody notices. `composables/fx.js` is the only place this rule may live."""
		self.assertRegex(
			self.src,
			r'import \{[^}]*priceListRateForOrder[^}]*\} from "\.\./\.\./composables/fx\.js"',
			"the shared conversion helper is not imported — a third copy of the rule",
		)
		self.assertIn(
			"priceListRateForOrder(",
			self._fetch_rate_body(),
			"the line's rate is decided without the shared helper",
		)

	def test_a_refusal_is_surfaced_rather_than_guessed_at_or_hidden(self):
		"""`unconverted: true` means no honest conversion exists.

		The helper refuses in two cases — no rate for the pair, and no price-list
		currency — and deliberately returns no number rather than a guessed one.
		Both remaining behaviours are wrong: writing a converted-at-a-guess figure,
		and silently keeping the old rate with nothing on screen to say so. The
		Sales Order forms keep the line's rate and raise a banner; so does this.
		"""
		self.assertIn(
			"unconverted",
			self._fetch_rate_body(),
			"the helper's refusal is discarded — the line silently keeps a rate "
			"nobody was told was not converted",
		)
		self.assertIn(
			'v-if="rateWarning"',
			self.src,
			"nothing on screen reports that a line's price was not converted",
		)
		self.assertIn(
			"Exchange rate unavailable — line prices were not converted. Enter the rate manually.",
			self.src,
			"the refusal does not reuse the wording the Sales Order forms already "
			"ship translated in all five languages",
		)

	def test_no_price_found_is_not_reported_as_a_currency_problem(self):
		"""`unresolved` must reach the helper, which falls back quietly for it.

		A tenant that keeps no price list would otherwise see the rate banner on
		every single line, and a warning nobody can act on is a warning nobody
		reads. The old code never passed `unresolved` on at all — both Sales Order
		forms do.
		"""
		body = self._fetch_rate_body()
		call_at = body.index("priceListRateForOrder(")
		self.assertNotIn(
			"unresolved",
			body[:call_at],
			"the form decides the no-price case itself instead of letting the "
			"shared helper do it — that decision now lives in two places",
		)
