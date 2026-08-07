<script setup>
/**
 * Party Center — işlem sekmeleri: Ekstre · Faturalar · Siparişler · Teklifler ·
 * Analitik (+ PartyCenter'dan gelen ek sekmeler, ör. "Alt kayıtlar").
 *
 * Ekstre mantığı (açılış bakiyesi, yürüyen bakiye, FX yeniden değerleme
 * satırlarının elenmesi, tip/metin filtresi, tarih sıralaması) Customers.vue'dan
 * OLDUĞU GİBİ taşındı — Excel çıktısı ve ekrandaki bakiye kolonu birebir aynı
 * kalmalı. Yeniden yazılmadı.
 */
import { computed, ref, watch } from "vue";
import DateInput from "../DateInput.vue";
import EmptyState from "../EmptyState.vue";
import SkeletonRows from "../SkeletonRows.vue";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatTime } from "../../composables/date.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { t } from "../../composables/i18n.js";

const props = defineProps({
	modelValue: { type: String, default: "ledger" },
	tabs: { type: Array, default: () => [] },
	// Ekstre
	ledger: { type: Object, default: null },
	ledgerLoading: { type: Boolean, default: false },
	ledgerError: { type: String, default: "" },
	fromDate: { type: String, default: "" },
	toDate: { type: String, default: "" },
	voucherTypeOptions: { type: Array, default: () => [] },
	invoiceDoctype: { type: String, default: "Sales Invoice" },
	orderDoctype: { type: String, default: "Sales Order" },
	quotationDoctype: { type: String, default: "Quotation" },
	// Listeler
	orders: { type: Array, default: () => [] },
	ordersLoading: { type: Boolean, default: false },
	invoices: { type: Array, default: () => [] },
	quotes: { type: Array, default: () => [] },
	quotesLoading: { type: Boolean, default: false },
	// Bağlam
	partyName: { type: String, default: "" },
	partyNameField: { type: String, default: "customer_name" },
	partyParam: { type: String, default: "customer" },
	partyCurrency: { type: String, default: "" },
	// Yürüyen bakiyenin işareti. Alacak (Customer) tarafında borç bakiyeyi
	// artırır → `+1` (`debit − credit`). Borç (Supplier) tarafında ise alacak
	// borcumuzu artırır → `-1` (`credit − debit`), ki bu backend'in açılış
	// bakiyesiyle aynı kural olsun (`purchasing.py:265`). Yanlış işaret açılışı
	// doğru gösterir ama her satırdan sonra bakiyeyi ters yöne kaydırır.
	ledgerSign: { type: Number, default: 1 },
	currency: { type: String, default: "" },
	language: { type: String, default: "" },
	labels: { type: Object, default: () => ({}) },
});

const emit = defineEmits([
	"update:modelValue",
	"update:fromDate",
	"update:toDate",
	"update:condensed",
	"open-voucher",
	"export",
]);

const ledgerTypeFilter = ref("");
const ledgerSearch = ref("");
const ledgerSortAsc = ref(false); // newest date first by default

function resetLedgerFilters() {
	ledgerTypeFilter.value = "";
	ledgerSearch.value = "";
	ledgerSortAsc.value = false;
}
defineExpose({ resetLedgerFilters });

/* Kaydırınca detay başlığını daraltma.
 *
 * Sayfadaki tek kaydıran eleman `.pc-pane`; başlık ise PartyCenter'da duruyor.
 * Bağlantı tek bir bayrakla kurulur: burada eşik aşılınca `update:condensed`
 * yayılır, PartyCenter `.pc-pane-right`'a `is-condensed` sınıfını basar.
 *
 * İki koruma şart:
 *  - Histerezis (40 aç / 12 kapa): eşiğin tam üstünde titremeyi engeller.
 *  - Geri besleme kilidi: başlık daralınca `.pc-pane` ~70 px büyür, içerik
 *    kısaysa tarayıcı `scrollTop`'u kırpar → eşiğin altına düşer → tekrar
 *    açılır → sonsuz döngü. Bu yüzden çok kısa ekstrede hiç daralmayız.
 *
 * Kilidin eşiği **tek değer olamaz**: kaydırma payı daralmış hâlde ölçülünce
 * zaten ~70 px küçüktür. Tek eşikle (160) ölçüldüğünde 161–229 px payı olan
 * ekstreler daralıp hemen kilide takılıyor ve başlık titriyordu (ölçüldü:
 * pay 179 → aç/kapa/aç/kapa). Bu yüzden açılış eşiği geniş hâlin geometrisine
 * (>160), kalış eşiği daralmış hâlinkine (>40) bakar; aradaki fark daralmayla
 * kazanılan payı fazlasıyla karşılar.
 */
