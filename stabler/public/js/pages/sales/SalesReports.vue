<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import { todayIso } from "../../composables/date.js";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const router = useRouter();

const today = todayIso();
const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);

const activeTab = ref("customer");
const fromDate = ref(monthAgo);
const toDate = ref(today);
const customer = ref("");
const customerDisplay = ref("");
const itemCode = ref("");
const itemDisplay = ref("");
const itemGroup = ref("");
const granularity = ref("day");
const dateBasis = ref("posting");
const includeDrafts = ref(false);

const scopeNote = computed(() =>
	includeDrafts.value
		? t("Including unposted drafts — does not tie to the GL.")
		: t("Submitted Sales Invoices only"),
);
const itemGroups = ref([]);
const rows = ref([]);
const drilldownCustomer = ref(null);
const drilldownRows = ref([]);
const loading = ref(false);
const drilldownLoading = ref(false);
const error = ref("");

const itemGroupOptions = computed(() => [
	{ name: "", label: t("All item groups") },
	...itemGroups.value.map((row) => ({ ...row, label: row.name })),
]);

const title = computed(() => {
	if (activeTab.value === "customer") return t("Sales by Customer");
	if (activeTab.value === "item") return t("Sales by Item");
	if (activeTab.value === "trend") return t("Sales Trend");
	if (activeTab.value === "orders") return t("Sales Orders");
	return t("Sales by Salesperson");
});

const tabs = [
	{ key: "customer", label: t("Customer"), icon: "ti-users" },
	{ key: "item", label: t("Item"), icon: "ti-ice-cream-2" },
	{ key: "trend", label: t("Trend"), icon: "ti-chart-line" },
	{ key: "salesperson", label: t("Salesperson"), icon: "ti-user-dollar" },
	{ key: "orders", label: t("Orders"), icon: "ti-clipboard-list" },
];

// Grand-total row. Counts and quantities always sum. Money columns only sum when
// every row shares one currency — summing across currencies would be meaningless,
// so in the mixed case we show a "mixed" marker instead of a fake number.
const totals = computed(() => {
	const r = rows.value;
	if (!r.length) return null;
	const currencies = new Set(r.map((x) => x.currency).filter(Boolean));
	const oneCurrency = currencies.size <= 1;
	const sum = (key) => r.reduce((acc, x) => acc + (Number(x[key]) || 0), 0);
	const baseNetRevenue = sum("base_net_revenue");
	const margin = sum("margin");
	return {
		oneCurrency,
		currency: oneCurrency ? [...currencies][0] || "" : "",
		invoice_count: sum("invoice_count"),
		total: sum("total"),
		outstanding: sum("outstanding"),
		revenue: sum("revenue"),
		qty: sum("qty"),
		gross: sum("gross"),
		returns_amt: sum("returns_amt"),
		order_count: sum("order_count"),
		booked: sum("booked"),
		to_deliver: sum("to_deliver"),
		to_bill: sum("to_bill"),
		// COGS & margin are in base currency (single per company), so unlike the
		// transaction-currency columns they always sum cleanly across rows.
		baseCurrency: r[0]?.base_currency || "",
		cogs: sum("cogs"),
		margin,
		margin_pct: baseNetRevenue ? Math.round((margin / baseNetRevenue) * 1000) / 10 : 0,
	};
});

function fmtTotalMoney(value) {
	// When rows span multiple currencies a summed money figure is meaningless, so
	// show "—" (matching the currency cell) instead of a misleading total.
	return totals.value?.oneCurrency ? formatMoney(value, totals.value.currency) : "—";
}

function fmtBaseMoney(value) {
	return formatMoney(value, totals.value?.baseCurrency || "");
}

function fmtPct(value) {
	return `${Number(value || 0).toFixed(1)}%`;
}

// Returns breakout: only widen the table with Gross/Returns columns when the
// period actually contains credit notes — keeps the common case clean.
const hasReturns = computed(() => rows.value.some((r) => Number(r.returns_amt) !== 0));

