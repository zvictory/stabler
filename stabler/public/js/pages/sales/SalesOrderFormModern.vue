<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { readableRate, formatRate, priceListRateForOrder } from "../../composables/fx.js";
import { formatDate, todayIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { itemSearcher } from "../../composables/items.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useConfirm } from "../../composables/useConfirm.js";
import DateInput from "../../components/DateInput.vue";
import Typeahead from "../../components/Typeahead.vue";
import Select from "../../components/Select.vue";
import RelatedDocuments from "../../components/RelatedDocuments.vue";
import FormPage from "../../components/form/FormPage.vue";
import LineItemsEditor from "../../components/LineItemsEditor.vue";
import SalesOrderLines from "./SalesOrderLines.vue";
import { useDocumentForm } from "../../composables/useDocumentForm.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
const route = useRoute();

const today = todayIso();

// Lookups
const warehouses = ref([]);
const warehousesLoading = ref(false);
const priceLists = ref([]);
const currencies = ref([]);
const showDiscounts = ref(false);
/* Ölçü sütunlarının VARSAYILAN görünürlüğü kiracıdan geliyor
 * (Stabler Company Modules → dimensional_lines). Bir tercih, bir yetki değil:
 * hesabı hiç etkilemiyor, yalnız alanları baştan açık getiriyor. Ölçüyle satan
 * kiracıda (anjan, laminor, mikas) satıcı ürünü seçmeden önce de ölçü
 * girebilsin diye. Formdan bu sipariş için geçici olarak değiştirilebiliyor. */
const showDims = ref(Boolean(session.modules?.dimensional_lines));
const lastReservationErrors = ref([]);
const autoSubmit = ref(1);
const exchangeRate = ref(null);
// Set by resolveRate()'s callers when a live rate was needed but unavailable —
// the line keeps its un-converted fallback price instead of a silently wrong one.
const rateWarning = ref(false);
const forceOverStock = ref(false);
const openDelivery = ref(false);
const openReserve = ref(true);

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		""
);

function defaultWarehouseName() {
	const match = warehouses.value.find(
		(w) => (w.warehouse_name || "").trim().toLowerCase() === "tayyor mahsulot"
	);
	return match ? match.name : "";
}

async function loadWarehouses() {
	if (!activeCompany.value) return;
	warehousesLoading.value = true;
	try {
		warehouses.value = await call("stabler.api.inventory.list_stock_warehouses", {
			company: activeCompany.value,
		});
	} catch {
		warehouses.value = [];
	} finally {
		warehousesLoading.value = false;
	}
}

async function loadPriceLists() {
	try {
		priceLists.value = await call("stabler.api.sales.list_price_lists", { selling_only: 1 });
	} catch {
		priceLists.value = [];
	}
}

async function loadCurrencies() {
	try {
		currencies.value = await call("stabler.api.sales.list_currencies");
	} catch {
		currencies.value = [];
	}
}

/* Tasarımdaki "Adım 3/3" göstergesi. Tasarım dosyasında üç çubuk da SABİT
 * dolu çizilmiş; öyle bırakmak boş bir siparişte de "3/3" yazmak olurdu.
 * Burada her bölüm KENDİ zorunlu alanları dolunca doluyor — gösterge
 * bölüm başlıklarındaki 1/2/3 numaralarıyla birebir aynı şeyi sayıyor. */
const sectionsDone = computed(() => {
	const f = form.value || {};
	return [
		Boolean(f.customer && f.set_warehouse),
		Array.isArray(f.items) && f.items.some((l) => l.item_code && Number(l.qty) > 0),
		Boolean(f.delivery_date),
	];
});
const stepsDone = computed(() => sectionsDone.value.filter(Boolean).length);

const itemsSummaryLabel = computed(() => {
	const lines = (form.value?.items || []).filter((l) => l.item_code);
	const byUom = new Map();
	for (const l of lines) {
		const u = l.stock_uom || l.uom || "";
		byUom.set(u, (byUom.get(u) || 0) + (Number(l.qty) || 0) * (Number(l.conversion_factor) || 1));
	}
	const qty = [...byUom].map(([u, q]) => `${Number(q.toFixed(2))} ${u}`).join(" · ");
	const n = `${lines.length} ${lines.length === 1 ? t("item") : t("items")}`;
	return qty ? `${n} · ${qty}` : n;
});

function removeLine(index) {
	form.value.items.splice(index, 1);
	if (!form.value.items.length) form.value.items.push(blankLine(form.value.set_warehouse));
}

/* Sağ raydaki rezerv listesi: satır verisinden TÜRETİLİR, ayrı bir çağrı yok.
 * availability zaten satır başına yükleniyor; burada sadece okunuyor. */
const reserveRows = computed(() =>
	(form.value?.items || [])
		.filter((l) => l.item_code)
		.map((l) => {
			const need = (Number(l.qty) || 0) * (Number(l.conversion_factor) || 1);
			const free = Number(l.availability?.free ?? 0);
			return {
				code: l.item_code,
				name: l.item_name || l.item_code,
				uom: l.stock_uom || l.uom || "",
				need: Number(need.toFixed(2)),
				free,
				known: Boolean(l.availability),
				short: Boolean(l.availability) && need > free,
			};
		})
);

function blankLine(defaultWh = null) {
	return {
		item_code: "",
		item_name: "",
		custom_line_note: "",
		uom: "",
		stock_uom: "",
		uoms: [],
		conversion_factor: 1,
		qty: 1,
		dimension_mode: "",
		custom_length: null,
		custom_width: null,
		custom_height: null,
		custom_pieces: null,
		rate: 0,
		rateTouched: false,
		discount_percentage: 0,
		discount_amount: 0,
		warehouse: defaultWh || defaultWarehouseName() || "",
		availability: null,
		availabilityLoading: false,
		reserved_qty: 0,
		delivered_qty: 0,
		price_list_rate: 0,
		amount: 0,
	};
}

function blankForm() {
	return {
		customer: "",
		customer_name: "",
		currency: "",
		exchange_rate: 1,
		price_list: "",
		set_warehouse: "",
		transaction_date: today,
		remarks: "",
		items: [blankLine()],
		crm_deal: "",
		// Teslim tarihi — backend (create/update_sales_order) doğrudan kabul
		// ediyor; gönderilmezse bugüne düşer. Formda artık girilebiliyor.
		delivery_date: "",
		// Müşteri açık borcu — bilgi amaçlı, payload'a girmiyor (kayıt sırasında
		// hesaplanmaz, seçim/odak anında fetchCustomerDefaults'tan gelir).
		customer_outstanding: 0,
		customer_outstanding_currency: "",
		/* Alan formdan kaldırıldı (sözleşme seçici artık çizilmiyor) ama model
		 * ve payload'da duruyor: doctype'ta custom_agreement gerçek bir alan ve
		 * kayıtlı siparişlerde dolu olabilir. Buradan silseydik mevcut bir
		 * siparişi açıp kaydetmek onun sözleşme bağını sessizce koparırdı. */
		agreement: "",
	};
}

// Map detail to our internal form model
function fromDetail(d) {
	return {
		customer: d.customer,
		customer_name: d.customer_name,
		currency: d.currency || "",
		exchange_rate: Number(d.conversion_rate) || 1,
		price_list: d.selling_price_list || "",
		set_warehouse: d.set_warehouse || "",
		transaction_date: d.transaction_date || "",
		delivery_date: d.delivery_date || "",
		remarks: d.remarks || "",
		agreement: d.custom_agreement || "",
		items: (d.items || []).map((it) => ({
			item_code: it.item_code,
			item_name: it.item_name,
			custom_line_note: it.custom_line_note || "",
			uom: it.uom || "",
			stock_uom: it.stock_uom || "",
			uoms: [],
			conversion_factor: Number(it.conversion_factor) || 1,
			qty: it.qty,
			dimension_mode: it.custom_dimension_mode || "",
			custom_length: it.custom_length ?? null,
			custom_width: it.custom_width ?? null,
			custom_height: it.custom_height ?? null,
			custom_pieces: it.custom_pieces ?? null,
			rate: it.rate,
			rateTouched: false,
			discount_percentage: it.discount_percentage || 0,
			discount_amount: it.discount_amount || 0,
			warehouse: it.warehouse || "",
			availability: null,
			availabilityLoading: false,
			reserved_qty: it.reserved_qty || 0,
			delivered_qty: it.delivered_qty || 0,
			price_list_rate: it.price_list_rate || 0,
			amount: it.amount || 0,
		})),
	};
}