const paneEl = ref(null);
const condensed = ref(false);

const CONDENSE_MIN_OVERFLOW = 160; // geniş hâlde ölçülür
const RELEASE_MIN_OVERFLOW = 40; // daralmış hâlde ölçülür

function setCondensed(v) {
	if (condensed.value === v) return;
	condensed.value = v;
	emit("update:condensed", v);
}

function onPaneScroll() {
	const el = paneEl.value;
	if (!el) return;
	const overflow = el.scrollHeight - el.clientHeight;
	if (overflow <= (condensed.value ? RELEASE_MIN_OVERFLOW : CONDENSE_MIN_OVERFLOW)) {
		setCondensed(false);
		return;
	}
	const y = el.scrollTop;
	if (y > 40) setCondensed(true);
	else if (y < 12) setCondensed(false);
}

// Yeni sekme / yeni kayıt her zaman tam başlıkla açılır.
watch(
	() => [props.modelValue, props.partyName],
	() => {
		setCondensed(false);
		if (paneEl.value) paneEl.value.scrollTop = 0;
	},
);

const ledgerRows = computed(() => {
	const e = props.ledger?.entries || [];
	let runBase = Number(props.ledger?.opening_base || 0);
	let runAcc = Number(props.ledger?.opening_acc || 0);
	const sign = Number(props.ledgerSign) < 0 ? -1 : 1;
	return e.map((row, idx) => {
		runBase += sign * (Number(row.debit || 0) - Number(row.credit || 0));
		runAcc +=
			sign *
			(Number(row.debit_in_account_currency || 0) -
				Number(row.credit_in_account_currency || 0));
		// _seq preserves the backend chronological order (posting_date, creation ASC)
		// so same-date rows sort correctly and the running balance stays monotonic.
		return { ...row, _seq: idx, running_base: runBase, running_acc: runAcc };
	});
});

const filteredLedgerRows = computed(() => {
	let list = ledgerRows.value || [];

	// Hide pure FX-revaluation rows — base-currency-only "Exchange Gain Or Loss"
	// entries that adjust the USD value of the UZS receivable but have ZERO
	// account-currency (UZS) movement. They never change the UZS running balance,
	// so in this account-currency ledger they're just empty "—/—" noise.
	list = list.filter((r) =>
		Math.abs(Number(r.debit_in_account_currency || 0)) > 0.005 ||
		Math.abs(Number(r.credit_in_account_currency || 0)) > 0.005
	);

	if (ledgerTypeFilter.value) {
		if (ledgerTypeFilter.value === "Invoice") {
			list = list.filter(r => r.voucher_type === props.invoiceDoctype);
		} else if (ledgerTypeFilter.value === "Return") {
			list = list.filter(r =>
				r.voucher_type === props.invoiceDoctype &&
				(Number(r.debit || 0) < 0 || Number(r.credit || 0) < 0 || String(r.remarks || "").toLowerCase().includes("return"))
			);
		} else {
			list = list.filter(r => r.voucher_type === ledgerTypeFilter.value);
		}
	}

	if (ledgerSearch.value.trim()) {
		const q = ledgerSearch.value.trim().toLowerCase();
		list = list.filter(r =>
			String(r.voucher_no || "").toLowerCase().includes(q) ||
			String(r.remarks || "").toLowerCase().includes(q)
		);
	}

	list = [...list].sort((a, b) => {
		const cmp = String(a.posting_date || "").localeCompare(String(b.posting_date || ""))
			|| ((a._seq || 0) - (b._seq || 0)); // same-date tiebreak by chronological order
		return ledgerSortAsc.value ? cmp : -cmp;
	});

	return list;
});

