<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { readableRate, toLineRate, formatRate, priceListRateForOrder } from "../../composables/fx.js";
import { formatDate, formatDateTime, todayIso} from "../../composables/date.js";
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
import MoneyInput from "../../components/MoneyInput.vue";
import { useDocumentForm } from "../../composables/useDocumentForm.js";
import { useBackdateGuard } from "../../composables/backdate.js";

const { canBackdate, minPostingDate } = useBackdateGuard();

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
const lastReservationErrors = ref([]);
const autoSubmit = ref(1);
/* Kur BİLİNMİYOR ile 1 aynı şey değil. `1` başlangıcı, CBU çağrısı düşerse
 * USD defterine 945 000 UZS'lik bir siparişi 945 000 USD olarak yazdırıyordu —
 * sessiz para hatası. Bilinmeyen kur `null` kalır ve payload'a hiç girmez. */
const exchangeRate = ref(null);
/* Bir fiyat listesi siparişin parasından başka bir parada kote edilmişse ve
 * çevirecek kur yoksa, satır fiyatı DOLDURULMAZ — sessizce çevrilmemiş bir sayı
 * yazmak düzeltilen hatanın ta kendisi. Kullanıcının bunu bilmesi gerekir. */
const rateWarning = ref(false);
const forceOverStock = ref(false);
const agreements = ref([]);
const agreementsEnabled = computed(() => session.canAccessModule("agreements"));

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

async function loadAgreements() {
	if (!agreementsEnabled.value || !activeCompany.value) return;
	try {
		agreements.value = await call("stabler.api.sales.list_agreements", {
			company: activeCompany.value,
			customer: form.value?.customer || undefined,
			limit: 100,
		});
	} catch {
		agreements.value = [];
	}
}

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
		remarks: m.remarks || undefined,
		items: lines,
		auto_submit: autoSubmit.value,
		currency: m.currency || undefined,
		// Kur bilinmiyorsa anahtar hiç gönderilmez (bkz. exchangeRate). Bilinen
		// tek meşru `1`, işlem parasının taban parayla aynı olduğu durumdur.
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
const currencySymbol = computed(() => {
	const code = form.value?.currency || currency.value;
	return (currencies.value.find((c) => c.name === code) || {}).symbol || "";
});

const isForeignCurrency = computed(() => {
	const txn = form.value?.currency || "";
	const base = currency.value;
	return !!txn && !!base && txn !== base;
});

/* Kur DAİMA güçlü paranın yönünde okunur ve yazılır: "1 USD = 12 101,84 сўм",
 * asla "0,000082632". ERPNext'in sakladığı `conversion_rate` ise yönünü
 * korur (1 işlem parası = N taban parası) — çevrilen yalnız gösterim ve giriş.
 *
 * Kuralın tek uygulaması `composables/fx.js`. Buradaki eski el yapımı sürüm
 * yönü `form.currency === "UZS"` literaliyle saptıyordu; RUB-belge/USD-defter
 * (kur ≈ 0,0065) gibi çiftlerde ters yön veriyordu ve CLAUDE.md'nin "tenant
 * variance lives in config/data, never in code constants" kuralını çiğniyordu. */
const rateQuote = computed(() =>
	readableRate(exchangeRate.value, form.value?.currency, currency.value)
);

// MoneyInput'un paydasındaki birim ("1 güçlü para = ? bu")
const rateDisplayCurrency = computed(() => rateQuote.value?.weak || currency.value);
const rateStrongCurrency = computed(() => rateQuote.value?.strong || form.value?.currency);

/* MoneyInput'un iki yönlü bağı. Kullanıcı etiketteki yönde, yani ≥ 1 olan
 * güçlü-yön sayısını girer (12 060) ve `toLineRate` bunu ERPNext'in saklama
 * yönüne geri çevirir (1/12060). Etiket de setter de aynı `rateQuote.strong`'u
 * okuduğu için giriş yönü hiçbir zaman belirsiz kalmaz. */
