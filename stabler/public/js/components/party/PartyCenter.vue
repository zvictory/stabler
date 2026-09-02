<script setup>
/**
 * Party Center — Müşteri/Tedarikçi merkezi için paylaşılan 2 panelli kabuk.
 *
 * Bu bileşen parti türünden BAĞIMSIZDIR: tüm uç noktalar, alan adları ve
 * yönlendirmeler `api` / `routes` prop'larından gelir. Kod içinde "Customer" ya
 * da "Supplier" sabiti yoktur (çok kiracılı disiplin: davranış koda değil,
 * yapılandırmaya bağlanır).
 *
 * Yerleşim: CSS grid + sürüklenebilir ayraç. Genişlik `--pc-left` değişkeninde
 * tutulur, `stabler.partyCenter.leftWidth` altında saklanır, 18–40rem aralığına
 * kısılır ve 768px altında tek kolona düşer.
 *
 * Korunan davranışlar (Customers.vue'dan taşındı, değiştirilmedi):
 *   · `?c=<ad>` derin bağlantısı + yenilemede seçimi geri yükleme
 *   · ESC → önce seçimi temizler, sonra geri gider
 *   · liste alt bilgisindeki para birimi bazlı toplamlar ve `grand_totals` koşulu
 *   · ekstre açılış/yürüyen bakiyesi ve Excel dışa aktarımı (PartyTransactions)
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useListViewState } from "../../composables/useListViewState.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { useLatestRequest } from "../../composables/useLatestRequest.js";
import PartyAvatar from "../PartyAvatar.vue";
import ApexChart from "../ApexChart.vue";
import PartyList from "./PartyList.vue";
import PartyKpiStrip from "./PartyKpiStrip.vue";
import PartyIdentityCard from "./PartyIdentityCard.vue";
import PartyTransactions from "./PartyTransactions.vue";
import PartyChildren from "./PartyChildren.vue";

const props = defineProps({
	/** "Customer" | "Supplier" — yalnızca rozet/etiket bağlamı için. */
	partyType: { type: String, required: true },
	/**
	 * Uç noktalar + alan eşlemesi. Bkz. dosya başındaki sözleşme notu.
	 * `ledgerSign`: alacak tarafı `+1` (varsayılan, `debit − credit`),
	 * borç tarafı `-1` (`credit − debit`) — backend'in açılış bakiyesiyle
	 * aynı kural olmalı.
	 */
	api: { type: Object, required: true },
	/** Parti türüne göre değişen kullanıcıya görünen metinler. */
	labels: { type: Object, default: () => ({}) },
	/** Üst/alt kayıt hiyerarşisi desteklensin mi (sunucu `has_hierarchy` ile kesişir). */
	hierarchy: { type: Boolean, default: false },
	/** `{ method, keys:{ total, today, trend, top }, labels:{ total, today, trend, top, empty } }` */
	cockpit: { type: Object, default: null },
	/** useListViewState anahtarı, ör. "stabler.customers.listState". */
	stateKey: { type: String, required: true },
	/** `{ vouchers: { "<Doctype>": "/path/:name" | { path, query } }, newPrimary }` */
	routes: { type: Object, default: () => ({}) },
	/** Ek sekmeler: `[{ key, label, badge? }]` — içerik `#extra-tabs` slotundan. */
	extraTabs: { type: Array, default: () => [] },
	/** Form kabuğu (alanları saran bileşen sağlar). */
	formOpen: { type: Boolean, default: false },
	formMode: { type: String, default: "create" },
	formTitle: { type: String, default: "" },
	submitting: { type: Boolean, default: false },
	deleting: { type: Boolean, default: false },
	submitError: { type: String, default: "" },
	canSubmit: { type: Boolean, default: true },
	canDelete: { type: Boolean, default: false },
});

const emit = defineEmits([
	"create",
	"select",
	"detail",
	"close-form",
	"submit-form",
	"delete-form",
]);

const session = useSession();
const router = useRouter();
const { activeCompany, user } = storeToRefs(session);

const language = computed(() => user.value.language);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const companyCurrency = ref("");
const currency = computed(() => companyCurrency.value || session.currency);

const NAME_FIELD = computed(() => props.api.nameField);
const PARAM = computed(() => props.api.param);

// --- Kalıcı liste durumu: URL ↔ localStorage (URL kaynak doğrudur) ----------
const {
	search,
	onlyWithBalance,
	onlyOverdue,
	filterGroup,
	filterTerritory,
	sortField,
	sortAsc,
	c: selectedName,
} = useListViewState(props.stateKey, {
	search: "",
	filterGroup: "",
	filterTerritory: "",
	onlyWithBalance: false,
	onlyOverdue: false,
	sortField: "name",
	sortAsc: true,
	c: "",
});

const selected = ref(null);
const selectedDetail = ref(null);

// ESC → önce açık kaydı bırak (sağ paneli temizle), sonra geri git.
useEscapeBack(() => {
	if (selected.value) {
		selected.value = null;
		selectedName.value = ""; // composable c'yi URL + localStorage'dan siler
		invalidatePartyRequests();
		emit("select", null);
		return true;
	}
	return false;
}, props.routes.back || "/");

// --- Ayraç (splitter) -------------------------------------------------------
const SPLIT_KEY = "stabler.partyCenter.leftWidth";
const MIN_REM = 18;
const MAX_REM = 40;
const leftRem = ref(readLeftWidth());
const dragging = ref(false);

function readLeftWidth() {
	const stored = Number(localStorage.getItem(SPLIT_KEY));
	// 26rem — UZS tutarları 15 karaktere kadar çıkıyor ("-211 400 000 сўм"),
	// 22rem'de bakiye sütunu ad sütununu ~9rem'e sıkıştırıyordu.
	if (!Number.isFinite(stored) || stored <= 0) return 26;
	return Math.min(MAX_REM, Math.max(MIN_REM, stored));
}
function rootFontPx() {
	const size = parseFloat(getComputedStyle(document.documentElement).fontSize);
	return Number.isFinite(size) && size > 0 ? size : 16;
}
const gridRef = ref(null);
function startDrag(ev) {
	dragging.value = true;
	ev.currentTarget.setPointerCapture?.(ev.pointerId);
	ev.preventDefault();
}
function onDrag(ev) {
	if (!dragging.value || !gridRef.value) return;
	const left = gridRef.value.getBoundingClientRect().left;
	const rem = (ev.clientX - left) / rootFontPx();
	leftRem.value = Math.min(MAX_REM, Math.max(MIN_REM, rem));
}
function endDrag(ev) {
	if (!dragging.value) return;
	dragging.value = false;
	ev.currentTarget.releasePointerCapture?.(ev.pointerId);
	localStorage.setItem(SPLIT_KEY, String(Math.round(leftRem.value * 100) / 100));
}
function nudge(delta) {
	leftRem.value = Math.min(MAX_REM, Math.max(MIN_REM, leftRem.value + delta));
	localStorage.setItem(SPLIT_KEY, String(Math.round(leftRem.value * 100) / 100));
}