const ledgerCurrencyMixed = computed(() => {
	const rows = props.ledger?.entries || [];
	if (!rows.length) return false;
	const set = new Set(rows.map((r) => r.account_currency).filter(Boolean));
	return set.size > 1;
});

const ledgerCurrency = computed(() => {
	if (ledgerCurrencyMixed.value) return props.currency;
	return props.partyCurrency || props.currency;
});

// --- Analitik ---------------------------------------------------------------
// Yeni uç nokta yok: aylık hareket ekstreden, yaşlandırma açık faturalardan
// türetiliyor. Para birimi çevirisi YAPILMAZ — yaşlandırma para birimi başına
// ayrı satır olarak gösterilir.
const monthlyMovement = computed(() => {
	const map = new Map();
	for (const r of ledgerRows.value) {
		const d = String(r.posting_date || "");
		if (!d) continue;
		const key = d.slice(0, 7);
		const debit = Number(ledgerCurrencyMixed.value ? r.debit : r.debit_in_account_currency) || 0;
		const credit = Number(ledgerCurrencyMixed.value ? r.credit : r.credit_in_account_currency) || 0;
		const bucket = map.get(key) || { key, debit: 0, credit: 0 };
		bucket.debit += debit;
		bucket.credit += credit;
		map.set(key, bucket);
	}
	return [...map.values()]
		.sort((a, b) => a.key.localeCompare(b.key))
		.slice(-12)
		.map((m) => ({ ...m, net: (Number(props.ledgerSign) < 0 ? -1 : 1) * (m.debit - m.credit) }));
});

const movementMax = computed(() => {
	let max = 0;
	for (const m of monthlyMovement.value) max = Math.max(max, Math.abs(m.debit), Math.abs(m.credit));
	return max || 1;
});

function monthLabel(key) {
	const [y, m] = String(key).split("-");
	return `${m}.${y}`;
}
function barWidth(v) {
	return `${Math.min(100, (Math.abs(v) / movementMax.value) * 100)}%`;
}

const AGING_BUCKETS = [
	{ key: "not_due", label: () => t("Not due") },
	{ key: "d30", label: () => "1–30" },
	{ key: "d60", label: () => "31–60" },
	{ key: "d90", label: () => "61–90" },
	{ key: "d90p", label: () => "90+" },
];

const agingRows = computed(() => {
	const today = new Date();
	today.setHours(0, 0, 0, 0);
	const byCurrency = new Map();
	for (const inv of props.invoices || []) {
		const outstanding = Number(inv.outstanding_amount || 0);
		if (!(outstanding > 0)) continue;
		const cur = inv.currency || props.currency;
		const row = byCurrency.get(cur) || { currency: cur, not_due: 0, d30: 0, d60: 0, d90: 0, d90p: 0, total: 0 };
		const due = inv.due_date ? new Date(`${inv.due_date}T00:00:00`) : null;
		const days = due ? Math.floor((today - due) / 86400000) : 0;
		if (!due || days <= 0) row.not_due += outstanding;
		else if (days <= 30) row.d30 += outstanding;
		else if (days <= 60) row.d60 += outstanding;
		else if (days <= 90) row.d90 += outstanding;
		else row.d90p += outstanding;
		row.total += outstanding;
		byCurrency.set(cur, row);
	}
	return [...byCurrency.values()];
});

const hasAnalytics = computed(() => monthlyMovement.value.length > 0 || agingRows.value.length > 0);

function openVoucher(type, name) {
	if (!name) return;
	emit("open-voucher", { voucher_type: type, voucher_no: name });
}
</script>