function toPayload(m) {
	const lines = m.items
		.filter((r) => r.item_code)
		.map((r) => ({
			item_code: r.item_code,
			qty: r.qty,
			rate: r.rate,
			custom_line_note: r.custom_line_note || undefined,
			uom: r.uom,
			conversion_factor: r.conversion_factor || 1,
			discount_percentage: r.discount_percentage || 0,
			discount_amount: r.discount_amount || 0,
			warehouse: r.warehouse || m.set_warehouse,
			custom_length: r.custom_length ?? undefined,
			custom_width: r.custom_width ?? undefined,
			custom_height: r.custom_height ?? undefined,
			custom_pieces: r.custom_pieces ?? undefined,
		}));
	return {
		company: activeCompany.value,
		customer: m.customer,
		set_warehouse: m.set_warehouse,
		transaction_date: m.transaction_date,
		// delivery_date gönderilmezse backend txn_date'a düşer; biz artık
		// formdan da alıyoruz ki adım göstergesi veTeslim tarihi tutarlı olsun.
		delivery_date: m.delivery_date || undefined,
		remarks: m.remarks || undefined,
		items: lines,
		auto_submit: autoSubmit.value,
		currency: m.currency || undefined,
		// Kur bilinmiyorsa anahtar hiç gönderilmez (bkz. exchangeRate). Bilinen bir
		// kur ERPNext yönünde (1 işlem parası = N taban parası) gider.
		conversion_rate: !m.currency || !currency.value || m.currency === currency.value
			? 1
			: (exchangeRate.value > 0 ? exchangeRate.value : undefined),
		price_list: m.price_list || undefined,
		crm_deal: m.crm_deal || undefined,
		agreement: m.agreement || undefined,
	};
}

// Document engine hook
const {
	model: form,
	loading,
	saving: actionRunning,
	loadError,
	error: actionError,
	isDirty,
	isCreate,
	editable,
	docstatus,
	status,
	modified,
	load,
	save,
	submit,
	cancel,
	amend,
	remove,
	can,
} = useDocumentForm({
	doctype: "Sales Order",
	detailApi: "stabler.api.sales.sales_order_detail",
	createApi: "stabler.api.sales.create_sales_order",
	updateApi: "stabler.api.sales.update_sales_order",
	submitApi: "stabler.api.sales.submit_sales_order",
	cancelApi: "stabler.api.sales.cancel_sales_order",
	amendApi: "stabler.api.sales.amend_sales_order",
	deleteApi: "stabler.api.sales.delete_sales_order",
	blankModel: blankForm,
	toPayload,
	fromDetail,
	backPath: "/sales/orders",
});

// All computeds that close over 'form' must live here, AFTER useDocumentForm
/* Satırda ölçülü kalem varsa sütun tercihten bağımsız açık kalır — miktarı o
 * ölçüden türüyor, gizlemek kullanıcıya açıklamasız bir sayı bırakmak olurdu.
 * Bu durumda düğme de kapatılıyor: basıldığında hiçbir şey olmayan bir düğme,
 * bozuk bir düğmedir. */
const dimsForced = computed(() =>
	(form.value?.items || []).some((l) => ["Linear", "Area", "Volume"].includes(l.dimension_mode))
);

const currencySymbol = computed(() => {
	const code = form.value?.currency || currency.value;
	return (currencies.value.find((c) => c.name === code) || {}).symbol || "";
});

const isForeignCurrency = computed(() => {
	const txn = form.value?.currency || "";
	const base = currency.value;
	return !!txn && !!base && txn !== base;
});

/* Canlı kurun hangi iki para birimi arasında sorulduğu.
 *
 * İşlem parası tabandan farklıysa çift DOĞRUDAN o ikilidir — belgenin
 * `conversion_rate`'i zaten "1 işlem parası = N taban parası"dır, başka bir
 * referansa çevirmek yönü bozar. (Regresyon: eski hâli UZS'yi koşulsuz USD'ye
 * çeviriyordu, dolayısıyla UZS-belge/USD-defter olan anjan'da çift
 * `{USD, USD}`'ye çöküyor, `equivalentAmount` daima `null` dönüyor ve
 * `resolveRate` her satırı `unconverted: true` işaretliyordu.)
 *
 * Yalnız işlem parası tabanla AYNIYSA belgenin kendi kuru yoktur; o zaman
 * `≈` satırı için CBU'nun yayımladığı Dolar kuru referans alınır. */
const exchangeRatePair = computed(() => {
	const cur = (form.value?.currency || currency.value || "UZS").toUpperCase();
	const base = (currency.value || "UZS").toUpperCase();
	if (cur !== base) return { from: cur, to: base };
	return { from: "USD", to: base };
});

/** CBU veya belge bazlı aktif kur. Belgenin kendi exchange_rate'i yalnızca işlem
 * para birimi şirket temel para biriminden farklıyken güvenilir (aynıyken ERPNext
 * her zaman 1 kaydeder). Kur hiç bilinmiyorsa null döner — sabit bir değere düşülmez. */
const activeRate = computed(() => {
	const docRate = Number(form.value?.exchange_rate);
	if (isForeignCurrency.value && docRate > 0) {
		return docRate;
	}
	return (exchangeRate.value && exchangeRate.value > 0) ? exchangeRate.value : null;
});

/* Kur DAİMA güçlü paranın yönünde okunur — "1 USD = 12 101,84 сўм", asla
 * "0,000082632". Muhasebeci kuru böyle söyler ve ekranda böyle bekler.
 * Saklanan `conversion_rate` ERPNext yönünde (1 işlem parası = N taban parası)
 * kalır; çevrilen yalnız gösterim. Kural ve tek uygulaması: composables/fx.js. */
const rateQuote = computed(() => {
	const { from, to } = exchangeRatePair.value;
	return readableRate(activeRate.value, from, to);
});

function lineAmount(line) {
	const qty = Number(line.qty || 0);
	const rate = Number(line.rate || 0);
	const discPct = Number(line.discount_percentage || 0);
	const discAmt = Number(line.discount_amount || 0);
	let amt = qty * rate;
	if (discPct > 0) amt = qty * Math.max(rate * (1 - discPct / 100), 0);
	else if (discAmt > 0) amt = qty * Math.max(rate - discAmt, 0);
	return amt;
}

const subtotal = computed(() =>
	(form.value?.items || []).reduce((s, l) => s + Number(l.qty || 0) * Number(l.rate || 0), 0)
);
const grandTotal = computed(() =>
	(form.value?.items || []).reduce((s, l) => s + lineAmount(l), 0)
);

/** Toplamın karşı birimindeki dengi (baz para birimi ↔ referans para birimi arasında).
 * Yön exchangeRatePair'den türetilir: işlem parası baz ise (to) kura BÖLÜNÜR,
 * referans ise (from) kur ile ÇARPILIR — hiçbir para birimi kodu burada sabit gömülmez.
 *
 * CLAUDE.md'nin "Currency display" kuralına belgelenmiş istisna (bkz. o bölüm): tek
 * satırlık `≈` gösterimi yalnız bu ekranda, yalnız canlı kur varken çizilir; işlem
 * para birimindeki asıl toplamın yerine geçmez. */
const equivalentAmount = computed(() => {
	const rate = activeRate.value;
	if (!rate || rate <= 0 || !grandTotal.value) return null;

	const orderCurrency = (form.value?.currency || currency.value || "").toUpperCase();
	const { from, to } = exchangeRatePair.value;

	if (orderCurrency === to) {
		const val = grandTotal.value / rate;
		return { amount: val, currency: from, formatted: formatMoney(val, from, user.language) };
	} else if (orderCurrency === from) {
		const val = grandTotal.value * rate;
		return { amount: val, currency: to, formatted: formatMoney(val, to, user.language) };
	}

	return null;
});

const totalDiscount = computed(() => subtotal.value - grandTotal.value);

async function fetchExchangeRate() {
	const { from, to } = exchangeRatePair.value;
	try {
		const res = await call("stabler.api.sales.get_currency_exchange_rate", {
			from_currency: from,
			to_currency: to,
			date: form.value?.transaction_date || undefined,
		});
		const rateNum = Number(res?.exchange_rate);
		exchangeRate.value = rateNum > 0 ? rateNum : null;
	} catch {
		exchangeRate.value = null;
	}
	if (exchangeRate.value) rateWarning.value = false;
}

// Load existing doc
const doc = ref(null);
const docName = computed(() => (route.params.name ? String(route.params.name) : null));