const displayExchangeRate = computed({
	get: () => rateQuote.value?.value || 0,
	set: (v) => {
		const n = Number(v) || 0;
		if (n <= 0) {
			exchangeRate.value = null;
			return;
		}
		exchangeRate.value = toLineRate(n, rateStrongCurrency.value, form.value?.currency);
	},
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
const totalDiscount = computed(() => subtotal.value - grandTotal.value);
// Kur yoksa taban karşılığı da yok — 0 yazmak yerine hiç çizilmiyor.
const grandTotalBase = computed(() =>
	exchangeRate.value > 0 ? grandTotal.value * exchangeRate.value : null
);

async function fetchExchangeRate() {
	const from = form.value?.currency;
	const to = currency.value;
	if (!from || !to) { exchangeRate.value = null; return; }
	// Aynı para birimi: kur gerçekten 1, varsayılana düşme değil.
	if (from === to) { exchangeRate.value = 1; return; }
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

/* Belge yüklenirken kur izleyicileri susturulur. `load()` `form.currency`'yi
 * doldurduğu anda aşağıdaki izleyici tetikleniyor ve BUGÜNKÜ canlı CBU kurunu
 * çekip belgenin kendi kurunu eziyordu: 2026-05890 no'lu sipariş 11 973,9 ile
 * defterlenmişken ekranda 12 006,39 görünüyordu. Onaylanmış bir siparişte
 * gösterilen kur, o siparişin defterlendiği kur olmak zorunda. */
const loadingDoc = ref(false);

async function loadDoc() {
	if (!docName.value) return;
	loadingDoc.value = true;
	try {
		await loadDocInner();
	} finally {
		await nextTick();
		loadingDoc.value = false;
	}
}

async function loadDocInner() {
	await load(docName.value);
	if (!actionError.value && form.value) {
		doc.value = form.value;
		// Belgenin kendi kuru yalnız işlem parası tabandan farklıyken anlamlı;
		// aynıyken ERPNext her zaman 1 yazar. Yoksa canlı kur denenir.
		{
			const docRate = Number(form.value.exchange_rate);
			if (docRate > 0) exchangeRate.value = docRate;
			else await fetchExchangeRate();
		}
		// Make sure it preserves discount column visibility if discounts exist
		showDiscounts.value = form.value.items.some(
			(l) => Number(l.discount_percentage) > 0 || Number(l.discount_amount) > 0
		);
		// Load UOM lists for draft items so the UOM toggle works in edit mode.
		if (docstatus.value === 0) await loadDraftUoms();
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

function searchAgreements(q) {
	return call("stabler.api.sales.list_agreements", {
		company: activeCompany.value,
		customer: form.value?.customer || undefined,
		search: q,
		limit: 20,
	});
}

function pickAgreement(agreement) {
	form.value.agreement = agreement.name;
}

async function pickCustomer(c) {
	form.value.customer = c.name;
	form.value.customer_name = c.customer_name;
	try {
		const defaults = await call("stabler.api.sales.get_customer_defaults", {
			company: activeCompany.value,
			customer: c.name,
		});
		form.value.currency = defaults.default_currency || "";
		form.value.price_list = defaults.resolved_price_list || "";
		await loadAgreements();
	} catch {
		// non-fatal
	}
}

function clearCustomer() {
	form.value.customer = "";
	form.value.customer_name = "";
	form.value.currency = "";
	form.value.price_list = "";
	form.value.agreement = "";
	agreements.value = [];
}

const searchItems = itemSearcher("sales", { warehouse: () => form.value.set_warehouse });

/* Fiyat listesinin parası siparişin parası olmak zorunda değil. Bu form
 * `price_list_rate`'i alıp satırın kur alanına yazıyordu ama yanında gelen
 * `currency`'yi hiç okumuyordu: UZS'de kote edilmiş bir liste, USD'ye
 * yazılmış bir siparişte so'm rakamını dolar alanına koyuyordu — geçerli kurda
 * ~12 000 katı hata, müşterinin lehine, fiyat listesinden fiyat alan her
 * yabancı para siparişinde. Kural ve tek uygulaması: composables/fx.js.
 *
 * Kur çifti buradan geliyor çünkü Klasik'in kur modeli Modern'inkinden farklı:
 * burada `exchangeRate` daima "1 işlem parası = N taban parası"dır ve işlem
 * parası tabanla aynıyken 1'dir. O durumda çift {taban, taban} olur, yani
 * başka bir paradaki liste çevrilemez ve `unconverted` döner — doğrusu da bu,
 * form o an gerçekten hiçbir yabancı kur tutmuyor. */
function toOrderRate(priced, fallback) {
	const txn = form.value?.currency || currency.value;
	return priceListRateForOrder(priced, txn, { rate: exchangeRate.value, from: txn, to: currency.value }, fallback);
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
 * birimi doğru varsayılandır; bayrak kapalıyken sessizce koliye geçmemeli.
 * Eski birim-adı literali bu kapıyı yedi kiracıda birden açık tutuyordu. */
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
async function handlePickItem({ line, item, index, field }) {
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
		const tbody = document.querySelector(".stbl-items-table tbody");
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
	async (cur) => {
		if (loadingDoc.value) return;
		if (!cur || cur === currency.value) { exchangeRate.value = 1; return; }
		await fetchExchangeRate();
	}
);

watch(
	() => form.value?.transaction_date,
	async (date) => {
		if (loadingDoc.value) return;
		if (isForeignCurrency.value && date) await fetchExchangeRate();
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
	await Promise.all([loadWarehouses(), loadPriceLists(), loadCurrencies(), loadAgreements()]);
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
	const res = await save();
	if (res?.reservation_errors) {
		lastReservationErrors.value = res.reservation_errors;
	}
}

async function submitDoc() {
	lastReservationErrors.value = [];
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
	>
		<div v-if="actionError" class="alert alert-danger">{{ actionError }}</div>

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

		<!-- Header fields -->
		<div class="row g-3 mb-3">
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
			</div>
			<div v-if="agreementsEnabled" class="col-md-6">
				<label class="form-label">{{ t("Agreement") }}</label>
				<Typeahead
					v-if="editable"
					v-model="form.agreement"
					:search="searchAgreements"
					:display="form.agreement || ''"
					:placeholder="t('Search agreement…')"
					:no-results-text="t('No agreements match that search')"
					open-on-focus
					@pick="pickAgreement"
					@clear="form.agreement = ''"
				>
					<template #option="{ item }">
						<div>
							<div class="fw-semibold">{{ item.agreement_no || item.name }}</div>
							<div class="small text-secondary">{{ item.name }} · {{ item.status || "—" }}</div>
						</div>
					</template>
				</Typeahead>
				<div v-else class="form-control-plaintext font-monospace py-1">{{ form.agreement || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Order date") }}</label>
				<DateInput v-if="editable" v-model="form.transaction_date" :min="minPostingDate" />
				<div v-else class="form-control-plaintext py-1">{{ formatDateTime(form.transaction_date) || "—" }}</div>
				<div v-if="editable && !canBackdate" class="form-hint">
					{{ t("Only an administrator can post to an earlier date.") }}
				</div>
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

		<!-- Exchange rate row — only when transaction currency ≠ company base currency -->
		<div v-if="isForeignCurrency" class="row g-2 mb-3">
			<div class="col-md-3">
				<label class="form-label">
					{{ t("Exchange rate") }}
					<span class="text-secondary fw-normal small">(1 {{ rateStrongCurrency }} = ? {{ rateDisplayCurrency }})</span>
				</label>
				<MoneyInput
					v-if="editable"
					v-model="displayExchangeRate"
					:currency="rateDisplayCurrency"
				/>
				<div v-else class="form-control-plaintext font-monospace py-1">
					1 {{ rateStrongCurrency }} = {{ formatRate(displayExchangeRate, user.language) }} {{ rateDisplayCurrency }}
				</div>
			</div>
			<div v-if="grandTotalBase !== null" class="col-md-auto d-flex align-items-end pb-1">
				<span class="text-secondary small">
					{{ t("Total in {0}", [currency]) }}:
					<span class="font-monospace fw-semibold">{{ formatMoney(grandTotalBase, currency, user.language) }}</span>
				</span>
			</div>
		</div>

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

		<!-- Items -->
		<div class="d-flex align-items-center mb-2">
			<h6 class="text-uppercase text-secondary small mb-0">{{ t("Items") }}</h6>
			<div class="form-check form-switch ms-auto mb-0">
				<input class="form-check-input" type="checkbox" id="soShowDisc" v-model="showDiscounts" />
				<label class="form-check-label small text-secondary" for="soShowDisc">{{ t("Show discounts") }}</label>
			</div>
		</div>

		<LineItemsEditor
			v-if="form"
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
					<input
						v-if="editable"
						v-model.number="line.discount_percentage"
						type="number"
						step="any"
						min="0"
						max="100"
						inputmode="decimal"
						data-field="disc-pct"
						class="form-control font-monospace text-end"
						placeholder="0"
					/>
					<div v-else class="text-end font-monospace small py-2">{{ line.discount_percentage > 0 ? line.discount_percentage + "%" : "—" }}</div>
				</td>
				<td v-if="showDiscounts" class="align-top">
					<MoneyInput
						v-if="editable"
						v-model="line.discount_amount"
						data-field="disc-amt"
					/>
					<div v-else class="text-end font-monospace small py-2">
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

		<!-- Running total summary block (QuickBooks-style) -->
		<div v-if="editable" class="d-flex justify-content-end mt-2 mb-1">
			<div class="total-summary-block border rounded p-3" style="min-width: 260px;">
				<div class="d-flex justify-content-between mb-1">
					<span class="text-secondary">{{ t("Subtotal") }}</span>
					<span class="font-monospace">{{ formatMoney(subtotal, form.currency || currency, user.language) }}</span>
				</div>
				<div v-if="totalDiscount > 0" class="d-flex justify-content-between mb-1 text-success small">
					<span>{{ t("Discount") }}</span>
					<span class="font-monospace">− {{ formatMoney(totalDiscount, form.currency || currency, user.language) }}</span>
				</div>
				<div class="d-flex justify-content-between border-top pt-2 mt-1">
					<span class="fw-bold">{{ t("Grand total") }}</span>
					<span class="font-monospace fw-bold fs-4">{{ formatMoney(grandTotal, form.currency || currency, user.language) }}</span>
				</div>
				<div v-if="isForeignCurrency && grandTotalBase !== null" class="text-secondary small mt-1 text-end">
					≈ {{ formatMoney(grandTotalBase, currency, user.language) }}
				</div>
				<!-- Fiyat listesi başka bir parada ve çevirecek kur yok: satır fiyatı
				     doldurulmadı. Kur satırının içinde değil burada, çünkü o satır
				     yalnız işlem parası tabandan farklıyken çiziliyor — oysa taban
				     paralı bir siparişte de yabancı bir liste bu duruma düşebilir. -->
				<div v-if="rateWarning" class="text-danger small fw-semibold mt-2">
					<i class="ti ti-alert-triangle me-1"></i>{{ t("Exchange rate unavailable — line prices were not converted. Enter the rate manually.") }}
				</div>
			</div>
		</div>

		<div class="mt-3">
			<label class="form-label">{{ t("Terms / remarks") }}</label>
			<textarea v-if="editable" v-model="form.remarks" class="form-control" rows="2"></textarea>
			<div v-else class="form-control-plaintext py-1">{{ form.remarks || "—" }}</div>
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

		<!-- Actions -->
		<template #actions>
			<template v-if="isCreate">
				<div v-if="hasOverAvailable" class="w-100 small text-danger mb-1">
					<i class="ti ti-alert-triangle me-1"></i>{{ t("One or more lines exceed available stock. Reduce qty or choose a different warehouse.") }}
				</div>
				<div v-if="hasOverAvailable && session.isAdmin" class="w-100 small mb-1 d-flex align-items-center gap-2">
					<input
						id="force-over-stock"
						v-model="forceOverStock"
						type="checkbox"
						class="form-check-input m-0"
					/>
					<label for="force-over-stock" class="text-warning mb-0" style="cursor:pointer">
						{{ t("Override — submit despite low stock (admin)") }}
					</label>
				</div>
				<button type="button" class="btn btn-link link-secondary" :disabled="actionRunning" @click="router.push('/sales/orders')">{{ t("Cancel") }}</button>
				<button type="button" class="btn btn-outline-primary ms-auto" :disabled="actionRunning || !isFormValid" @click="submitCreate({ autoSubmitMode: 0 })">
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Save as draft") }}
				</button>
				<button type="button" class="btn btn-primary" :disabled="actionRunning || !isFormValid || (hasOverAvailable && !(session.isAdmin && forceOverStock))" @click="submitCreate({ autoSubmitMode: 1 })">
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					{{ session.isAdmin && forceOverStock ? t("Force submit & reserve") : t("Submit & reserve stock") }}
				</button>
			</template>
			<template v-else>
				<button
					v-if="can.save"
					type="button"
					class="btn btn-outline-primary"
					:disabled="actionRunning || !isFormValid"
					@click="save"
				>
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-device-floppy me-1"></i>{{ t("Save changes") }}
				</button>
				<button
					v-if="can.submit"
					type="button"
					class="btn btn-primary"
					:disabled="actionRunning"
					@click="submitDoc"
				>
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-check me-1"></i>{{ t("Submit") }}
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
					class="btn btn-outline-danger ms-auto"
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
					:class="{ 'ms-auto': !can.cancel }"
					:disabled="actionRunning"
					@click="remove"
				>
					<i class="ti ti-trash me-1"></i>{{ t("Delete") }}
				</button>
			</template>
		</template>
	</FormPage>
</template>