// --- CSV export of the current tab (raw numbers, current filters) -------------
// Mirrors the on-screen columns plus the underlying id/code, which is handy for
// downstream analysis. Money totals are only written when rows share a currency.
function csvCell(v) {
	if (v == null) v = "";
	v = String(v).replace(/"/g, '""');
	return /[",\n]/.test(v) ? `"${v}"` : v;
}

function exportColumns() {
	const t1 = totals.value;
	const money = (key) => (t1?.oneCurrency ? t1[key] : "");
	if (activeTab.value === "customer")
		return [
			{ label: t("Customer"), value: (r) => r.customer_name || r.customer, total: () => t("Total") },
			{ label: t("Customer ID"), value: (r) => r.customer, total: () => "" },
			{ label: t("Currency"), value: (r) => r.currency, total: () => (t1?.oneCurrency ? t1.currency : "") },
			{ label: t("Invoices"), value: (r) => r.invoice_count, total: () => t1?.invoice_count },
			...(hasReturns.value
				? [
						{ label: t("Gross"), value: (r) => r.gross, total: () => money("gross") },
						{ label: t("Returns"), value: (r) => r.returns_amt, total: () => money("returns_amt") },
					]
				: []),
			{ label: t("Total"), value: (r) => r.total, total: () => money("total") },
			{ label: t("Outstanding"), value: (r) => r.outstanding, total: () => money("outstanding") },
			{ label: t("COGS"), value: (r) => r.cogs, total: () => t1?.cogs },
			{ label: t("Margin"), value: (r) => r.margin, total: () => t1?.margin },
			{ label: t("Margin %"), value: (r) => r.margin_pct, total: () => t1?.margin_pct },
		];
	if (activeTab.value === "item")
		return [
			{ label: t("Item"), value: (r) => r.item_name || r.item_code, total: () => t("Total") },
			{ label: t("Item Code"), value: (r) => r.item_code, total: () => "" },
			{ label: t("Group"), value: (r) => r.item_group || "", total: () => "" },
			{ label: t("Qty"), value: (r) => r.qty, total: () => t1?.qty },
			...(hasReturns.value
				? [
						{ label: t("Gross"), value: (r) => r.gross, total: () => money("gross") },
						{ label: t("Returns"), value: (r) => r.returns_amt, total: () => money("returns_amt") },
					]
				: []),
			{ label: t("Revenue"), value: (r) => r.revenue, total: () => money("revenue") },
			{ label: t("Invoices"), value: (r) => r.invoice_count, total: () => t1?.invoice_count },
			{ label: t("COGS"), value: (r) => r.cogs, total: () => t1?.cogs },
			{ label: t("Margin"), value: (r) => r.margin, total: () => t1?.margin },
			{ label: t("Margin %"), value: (r) => r.margin_pct, total: () => t1?.margin_pct },
		];
	if (activeTab.value === "trend")
		return [
			{ label: t("Period"), value: (r) => r.period, total: () => t("Total") },
			{ label: t("Currency"), value: (r) => r.currency, total: () => (t1?.oneCurrency ? t1.currency : "") },
			{ label: t("Invoices"), value: (r) => r.invoice_count, total: () => t1?.invoice_count },
			{ label: t("Total"), value: (r) => r.total, total: () => money("total") },
			{ label: t("Outstanding"), value: (r) => r.outstanding, total: () => money("outstanding") },
		];
	if (activeTab.value === "orders")
		return [
			{ label: t("Customer"), value: (r) => r.customer_name || r.customer, total: () => t("Total") },
			{ label: t("Customer ID"), value: (r) => r.customer, total: () => "" },
			{ label: t("Currency"), value: (r) => r.currency, total: () => (t1?.oneCurrency ? t1.currency : "") },
			{ label: t("Orders"), value: (r) => r.order_count, total: () => t1?.order_count },
			{ label: t("Booked"), value: (r) => r.booked, total: () => money("booked") },
			{ label: t("To deliver"), value: (r) => r.to_deliver, total: () => money("to_deliver") },
			{ label: t("To bill"), value: (r) => r.to_bill, total: () => money("to_bill") },
		];
	return [
		{ label: t("Salesperson"), value: (r) => r.sales_person, total: () => t("Total") },
		{ label: t("Currency"), value: (r) => r.currency, total: () => (t1?.oneCurrency ? t1.currency : "") },
		{ label: t("Invoices"), value: (r) => r.invoice_count, total: () => t1?.invoice_count },
		{ label: t("Total"), value: (r) => r.total, total: () => money("total") },
	];
}

function exportCsv() {
	if (!rows.value.length) return;
	const cols = exportColumns();
	const lines = [cols.map((c) => csvCell(c.label)).join(",")];
	for (const r of rows.value) lines.push(cols.map((c) => csvCell(c.value(r))).join(","));
	if (totals.value) lines.push(cols.map((c) => csvCell(c.total())).join(","));
	const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
	const a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	a.download = `sales-by-${activeTab.value}_${fromDate.value}_${toDate.value}.csv`;
	a.click();
	URL.revokeObjectURL(a.href);
}

const customerSearch = (search) =>
	call("stabler.api.sales.list_customers", {
		company: activeCompany.value,
		search,
		limit: 20,
	});

const itemSearch = (search) =>
	call("stabler.api.inventory.list_items", {
		search,
		item_group: itemGroup.value || undefined,
		limit: 20,
	});

function pickCustomer(row) {
	customer.value = row.name;
	customerDisplay.value = row.customer_name ? `${row.customer_name} · ${row.name}` : row.name;
}

function clearCustomer() {
	customer.value = "";
	customerDisplay.value = "";
}

function pickItem(row) {
	itemCode.value = row.item_code || row.name;
	itemDisplay.value = row.item_name ? `${row.item_name} · ${row.item_code || row.name}` : row.item_code || row.name;
}

function clearItem() {
	itemCode.value = "";
	itemDisplay.value = "";
}

async function loadItemGroups() {
	if (!activeCompany.value) return;
	try {
		itemGroups.value = await call("stabler.api.inventory.list_item_groups", { limit: 300 });
	} catch {
		itemGroups.value = [];
	}
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	clearDrilldown();
	const base = {
		company: activeCompany.value,
		from_date: fromDate.value,
		to_date: toDate.value,
		date_basis: dateBasis.value,
		include_drafts: includeDrafts.value ? 1 : 0,
	};
	let endpoint = "stabler.api.sales.sales_report_by_customer";
	const params = { ...base };
	if (activeTab.value === "customer" && customer.value) params.customer = customer.value;
	if (activeTab.value === "item") {
		endpoint = "stabler.api.sales.sales_report_by_item";
		if (itemGroup.value) params.item_group = itemGroup.value;
		if (itemCode.value) params.item_code = itemCode.value;
	}
	if (activeTab.value === "trend") {
		endpoint = "stabler.api.sales.sales_report_by_date";
		params.granularity = granularity.value;
	}
	if (activeTab.value === "salesperson") endpoint = "stabler.api.sales.sales_report_by_salesperson";
	if (activeTab.value === "orders") endpoint = "stabler.api.sales.sales_report_orders";
	try {
		rows.value = await call(endpoint, params);
	} catch (err) {
		error.value = err?.message || t("Failed to load sales report.");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

async function openCustomer(row) {
	if (activeTab.value !== "customer" || !row?.customer || drilldownLoading.value) return;
	drilldownCustomer.value = row;
	drilldownLoading.value = true;
	error.value = "";
	try {
		drilldownRows.value = await call("stabler.api.sales.sales_report_customer_invoices", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			customer: row.customer,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load customer invoices.");
		drilldownRows.value = [];
	} finally {
		drilldownLoading.value = false;
	}
}

function clearDrilldown() {
	drilldownCustomer.value = null;
	drilldownRows.value = [];
	drilldownLoading.value = false;
}

function openInvoice(name) {
	if (!name) return;
	router.push(`/sales/invoices/${encodeURIComponent(name)}`);
}

watch(activeCompany, () => {
	loadItemGroups();
	load();
});
watch(activeTab, () => {
	clearDrilldown();
	load();
});
watch(dateBasis, () => load());
watch(includeDrafts, () => load());

onMounted(() => {
	loadItemGroups();
	load();
});
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div>
				<div class="card-subtitle" :class="includeDrafts ? 'text-warning' : ''">{{ scopeNote }}</div>
				<h3 class="card-title mb-0">{{ title }}</h3>
			</div>
			<div class="card-actions">
				<button
					type="button"
					class="btn btn-sm btn-outline-secondary"
					:disabled="loading || !rows.length"
					@click="exportCsv"
				>
					<i class="ti ti-download me-1"></i>{{ t("Export") }}
				</button>
			</div>
		</div>
		<div class="card-body border-bottom">
			<div class="row g-2 align-items-end">
				<div class="col-12 col-md-3">
					<label class="form-label">{{ t("From") }}</label>
					<DateInput v-model="fromDate" size="sm" />
				</div>
				<div class="col-12 col-md-3">
					<label class="form-label">{{ t("To") }}</label>
					<DateInput v-model="toDate" size="sm" />
				</div>
				<div class="col-12 col-md-3">
					<label class="form-label">{{ t("Date basis") }}</label>
					<Select
						v-model="dateBasis"
						:options="[
							{ value: 'posting', label: t('Posting date') },
							{ value: 'due', label: t('Due date') },
						]"
						value-key="value"
						label-key="label"
						size="sm"
					/>
				</div>
				<div v-if="activeTab === 'customer'" class="col-12 col-md-3">
					<label class="form-label">{{ t("Customer") }}</label>
					<Typeahead
						v-model="customer"
						:search="customerSearch"
						:display="customerDisplay"
						:placeholder="t('All customers')"
						size="sm"
						:min-chars="0"
						open-on-focus
						@pick="pickCustomer"
						@clear="clearCustomer"
					>
						<template #option="{ item }">
							<div class="text-start">
								<div class="fw-medium">{{ item.customer_name || item.name }}</div>
								<div class="small text-secondary">{{ item.name }}</div>
							</div>
						</template>
					</Typeahead>
				</div>
				<div v-if="activeTab === 'item'" class="col-12 col-md-3">
					<label class="form-label">{{ t("Item Group") }}</label>
					<Select v-model="itemGroup" :options="itemGroupOptions" value-key="name" label-key="label" size="sm" />
				</div>
				<div v-if="activeTab === 'item'" class="col-12 col-md-3">
					<label class="form-label">{{ t("Item") }}</label>
					<Typeahead
						v-model="itemCode"
						:search="itemSearch"
						:display="itemDisplay"
						:placeholder="t('All items')"
						size="sm"
						:min-chars="0"
						open-on-focus
						@pick="pickItem"
						@clear="clearItem"
					>
						<template #option="{ item }">
							<div class="text-start">
								<div class="fw-medium">{{ item.item_name || item.item_code || item.name }}</div>
								<div class="small text-secondary">{{ item.item_code || item.name }}</div>
							</div>
						</template>
					</Typeahead>
				</div>
				<div v-if="activeTab === 'trend'" class="col-12 col-md-3">
					<label class="form-label">{{ t("Granularity") }}</label>
					<Select
						v-model="granularity"
						:options="[
							{ value: 'day', label: t('Day') },
							{ value: 'month', label: t('Month') },
						]"
						value-key="value"
						label-key="label"
						size="sm"
					/>
				</div>
				<div class="col-12 col-md-auto ms-md-auto d-flex align-items-end">
					<label class="form-check mb-2">
						<input class="form-check-input" type="checkbox" v-model="includeDrafts" />
						<span class="form-check-label">{{ t("Include drafts") }}</span>
					</label>
				</div>
				<div class="col-12 col-md-auto">
					<button class="btn btn-primary btn-sm w-100" :disabled="loading" @click="load">
						<span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-refresh me-1"></i>{{ t("Run") }}
					</button>
				</div>
			</div>
		</div>
		<div class="card-body py-2">
			<div class="nav nav-segmented">
				<button
					v-for="tab in tabs"
					:key="tab.key"
					type="button"
					class="nav-link"
					:class="{ active: activeTab === tab.key }"
					@click="activeTab = tab.key"
				>
					<i class="ti me-1" :class="tab.icon"></i>{{ tab.label }}
				</button>
			</div>
		</div>
		<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>
		<div v-else-if="drilldownCustomer" class="border-top">
			<div class="card-header bg-light">
				<div>
					<div class="card-subtitle">{{ t("Customer invoices") }}</div>
					<h3 class="card-title mb-0">
						{{ drilldownCustomer.customer_name || drilldownCustomer.customer }}
					</h3>
					<div class="text-secondary small">{{ drilldownCustomer.customer }}</div>
				</div>
				<div class="card-actions">
					<button type="button" class="btn btn-sm btn-outline-secondary" @click="clearDrilldown">
						<i class="ti ti-arrow-left me-1"></i>{{ t("Back to summary") }}
					</button>
				</div>
			</div>
			<div v-if="drilldownLoading" class="p-4 text-center text-secondary">
				<span class="spinner-border spinner-border-sm me-2"></span>{{ t("Loading invoices") }}
			</div>
			<div v-else-if="!drilldownRows.length" class="p-4">
				<EmptyState :title="t('No invoices found')" :subtitle="t('This customer has no submitted invoices for the selected period.')" />
			</div>
			<div v-else class="table-responsive">
				<table class="table table-vcenter card-table">
					<thead>
						<tr>
							<th>{{ t("Invoice") }}</th>
							<th>{{ t("Date") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Total") }}</th>
							<th class="text-end">{{ t("Outstanding") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="invoice in drilldownRows"
							:key="invoice.name"
							class="cursor-pointer"
							@click="openInvoice(invoice.name)"
						>
							<td>
								<button type="button" class="btn btn-link p-0 fw-medium">
									{{ invoice.name }}
								</button>
								<span v-if="invoice.is_return" class="badge bg-purple-lt ms-2">{{ t("Return") }}</span>
							</td>
							<td>{{ invoice.posting_date }}</td>
							<td>{{ invoice.status }}</td>
							<td class="text-end font-monospace">{{ formatMoney(invoice.grand_total, invoice.currency) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(invoice.outstanding_amount, invoice.currency) }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
		<div v-else-if="!loading && !rows.length" class="p-4">
			<EmptyState :title="t('No sales data found')" :subtitle="t('Adjust filters and run the report again.')" />
		</div>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr v-if="activeTab === 'customer'">
						<th>{{ t("Customer") }}</th>
						<th>{{ t("Currency") }}</th>
						<th class="text-end">{{ t("Invoices") }}</th>
						<th v-if="hasReturns" class="text-end">{{ t("Gross") }}</th>
						<th v-if="hasReturns" class="text-end">{{ t("Returns") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
						<th class="text-end">{{ t("Outstanding") }}</th>
						<th class="text-end">{{ t("COGS") }}</th>
						<th class="text-end">{{ t("Margin") }}</th>
						<th class="text-end">{{ t("Margin %") }}</th>
					</tr>
					<tr v-else-if="activeTab === 'item'">
						<th>{{ t("Item") }}</th>
						<th>{{ t("Group") }}</th>
						<th class="text-end">{{ t("Qty") }}</th>
						<th v-if="hasReturns" class="text-end">{{ t("Gross") }}</th>
						<th v-if="hasReturns" class="text-end">{{ t("Returns") }}</th>
						<th class="text-end">{{ t("Revenue") }}</th>
						<th class="text-end">{{ t("Invoices") }}</th>
						<th class="text-end">{{ t("COGS") }}</th>
						<th class="text-end">{{ t("Margin") }}</th>
						<th class="text-end">{{ t("Margin %") }}</th>
					</tr>
					<tr v-else-if="activeTab === 'trend'">
						<th>{{ t("Period") }}</th>
						<th>{{ t("Currency") }}</th>
						<th class="text-end">{{ t("Invoices") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
						<th class="text-end">{{ t("Outstanding") }}</th>
					</tr>
					<tr v-else-if="activeTab === 'salesperson'">
						<th>{{ t("Salesperson") }}</th>
						<th>{{ t("Currency") }}</th>
						<th class="text-end">{{ t("Invoices") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
					</tr>
					<tr v-else>
						<th>{{ t("Customer") }}</th>
						<th>{{ t("Currency") }}</th>
						<th class="text-end">{{ t("Orders") }}</th>
						<th class="text-end">{{ t("Booked") }}</th>
						<th class="text-end">{{ t("To deliver") }}</th>
						<th class="text-end">{{ t("To bill") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="row in rows"
						:key="JSON.stringify(row)"
						:class="{ 'cursor-pointer': activeTab === 'customer' }"
						@click="activeTab === 'customer' && openCustomer(row)"
					>
						<template v-if="activeTab === 'customer'">
							<td>
								<button type="button" class="btn btn-link p-0 fw-medium text-start">
									{{ row.customer_name || row.customer }}
								</button>
								<div class="text-muted small">{{ row.customer }}</div>
							</td>
							<td>{{ row.currency }}</td>
							<td class="text-end">{{ row.invoice_count }}</td>
							<td v-if="hasReturns" class="text-end font-monospace">{{ formatMoney(row.gross, row.currency) }}</td>
							<td v-if="hasReturns" class="text-end font-monospace" :class="Number(row.returns_amt) ? 'text-danger' : ''">{{ formatMoney(row.returns_amt, row.currency) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.total, row.currency) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.outstanding, row.currency) }}</td>
							<td class="text-end font-monospace text-secondary">{{ formatMoney(row.cogs, row.base_currency) }}</td>
							<td class="text-end font-monospace" :class="Number(row.margin) < 0 ? 'text-danger' : ''">{{ formatMoney(row.margin, row.base_currency) }}</td>
							<td class="text-end font-monospace" :class="Number(row.margin) < 0 ? 'text-danger' : ''">{{ fmtPct(row.margin_pct) }}</td>
						</template>
						<template v-else-if="activeTab === 'item'">
							<td>
								<div class="fw-medium">{{ row.item_name || row.item_code }}</div>
								<div class="text-muted small">{{ row.item_code }}</div>
							</td>
							<td>{{ row.item_group || "—" }}</td>
							<td class="text-end font-monospace">{{ Number(row.qty || 0).toLocaleString() }}</td>
							<td v-if="hasReturns" class="text-end font-monospace">{{ formatMoney(row.gross, row.currency) }}</td>
							<td v-if="hasReturns" class="text-end font-monospace" :class="Number(row.returns_amt) ? 'text-danger' : ''">{{ formatMoney(row.returns_amt, row.currency) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.revenue, row.currency) }}</td>
							<td class="text-end">{{ row.invoice_count }}</td>
							<td class="text-end font-monospace text-secondary">{{ formatMoney(row.cogs, row.base_currency) }}</td>
							<td class="text-end font-monospace" :class="Number(row.margin) < 0 ? 'text-danger' : ''">{{ formatMoney(row.margin, row.base_currency) }}</td>
							<td class="text-end font-monospace" :class="Number(row.margin) < 0 ? 'text-danger' : ''">{{ fmtPct(row.margin_pct) }}</td>
						</template>
						<template v-else-if="activeTab === 'trend'">
							<td class="fw-medium">{{ row.period }}</td>
							<td>{{ row.currency }}</td>
							<td class="text-end">{{ row.invoice_count }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.total, row.currency) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.outstanding, row.currency) }}</td>
						</template>
						<template v-else-if="activeTab === 'salesperson'">
							<td class="fw-medium">{{ row.sales_person }}</td>
							<td>{{ row.currency }}</td>
							<td class="text-end">{{ row.invoice_count }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.total, row.currency) }}</td>
						</template>
						<template v-else>
							<td>
								<div class="fw-medium">{{ row.customer_name || row.customer }}</div>
								<div class="text-muted small">{{ row.customer }}</div>
							</td>
							<td>{{ row.currency }}</td>
							<td class="text-end">{{ row.order_count }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.booked, row.currency) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.to_deliver, row.currency) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.to_bill, row.currency) }}</td>
						</template>
					</tr>
				</tbody>
				<tfoot v-if="totals" class="fw-bold">
					<tr v-if="activeTab === 'customer'">
						<td>{{ t("Total") }}</td>
						<td>{{ totals.oneCurrency ? totals.currency : "—" }}</td>
						<td class="text-end">{{ totals.invoice_count }}</td>
						<td v-if="hasReturns" class="text-end font-monospace">{{ fmtTotalMoney(totals.gross) }}</td>
						<td v-if="hasReturns" class="text-end font-monospace text-danger">{{ fmtTotalMoney(totals.returns_amt) }}</td>
						<td class="text-end font-monospace">{{ fmtTotalMoney(totals.total) }}</td>
						<td class="text-end font-monospace">{{ fmtTotalMoney(totals.outstanding) }}</td>
						<td class="text-end font-monospace text-secondary">{{ fmtBaseMoney(totals.cogs) }}</td>
						<td class="text-end font-monospace" :class="totals.margin < 0 ? 'text-danger' : ''">{{ fmtBaseMoney(totals.margin) }}</td>
						<td class="text-end font-monospace" :class="totals.margin < 0 ? 'text-danger' : ''">{{ fmtPct(totals.margin_pct) }}</td>
					</tr>
					<tr v-else-if="activeTab === 'item'">
						<td>{{ t("Total") }}</td>
						<td></td>
						<td class="text-end font-monospace">{{ Number(totals.qty || 0).toLocaleString() }}</td>
						<td v-if="hasReturns" class="text-end font-monospace">{{ fmtTotalMoney(totals.gross) }}</td>
						<td v-if="hasReturns" class="text-end font-monospace text-danger">{{ fmtTotalMoney(totals.returns_amt) }}</td>
						<td class="text-end font-monospace">{{ fmtTotalMoney(totals.revenue) }}</td>
						<td class="text-end">{{ totals.invoice_count }}</td>
						<td class="text-end font-monospace text-secondary">{{ fmtBaseMoney(totals.cogs) }}</td>
						<td class="text-end font-monospace" :class="totals.margin < 0 ? 'text-danger' : ''">{{ fmtBaseMoney(totals.margin) }}</td>
						<td class="text-end font-monospace" :class="totals.margin < 0 ? 'text-danger' : ''">{{ fmtPct(totals.margin_pct) }}</td>
					</tr>
					<tr v-else-if="activeTab === 'trend'">
						<td>{{ t("Total") }}</td>
						<td>{{ totals.oneCurrency ? totals.currency : "—" }}</td>
						<td class="text-end">{{ totals.invoice_count }}</td>
						<td class="text-end font-monospace">{{ fmtTotalMoney(totals.total) }}</td>
						<td class="text-end font-monospace">{{ fmtTotalMoney(totals.outstanding) }}</td>
					</tr>
					<tr v-else-if="activeTab === 'salesperson'">
						<td>{{ t("Total") }}</td>
						<td>{{ totals.oneCurrency ? totals.currency : "—" }}</td>
						<td class="text-end">{{ totals.invoice_count }}</td>
						<td class="text-end font-monospace">{{ fmtTotalMoney(totals.total) }}</td>
					</tr>
					<tr v-else>
						<td>{{ t("Total") }}</td>
						<td>{{ totals.oneCurrency ? totals.currency : "—" }}</td>
						<td class="text-end">{{ totals.order_count }}</td>
						<td class="text-end font-monospace">{{ fmtTotalMoney(totals.booked) }}</td>
						<td class="text-end font-monospace">{{ fmtTotalMoney(totals.to_deliver) }}</td>
						<td class="text-end font-monospace">{{ fmtTotalMoney(totals.to_bill) }}</td>
					</tr>
				</tfoot>
			</table>
		</div>
	</div>
</template>

<style scoped>
.cursor-pointer {
	cursor: pointer;
}
</style>