async function loadDoc() {
	if (!docName.value) return;
	await load(docName.value);
	if (!actionError.value && form.value) {
		doc.value = form.value;
		if (isForeignCurrency.value && Number(form.value.exchange_rate) > 0) {
			exchangeRate.value = Number(form.value.exchange_rate);
		} else {
			await fetchExchangeRate();
		}
		// Make sure it preserves discount column visibility if discounts exist
		showDiscounts.value = form.value.items.some(
			(l) => Number(l.discount_percentage) > 0 || Number(l.discount_amount) > 0
		);
		// Load UOM lists for draft items so the UOM toggle works in edit mode.
		if (docstatus.value === 0) await loadDraftUoms();
		/* Uygunluk her YÜKLEME yolunda çekilmeli, yalnız ilk mount'ta değil.
		 * Bunu onMounted'a koymuştum; oysa belge üç ayrı yoldan yükleniyor:
		 * mount, `watch(docName, loadDoc)` (uygulama içinde sipariş A'dan
		 * B'ye geçiş) ve kaydetme sonrası yeniden okuma. Yalnız ilkini
		 * kapatınca diğer ikisinde sağdaki rezerv paneli sonsuza kadar
		 * "kontrol ediliyor" diyordu. Yükleme fonksiyonunun kendisine
		 * taşındı — hangi yoldan gelinirse gelinsin aynı davranış. */
		if (editable.value) {
			for (const line of form.value.items || []) scheduleAvailability(line);
		}
		/* Mevcut siparişte müşteri doc'tan gelir, pickCustomer çağrılmaz;
		 * outstanding (ve güncel fiyat listesi/para birimi) o yolda set
		 * edilmezdi. Müşteri varsa varsayılanları buradan da çek — yeni
		 * sipariş yoluyla aynı veriyi görmek için. */
		if (form.value.customer) await fetchCustomerDefaults(form.value.customer);
	}
}

async function loadDraftUoms() {
	await Promise.all(
		form.value.items
			.filter((l) => l.item_code)
			.map(async (l) => {
				try {
					const meta = await call("stabler.api.sales.item_sales_meta", {
						item_code: l.item_code,
						company: activeCompany.value,
						customer: form.value.customer || undefined,
						price_list: form.value.price_list || undefined,
					});
					l.stock_uom = meta.stock_uom || l.stock_uom;
					l.uoms = meta.uoms || [];
				} catch {
					// non-fatal
				}
			})
	);
}

// Lookups and callbacks
function searchCustomers(q) {
	return call("stabler.api.sales.list_customers", {
		company: activeCompany.value,
		search: q,
		limit: 10,
	});
}

/* Müşteri varsayılanlarını (fiyat listesi, para birimi VE açık borç) çek ve
 * forma yansıt. pickCustomer ile loadDoc AYNI yolu paylaşır: yeni siparişte
 * kullanıcı müşteriyi elle seçer, mevcut siparişi açarken ise müşteri zaten
 * doc'ta vardır ve pickCustomer çağrılmaz — outstanding o yolda görünmezdi.
 * Önce sadece parametre listesi ayrışır (name/transaction_date), sonra her
 * iki yol da burayı çağırır. */
async function fetchCustomerDefaults(customer) {
	try {
		const defaults = await call("stabler.api.sales.get_customer_defaults", {
			company: activeCompany.value,
			customer,
		});
		form.value.currency = defaults.default_currency || "";
		form.value.price_list = defaults.resolved_price_list || "";
		form.value.customer_outstanding = Number(defaults.outstanding_base) || 0;
		form.value.customer_outstanding_currency =
			defaults.outstanding_currency || currency.value;
	} catch {
		// non-fatal — fiyat listesi/borç olmadan da devam
	}
}

async function pickCustomer(c) {
	form.value.customer = c.name;
	form.value.customer_name = c.customer_name;
	await fetchCustomerDefaults(c.name);
}

function clearCustomer() {
	form.value.customer = "";
	form.value.customer_name = "";
	form.value.currency = "";
	form.value.price_list = "";
	form.value.agreement = "";
	form.value.customer_outstanding = 0;
	form.value.customer_outstanding_currency = "";
}

// priceList is a getter for the same reason warehouse is: the user picks the customer
// (and with it the price list) after the searcher is built, so freezing it here would
// price the whole dropdown off whatever list was selected when the form mounted.
const searchItems = itemSearcher("sales", {
	warehouse: () => form.value.set_warehouse,
	priceList: () => form.value.price_list,
});

/* Fiyat listesi → işlem parası çevrimi. Kural ve tek uygulaması artık
 * composables/fx.js: iki SO formunun ikisi de aynı fonksiyonu çağırıyor, çünkü
 * bu çevrimin iki kopyası tam olarak birinin sessizce yanlış kalma yoludur —
 * Klasik'te `res.currency` hiç okunmuyordu. Buradaki tek davranış değişikliği,
 * eksik bir fiyat listesi parasının artık "UZS" varsayılmaması. */
function toOrderRate(priced, fallback) {
	const { from, to } = exchangeRatePair.value;
	return priceListRateForOrder(
		priced,
		form.value.currency || currency.value,
		{ rate: activeRate.value, from, to },
		fallback
	);
}

async function resolveRate(itemCode, fallback = 0, uom = undefined) {
	if (!itemCode || !activeCompany.value) return { rate: Number(fallback || 0) };
	try {
		const res = await call("stabler.api.sales.get_item_price", {
			item_code: itemCode,
			company: activeCompany.value,
			customer: form.value.customer || undefined,
			price_list: form.value.price_list || undefined,
			uom: uom || undefined,
		});
		return toOrderRate(res, Number(fallback || 0));
	} catch {
		return { rate: Number(fallback || 0) };
	}
}

async function refreshLineRatesForPriceList() {
	const lines = form.value.items.filter((line) => line.item_code && !line.rateTouched);
	for (const line of lines) {
		const { rate, unconverted } = await resolveRate(line.item_code, line.rate, line.uom);
		if (unconverted) rateWarning.value = true;
		else if (rate) line.rate = rate;
	}
}

/* Koli/kutu birimi tercihi kiracıya özgü (Stabler Company Modules →
 * sales_box_uom). Kayış (dts) ya da hizmet (horeca) satan kiracıda stok
 * birimi doğru varsayılandır; bayrak kapalıyken sessizce koliye geçmemeli. */
function preferredSalesUom(meta) {
	const uoms = meta.uoms || [];
	if (!session.modules?.sales_box_uom) {
		return uoms.find((u) => u.uom === meta.stock_uom) || null;
	}
	const boxUom = uoms
		.filter((u) => u.uom !== meta.stock_uom && Number(u.conversion_factor) > 1)
		.sort((a, b) => Number(b.conversion_factor) - Number(a.conversion_factor))[0];
	return boxUom || uoms.find((u) => u.uom === (meta.default_uom || meta.stock_uom)) || null;
}

// Line Item Editor pick handler
/* Kalem değişince ölçüler ESKI kaleme aitti — taşınmamalı. 3 m'lik bir profilden
 * sonra seçilen sandviç panele o 3 kalırsa miktar sessizce yanlış çıkar, üstelik
 * sunucu kancası onu kayıtta doğru kabul edip qty'ye yazar. */
function setDimensionMode(line, mode) {
	line.dimension_mode = mode || "";
	if (["Linear", "Area", "Volume"].includes(line.dimension_mode)) {
		line.custom_length = null;
		line.custom_width = null;
		line.custom_height = null;
		line.custom_pieces = null;
		line.qty = 0;
		// Ölçülü kalemde fiyat da miktar da stok biriminde — katsayı devre dışı.
		line.uom = line.stock_uom || line.uom || "";
		line.conversion_factor = 1;
	}
}