// --- Liste ------------------------------------------------------------------
const totalCount = ref(0);
const listTruncated = ref(false);
const grandTotals = ref([]);

// Sunucu sayfayı `limit` ile kırptığında kitabın tamamına ait toplam. Yalnızca
// sayfa GERÇEKTEN kırpıldığında gösterilir: aksi halde alt bilgi zaten kitabın
// tamamıdır ve yanına ikinci bir rakam koymak yuvarlama hatası gibi görünür.
// Grup/bölge/gecikme filtreleri kümeyi istemcide daraltır, sunucu rakamı
// ekrandakiyle uyuşmaz — onlarda da gizle.
const showGrandTotals = computed(
	() =>
		listTruncated.value &&
		grandTotals.value.length > 0 &&
		!onlyOverdue.value &&
		!filterGroup.value &&
		!filterTerritory.value
);

const availableGroups = computed(() => {
	const f = props.api.groupField;
	if (!f) return [];
	return [...new Set(rows.value.map((r) => r[f]).filter(Boolean))].sort();
});
const availableTerritories = computed(() => {
	const f = props.api.territoryField;
	if (!f) return [];
	return [...new Set(rows.value.map((r) => r[f]).filter(Boolean))].sort();
});

const filteredRows = computed(() => {
	let list = rows.value;
	if (filterGroup.value && props.api.groupField) {
		list = list.filter((r) => r[props.api.groupField] === filterGroup.value);
	}
	if (filterTerritory.value && props.api.territoryField) {
		list = list.filter((r) => r[props.api.territoryField] === filterTerritory.value);
	}
	return list;
});

// Alt bilgi toplamları: satırların KENDİ para biriminde, para birimi başına
// gruplanır (temel para birimine çevrilmez) ve ağaç modunda çocukları iki kez
// saymamak için düz filtrelenmiş küme üzerinden hesaplanır.
const visibleTotals = computed(() => {
	const byCurrency = new Map();
	for (const r of filteredRows.value) {
		const amount = Number(r.balance_acc ?? r.balance_base ?? 0);
		if (!amount) continue;
		const cur = r.account_currency || currency.value;
		byCurrency.set(cur, (byCurrency.get(cur) || 0) + amount);
	}
	return [...byCurrency.entries()].map(([cur, amount]) => ({ currency: cur, amount }));
});

// --- Hiyerarşi --------------------------------------------------------------
const hasHierarchy = ref(false);
const hierarchyOn = computed(() => props.hierarchy && hasHierarchy.value);
const VIEW_KEY = computed(() => `${props.stateKey}.viewMode`);
const EXPANDED_KEY = computed(() => `${props.stateKey}.expanded`);
const viewMode = ref("tree");
const childrenBalAcc = ref({});
const expanded = ref({});

function loadSplitPrefs() {
	viewMode.value = localStorage.getItem(VIEW_KEY.value) === "flat" ? "flat" : "tree";
	try {
		expanded.value = JSON.parse(localStorage.getItem(EXPANDED_KEY.value) || "{}") || {};
	} catch {
		expanded.value = {};
	}
}
loadSplitPrefs();

watch(viewMode, (v) => localStorage.setItem(VIEW_KEY.value, v));
function toggleView() {
	viewMode.value = viewMode.value === "tree" ? "flat" : "tree";
}
function toggleExpand(name) {
	expanded.value = { ...expanded.value, [name]: !expanded.value[name] };
	localStorage.setItem(EXPANDED_KEY.value, JSON.stringify(expanded.value));
}

const byName = computed(() => {
	const m = {};
	for (const r of rows.value) m[r.name] = r;
	return m;
});
const childrenByParent = computed(() => {
	const m = {};
	const f = props.api.parentField;
	if (!f) return m;
	for (const r of rows.value) {
		if (r[f]) (m[r[f]] ||= []).push(r);
	}
	return m;
});
const isSearching = computed(() => !!(search.value || "").trim());
const treeMode = computed(() => hierarchyOn.value && viewMode.value === "tree" && !isSearching.value);

function ownBalanceOf(r) {
	return Number(r?.balance_acc ?? r?.balance_base ?? 0);
}
function rowIsParent(r) {
	return (childrenByParent.value[r.name] || []).length > 0;
}
function cumulativeAccOf(name) {
	return ownBalanceOf(byName.value[name]) + Number(childrenBalAcc.value[name] || 0);
}

function sortList(list, useCumulative) {
	if (sortField.value === "name") {
		return [...list].sort((a, b) => {
			const cmp = (a[NAME_FIELD.value] || "").localeCompare(b[NAME_FIELD.value] || "");
			return sortAsc.value ? cmp : -cmp;
		});
	}
	if (sortField.value === "balance") {
		return [...list].sort((a, b) => {
			const av = useCumulative && rowIsParent(a) ? cumulativeAccOf(a.name) : ownBalanceOf(a);
			const bv = useCumulative && rowIsParent(b) ? cumulativeAccOf(b.name) : ownBalanceOf(b);
			return sortAsc.value ? av - bv : bv - av;
		});
	}
	return list;
}

function decorate(raw, level, isParent, childCount, parentLabel) {
	const value = isParent ? cumulativeAccOf(raw.name) : ownBalanceOf(raw);
	let tooltip = "";
	if (isParent) {
		const cur = raw.account_currency || currency.value;
		const own = formatMoney(ownBalanceOf(raw), cur, language.value);
		const kids = formatMoney(Number(childrenBalAcc.value[raw.name] || 0), cur, language.value);
		tooltip = `${t("Own")}: ${own} · ${t("Children")}: ${kids}`;
	}
	return {
		key: raw.name,
		name: raw.name,
		raw,
		level,
		isParent,
		childCount,
		parentLabel,
		title: raw[NAME_FIELD.value] || raw.name,
		code: raw.name,
		balance: value,
		balanceCurrency: value ? raw.account_currency || currency.value : currency.value,
		tooltip,
	};
}