<template>
	<div class="pc-tx">
		<div class="pc-tabs" role="tablist">
			<button
				v-for="tab in props.tabs"
				:key="tab.key"
				type="button"
				role="tab"
				class="pc-tab"
				:class="{ 'pc-tab-active': props.modelValue === tab.key }"
				:aria-selected="props.modelValue === tab.key ? 'true' : 'false'"
				@click="emit('update:modelValue', tab.key)"
			>
				{{ tab.label }}
				<span v-if="tab.badge != null" class="pc-badge">{{ tab.badge }}</span>
			</button>
		</div>

		<div ref="paneEl" class="pc-pane" @scroll.passive="onPaneScroll">
			<!-- EKSTRE -->
			<div v-if="props.modelValue === 'ledger'" class="pc-ledger">
				<div class="pc-ledger-bar">
					<select v-model="ledgerTypeFilter" class="ds-input pc-select" :aria-label="t('Voucher type')">
						<option v-for="v in props.voucherTypeOptions" :key="v.value" :value="v.value">{{ v.label }}</option>
					</select>
					<DateInput
						:model-value="props.fromDate"
						size="sm"
						class="pc-date"
						@update:model-value="emit('update:fromDate', $event)"
					/>
					<DateInput
						:model-value="props.toDate"
						size="sm"
						class="pc-date"
						@update:model-value="emit('update:toDate', $event)"
					/>
					<input
						v-model="ledgerSearch"
						type="search"
						class="ds-input pc-ledger-search"
						:placeholder="t('Search voucher… ⌘K')"
					/>
					<button
						type="button"
						class="ds-btn pc-btn-sm pc-icon-btn"
						:title="t('Toggle date sort')"
						@click="ledgerSortAsc = !ledgerSortAsc"
					>
						<i class="ti" :class="ledgerSortAsc ? 'ti-arrow-narrow-up' : 'ti-arrow-narrow-down'"></i>
					</button>
					<button
						type="button"
						class="ds-btn pc-btn-sm"
						:disabled="!props.ledger?.entries?.length"
						:title="t('Professional Excel export of this ledger')"
						@click="emit('export')"
					>
						<i class="ti ti-file-spreadsheet"></i>{{ t("Excel") }}
					</button>
				</div>

				<table v-if="props.ledgerLoading" class="ds-table">
					<SkeletonRows :rows="8" :cols="5" />
				</table>
				<div v-else-if="props.ledgerError" class="pc-error">{{ props.ledgerError }}</div>
				<div v-else-if="!filteredLedgerRows.length" class="ds-empty pc-empty">
					{{ t("No transactions in this period.") }}
				</div>
				<template v-else>
					<div v-if="ledgerCurrencyMixed" class="pc-warn">
						<i class="ti ti-alert-triangle"></i>
						{{ t("Ledger spans multiple account currencies; amounts shown in base currency.") }}
					</div>
					<table class="ds-table pc-ledger-table">
						<thead>
							<tr>
								<th>{{ t("Date") }}</th>
								<th>{{ t("Voucher") }}</th>
								<th class="ds-td-num">{{ t("Debit") }}</th>
								<th class="ds-td-num">{{ t("Credit") }}</th>
								<th class="ds-td-num">{{ t("Balance") }} ({{ ledgerCurrency }})</th>
							</tr>
						</thead>
						<tbody>
							<tr v-if="props.ledger" class="pc-opening">
								<td colspan="4" class="pc-opening-label">{{ t("Opening balance") }}</td>
								<td class="ds-td-num">
									{{ formatMoney(
										ledgerCurrencyMixed ? props.ledger.opening_base : props.ledger.opening_acc,
										ledgerCurrency,
										props.language,
									) }}
								</td>
							</tr>
							<tr v-for="e in filteredLedgerRows" :key="e.name">
								<td class="pc-nowrap">
									<div>{{ formatDate(e.posting_date) }}</div>
									<div v-if="e.creation && formatTime(e.creation)" class="pc-time">
										{{ formatTime(e.creation) }}
									</div>
								</td>
								<td>
									<div class="pc-voucher-head">
										<span class="pc-voucher-type">{{ e.voucher_type }}</span>
										<span
											v-if="e.party && e.party !== props.partyName"
											class="pc-party-badge"
											:title="e.party_name || e.party"
										>
											<i class="ti ti-building-store"></i>{{ e.party_name || e.party }}
										</span>
										<span v-if="e.channel" class="pc-channel-badge">{{ t(e.channel) }}</span>
									</div>
									<!-- source_route/source_label: CI kaynakli satirlar dogrudan kaynak belgeye
									     gider; backend bu alanlari dondurmezse eski davranis aynen surer. -->
									<router-link v-if="e.source_route" :to="e.source_route" class="pc-voucher-link">
										{{ e.source_label || e.voucher_no }}
									</router-link>
									<button
										v-else-if="e.voucher_no"
										type="button"
										class="pc-voucher-link"
										@click="emit('open-voucher', e)"
									>
										{{ e.source_label || e.voucher_no }}
									</button>
									<div v-else class="pc-dash">—</div>
									<!-- Ustteki baglanti isletmenin tanidigi belgeyi acar (ithalatta CI).
									     Arkasindaki muhasebe fisi denetci istedigi icin kaybolamaz: kimlik
									     farkliysa ikinci, soluk bir dugme olarak yaninda durur. -->
									<button
										v-if="e.voucher_no && e.source_name !== e.voucher_no"
										type="button"
										class="pc-voucher-link pc-voucher-secondary"
										:title="t('Accounting voucher')"
										@click="emit('open-voucher', e)"
									>
										{{ e.voucher_no }}
									</button>
									<div class="pc-remark" :title="e.display_remark">{{ e.display_remark || "—" }}</div>
								</td>
								<td class="ds-td-num">
									<span v-if="Number(ledgerCurrencyMixed ? e.debit : e.debit_in_account_currency) > 0">
										{{ formatMoney(
											ledgerCurrencyMixed ? e.debit : e.debit_in_account_currency,
											ledgerCurrencyMixed ? props.currency : (e.account_currency || ledgerCurrency),
											props.language,
										) }}
									</span>
									<span v-else class="pc-dash">—</span>
								</td>
								<td class="ds-td-num">
									<span v-if="Number(ledgerCurrencyMixed ? e.credit : e.credit_in_account_currency) > 0">
										{{ formatMoney(
											ledgerCurrencyMixed ? e.credit : e.credit_in_account_currency,
											ledgerCurrencyMixed ? props.currency : (e.account_currency || ledgerCurrency),
											props.language,
										) }}
									</span>
									<span v-else class="pc-dash">—</span>
								</td>
								<td class="ds-td-num pc-running">
									{{ formatMoney(
										ledgerCurrencyMixed ? e.running_base : e.running_acc,
										ledgerCurrency,
										props.language,
									) }}
								</td>
							</tr>
						</tbody>
					</table>
				</template>
			</div>

			<!-- FATURALAR -->
			<div v-else-if="props.modelValue === 'invoices'">
				<table class="ds-table">
					<thead>
						<tr>
							<th>{{ t("Invoice #") }}</th>
							<th>{{ t("Date") }}</th>
							<th class="ds-td-num">{{ t("Total") }}</th>
							<th class="ds-td-num">{{ t("Outstanding") }}</th>
							<th>{{ t("Status") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="inv in props.invoices"
							:key="inv.name"
							class="pc-row"
							@click="openVoucher(props.invoiceDoctype, inv.name)"
						>
							<td>
								<div class="pc-voucher-head">
									<span class="pc-code">{{ inv.name }}</span>
									<span
										v-if="inv[props.partyParam] && inv[props.partyParam] !== props.partyName"
										class="pc-party-badge"
										:title="inv[props.partyNameField] || inv[props.partyParam]"
									>
										<i class="ti ti-building-store"></i>{{ inv[props.partyNameField] || inv[props.partyParam] }}
									</span>
								</div>
							</td>
							<td>{{ formatDate(inv.posting_date) }}</td>
							<td class="ds-td-num">{{ formatMoney(inv.grand_total, inv.currency || props.currency, props.language) }}</td>
							<td class="ds-td-num">{{ formatMoney(inv.outstanding_amount, inv.currency || props.currency, props.language) }}</td>
							<td>
								<span class="badge" :class="getStatusBadgeClass(props.invoiceDoctype, inv.status)">{{ t(inv.status) }}</span>
							</td>
						</tr>
						<tr v-if="!props.invoices.length">
							<td colspan="5" class="pc-empty">{{ t("No invoices found.") }}</td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- SİPARİŞLER -->
			<div v-else-if="props.modelValue === 'orders'">
				<table v-if="props.ordersLoading" class="ds-table">
					<SkeletonRows :rows="5" :cols="4" />
				</table>
				<EmptyState
					v-else-if="!props.orders.length"
					icon="ti-clipboard-list"
					tone="primary"
					:title="props.labels.noOrdersTitle || t('No orders yet')"
					:subtitle="props.labels.noOrdersSubtitle || ''"
					class="pc-emptystate"
				/>
				<table v-else class="ds-table">
					<thead>
						<tr>
							<th>{{ t("Order #") }}</th>
							<th>{{ t("Date") }}</th>
							<th class="ds-td-num">{{ t("Total") }}</th>
							<th>{{ t("Status") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="o in props.orders"
							:key="o.name"
							class="pc-row"
							@click="openVoucher(props.orderDoctype, o.name)"
						>
							<td>
								<div class="pc-voucher-head">
									<span class="pc-code">{{ o.name }}</span>
									<span
										v-if="o[props.partyParam] && o[props.partyParam] !== props.partyName"
										class="pc-party-badge"
										:title="o[props.partyNameField] || o[props.partyParam]"
									>
										<i class="ti ti-building-store"></i>{{ o[props.partyNameField] || o[props.partyParam] }}
									</span>
								</div>
							</td>
							<td>{{ formatDate(o.transaction_date) }}</td>
							<td class="ds-td-num">{{ formatMoney(o.grand_total, o.currency || props.currency, props.language) }}</td>
							<td>
								<span class="badge" :class="getStatusBadgeClass(props.orderDoctype, o.status)">{{ t(o.status) }}</span>
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- TEKLİFLER -->
			<div v-else-if="props.modelValue === 'quotes'">
				<table v-if="props.quotesLoading" class="ds-table">
					<SkeletonRows :rows="5" :cols="4" />
				</table>
				<table v-else class="ds-table">
					<thead>
						<tr>
							<th>{{ t("Quotation #") }}</th>
							<th>{{ t("Date") }}</th>
							<th>{{ t("Valid till") }}</th>
							<th class="ds-td-num">{{ t("Total") }}</th>
							<th>{{ t("Status") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="q in props.quotes"
							:key="q.name"
							class="pc-row"
							@click="openVoucher(props.quotationDoctype, q.name)"
						>
							<td><span class="pc-code">{{ q.name }}</span></td>
							<td>{{ formatDate(q.transaction_date) }}</td>
							<td>{{ q.valid_till ? formatDate(q.valid_till) : "—" }}</td>
							<td class="ds-td-num">{{ formatMoney(q.grand_total, q.currency || props.currency, props.language) }}</td>
							<td>
								<span class="badge" :class="getStatusBadgeClass(props.quotationDoctype, q.status)">{{ t(q.status) }}</span>
							</td>
						</tr>
						<tr v-if="!props.quotes.length">
							<td colspan="5" class="pc-empty">{{ t("No quotations found.") }}</td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- ANALİTİK -->
			<div v-else-if="props.modelValue === 'analytics'" class="pc-analytics">
				<div v-if="!hasAnalytics" class="ds-empty pc-empty">{{ t("Not enough data to analyse yet.") }}</div>
				<template v-else>
					<section v-if="monthlyMovement.length" class="pc-analytic-block">
						<h3 class="pc-section-title">{{ t("Monthly movement") }} ({{ ledgerCurrency }})</h3>
						<table class="ds-table">
							<thead>
								<tr>
									<th>{{ t("Month") }}</th>
									<th class="pc-bar-col">{{ t("Activity") }}</th>
									<th class="ds-td-num">{{ t("Debit") }}</th>
									<th class="ds-td-num">{{ t("Credit") }}</th>
									<th class="ds-td-num">{{ t("Net") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="m in monthlyMovement" :key="m.key">
									<td class="pc-nowrap">{{ monthLabel(m.key) }}</td>
									<td class="pc-bar-col">
										<div class="pc-bar pc-bar-debit" :style="{ width: barWidth(m.debit) }"></div>
										<div class="pc-bar pc-bar-credit" :style="{ width: barWidth(m.credit) }"></div>
									</td>
									<td class="ds-td-num">{{ formatMoney(m.debit, ledgerCurrency, props.language) }}</td>
									<td class="ds-td-num">{{ formatMoney(m.credit, ledgerCurrency, props.language) }}</td>
									<td class="ds-td-num" :class="m.net > 0 ? 'pc-pos' : m.net < 0 ? 'pc-neg' : 'pc-dash'">
										{{ formatMoney(m.net, ledgerCurrency, props.language) }}
									</td>
								</tr>
							</tbody>
						</table>
					</section>

					<section v-if="agingRows.length" class="pc-analytic-block">
						<h3 class="pc-section-title">{{ t("Open items by age") }}</h3>
						<table class="ds-table">
							<thead>
								<tr>
									<th>{{ t("Currency") }}</th>
									<th v-for="b in AGING_BUCKETS" :key="b.key" class="ds-td-num">{{ b.label() }}</th>
									<th class="ds-td-num">{{ t("Total") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="row in agingRows" :key="row.currency">
									<td class="pc-code">{{ row.currency }}</td>
									<td v-for="b in AGING_BUCKETS" :key="b.key" class="ds-td-num">
										{{ formatMoney(row[b.key], row.currency, props.language) }}
									</td>
									<td class="ds-td-num pc-running">{{ formatMoney(row.total, row.currency, props.language) }}</td>
								</tr>
							</tbody>
						</table>
					</section>
				</template>
			</div>

			<!-- PartyCenter'dan gelen ek sekmeler (ör. alt kayıtlar) -->
			<slot v-else name="pane" :tab="props.modelValue"></slot>
		</div>
	</div>
</template>

<style scoped>
.pc-tx {
	display: flex;
	flex-direction: column;
	min-height: 0;
	flex: 1 1 auto;
	background: #fff;
}
.pc-tabs {
	display: flex;
	flex-wrap: wrap;
	gap: 2px;
	padding: 0 12px;
	border-bottom: 2px solid rgba(29, 39, 59, 0.32);
	background: #fff;
	flex: 0 0 auto;
}
.pc-tab {
	min-height: 36px;
	padding: 7px 12px;
	border: 0;
	border-bottom: 3px solid transparent;
	margin-bottom: -2px;
	background: transparent;
	font-size: 13.5px;
	font-weight: 600;
	color: var(--tblr-gray-600, #667382);
	cursor: pointer;
}
.pc-tab:hover {
	color: #1d273b;
}
.pc-tab-active {
	color: #1d273b;
	border-bottom: 3px solid #206bc4;
}
.pc-badge {
	display: inline-block;
	margin-left: 6px;
	padding: 0 5px;
	font-family: var(--ds-mono, monospace);
	font-size: 11px;
	color: var(--tblr-gray-600, #667382);
	background: #eef0f3;
}
.pc-pane {
	flex: 1 1 auto;
	min-height: 0;
	overflow-y: auto;
}

.pc-ledger-bar {
	display: flex;
	flex-wrap: wrap;
	align-items: center;
	gap: 6px;
	padding: 6px 10px;
	border-bottom: 1px solid #e3e5e8;
	background: #f6f8fb;
	position: sticky;
	top: 0;
	z-index: 2;
}
.pc-select {
	width: 8.5rem;
	min-height: 32px;
	padding: 4px 7px;
	font-size: 12.5px;
}
.pc-date {
	width: 7.5rem;
}
/* DateInput kendi Bootstrap sarmalayıcısını getiriyor; çubuğun yüksekliğini
   o belirlemesin diye alanı diğer kontrollerle aynı ölçüye çekiyoruz. */
.pc-date :deep(.form-control) {
	min-height: 32px;
	height: 32px;
	padding: 4px 7px;
	font-size: 12.5px;
}
.pc-ledger-search {
	flex: 1 1 8rem;
	min-width: 6rem;
	min-height: 32px;
	padding: 4px 8px;
	font-size: 12.5px;
}
/* Global `.ds-btn` 40 px; ekstre çubuğunda satır yüksekliğini o belirliyordu
   ve dar panelde Excel butonu ikinci satıra sarıyordu. Yerel küçük boy. */
.pc-btn-sm {
	min-height: 32px;
	padding: 4px 9px;
	font-size: 12.5px;
	gap: 5px;
}
.pc-icon-btn {
	padding: 4px 8px;
}

/* Çubuk 62 → 44 px indi; başlık satırı onun altına yapışmalı, yoksa
   kaydırırken ilk ekstre satırı çubuğun arkasında kalıyor. */
.pc-ledger-table thead th {
	position: sticky;
	top: 44px;
	z-index: 1;
	background: #fff;
}
.pc-opening td {
	color: var(--tblr-gray-600, #667382);
	font-style: italic;
}
.pc-opening-label {
	text-align: right;
}
.pc-nowrap {
	white-space: nowrap;
}
.pc-time {
	font-family: var(--ds-mono, monospace);
	font-size: 11px;
	color: var(--tblr-gray-600, #667382);
}
.pc-voucher-head {
	display: flex;
	align-items: center;
	gap: 6px;
	flex-wrap: wrap;
}
.pc-voucher-type {
	font-size: 12px;
	font-weight: 600;
	color: var(--tblr-gray-600, #667382);
}
.pc-party-badge {
	display: inline-flex;
	align-items: center;
	gap: 3px;
	padding: 1px 6px;
	font-size: 11.5px;
	color: #1d273b;
	background: #eef0f3;
}
.pc-channel-badge {
	padding: 1px 6px;
	font-size: 11px;
	letter-spacing: 0.02em;
	text-transform: uppercase;
	color: var(--tblr-gray-600, #667382);
	border: 1px solid var(--ds-ln, #e3e6ea);
}
.pc-voucher-link {
	text-decoration: none;
	padding: 0;
	border: 0;
	background: transparent;
	font-family: var(--ds-mono, monospace);
	font-size: 12px;
	font-weight: 600;
	color: #206bc4;
	cursor: pointer;
}
.pc-voucher-link:hover {
	text-decoration: underline;
}
.pc-voucher-secondary {
	margin-left: 0.5rem;
	font-size: 11px;
	font-weight: 500;
	color: var(--tblr-gray-600, #667382);
}
.pc-remark {
	max-width: 280px;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
	font-size: 11.5px;
	color: var(--tblr-gray-600, #667382);
}
.pc-code {
	font-family: var(--ds-mono, monospace);
	font-size: 12.5px;
	font-weight: 600;
	color: #206bc4;
}
.pc-running {
	font-weight: 600;
}
.pc-row {
	cursor: pointer;
}
.pc-dash {
	color: var(--tblr-gray-600, #667382);
}
.pc-pos {
	color: #1c7a3a;
}
.pc-neg {
	color: #b32424;
}
.pc-empty {
	padding: 32px 16px;
	text-align: center;
	color: var(--tblr-gray-600, #667382);
	font-size: 13px;
}
.pc-emptystate {
	border: 0;
	background: transparent;
}
.pc-error {
	margin: 12px;
	padding: 10px 12px;
	border: 1px solid #d63939;
	color: #b32424;
	font-size: 13px;
}
.pc-warn {
	display: flex;
	align-items: center;
	gap: 6px;
	margin: 12px;
	padding: 9px 12px;
	border: 1px solid #f76707;
	color: #9a4d06;
	font-size: 12.5px;
}

.pc-analytics {
	padding: 16px 12px;
}
.pc-analytic-block + .pc-analytic-block {
	margin-top: 24px;
}
.pc-section-title {
	margin: 0 0 8px;
	padding-bottom: 6px;
	border-bottom: 2px solid rgba(29, 39, 59, 0.32);
	font-size: 14px;
	font-weight: 700;
	color: #1d273b;
}
.pc-bar-col {
	width: 30%;
	min-width: 8rem;
}
.pc-bar {
	height: 6px;
	min-width: 1px;
}
.pc-bar-debit {
	background: #206bc4;
}
.pc-bar-credit {
	margin-top: 3px;
	background: #2fb344;
}
</style>
