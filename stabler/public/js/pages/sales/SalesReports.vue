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

const session = useSession();
const { activeCompany } = storeToRefs(session);
const router = useRouter();

const today = new Date().toISOString().slice(0, 10);
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
	return t("Sales by Salesperson");
});

const tabs = [
	{ key: "customer", label: t("Customer"), icon: "ti-users" },
	{ key: "item", label: t("Item"), icon: "ti-ice-cream-2" },
	{ key: "trend", label: t("Trend"), icon: "ti-chart-line" },
	{ key: "salesperson", label: t("Salesperson"), icon: "ti-user-dollar" },
];

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

onMounted(() => {
	loadItemGroups();
	load();
});
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div>
				<div class="card-subtitle">{{ t("Submitted Sales Invoices only") }}</div>
				<h3 class="card-title mb-0">{{ title }}</h3>
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
				<div class="col-12 col-md-auto ms-md-auto">
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
						<th class="text-end">{{ t("Total") }}</th>
						<th class="text-end">{{ t("Outstanding") }}</th>
					</tr>
					<tr v-else-if="activeTab === 'item'">
						<th>{{ t("Item") }}</th>
						<th>{{ t("Group") }}</th>
						<th class="text-end">{{ t("Qty") }}</th>
						<th class="text-end">{{ t("Revenue") }}</th>
						<th class="text-end">{{ t("Invoices") }}</th>
					</tr>
					<tr v-else-if="activeTab === 'trend'">
						<th>{{ t("Period") }}</th>
						<th>{{ t("Currency") }}</th>
						<th class="text-end">{{ t("Invoices") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
						<th class="text-end">{{ t("Outstanding") }}</th>
					</tr>
					<tr v-else>
						<th>{{ t("Salesperson") }}</th>
						<th>{{ t("Currency") }}</th>
						<th class="text-end">{{ t("Invoices") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
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
							<td class="text-end font-monospace">{{ formatMoney(row.total, row.currency) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.outstanding, row.currency) }}</td>
						</template>
						<template v-else-if="activeTab === 'item'">
							<td>
								<div class="fw-medium">{{ row.item_name || row.item_code }}</div>
								<div class="text-muted small">{{ row.item_code }}</div>
							</td>
							<td>{{ row.item_group || "—" }}</td>
							<td class="text-end font-monospace">{{ Number(row.qty || 0).toLocaleString() }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.revenue, row.currency) }}</td>
							<td class="text-end">{{ row.invoice_count }}</td>
						</template>
						<template v-else-if="activeTab === 'trend'">
							<td class="fw-medium">{{ row.period }}</td>
							<td>{{ row.currency }}</td>
							<td class="text-end">{{ row.invoice_count }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.total, row.currency) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.outstanding, row.currency) }}</td>
						</template>
						<template v-else>
							<td class="fw-medium">{{ row.sales_person }}</td>
							<td>{{ row.currency }}</td>
							<td class="text-end">{{ row.invoice_count }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.total, row.currency) }}</td>
						</template>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>

<style scoped>
.cursor-pointer {
	cursor: pointer;
}
</style>