const visibleRows = computed(() => {
	if (!treeMode.value) {
		const list = sortList(filteredRows.value, false);
		const pf = props.api.parentField;
		return list.map((r) =>
			decorate(
				r,
				0,
				false,
				0,
				pf && r[pf] ? byName.value[r[pf]]?.[NAME_FIELD.value] || r[pf] : ""
			)
		);
	}
	const pf = props.api.parentField;
	const tops = filteredRows.value.filter((r) => !r[pf]);
	const out = [];
	for (const p of sortList(tops, true)) {
		const kids = childrenByParent.value[p.name] || [];
		const isParent = kids.length > 0;
		out.push(decorate(p, 0, isParent, kids.length, ""));
		if (isParent && expanded.value[p.name]) {
			for (const k of sortList(kids, false)) out.push(decorate(k, 1, false, 0, ""));
		}
	}
	return out;
});

function toggleSort(field) {
	if (sortField.value === field) {
		sortAsc.value = !sortAsc.value;
	} else {
		sortField.value = field;
		sortAsc.value = true;
	}
}

async function loadChildrenBalanceMap() {
	if (!props.api.childrenBalanceMap) return;
	try {
		const res = await call(props.api.childrenBalanceMap, { company: activeCompany.value });
		childrenBalAcc.value = res.acc || {};
	} catch {
		childrenBalAcc.value = {};
	}
}

async function loadList() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await call(props.api.list, {
			company: activeCompany.value,
			search: search.value || "",
			only_with_balance: onlyWithBalance.value ? 1 : 0,
			only_overdue: onlyOverdue.value ? 1 : 0,
			limit: 2500,
		});
		rows.value = res.rows || [];
		totalCount.value = Number(res.total_count || 0);
		listTruncated.value = !!res.truncated;
		grandTotals.value = res.grand_totals || [];
		companyCurrency.value = res.company_currency || "";
		hasHierarchy.value = !!res.has_hierarchy;
		if (hierarchyOn.value) loadChildrenBalanceMap();
		if (selected.value) {
			const fresh = rows.value.find((r) => r.name === selected.value.name);
			if (fresh) {
				selected.value = fresh;
				emit("select", fresh);
			} else {
				selected.value = null;
				ledger.value = null;
				invalidatePartyRequests();
				emit("select", null);
			}
		}
	} catch (err) {
		error.value = err?.message || props.labels.loadError || t("Failed to load.");
	} finally {
		loading.value = false;
	}
}

let searchTimer = null;
function onSearchInput() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(loadList, 300);
}
watch([onlyWithBalance, onlyOverdue], loadList);

// --- Seçili kayıt -----------------------------------------------------------
const ledger = ref(null);
const ledgerLoading = ref(false);
const ledgerError = ref("");
const ledgerFromDate = ref("");
const ledgerToDate = ref("");
const recentInvoices = ref([]);
const orders = ref([]);
const ordersLoading = ref(false);
const quotes = ref([]);
const quotesLoading = ref(false);
const includeChildren = ref(true);
const currentTab = ref("ledger");
const txRef = ref(null);

// Dört yükleyicinin her biri KENDİ biletini alır (useLatestRequest.js). Tek bir
// ortak sayaç işe yaramaz: `selectRow` / `prefetchSelection` dördünü peş peşe
// çağırıyor, ortak sayaçta yalnız sonuncusu geçerli kalır ve diğer üç panel hiç
// dolmazdı. Amaç, A kaydından B'ye geçildiğinde A'nın geç dönen yanıtının
// B'nin adı altında boyanmasını engellemek.
const ledgerReq = useLatestRequest();
const ordersReq = useLatestRequest();
const quotesReq = useLatestRequest();
const detailReq = useLatestRequest();

// Seçim kalkarken uçuştaki her istek emekliye ayrılmalı; aksi halde artık seçili
// olmayan bir kayıt için dönen yanıt paneli yeniden doldurur. Yükleniyor
// bayrakları da burada iner: yükleyicilerin `finally` blokları artık bilete
// bakıyor, yani emekli isteğin `finally`'si onları temizlemeyecek.
function invalidatePartyRequests() {
	ledgerReq.invalidate();
	ordersReq.invalidate();
	quotesReq.invalidate();
	detailReq.invalidate();
	ledgerLoading.value = false;
	ordersLoading.value = false;
	quotesLoading.value = false;
}
// Ekstre kaydırılınca detay başlığı tek satıra çöker. Bayrağı PartyTransactions
// üretir (kaydıran eleman orada); burada yalnızca sınıfa çevrilir.
const headCondensed = ref(false);

const selectedIsParent = computed(() => !!selectedDetail.value?.is_parent);
const headerBalanceValue = computed(() => {
	if (selectedIsParent.value) return selectedDetail.value?.cumulative_balance_acc ?? 0;
	return selected.value?.balance_acc ?? selected.value?.balance_base ?? 0;
});
const headerBalanceCurrency = computed(
	() => selected.value?.account_currency || selectedDetail.value?.account_currency || currency.value
);