async function handlePickItem(payload) {
	let { line, index } = payload;
	const { item } = payload;
	let field = payload.field;

	// Arama çubuğu hangi satıra yazacağını bilmiyor — bilmesi de gerekmiyor,
	// `items` ona prop olarak geçiyor ve listenin sahibi burası. Hazırda boş
	// satır varsa onu doldur: form açılışta bir boş satırla geliyor, yoksa ilk
	// seçimden sonra ekranda kullanılmayan bir boş satır kalırdı.
	if (field === "search") {
		let slot = form.value.items.findIndex((l) => !l.item_code);
		if (slot === -1) {
			form.value.items.push(blankLine(form.value.set_warehouse));
			slot = form.value.items.length - 1;
		}
		line = form.value.items[slot];
		index = slot;
		field = "item";
	}

	if (field === "item") {
		line.item_code = item.item_code || item.name;
		line.item_name = item.item_name;
		if (!line.warehouse) line.warehouse = form.value.set_warehouse;
		try {
			const meta = await call("stabler.api.sales.item_sales_meta", {
				item_code: line.item_code,
				company: activeCompany.value,
				customer: form.value.customer || undefined,
				price_list: form.value.price_list || undefined,
			});
			line.stock_uom = meta.stock_uom || "";
			line.uoms = meta.uoms || [];
			// Ölçü modu satırın kendi kalemine ait: aynı siparişte panel (m²) ile
			// dondurma (koli) yan yana durabiliyor. Paylaşılan düzenleyici bunu
			// kendi içinde yazıyordu; SO formu kendi düzenleyicisine geçince o
			// atama düştü ve ölçü girişi sessizce kayboldu. Artık burada, yani
			// hangi düzenleyici çizerse çizsin aynı yerden geliyor.
			setDimensionMode(line, meta.dimension_mode || item?.custom_dimension_mode || "");
			const preferredUom = preferredSalesUom(meta);
			line.uom = preferredUom ? preferredUom.uom : (meta.default_uom || meta.stock_uom || "");
			line.conversion_factor = preferredUom ? Number(preferredUom.conversion_factor) : 1;
			line.rateTouched = false;
			/* `item_sales_meta` de fiyatı aynı fiyat listesinden, aynı `currency`
			 * etiketiyle veriyor — yani çevrim burada da şart. İki sebeple önce
			 * çevriliyor: aşağıdaki `else` dalı (tercih edilen birim varsayılanla
			 * aynı olduğunda) asıl sık kullanılan yol, ve çevrilmemiş bir liste
			 * fiyatı `resolveRate`'e YEDEK olarak geçirilirse hata o kapıdan geri
			 * gelir. `listed.rate` her iki durumda da güvenli: ya çevrilmiş liste
			 * fiyatı ya da kalemin standart fiyatı. */
			const listed = toOrderRate(meta, Number(meta.standard_rate || 0));
			if (preferredUom && preferredUom.uom !== meta.default_uom && form.value.price_list) {
				const { rate, unconverted } = await resolveRate(line.item_code, listed.rate, line.uom);
				if (unconverted) rateWarning.value = true;
				else line.rate = rate;
			} else {
				const { rate, unconverted } = listed;
				if (unconverted) rateWarning.value = true;
				else line.rate = rate;
			}
		} catch {
			line.uom = item.stock_uom || "";
			line.stock_uom = item.stock_uom || "";
			line.uoms = [];
			line.conversion_factor = 1;
			// Sunucu çağrısı düştüyse arama satırındaki mod son çare.
			setDimensionMode(line, item?.custom_dimension_mode || "");
			const { rate, unconverted } = await resolveRate(line.item_code, item.standard_rate);
			if (unconverted) rateWarning.value = true;
			else line.rate = rate;
		}
		scheduleAvailability(line);
		// Focus qty after all async item data is loaded (nextTick here fires after
		// Vue flushes the reactive updates from the awaits above, not before them).
		// Use data-field="qty" so the lookup is semantic, not positional — after item
		// pick the Typeahead input becomes readonly and drops out of :not([readonly]),
		// which would shift positional index 1 from qty to rate (the corruption cause).
		await nextTick();
		// İki düzenleyici var: düzenlenebilir yolda SalesOrderLines (.so-lines),
		// salt-okunur yolda paylaşılan LineItemsEditor (.stbl-items-table).
		// Yalnız ikincisini aramak, formun asıl kullanıldığı yolda odağı ölü
		// bırakıyordu — kalem seçtikten sonra imleç hiçbir yere gitmiyordu.
		const tbody = document.querySelector(".so-lines tbody, .stbl-items-table tbody");
		if (tbody) {
			const rows = Array.from(tbody.querySelectorAll("tr"));
			const row = rows[index];
			if (row) {
				const qty = row.querySelector('[data-field="qty"]');
				qty?.focus();
				qty?.select?.();
			}
		}
	} else if (field === "uom") {
		if (line.item_code && !line.rateTouched) {
			const { rate, unconverted } = await resolveRate(line.item_code, line.rate, line.uom);
			if (unconverted) rateWarning.value = true;
			else line.rate = rate;
		}
	}
}

// Per-line availability (debounced 200ms)
const _availabilityTimers = new WeakMap();
function scheduleAvailability(line) {
	const prev = _availabilityTimers.get(line);
	if (prev) clearTimeout(prev);
	if (!line.item_code || !line.warehouse) {
		line.availability = null;
		return;
	}
	const handle = setTimeout(() => loadAvailability(line), 200);
	_availabilityTimers.set(line, handle);
}

async function loadAvailability(line) {
	if (!line.item_code || !line.warehouse) return;
	line.availabilityLoading = true;
	try {
		line.availability = await call("stabler.api.inventory.item_availability", {
			item_code: line.item_code,
			warehouse: line.warehouse,
		});
	} catch {
		line.availability = null;
	} finally {
		line.availabilityLoading = false;
	}
}

function lineStockQty(line) {
	return Number(line.qty || 0) * Number(line.conversion_factor || 1);
}

function isOverAvailable(line) {
	if (!line.item_code || !line.availability) return false;
	return lineStockQty(line) > Number(line.availability.free || 0);
}

const overAvailableRows = computed(() =>
	form.value.items
		.map((line, i) => ({ line, i }))
		.filter(({ line }) => line.item_code && isOverAvailable(line))
);

const hasOverAvailable = computed(() => overAvailableRows.value.length > 0);

// Watchers
watch(
	() => form.value.customer,
	async (customer) => {
		if (!isCreate.value || !customer) return;
		await refreshLineRatesForPriceList();
	}
);

watch(
	() => form.value.price_list,
	async () => {
		if (!editable.value) return;
		await refreshLineRatesForPriceList();
	}
);

watch(
	() => form.value?.currency,
	async () => {
		await fetchExchangeRate();
		if (editable.value) await refreshLineRatesForPriceList();
	}
);

watch(
	() => form.value?.transaction_date,
	async (date) => {
		if (date) await fetchExchangeRate();
	}
);

watch(
	() => form.value.set_warehouse,
	(now, was) => {
		if (!isCreate.value) return;
		for (const line of form.value.items) {
			if (!line.warehouse || line.warehouse === was) {
				line.warehouse = now;
				scheduleAvailability(line);
			}
		}
	}
);

async function prefillNewForCustomer(customerName) {
	if (!customerName) return;
	try {
		const customers = await searchCustomers(customerName);
		const match = customers.find(c => c.name === customerName || c.customer_name === customerName) || customers[0];
		if (match) {
			await pickCustomer(match);
		}
	} catch {
		// non-fatal
	}
}

watch(docName, loadDoc);

onMounted(async () => {
	await Promise.all([loadWarehouses(), loadPriceLists(), loadCurrencies()]);
	await fetchExchangeRate();
	if (!docName.value) {
		form.value = blankForm();
		form.value.set_warehouse = defaultWarehouseName();
		const newFor = route.query?.new_for || route.query?.customer;
		if (newFor) await prefillNewForCustomer(String(newFor));
		if (route.query?.crm_deal) form.value.crm_deal = String(route.query.crm_deal);
		if (route.query?.agreement) form.value.agreement = String(route.query.agreement);
	} else {
		await loadDoc();
	}
});

// Operations
async function submitCreate({ autoSubmitMode = 1 } = {}) {
	actionError.value = "";
	if (!form.value.customer) {
		actionError.value = t("Pick a customer.");
		return;
	}
	if (!form.value.set_warehouse) {
		actionError.value = t("Pick a warehouse.");
		return;
	}
	// Check stock availability
	await Promise.all(
		form.value.items
			.filter((l) => l.item_code && l.warehouse && !l.availability)
			.map((l) => loadAvailability(l))
	);
	if (autoSubmitMode && hasOverAvailable.value && !(session.isAdmin && forceOverStock.value)) {
		const { line, i } = overAvailableRows.value[0];
		actionError.value = t(
			"Row {n} ({item}): qty exceeds available stock (available {free}).",
			{ n: i + 1, item: line.item_name || line.item_code, free: Number(line.availability.free).toFixed(2) }
		);
		return;
	}

	autoSubmit.value = autoSubmitMode;
	if (isCreate.value) {
		const res = await save();
		if (res?.reservation_errors) {
			lastReservationErrors.value = res.reservation_errors;
		}
		return;
	}
	// update_sales_order (unlike create_sales_order) never submits — it only
	// persists field edits. So submitting an already-saved draft needs its own
	// save-then-submit here, same as the pre-redesign submitDoc() did.
	if (!autoSubmitMode) {
		await save();
		return;
	}
	if (isDirty.value) {
		const saveRes = await save();
		if (!saveRes) return;
	}
	const res = await submit();
	if (res?.reservation_errors) {
		lastReservationErrors.value = res.reservation_errors;
	}
}

async function createInvoice() {
	if (!docName.value) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		const res = await call("stabler.api.sales.create_sales_invoice", {
			sales_order: docName.value,
		});
		if (res?.name) {
			router.push("/sales/invoices/" + res.name);
		}
	} catch (err) {
		actionError.value = err?.message || t("Failed to create invoice.");
	} finally {
		actionRunning.value = false;
	}
}

// Inline validations for editor state check
const isFormValid = ref(true);

function handleValidityChange(valid) {
	isFormValid.value = valid;
}

// Calculations are handled by LineItemsEditor.vue