function defaultDateRange() {
	const to = new Date();
	const from = new Date();
	from.setDate(from.getDate() - 365);
	// LOCAL date (not toISOString → UTC shift, off-by-one in UTC+N zones).
	const iso = (d) =>
		`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
	return { from: iso(from), to: iso(to) };
}

async function loadLedger(row) {
	if (!row) return;
	ledgerLoading.value = true;
	ledgerError.value = "";
	const isCurrent = ledgerReq.take();
	try {
		const params = {
			company: activeCompany.value,
			[PARAM.value]: row.name,
			include_children: includeChildren.value ? 1 : 0,
			limit: 1000,
		};
		if (ledgerFromDate.value) params.from_date = ledgerFromDate.value;
		if (ledgerToDate.value) params.to_date = ledgerToDate.value;
		const res = await call(props.api.ledger, params);
		if (!isCurrent()) return;
		ledger.value = res;
	} catch (err) {
		if (!isCurrent()) return;
		ledger.value = null;
		ledgerError.value = err?.message || t("Failed to load ledger.");
	} finally {
		if (isCurrent()) ledgerLoading.value = false;
	}
}

async function loadOrders(row) {
	if (!row || !activeCompany.value || !props.api.orders) return;
	ordersLoading.value = true;
	const isCurrent = ordersReq.take();
	try {
		const res = await call(props.api.orders, {
			company: activeCompany.value,
			[PARAM.value]: row.name,
			include_children: includeChildren.value ? 1 : 0,
			limit: 50,
		});
		if (!isCurrent()) return;
		orders.value = res;
	} catch {
		if (!isCurrent()) return;
		orders.value = [];
	} finally {
		if (isCurrent()) ordersLoading.value = false;
	}
}

async function loadQuotes(row) {
	if (!row || !activeCompany.value || !props.api.quotes) return;
	quotesLoading.value = true;
	const isCurrent = quotesReq.take();
	try {
		const res = await call(props.api.quotes, {
			company: activeCompany.value,
			[PARAM.value]: row.name,
			limit: 50,
		});
		if (!isCurrent()) return;
		quotes.value = Array.isArray(res) ? res : res?.rows || [];
	} catch {
		if (!isCurrent()) return;
		quotes.value = [];
	} finally {
		if (isCurrent()) quotesLoading.value = false;
	}
}

async function loadDetail(row) {
	const isCurrent = detailReq.take();
	try {
		const detail = await call(props.api.detail, {
			name: row.name,
			company: activeCompany.value,
			include_children: includeChildren.value ? 1 : 0,
		});
		if (!isCurrent()) return;
		recentInvoices.value = detail.recent_invoices || [];
		selectedDetail.value = detail;
		emit("detail", detail);
		// Alt kayıtlar sekmesi yalnızca üst kayıtlarda var — aksi halde ekstreye dön.
		if (currentTab.value === "children" && !detail.is_parent) currentTab.value = "ledger";
	} catch (err) {
		console.error(err);
	}
}

// Ekstre penceresi hem seçim hem ön-getirme yolunda AYNI SIRAYLA kurulmalı;
// aksi halde `loadLedger` iki farklı tarih aralığıyla iki kez koşar.
function ensureLedgerRange() {
	if (ledgerFromDate.value || ledgerToDate.value) return;
	const r = defaultDateRange();
	ledgerFromDate.value = r.from;
	ledgerToDate.value = r.to;
}

// Derin bağlantı (`?c=<ad>`) ön-getirmesi: dört yükleyicinin dördü de satır
// nesnesinden yalnız `name` okuyor, dolayısıyla listenin dönmesi beklenmeden
// çağrılabilirler — kritik yoldan tam bir ağ turu kalkar.
function prefetchSelection(name) {
	if (!name || !activeCompany.value) return;
	const stub = { name };
	ensureLedgerRange();
	loadLedger(stub);
	loadOrders(stub);
	loadQuotes(stub);
	loadDetail(stub);
}

// `fetch: false` → satırı yalnız seçili duruma bağla, ağ çağrılarını atla.
// `prefetchSelection` verileri zaten istemişken, liste dönüp satır nesnesi
// gerçeğiyle değiştirilirken aynı dört çağrının tekrarlanmaması için.
async function selectRow(row, { fetch = true } = {}) {
	if (!row) return;
	selected.value = row;
	selectedName.value = row.name; // composable → URL + localStorage
	if (fetch) {
		orders.value = [];
		quotes.value = [];
		recentInvoices.value = [];
		txRef.value?.resetLedgerFilters?.();
	}

	ensureLedgerRange();
	emit("select", row);
	if (!fetch) return;
	loadLedger(row);
	loadOrders(row);
	loadQuotes(row);
	await loadDetail(row);
}

function selectByName(name) {
	const row = byName.value[name];
	if (row) selectRow(row);
}

// `c` artık remount olmadan da değişebiliyor (useListViewState query'yi izliyor),
// dolayısıyla mount'taki derin bağlantı çözümü bir adın panele ulaşmasının tek
// yolu değil: adres çubuğu düzenlemesi ya da yapıştırılan bir bağlantı onu canlı
// panelin altından değiştirir.
watch(selectedName, (name) => {
	// selectRow selectedName'i kendisi yazıyor — bu koruma olmadan her tıklama
	// buraya yeniden girip zaten açık satır için dört yükleyiciyi tekrarlardı.
	if (name === (selected.value?.name || "")) return;
	const row = name ? byName.value[name] : null;
	if (row) {
		selectRow(row);
		return;
	}
	// Boş, ya da bu listenin taşımadığı bir ad. Mount da çözülemeyen derin bağlantıyı
	// böyle ele alıyor: seçim yok, kokpiti `watch(selected, …)` gösteriyor.
	selected.value = null;
	selectedDetail.value = null;
	invalidatePartyRequests();
	emit("select", null);
});

// Kokpit satırı liste sayfasının dışında kalmış olabilir (liste `limit` ile
// kırpılır) — o durumda kokpitin kendi satırıyla aç.
function selectFromCockpit(row) {
	selectRow(byName.value[row.name] || row);
}

watch(includeChildren, () => {
	if (!selected.value) return;
	loadLedger(selected.value);
	loadOrders(selected.value);
	loadDetail(selected.value);
});

watch([ledgerFromDate, ledgerToDate], () => {
	if (selected.value) loadLedger(selected.value);
});

// --- Fiş yönlendirmesi ------------------------------------------------------
function openVoucher(entry) {
	if (!entry?.voucher_no) return;
	const target = (props.routes.vouchers || {})[entry.voucher_type];
	if (!target) return;
	if (typeof target === "string") {
		router.push(target.replace(":name", encodeURIComponent(entry.voucher_no)));
	} else if (target.path && target.query) {
		router.push({ path: target.path, query: { [target.query]: entry.voucher_no } });
	}
}

// Açık kaydın ekstresinin profesyonel .xlsx dökümü (açılış / hareketler /
// yürüyen bakiye / kapanış) — geçerli kayıt + tarih aralığı için sunucuda
// yeniden koşar.
function exportLedger() {
	if (!selected.value?.name) return;
	const qs = new URLSearchParams({
		report_key: props.api.ledgerReportKey,
		filters: JSON.stringify({
			company: activeCompany.value,
			[PARAM.value]: selected.value.name,
			from_date: ledgerFromDate.value || undefined,
			to_date: ledgerToDate.value || undefined,
		}),
	});
	window.open(`/api/method/stabler.api.export.export_report_xlsx?${qs.toString()}`, "_blank");
}

// --- Kokpit -----------------------------------------------------------------
const cockpitData = ref(null);
const cockpitLoading = ref(false);
const ck = computed(() => props.cockpit?.keys || {});

async function loadCockpit() {
	if (!activeCompany.value || !props.cockpit?.method) return;
	cockpitLoading.value = true;
	try {
		cockpitData.value = await call(props.cockpit.method, { company: activeCompany.value });
	} catch (err) {
		console.error(err);
	} finally {
		cockpitLoading.value = false;
	}
}

const cockpitTop = computed(() => cockpitData.value?.[ck.value.top] || []);
const trendSeries = computed(() => [
	{ name: props.cockpit?.labels?.trendSeries || t("Trend"), data: cockpitData.value?.[ck.value.trend] || [] },
]);
const trendOptions = computed(() => ({
	chart: { sparkline: { enabled: true } },
	stroke: { curve: "smooth", width: 2 },
	colors: ["#206bc4"],
	tooltip: {
		fixed: { enabled: false },
		x: { show: false },
		y: { title: { formatter: () => (props.cockpit?.labels?.trendSeries || t("Trend")) + ": " } },
		marker: { show: false },
	},
}));

watch(selected, (v) => {
	if (!v) loadCockpit();
});

// --- KPI'lar ----------------------------------------------------------------
const kpiItems = computed(() => {
	const d = selectedDetail.value;
	const items = [
		{
			key: "balance",
			label: selectedIsParent.value ? `${t("Balance")} (${t("Cumulative")})` : t("Balance"),
			chip: {
				value: headerBalanceValue.value,
				currency: headerBalanceCurrency.value,
				partyType: props.partyType,
			},
			note: selectedIsParent.value
				? `${t("Own")}: ${formatMoney(d?.own_balance_acc || 0, headerBalanceCurrency.value, language.value)}`
				: "",
			sev: "neutral",
		},
		{
			key: "overdue",
			label: t("Overdue"),
			text: formatMoney(
				d?.overdue_amount || 0,
				d?.overdue_currency || selected.value?.account_currency || currency.value,
				language.value
			),
			sev: Number(d?.overdue_amount || 0) > 0 ? "crit" : "neutral",
		},
		{
			key: "lifetime",
			label: props.labels.lifetimeLabel || t("Lifetime"),
			text: formatMoney(
				d?.lifetime_amount ?? d?.lifetime_base ?? 0,
				d?.lifetime_currency || currency.value,
				language.value
			),
			sev: "neutral",
		},
		{
			key: "last_payment",
			label: t("Last Payment"),
			text: d?.last_payment_date ? formatDate(d.last_payment_date) : "—",
			sev: "neutral",
		},
	];
	return items;
});

// Daralmış başlıkta KPI şeridi gizlenir. Gecikmiş tutar bu ekranın tek "risk"
// göstergesi olduğu için orada kaybolmaz, başlığa mini rozet olarak taşınır.
const overdueChip = computed(() => {
	const d = selectedDetail.value;
	const amt = Number(d?.overdue_amount || 0);
	if (!(amt > 0)) return "";
	return formatMoney(amt, d?.overdue_currency || selected.value?.account_currency || currency.value, language.value);
});

// --- Sekmeler ---------------------------------------------------------------
const tabs = computed(() => {
	const list = [];
	if (selectedIsParent.value && hierarchyOn.value) {
		list.push({
			key: "children",
			label: props.labels.childrenTab || t("Children"),
			badge: selectedDetail.value?.children?.length || 0,
		});
	}
	list.push({ key: "ledger", label: t("Ledger") });
	if (props.api.orders) list.push({ key: "orders", label: t("Orders"), badge: orders.value.length });
	list.push({ key: "invoices", label: t("Invoices"), badge: recentInvoices.value.length });
	if (props.api.quotes) list.push({ key: "quotes", label: t("Quotations"), badge: quotes.value.length });
	list.push({ key: "analytics", label: t("Analytics") });
	for (const tab of props.extraTabs) list.push(tab);
	return list;
});

const voucherTypeOptions = computed(() => [
	{ value: "", label: t("All vouchers") },
	{ value: "Payment Entry", label: t("Payment") },
	{ value: props.api.invoiceDoctype, label: t("Invoice") },
	{ value: "Journal Entry", label: t("Journal") },
	{ value: "Return", label: t("Return") },
]);

// --- Yaşam döngüsü ----------------------------------------------------------
onMounted(async () => {
	// selectedName, useListViewState tarafından URL/localStorage'dan bu koşmadan
	// önce hidrasyona uğratılır — `?c=<ad>` derin bağlantısı böyle çalışır.
	const deepLink = selectedName.value;
	const listPromise = loadList(); // bilerek await edilmiyor

	if (deepLink) {
		prefetchSelection(deepLink);
	} else {
		// Kokpit yalnız hiçbir kayıt seçili DEĞİLKEN görünüyor; derin bağlantıda
		// çağırmak boşa bir tur. Seçim kalkınca `watch(selected, …)` yüklüyor.
		loadCockpit();
	}

	await listPromise;

	if (deepLink) {
		const match = rows.value.find((r) => r.name === deepLink);
		if (match) selectRow(match, { fetch: false });
		else loadCockpit(); // derin bağlantı tutmadı → kokpit görünür kalır
	}
});

watch(activeCompany, () => {
	selected.value = null;
	selectedDetail.value = null;
	ledger.value = null;
	selectedName.value = "";
	invalidatePartyRequests();
	emit("select", null);
	loadList();
	loadCockpit();
});

function refreshSelected() {
	if (selected.value) selectRow(selected.value);
}

defineExpose({
	reload: loadList,
	refreshSelected,
	reloadLedger: () => loadLedger(selected.value),
	selectByName,
	exportLedger,
	rows,
	selected,
	selectedDetail,
});
</script>

<template>
	<div class="stbl-ds pc-root">
		<div ref="gridRef" class="pc-grid" :class="{ 'pc-dragging': dragging }" :style="{ '--pc-left': leftRem + 'rem' }">
			<PartyList
				class="pc-pane-left"
				:rows="visibleRows"
				:loading="loading"
				:error="error"
				:selected-name="selected?.name || ''"
				:search="search"
				:only-with-balance="onlyWithBalance"
				:only-overdue="onlyOverdue"
				:filter-group="filterGroup"
				:filter-territory="filterTerritory"
				:group-options="availableGroups"
				:territory-options="availableTerritories"
				:sort-field="sortField"
				:sort-asc="sortAsc"
				:hierarchy-enabled="hierarchyOn"
				:tree-mode="treeMode"
				:expanded-map="expanded"
				:filtered-count="filteredRows.length"
				:loaded-count="rows.length"
				:total-count="totalCount"
				:truncated="listTruncated"
				:visible-totals="visibleTotals"
				:grand-totals="grandTotals"
				:show-grand-totals="showGrandTotals"
				:language="language"
				:labels="props.labels"
				@update:search="search = $event"
				@update:only-with-balance="onlyWithBalance = $event"
				@update:only-overdue="onlyOverdue = $event"
				@update:filter-group="filterGroup = $event"
				@update:filter-territory="filterTerritory = $event"
				@search-input="onSearchInput"
				@sort="toggleSort"
				@toggle-view="toggleView"
				@toggle-expand="toggleExpand"
				@select="selectRow"
				@create="emit('create')"
			/>

			<div
				class="pc-splitter"
				role="separator"
				aria-orientation="vertical"
				tabindex="0"
				:aria-label="t('Resize list panel')"
				@pointerdown="startDrag"
				@pointermove="onDrag"
				@pointerup="endDrag"
				@pointercancel="endDrag"
				@keydown.left.prevent="nudge(-1)"
				@keydown.right.prevent="nudge(1)"
			>
				<span class="pc-splitter-grip"></span>
			</div>

			<div class="pc-pane-right" :class="{ 'is-condensed': headCondensed }">
				<!-- KOKPİT (seçim yokken) -->
				<div v-if="!selected" class="pc-cockpit">
					<div class="ds-kpis pc-cockpit-kpis" data-cols="2">
						<div class="ds-kpi" data-sev="neutral">
							<div class="pc-label">{{ props.cockpit?.labels?.total || t("Total outstanding") }}</div>
							<div class="ds-kpi-val">
								{{ formatMoney(cockpitData?.[ck.total] || 0, currency, language) }}
							</div>
							<!-- Kapsamı adlandırır: liste alt bilgisi filtrelenmiş sayfayı,
							     bu rakam defterdeki tüm kayıtları anlatır. -->
							<div class="ds-kpi-note pc-note">{{ props.labels.allRecords || t("All records") }}</div>
						</div>
						<div class="ds-kpi" data-sev="ok">
							<div class="pc-label">{{ props.cockpit?.labels?.today || t("Payments today") }}</div>
							<div class="ds-kpi-val">
								{{ formatMoney(cockpitData?.[ck.today] || 0, currency, language) }}
							</div>
						</div>
					</div>

					<div class="ds-panel pc-cockpit-panel">
						<div class="ds-panel-head">
							<span class="pc-label">{{ props.cockpit?.labels?.trend || t("Trend (last 8 weeks)") }}</span>
						</div>
						<div class="pc-panel-body">
							<div v-if="cockpitLoading" class="ds-skel pc-chart-skel"></div>
							<ApexChart
								v-else-if="cockpitData?.[ck.trend]?.length"
								type="line"
								height="120"
								:series="trendSeries"
								:options="trendOptions"
							/>
						</div>
					</div>

					<div class="ds-panel pc-cockpit-panel">
						<div class="ds-panel-head">
							<span class="pc-label">{{ props.cockpit?.labels?.top || t("Top 10") }}</span>
						</div>
						<table class="ds-table">
							<tbody>
								<tr v-for="d in cockpitTop" :key="d.name" class="pc-row" @click="selectFromCockpit(d)">
									<td>
										<div class="pc-top-name">
											<PartyAvatar :name="d[NAME_FIELD] || d.name" size="sm" />
											<div class="pc-top-text">
												<div class="pc-top-title">{{ d[NAME_FIELD] || d.name }}</div>
												<div class="pc-top-code">{{ d.name }}</div>
											</div>
										</div>
									</td>
									<td class="ds-td-num font-monospace pc-top-amount">
										{{ formatMoney(d.balance_acc ?? d.balance, d.account_currency || currency, language) }}
									</td>
								</tr>
								<tr v-if="!cockpitTop.length">
									<td colspan="2" class="pc-empty">{{ props.cockpit?.labels?.empty || t("Nothing to show.") }}</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>

				<!-- SEÇİLİ KAYIT -->
				<template v-else>
					<div class="pc-detail-head">
						<PartyAvatar :name="selected[NAME_FIELD] || selected.name" size="md" class="pc-detail-avatar" />
						<div class="pc-detail-id">
							<button
								v-if="selectedDetail?.parent_customer || selectedDetail?.parent_supplier"
								type="button"
								class="pc-parent-link"
								:title="props.labels.parentLabel || t('Parent')"
								@click="selectByName(selectedDetail.parent_customer || selectedDetail.parent_supplier)"
							>
								<i class="ti ti-arrow-up"></i>
								{{
									selectedDetail.parent_customer_name ||
									selectedDetail.parent_supplier_name ||
									selectedDetail.parent_customer ||
									selectedDetail.parent_supplier
								}}
							</button>
							<!-- Kod başlıkla aynı satırda: kimlik öbeği üç satırdan ikiye iner. -->
							<div class="pc-detail-line">
								<h2 class="pc-detail-title">{{ selected[NAME_FIELD] || selected.name }}</h2>
								<span class="pc-detail-code">{{ selected.name }}</span>
								<span v-if="selectedIsParent" class="pc-parent-badge">{{ props.labels.parentLabel || t("Parent") }}</span>
								<span v-if="overdueChip" class="pc-overdue-chip" :title="t('Overdue')">
									<i class="ti ti-clock-exclamation"></i>{{ overdueChip }}
								</span>
							</div>
							<PartyIdentityCard
								:detail="selectedDetail"
								:fields="{ group: props.api.groupField, territory: props.api.territoryField }"
								:labels="props.labels"
							/>
						</div>
						<div class="pc-detail-actions">
							<slot
								name="actions"
								:selected="selected"
								:detail="selectedDetail"
								:is-parent="selectedIsParent"
								:balance="headerBalanceValue"
								:balance-currency="headerBalanceCurrency"
								:export-ledger="exportLedger"
							></slot>
						</div>
					</div>

					<PartyKpiStrip :items="kpiItems" :cols="4" :language="language" />

					<!-- Sekmelerden bağımsız, her zaman görünür şerit. Tedarikçi tarafındaki
					     "Import Exposure + Open Commitments" bunu kullanır: bir sekme değil,
					     KPI'ların hemen altında duran bir bant. Sarmalayıcı doldurmazsa
					     hiçbir şey render edilmez. -->
					<slot name="detail-banner" :selected="selected" :detail="selectedDetail" :is-parent="selectedIsParent"></slot>

					<div v-if="selectedIsParent" class="pc-include">
						<label class="pc-switch">
							<input v-model="includeChildren" type="checkbox" />
							<span>{{ props.labels.includeChildren || t("Include child transactions") }}</span>
						</label>
						<span class="pc-include-state">
							{{
								includeChildren
									? `${t("Consolidated View")} (${selectedDetail?.children?.length || 0})`
									: t("Parent Only View")
							}}
						</span>
					</div>

					<PartyTransactions
						ref="txRef"
						v-model="currentTab"
						@update:condensed="headCondensed = $event"
						:tabs="tabs"
						:ledger="ledger"
						:ledger-loading="ledgerLoading"
						:ledger-error="ledgerError"
						:from-date="ledgerFromDate"
						:to-date="ledgerToDate"
						:voucher-type-options="voucherTypeOptions"
						:invoice-doctype="props.api.invoiceDoctype"
						:order-doctype="props.api.orderDoctype"
						:quotation-doctype="props.api.quotationDoctype"
						:orders="orders"
						:orders-loading="ordersLoading"
						:invoices="recentInvoices"
						:quotes="quotes"
						:quotes-loading="quotesLoading"
						:party-name="selected.name"
						:party-name-field="NAME_FIELD"
						:party-param="PARAM"
						:party-currency="selected.account_currency || ''"
						:ledger-sign="props.api.ledgerSign ?? 1"
						:currency="currency"
						:language="language"
						:labels="props.labels"
						@update:from-date="ledgerFromDate = $event"
						@update:to-date="ledgerToDate = $event"
						@open-voucher="openVoucher"
						@export="exportLedger"
					>
						<template #pane="{ tab }">
							<PartyChildren
								v-if="tab === 'children'"
								:children="selectedDetail?.children || []"
								:name-field="NAME_FIELD"
								:status-doctype="props.partyType"
								:currency="currency"
								:language="language"
								@open="selectByName"
							/>
							<slot v-else name="extra-tabs" :tab="tab" :selected="selected" :detail="selectedDetail"></slot>
						</template>
					</PartyTransactions>
				</template>
			</div>
		</div>

		<!-- Oluştur / düzenle kabuğu — alanlar `#form-fields` slotundan gelir -->
		<template v-if="props.formOpen">
			<div class="modal-backdrop fade show" @click="emit('close-form')"></div>
			<div class="modal fade show d-block" tabindex="-1" role="dialog">
				<div class="modal-dialog modal-dialog-centered" role="document">
					<div class="modal-content">
						<div class="modal-header">
							<h5 class="modal-title">{{ props.formTitle }}</h5>
							<button type="button" class="btn-close" :aria-label="t('Close')" @click="emit('close-form')"></button>
						</div>
						<div class="modal-body">
							<div v-if="props.submitError" class="alert alert-danger">{{ props.submitError }}</div>
							<slot name="form-fields"></slot>
						</div>
						<div class="modal-footer">
							<button
								type="button"
								class="btn btn-link link-secondary"
								:disabled="props.submitting || props.deleting"
								@click="emit('close-form')"
							>
								{{ t("Cancel") }}
							</button>
							<button
								v-if="props.formMode === 'edit' && props.canDelete"
								type="button"
								class="btn btn-outline-danger me-auto"
								:disabled="props.submitting || props.deleting"
								@click="emit('delete-form')"
							>
								<span v-if="props.deleting" class="spinner-border spinner-border-sm me-1"></span>
								<i v-else class="ti ti-trash me-1"></i>
								{{ t("Delete") }}
							</button>
							<button
								type="button"
								class="btn btn-primary ms-auto"
								:disabled="props.submitting || props.deleting || !props.canSubmit"
								@click="emit('submit-form')"
							>
								<span v-if="props.submitting" class="spinner-border spinner-border-sm me-2"></span>
								<i v-else class="ti ti-device-floppy me-1"></i>
								{{ t("Save") }}
							</button>
						</div>
					</div>
				</div>
			</div>
		</template>
	</div>
</template>

<style scoped>
.pc-root {
	display: flex;
	flex-direction: column;
	min-height: 0;
	height: calc(100vh - 3.5rem);
	background: #f6f8fb;
}
.pc-grid {
	display: grid;
	grid-template-columns: var(--pc-left, 26rem) 7px minmax(0, 1fr);
	flex: 1 1 auto;
	min-height: 0;
	border-top: 2px solid rgba(29, 39, 59, 0.32);
}
.pc-dragging {
	user-select: none;
	cursor: col-resize;
}
.pc-pane-left {
	min-width: 0;
	min-height: 0;
	border-right: 1px solid #e3e5e8;
	background: #fff;
}
.pc-pane-right {
	min-width: 0;
	min-height: 0;
	display: flex;
	flex-direction: column;
	overflow-y: auto;
	background: #f6f8fb;
}

.pc-splitter {
	position: relative;
	cursor: col-resize;
	background: #eef0f3;
	border: 0;
	border-left: 1px solid #e3e5e8;
	border-right: 1px solid #e3e5e8;
	touch-action: none;
}
.pc-splitter:hover,
.pc-splitter:focus-visible {
	background: #d7dde6;
	outline: none;
}
.pc-splitter-grip {
	position: absolute;
	top: 50%;
	left: 50%;
	width: 1px;
	height: 28px;
	margin: -14px 0 0 0;
	background: #667382;
}

.pc-cockpit {
	display: flex;
	flex-direction: column;
	gap: 16px;
	padding: 16px;
}
.pc-cockpit-kpis {
	background: #fff;
}
.pc-cockpit-panel {
	background: #fff;
}
.pc-panel-body {
	padding: 12px 16px;
}
.pc-chart-skel {
	height: 120px;
}
.pc-top-name {
	display: flex;
	align-items: center;
	gap: 8px;
	min-width: 0;
}
.pc-top-text {
	min-width: 0;
}
.pc-top-title {
	font-weight: 600;
	color: #1d273b;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.pc-top-code {
	font-family: var(--ds-mono, monospace);
	font-size: 11.5px;
	color: var(--tblr-gray-600, #667382);
}
.pc-top-amount {
	font-weight: 700;
	color: #b32424;
}
.pc-row {
	cursor: pointer;
}
.pc-empty {
	padding: 28px 16px;
	text-align: center;
	color: var(--tblr-gray-600, #667382);
	font-size: 13px;
}

.pc-detail-head {
	display: flex;
	align-items: center;
	gap: 10px;
	flex-wrap: wrap;
	padding: 8px 14px;
	background: #fff;
	border-bottom: 2px solid rgba(29, 39, 59, 0.32);
}
.pc-detail-id {
	/* 12rem taban butonları ikinci satıra itiyordu (48+14+738+14+606 > 832). */
	flex: 1 1 8rem;
	min-width: 0;
}
.pc-detail-line {
	display: flex;
	align-items: baseline;
	gap: 8px;
	min-width: 0;
}
.pc-detail-title {
	margin: 0;
	font-size: 16px;
	font-weight: 700;
	color: #1d273b;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.pc-detail-code {
	flex: 0 0 auto;
	font-family: var(--ds-mono, monospace);
	font-size: 11.5px;
	color: var(--tblr-gray-600, #667382);
}
/* KPI şeridi daralınca gizlendiği için gecikme riski başlıkta kalır. */
.pc-overdue-chip {
	display: none;
	flex: 0 0 auto;
	align-items: center;
	gap: 4px;
	padding: 1px 6px;
	font-size: 11.5px;
	font-weight: 600;
	color: var(--ds-crit-tx, #b32424);
	background: #fdecec;
}
.pc-parent-link {
	display: inline-flex;
	align-items: center;
	gap: 4px;
	padding: 0;
	border: 0;
	background: transparent;
	font-size: 12px;
	color: #206bc4;
	cursor: pointer;
}
.pc-parent-link:hover {
	text-decoration: underline;
}
.pc-parent-badge {
	display: inline-block;
	margin-left: 6px;
	padding: 1px 6px;
	vertical-align: middle;
	font-size: 11px;
	font-weight: 600;
	color: #206bc4;
	background: #e7f0fb;
}
.pc-detail-actions {
	display: flex;
	align-items: center;
	gap: 6px;
	flex-wrap: wrap;
}
/* Global `.ds-btn` 40 px. Sarmalayıcı sayfalar (`Customers.vue` / `Suppliers.vue`)
   `#actions` slot'una düz `ds-btn` basıyor; ölçüyü token'a dokunmadan burada
   küçültüyoruz — beş buton 832 px'lik panelde tek satıra ancak böyle sığıyor. */
.pc-detail-actions :deep(.ds-btn) {
	min-height: 34px;
	padding: 6px 10px;
	font-size: 13px;
	gap: 5px;
}

/* --- Kaydırınca daralan başlık --------------------------------------------
   Bayrak PartyTransactions'tan gelir (kaydıran eleman `.pc-pane`). DOM
   değişmez, yalnız görünürlük/ölçü; böylece `#actions` slot'u tek yerde kalır
   ve daralma sırasında hiçbir buton yeniden monte edilmez. */
.pc-pane-right.is-condensed .pc-detail-head {
	padding: 4px 14px;
}
.pc-pane-right.is-condensed .pc-detail-avatar {
	--tblr-avatar-size: 1.75rem;
	width: 1.75rem;
	height: 1.75rem;
	font-size: 11px;
}
.pc-pane-right.is-condensed .pc-detail-title {
	font-size: 14px;
}
.pc-pane-right.is-condensed .pc-detail-code,
.pc-pane-right.is-condensed .pc-parent-link,
.pc-pane-right.is-condensed :deep(.pc-meta) {
	display: none;
}
.pc-pane-right.is-condensed .pc-overdue-chip {
	display: inline-flex;
}
.pc-pane-right.is-condensed :deep(.pc-kpis) {
	max-height: 0;
	opacity: 0;
	overflow: hidden;
	border-width: 0;
}
.pc-pane-right.is-condensed .pc-detail-actions :deep(.ds-btn) {
	min-height: 30px;
	padding: 5px 9px;
}
/* Sekonder butonlar ikon-only düşer. Sarmalayıcı sayfalar hangi metnin
   düşebileceğini `pc-btn-txt` ile işaretler; Payment butonunun etiketi ve
   satır içi tutarı işaretlenmez — yanlış tarafa ödeme bu ekranın pahalı
   hatası, tutar her iki durumda da görünür kalır. */
.pc-pane-right.is-condensed .pc-detail-actions :deep(.pc-btn-txt) {
	display: none;
}
.pc-detail-head,
:deep(.pc-kpis) {
	transition:
		max-height 0.16s ease,
		opacity 0.12s ease,
		padding 0.16s ease;
}
@media (prefers-reduced-motion: reduce) {
	.pc-detail-head,
	:deep(.pc-kpis) {
		transition: none;
	}
}

.pc-include {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	flex-wrap: wrap;
	padding: 8px 16px;
	background: #eef0f3;
	border-bottom: 1px solid #e3e5e8;
	font-size: 12.5px;
}
.pc-switch {
	display: flex;
	align-items: center;
	gap: 8px;
	margin: 0;
	font-weight: 600;
	color: #1d273b;
	cursor: pointer;
}
.pc-include-state {
	color: var(--tblr-gray-600, #667382);
}
/* Mikro etiket — `.ds-label` çevrilmeyen teknik kimliklere ayrılmıştır;
   çevrili etiketler tipografiyi buradan alır, tonu AA'ya çekilir. */
.pc-label {
	font-family: var(--ds-mono);
	font-size: 10px;
	letter-spacing: 0.14em;
	text-transform: uppercase;
	color: var(--tblr-gray-600, #667382);
}
.pc-note {
	color: var(--tblr-gray-600, #667382);
}

@media (max-width: 767.98px) {
	.pc-root {
		height: auto;
	}
	.pc-grid {
		grid-template-columns: minmax(0, 1fr);
	}
	.pc-splitter {
		display: none;
	}
	.pc-pane-left {
		border-right: 0;
		border-bottom: 1px solid #e3e5e8;
	}
	.pc-pane-right {
		overflow-y: visible;
	}
}
</style>