// Stage calculation
function pipelineStage(d) {
	if (!d) return 2;
	const delivered = Number(d.per_delivered) || 0;
	const billed = Number(d.per_billed) || 0;
	const invoiced = (d.sales_invoices || []).some((si) => Number(si.docstatus) === 1);
	if (invoiced || billed >= 100) return 4;
	if (delivered > 0 || billed > 0) return 3;
	return 2;
}

const canCreateInvoice = computed(() => {
	if (isCreate.value || docstatus.value !== 1) return false;
	const billed = Number(form.value?.per_billed || 0);
	return billed < 100;
});

const paymentBadge = computed(() => {
	const sis = (form.value?.sales_invoices || []).filter((si) => Number(si.docstatus) === 1);
	if (!sis.length) return null;
	const grand = sis.reduce((s, si) => s + (Number(si.grand_total) || 0), 0);
	const due = sis.reduce((s, si) => s + (Number(si.outstanding_amount) || 0), 0);
	if (due <= 0.005) return { label: t("Paid"), cls: "bg-green-lt", icon: "ti-check" };
	if (due >= grand - 0.005) return { label: t("Unpaid"), cls: "bg-red-lt", icon: "ti-clock" };
	return { label: t("Partly paid"), cls: "bg-yellow-lt", icon: "ti-progress" };
});

const { confirm } = useConfirm();
const closingSo = ref(false);

const canCloseSo = computed(() => {
	if (isCreate.value || docstatus.value !== 1) return false;
	const s = form.value?.status;
	return !!s && s !== "Closed" && s !== "On Hold" && s !== "Cancelled";
});

// Computes a plain-language explanation for why a submitted SO is still open.
const whyStillOpen = computed(() => {
	if (!form.value || docstatus.value !== 1) return null;
	if (form.value.status === "Closed") return null;

	const sis = form.value.sales_invoices || [];
	const hasDraft = sis.some((si) => Number(si.docstatus) === 0);
	const submittedSis = sis.filter((si) => Number(si.docstatus) === 1);
	const hasNoStock = submittedSis.some((si) => !si.update_stock);
	const billingStatus = form.value.billing_status || "";
	const perBilled = Number(form.value.per_billed || 0);

	if (hasDraft) return t("Invoice not submitted yet.");
	if (hasNoStock)
		return t("Invoiced without stock movement — stock still reserved; needs a delivery/backfill or manual close.");
	if (billingStatus !== "Fully Billed")
		return t("Partially billed — {pct}% invoiced.", { pct: perBilled.toFixed(0) });
	// billing_status is Fully Billed but SO is still open — auto-close didn't fire
	return t("Fully billed but auto-close did not run — use Close below.");
});

async function closeSalesOrder() {
	const ok = await confirm({
		title: t("Close Sales Order"),
		body: t("This will close the order and release any reserved stock. Continue?"),
		confirmLabel: t("Close & release"),
		danger: true,
	});
	if (!ok) return;
	closingSo.value = true;
	actionError.value = "";
	try {
		await call("stabler.api.sales.close_sales_order", {
			name: docName.value,
			modified: modified.value,
		});
		await loadDoc();
	} catch (err) {
		actionError.value = err?.message || t("Failed to close sales order.");
	} finally {
		closingSo.value = false;
	}
}
</script>

<template>
	<!-- Tasarım katmanını açan sarmalayıcı. FormPage çok köklü olduğu için
	     öznitelik geçişi güvenilir değil; sınıf burada veriliyor. Paylaşılan
	     bileşenlerin hiçbirine dokunulmuyor — katmandaki köprü bölümü
	     Tabler sınıflarını YALNIZCA .stbl-ds altında yeniden giydiriyor. -->
	<div class="stbl-ds">
	<FormPage
		:title="isCreate ? t('New Sales Order') : t('Sales Order')"
		:doc-name="docName"
		:status="status"
		doctype="Sales Order"
		:docstatus="docstatus"
		:loading="loading"
		:error="loadError"
		:action-error="actionError"
		back-path="/sales/orders"
		frameless
	>
		<!-- Page Header (matching Image 2) -->
		<header class="so-page-head">
			<div>
				<div class="so-page-meta">
					<router-link to="/sales/orders" class="so-back-link">
						<i class="ti ti-arrow-left me-1"></i>{{ t("Sales orders") }}
					</router-link>
					<span class="so-meta-sep">·</span>
					<span class="badge" :class="docstatus === 1 ? 'bg-green-lt' : 'bg-warning-lt'">
						{{ docstatus === 1 ? t("Submitted") : t("Draft") }}
					</span>
					<span class="so-saved-at ms-1">
						{{ isDirty ? t("unsaved changes") : (modified ? formatDate(modified) : t("not saved")) }}
					</span>
				</div>
				<h1 class="so-page-title">
					{{ isCreate ? t("New sales order") : (docName || t("Sales Order")) }}
				</h1>
			</div>
			<div class="so-steps-head">
				<span class="ds-label">{{ t("Step") }} {{ stepsDone }}/3</span>
				<span class="so-steps-bars">
					<i v-for="(done, n) in sectionsDone" :key="n" :data-on="done ? '1' : null"></i>
				</span>
			</div>
		</header>

		<!-- Pipeline stepper + reservation badge (view mode) -->
		<div v-if="!isCreate && form" class="mb-4">
			<div class="d-flex align-items-center gap-2 mb-3">
				<span class="text-secondary">{{ form.customer_name }}</span>
				<span v-if="form.has_reservations" class="badge bg-green-lt">
					<i class="ti ti-lock me-1"></i>{{ t("Reserved") }}
				</span>
				<span v-if="paymentBadge" class="badge" :class="paymentBadge.cls">
					<i class="ti me-1" :class="paymentBadge.icon"></i>{{ paymentBadge.label }}
				</span>
			</div>
			<ul class="steps steps-counter mb-0">
				<li class="step-item" :class="{ active: pipelineStage(form) === 1 }">{{ t("Quotation") }}</li>
				<li class="step-item" :class="{ active: pipelineStage(form) === 2 }">{{ t("Sales Order") }}</li>
				<li class="step-item" :class="{ active: pipelineStage(form) === 3 }">{{ t("Deliver") }}</li>
				<li class="step-item" :class="{ active: pipelineStage(form) === 4 }">{{ t("Invoice") }}</li>
			</ul>
		</div>

		<div v-if="lastReservationErrors.length" class="alert alert-warning">
			<div class="fw-semibold mb-1">
				<i class="ti ti-alert-triangle me-1"></i>{{ t("Some lines could not be reserved") }}
			</div>
			<ul class="mb-0 ps-3 small">
				<li v-for="(e, i) in lastReservationErrors" :key="i">
					<span v-if="e.item" class="font-monospace">{{ e.item }}</span>
					<span v-if="e.line"> · {{ t("line") }} {{ e.line }}</span>
					<span v-if="e.error"> — {{ e.error }}</span>
				</li>
			</ul>
		</div>

		<div v-if="form?.sales_invoices && form.sales_invoices.length" class="alert alert-info">
			<div class="fw-semibold mb-1"><i class="ti ti-link me-1"></i>{{ t("Linked invoices") }}</div>
			<div class="small">
				<router-link
					v-for="si in form.sales_invoices"
					:key="si.name"
					:to="'/sales/invoices/' + si.name"
					class="badge bg-blue-lt me-1 font-monospace text-decoration-none"
				>{{ si.name }}</router-link>
			</div>
		</div>

		<!-- Linked tender deal (F7) -->
		<div v-if="isCreate && form && form.crm_deal" class="alert bg-purple-lt text-purple d-flex align-items-center gap-2 mb-3 py-2">
			<i class="ti ti-flag"></i>
			<span>{{ t("From tender deal") }}: <strong>{{ form.crm_deal }}</strong></span>
		</div>

		<div class="so-single-column">
		<!-- 1 · Taraflar ve koşullar -->
		<section class="ds-form-section">
			<div class="ds-form-section-head">
				<span class="ds-label">1 · {{ t("Parties and terms") }}</span>
			</div>
		<div class="ds-form-body row g-3">
			<div class="col-md-6">
				<label class="form-label" :class="{ required: editable }">{{ t("Customer") }}</label>
				<Typeahead
					v-if="editable"
					v-model="form.customer"
					:search="searchCustomers"
					:display="form.customer_name || form.customer"
					:placeholder="t('Search customer name…')"
					:no-results-text="t('No customers match that name')"
					open-on-focus
					@pick="pickCustomer"
					@clear="clearCustomer"
				>
					<template #option="{ item }">
						<div class="d-flex align-items-center gap-2">
							<span class="avatar avatar-xs bg-purple-lt">{{ (item.customer_name || item.name).charAt(0).toUpperCase() }}</span>
							<div>
								<div class="fw-semibold">{{ item.customer_name || item.name }}</div>
								<div v-if="item.customer_name && item.customer_name !== item.name" class="small text-secondary">{{ item.name }} · {{ item.customer_group || "—" }}</div>
								<div v-else class="small text-secondary">{{ item.customer_group || "—" }}</div>
							</div>
						</div>
					</template>
				</Typeahead>
				<div v-else class="form-control-plaintext fw-semibold py-1">
					{{ form.customer_name }}
					<span class="text-secondary fw-normal font-monospace small">· {{ form.customer }}</span>
				</div>
				<div
					v-if="form.customer && form.customer_outstanding != null"
					class="so-debt"
					:data-debt="Number(form.customer_outstanding) > 0 ? '1' : null"
				>
					<i aria-hidden="true"></i>
					<span v-if="Number(form.customer_outstanding) > 0" class="ds-mono">
						{{ formatMoney(form.customer_outstanding, currency, user.language) }}
						{{ t("open debt") }}
					</span>
					<span v-else class="ds-mono">{{ t("No open debt") }}</span>
				</div>
			</div>
			<div class="col-md-6">
				<label class="form-label" :class="{ required: editable }">{{ t("Warehouse") }}</label>
				<Select
					v-if="editable"
					v-model="form.set_warehouse"
					:options="warehouses"
					value-key="name"
					:disabled="warehousesLoading"
					:placeholder="warehousesLoading ? t('Loading warehouses…') : t('Pick a warehouse')"
				>
					<template #option="{ option }">{{ option.warehouse_name }} ({{ option.name }})</template>
					<template #selected="{ option }">{{ option.warehouse_name }} ({{ option.name }})</template>
				</Select>
				<div v-else class="form-control-plaintext font-monospace py-1">{{ form.set_warehouse || "—" }}</div>
				<div class="so-field-subtext small text-secondary mt-1">
					{{ t("Stock and reservations are read from this warehouse") }}
				</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Order date") }}</label>
			<DateInput v-if="editable" v-model="form.transaction_date" />
			<div v-else class="form-control-plaintext py-1">{{ formatDate(form.transaction_date) || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Price list") }}</label>
				<Select
					v-if="editable"
					v-model="form.price_list"
					:options="priceLists"
					value-key="name"
					:placeholder="t('— auto from customer —')"
				>
					<template #option="{ option }">{{ option.name }} ({{ option.currency }})</template>
					<template #selected="{ option }">{{ option.name }} ({{ option.currency }})</template>
				</Select>
				<div v-else class="form-control-plaintext py-1">{{ form.price_list || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Currency") }}</label>
				<Select
					v-if="editable"
					v-model="form.currency"
					:options="currencies"
					value-key="name"
					:placeholder="currency || '—'"
				>
					<template #option="{ option }">{{ option.name }}<span v-if="option.symbol" class="text-secondary ms-1">({{ option.symbol }})</span></template>
					<template #selected="{ option }">{{ option.name }}<span v-if="option.symbol" class="text-secondary ms-1">({{ option.symbol }})</span></template>
				</Select>
				<div v-else class="form-control-plaintext font-monospace fw-semibold py-1">
					{{ form.currency || currency }}
					<span v-if="currencySymbol" class="text-secondary fw-normal">({{ currencySymbol }})</span>
				</div>
			</div>
		</div>


		</section>

		<!-- Read-only post-submit datagrid (view mode) -->
		<div v-if="!isCreate && form" class="datagrid mb-3">
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Net total") }}</div>
				<div class="datagrid-content font-monospace">{{ formatMoney(form.net_total, form.currency, user.language) }}</div>
			</div>
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Grand total") }}</div>
				<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(form.grand_total, form.currency, user.language) }}</div>
			</div>
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Advance paid") }}</div>
				<div class="datagrid-content font-monospace">{{ formatMoney(form.advance_paid, form.currency, user.language) }}</div>
			</div>
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Delivered") }}</div>
				<div class="datagrid-content font-monospace">{{ Number(form.per_delivered || 0).toFixed(0) }}%</div>
			</div>
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Billed") }}</div>
				<div class="datagrid-content font-monospace">{{ Number(form.per_billed || 0).toFixed(0) }}%</div>
			</div>
		</div>

		<!-- 2 · Kalemler -->
		<section class="ds-form-section">
			<div class="ds-form-section-head">
				<span class="ds-label">2 · {{ t("Items") }}</span>
				<span class="so-head-right">
					<span class="ds-label">{{ itemsSummaryLabel }}</span>
					<button
						type="button"
						class="ds-btn so-disc-btn"
						:aria-pressed="String(showDims || dimsForced)"
						:disabled="dimsForced"
						:title="dimsForced ? t('A line on this order is priced by size, so the measurement columns cannot be hidden.') : ''"
						@click="showDims = !showDims"
					>
						{{ t("Measurement columns") }}
					</button>
					<button type="button" class="ds-btn so-disc-btn" :aria-pressed="String(showDiscounts)" @click="showDiscounts = !showDiscounts">
						{{ t("Discount column") }}
					</button>
				</span>
			</div>

			<SalesOrderLines
				v-if="editable"
				:items="form.items"
				:editable="editable"
				:currency="form.currency || currency"
				:language="user.language"
				:search-items="searchItems"
				:show-discounts="showDiscounts"
				:show-dims="showDims"
				@pick-item="handlePickItem"
				@remove="removeLine"
			/>

		<LineItemsEditor
			v-if="form && !editable"
			:items="form.items"
			:editable="editable"
			:currency="form.currency || currency"
			:language="user.language"
			:currency-symbol="currencySymbol"
			:search-items="searchItems"
			:blank-line="() => blankLine(form.set_warehouse)"
			@pick-item="handlePickItem"
			@validity-change="handleValidityChange"
		>
			<template #header-extra>
				<th v-if="!editable" class="text-end" style="width: 120px;">{{ t("Reserved") }}</th>
				<th v-if="!editable" class="text-end" style="width: 120px;">{{ t("Delivered") }}</th>
				<th v-if="!editable" class="text-end" style="width: 120px;">{{ t("List rate") }}</th>
				<th v-if="showDiscounts" style="width: 80px;">%</th>
				<th v-if="showDiscounts" style="width: 130px;">{{ t("Disc") }}</th>
			</template>

			<template #item-extra="{ line }">
				<div v-if="line.item_code && line.warehouse" class="mt-1">
					<span v-if="line.availabilityLoading" class="text-secondary small">
						<span class="spinner-border spinner-border-sm me-1"></span>
					</span>
					<span
						v-else-if="line.availability"
						class="small"
						:class="isOverAvailable(line) ? 'text-danger fw-semibold' : 'text-secondary'"
					>{{ Number(line.availability.free).toFixed(0) }} {{ t("avail") }} · {{ Number(line.availability.actual).toFixed(0) }} {{ t("stock") }} / {{ Number(line.availability.reserved).toFixed(0) }} {{ t("reserved") }}</span>
				</div>
			</template>

			<template #uom-extra="{ line }">
				<div
					v-if="line.conversion_factor > 1 && line.uom && line.stock_uom && line.uom !== line.stock_uom"
					class="mt-1 text-secondary"
					style="font-size:0.72rem"
				>1 {{ line.uom }} = {{ line.conversion_factor }} {{ line.stock_uom }}</div>
			</template>

			<template #row-extra="{ line }">
				<td v-if="!editable" class="align-top text-end font-monospace py-2">
					<span v-if="Number(line.reserved_qty || 0) > 0" class="badge bg-green-lt">{{ Number(line.reserved_qty).toFixed(2) }}</span>
					<span v-else class="text-secondary">—</span>
				</td>
				<td v-if="!editable" class="align-top text-end font-monospace py-2">{{ line.delivered_qty || 0 }}</td>
				<td v-if="!editable" class="align-top text-end font-monospace text-secondary small py-2">
					{{ line.price_list_rate > 0 ? formatMoney(line.price_list_rate, form.currency, user.language) : "—" }}
				</td>
				<td v-if="showDiscounts" class="align-top">
					<div class="text-end font-monospace small py-2">{{ line.discount_percentage > 0 ? line.discount_percentage + "%" : "—" }}</div>
				</td>
				<td v-if="showDiscounts" class="align-top">
					<div class="text-end font-monospace small py-2">
						{{ line.discount_amount > 0 ? formatMoney(line.discount_amount, form.currency, user.language) : "—" }}
					</div>
				</td>
			</template>

			<template #footer-extra="{ totalsByUom: tUoms }">
				<tr>
					<td colspan="20" class="pt-2 pb-0">
						<span class="badge bg-secondary-lt">{{ form.items.length }} {{ form.items.length === 1 ? t('item') : t('items') }}</span>
						<span v-for="[uom, qty] in tUoms" :key="uom" class="badge bg-blue-lt ms-1 font-monospace">{{ qty }} {{ uom }}</span>
					</td>
				</tr>
			</template>
		</LineItemsEditor>

		</section>

		<!-- 3 · Teslim ve not (Collapsible) -->
		<section class="ds-form-section">
			<button
				type="button"
				class="so-fold-head"
				:aria-expanded="String(openDelivery)"
				@click="openDelivery = !openDelivery"
			>
				<span class="ds-label">3 · {{ t("Delivery and notes") }}</span>
				<span class="so-fold-opt">{{ sectionsDone[2] ? t("complete") : t("optional") }}</span>
				<span class="flex-grow-1"></span>
				<span v-if="!openDelivery" class="so-fold-meta">
					{{ form.delivery_date ? formatDate(form.delivery_date) : t("no date set") }}
					{{ form.remarks ? " · " + form.remarks : "" }}
				</span>
				<span class="so-fold-chev">{{ openDelivery ? "▾" : "▸" }}</span>
			</button>
			<div v-if="openDelivery" class="ds-form-body so-deliv p-3 border-top">
				<div class="so-deliv-date">
					<label class="form-label">{{ t("Delivery date") }}</label>
					<DateInput v-if="editable" v-model="form.delivery_date" />
					<div v-else class="form-control-plaintext py-1">{{ formatDate(form.delivery_date) || "—" }}</div>
				</div>
				<div class="so-deliv-notes">
					<label class="form-label">{{ t("Terms / remarks") }}</label>
					<textarea v-if="editable" v-model="form.remarks" class="form-control" rows="2"></textarea>
					<div v-else class="form-control-plaintext py-1">{{ form.remarks || "—" }}</div>
				</div>
			</div>
		</section>

		<!-- 4 · Stok rezervi (Collapsible) -->
		<section v-if="reserveRows.length" class="ds-form-section" :data-warning="hasOverAvailable ? '1' : null">
			<button
				type="button"
				class="so-fold-head"
				:aria-expanded="String(openReserve)"
				@click="openReserve = !openReserve"
			>
				<span class="ds-label">4 · {{ t("Stock reservation") }}</span>
				<span class="so-res-state-badge" :data-warning="hasOverAvailable ? '1' : null">
					<i class="so-pick-dot" aria-hidden="true"></i>
					{{ hasOverAvailable ? overAvailableRows.length + " " + t("lines blocked") : t("all reservable") }}
				</span>
				<span class="flex-grow-1"></span>
				<span v-if="!openReserve" class="so-fold-meta">
					{{ reserveRows.length }} {{ reserveRows.length === 1 ? t("item to reserve") : t("items to reserve") }}
				</span>
				<span class="so-fold-chev">{{ openReserve ? "▾" : "▸" }}</span>
			</button>
			<div v-if="openReserve" class="so-reserve-body border-top">
				<div class="so-reserve-grid">
					<div v-for="r in reserveRows" :key="r.code" class="so-res-card" :data-short="r.short ? '1' : null">
						<div class="so-res-card-head">
							<span class="so-res-card-title"><strong class="ds-mono">{{ r.code }}</strong> — {{ r.name }}</span>
							<span class="ds-mono so-res-card-state" :data-short="r.short ? '1' : null">
								{{ !r.known ? t("checking…") : r.short ? t("short stock") : t("will be reserved") }}
							</span>
						</div>
						<div class="ds-mono so-res-card-detail">
							{{ r.need }} {{ r.uom }} {{ t("needed") }} · {{ Number(r.free).toLocaleString() }} {{ r.uom }} {{ t("available") }}
						</div>
					</div>
				</div>
				<div class="so-res-guidance p-3 small text-secondary">
					<template v-if="hasOverAvailable">
						<i class="ti ti-alert-triangle me-1 text-danger"></i>
						{{ t("Some lines exceed available stock. Adjust quantities or warehouse before submitting.") }}
					</template>
					<template v-else>
						<i class="ti ti-info-circle me-1 text-success"></i>
						{{ t("On approval these quantities are reserved in the warehouse and cannot be given to another order.") }}
					</template>
				</div>
			</div>
		</section>
		</div>


		<RelatedDocuments v-if="!isCreate && form" doctype="Sales Order" :name="docName" />

		<!-- Fulfilment & Billing panel (submitted view only) -->
		<div v-if="!isCreate && form && docstatus === 1" class="card mt-3">
			<div class="card-header">
				<h5 class="card-title mb-0">{{ t("Fulfilment & Billing") }}</h5>
			</div>
			<div class="card-body">
				<!-- Totals -->
				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Grand total") }}</div>
						<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(form.grand_total, form.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Advance paid") }}</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(form.advance_paid, form.currency, user.language) }}</div>
					</div>
				</div>

				<!-- Progress bars -->
				<div class="mb-3">
					<div class="d-flex justify-content-between mb-1">
						<span class="text-secondary small">{{ t("Billed") }}</span>
						<span class="font-monospace small fw-semibold">{{ Number(form.per_billed || 0).toFixed(0) }}%</span>
					</div>
					<div class="progress mb-2" style="height: 6px;">
						<div class="progress-bar bg-green" :style="{ width: Math.min(Number(form.per_billed || 0), 100) + '%' }"></div>
					</div>
					<div class="d-flex justify-content-between mb-1">
						<span class="text-secondary small">{{ t("Delivered") }}</span>
						<span class="font-monospace small fw-semibold">{{ Number(form.per_delivered || 0).toFixed(0) }}%</span>
					</div>
					<div class="progress" style="height: 6px;">
						<div class="progress-bar bg-blue" :style="{ width: Math.min(Number(form.per_delivered || 0), 100) + '%' }"></div>
					</div>
				</div>

				<!-- Per-line fulfilment table -->
				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Line details") }}</h6>
				<table class="table table-sm table-vcenter mb-3">
					<thead>
						<tr>
							<th>{{ t("Item") }}</th>
							<th class="text-end">{{ t("Ordered") }}</th>
							<th class="text-end">{{ t("Delivered") }}</th>
							<th class="text-end">{{ t("Billed amt") }}</th>
							<th class="text-end">{{ t("Reserved") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="it in form.items" :key="it.name">
							<td class="font-monospace small">{{ it.item_code }}</td>
							<td class="text-end font-monospace small">{{ it.qty }}</td>
							<td class="text-end font-monospace small">{{ it.delivered_qty }}</td>
							<td class="text-end font-monospace small">{{ formatMoney(it.billed_amt, form.currency, user.language) }}</td>
							<td class="text-end font-monospace small">
								<span v-if="Number(it.reserved_qty) > 0" class="badge bg-green-lt">{{ it.reserved_qty }}</span>
								<span v-else class="text-secondary">—</span>
							</td>
						</tr>
					</tbody>
				</table>

				<!-- Linked invoices detail table -->
				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Linked invoices") }}</h6>
				<table class="table table-sm table-vcenter mb-3">
					<thead>
						<tr>
							<th>{{ t("Invoice") }}</th>
							<th>{{ t("Date") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Total") }}</th>
							<th>{{ t("Stock") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="si in form.sales_invoices" :key="si.name">
							<td>
								<router-link
									:to="'/sales/invoices/' + si.name"
									class="font-monospace text-decoration-none"
								>{{ si.name }}</router-link>
							</td>
							<td class="font-monospace small">{{ formatDate(si.posting_date) }}</td>
							<td>
								<span class="badge" :class="getStatusBadgeClass('Sales Invoice', si.status)">{{ si.status }}</span>
							</td>
							<td class="text-end font-monospace small">{{ formatMoney(si.grand_total, form.currency, user.language) }}</td>
							<td>
								<span v-if="si.update_stock" class="badge bg-green-lt">{{ t("moves stock") }}</span>
								<span v-else class="badge bg-orange-lt">{{ t("no stock movement") }}</span>
							</td>
						</tr>
					</tbody>
				</table>

				<!-- Why is this still open? -->
				<div v-if="whyStillOpen" class="alert alert-warning mb-0">
					<i class="ti ti-info-circle me-1"></i>{{ whyStillOpen }}
				</div>
			</div>
		</div>

		<!-- Sticky Bottom Action & Summary Bar -->
		<div class="so-sticky-foot">
			<div class="so-sticky-foot-inner">
				<div class="so-sticky-meta">
					<span class="so-sticky-title">
						{{ t("Grand total") }} · {{ form.items.length }} {{ form.items.length === 1 ? t("item") : t("items") }}
					</span>
					<span class="so-sticky-submeta">
						{{ t("Subtotal") }}: {{ formatMoney(subtotal, form.currency || currency, user.language) }}
						<template v-if="totalDiscount > 0">
							· {{ t("Discount") }}: −{{ formatMoney(totalDiscount, form.currency || currency, user.language) }}
						</template>
						<template v-if="rateQuote && rateQuote.value > 0">
							· 1 {{ rateQuote.strong }} = {{ formatRate(rateQuote.value, user.language) }} {{ rateQuote.weak }}
						</template>
					</span>
					<span v-if="rateWarning" class="so-sticky-submeta text-danger fw-semibold">
						<i class="ti ti-alert-triangle me-1"></i>{{ t("Exchange rate unavailable — line prices were not converted. Enter the rate manually.") }}
					</span>
					<div class="so-sticky-amounts">
						<span class="ds-mono so-sticky-total">
							{{ formatMoney(grandTotal, form.currency || currency, user.language) }}
						</span>
						<span v-if="equivalentAmount" class="ds-mono so-sticky-base">
							≈ {{ equivalentAmount.formatted }}
						</span>
					</div>
				</div>

				<div class="so-sticky-actions">
					<div v-if="editable && session.isAdmin && hasOverAvailable" class="form-check me-2 align-self-center">
						<input id="adminForceStock" v-model="forceOverStock" class="form-check-input" type="checkbox" />
						<label class="form-check-label small text-danger fw-semibold" for="adminForceStock" style="cursor:pointer">
							{{ t("Force allow over-stock submit (Admin)") }}
						</label>
					</div>
					<button
						v-if="editable"
						type="button"
						class="btn btn-outline-secondary btn-lg"
						:disabled="actionRunning"
						@click="submitCreate({ autoSubmitMode: 0 })"
					>
						{{ t("Save as draft") }}
					</button>
					<button
						v-if="editable"
						type="button"
						class="btn btn-primary btn-lg"
						:disabled="actionRunning || (hasOverAvailable && !(session.isAdmin && forceOverStock))"
						@click="submitCreate({ autoSubmitMode: 1 })"
					>
						<span v-if="actionRunning" class="spinner-border spinner-border-sm me-2"></span>
						<span>
							{{ hasOverAvailable && !(session.isAdmin && forceOverStock) ? t("Stock insufficient — cannot submit") : t("Submit & reserve stock") }}
						</span>
						<i class="ti ti-arrow-right ms-2"></i>
					</button>
					<button
						v-if="canCreateInvoice"
						type="button"
						class="btn btn-success"
						:disabled="actionRunning"
						@click="createInvoice"
					>
						<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-file-invoice me-1"></i>{{ t("Create Invoice") }}
					</button>
					<button
						v-if="can.cancel"
						type="button"
						class="btn btn-outline-danger"
						:disabled="actionRunning"
						@click="cancel"
					>
						<i class="ti ti-ban me-1"></i>{{ t("Cancel") }}
					</button>
					<button
						v-if="can.amend"
						type="button"
						class="btn btn-outline-secondary"
						:disabled="actionRunning"
						@click="amend"
					>
						<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-copy me-1"></i>{{ t("Amend") }}
					</button>
					<button
						v-if="canCloseSo"
						type="button"
						class="btn btn-outline-secondary"
						:disabled="actionRunning || closingSo"
						@click="closeSalesOrder"
					>
						<span v-if="closingSo" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-lock me-1"></i>{{ t("Close & release reserved stock") }}
					</button>
					<button
						v-if="can.delete"
						type="button"
						class="btn btn-outline-danger"
						:disabled="actionRunning"
						@click="remove"
					>
						<i class="ti ti-trash me-1"></i>{{ t("Delete") }}
					</button>
				</div>
			</div>
		</div>
	</FormPage>
	</div>
</template>

<style scoped>
/* ── Tasarım yerleşimi (yalnız bu ekran) ──────────────────────────────── */
.so-steps-bars {
	display: flex;
	gap: 4px;
}

/* Dolmamış adım soluk kalır: gösterge "kaç bölüm bitti" diyor, süs değil. */
.so-steps-bars i {
	width: 26px;
	height: 5px;
	display: block;
	background: var(--ds-ln2);
}

.so-steps-bars i[data-on="1"] {
	background: var(--ds-ink);
}

/* Özet tasarımda sağda; dar ekranda kalemlerin altına iner. */

/* ── Tek sütun düzeni & katlanabilir bölümler ─────────────────────────── */
.so-single-column {
	display: flex;
	flex-direction: column;
	gap: 16px;
	width: 100%;
}

.so-fold-head {
	display: flex;
	align-items: center;
	gap: 12px;
	width: 100%;
	padding: 12px 18px;
	background: transparent;
	border: 0;
	border-radius: 0;
	cursor: pointer;
	font-family: inherit;
	text-align: left;
}

.so-fold-opt {
	font-family: var(--ds-mono, monospace);
	font-size: 10.5px;
	letter-spacing: .06em;
	color: var(--ds-tx3, #9099a6);
}

.so-fold-meta {
	font-family: var(--ds-mono, monospace);
	font-size: 11px;
	color: var(--ds-tx2, #667382);
}

.so-fold-chev {
	font-family: var(--ds-mono, monospace);
	font-size: 13px;
	color: var(--ds-acc, #206bc4);
}

.so-res-state-badge {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	font-family: var(--ds-mono, monospace);
	font-size: 11px;
	color: var(--ds-ok, #2fb344);
}

.so-res-state-badge[data-warning="1"] {
	color: var(--ds-crit-tx, #b32424);
}

.so-reserve-grid {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
	gap: 10px;
	padding: 14px 18px;
	background: var(--ds-surface, #ffffff);
}

.so-res-card {
	background: var(--ds-surface, #ffffff);
	padding: 10px 12px;
	display: flex;
	flex-direction: column;
	gap: 4px;
	border: 1px solid var(--ds-ln, #e3e5e8);
	border-top: 3px solid var(--ds-ok, #2fb344);
}

.so-res-card[data-short="1"] {
	border-top-color: var(--ds-crit, #d63939);
}

.so-res-card-head {
	display: flex;
	align-items: baseline;
	justify-content: space-between;
	gap: 8px;
}

.so-res-card-title {
	font-size: 13px;
	font-weight: 600;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.so-res-card-state {
	font-size: 11px;
	color: var(--ds-ok, #2fb344);
	white-space: nowrap;
}

.so-res-card-state[data-short="1"] {
	color: var(--ds-crit-tx, #b32424);
}

.so-res-card-detail {
	font-size: 10.5px;
	color: var(--ds-tx3, #9099a6);
}

/* ── Yapışkan alt özet ve aksiyon çubuğu ─────────────────────────────── */
.so-sticky-foot {
	position: sticky;
	bottom: 0;
	z-index: 30;
	background: var(--ds-surface, #ffffff);
	border-top: 2px solid rgba(29, 39, 59, .32);
	box-shadow: 0 -8px 24px rgba(24, 36, 51, .10);
	padding: 14px 24px;
	margin: 20px -20px 0;
}

.so-sticky-foot-inner {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 20px;
	flex-wrap: wrap;
}

.so-sticky-meta {
	display: flex;
	flex-direction: column;
	gap: 2px;
	min-width: 0;
}

.so-sticky-title {
	font-family: var(--ds-mono, monospace);
	font-size: 10px;
	letter-spacing: .14em;
	text-transform: uppercase;
	color: var(--ds-tx3, #9099a6);
}

.so-sticky-submeta {
	font-family: var(--ds-mono, monospace);
	font-size: 11px;
	color: var(--ds-tx2, #667382);
}

.so-sticky-amounts {
	display: flex;
	align-items: baseline;
	gap: 12px;
}

.so-sticky-total {
	font-size: 24px;
	font-weight: 700;
	color: var(--ds-tx, #1d273b);
	letter-spacing: -0.02em;
}

.so-sticky-base {
	font-size: 12.5px;
	color: var(--ds-tx2, #667382);
}

.so-sticky-actions {
	display: flex;
	align-items: center;
	gap: 12px;
}

.so-head-right {
	display: inline-flex;
	align-items: center;
	gap: 12px;
}

.so-disc-btn {
	min-height: 34px;
	padding: 6px 12px;
	font-size: 13px;
}

/* ── Müşteri açık borç satırı ─────────────────────────────────────────── */
.so-debt {
	display: flex;
	align-items: center;
	gap: 7px;
	margin-top: 7px;
	font-size: 10.5px;
	color: var(--ds-tx3);
}

.so-debt > i {
	width: 8px;
	height: 8px;
	flex: none;
	background: var(--ds-ok);
}

.so-debt[data-debt="1"] {
	color: var(--ds-crit-tx);
}

.so-debt[data-debt="1"] > i {
	background: var(--ds-crit);
}

/* ── Teslim tarihi + not (iki sütun) ──────────────────────────────────── */
.so-deliv {
	display: grid;
	grid-template-columns: minmax(160px, 240px) minmax(0, 1fr);
	gap: var(--ds-gap, 14px);
	align-items: start;
}

@media (max-width: 575px) {
	.so-deliv {
		grid-template-columns: 1fr;
	}
}

.so-deliv-notes textarea {
	min-height: 44px;
}
</style>
