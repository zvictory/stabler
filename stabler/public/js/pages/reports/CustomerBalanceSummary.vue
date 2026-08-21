<script setup>
// Report Center: Customer Balance Summary — every customer's CURRENT receivable
// (all-time, all vouchers), period-independent. Same source as the Customer
// Center, so the numbers tie 1:1. QuickBooks-style A/R snapshot.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import ReportTable from "../../components/ReportTable.vue";
import MultiSelectPicker from "../../components/MultiSelectPicker.vue";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const onlyWithBalance = ref(1);
const customers = ref([]);
// Boş = canlı bakiye (bugüne kadar her şey). Bir tarih seçilince rapor aynı
// defteri o güne kadar oynatır ve Customer Center ile 1:1 tutma sözü bilerek
// düşer — `report.meta.basis` hangisine bakıldığını yazar.
const asOf = ref("");
const sortBy = ref("balance");
const sortDir = ref("desc");
const loading = ref(false);
const error = ref("");
const report = ref(null);
const lang = () => user.value?.language || "en";

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);
const detailCustomer = ref("");

const exportFilters = computed(() => ({
	company: activeCompany.value,
	only_with_balance: onlyWithBalance.value,
	customers: customers.value,
	sort_by: sortBy.value,
	sort_dir: sortDir.value,
	as_of: asOf.value,
}));
const detailExportFilters = computed(() => ({
	company: activeCompany.value,
	customer: detailCustomer.value,
}));

async function load() {
	if (!activeCompany.value) return;
	detailOpen.value = false;
	loading.value = true;
	error.value = "";
	try {
		report.value = await call("stabler.api.reports.customer_balance_summary", {
			company: activeCompany.value,
			only_with_balance: onlyWithBalance.value,
			customers: customers.value,
			sort_by: sortBy.value,
			sort_dir: sortDir.value,
			as_of: asOf.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load report.");
	} finally {
		loading.value = false;
	}
}

function onSort({ sort_by, sort_dir }) {
	sortBy.value = sort_by;
	sortDir.value = sort_dir;
	load();
}

async function onDrill({ row }) {
	detailCustomer.value = row.customer;
	detailOpen.value = true;
	detailLoading.value = true;
	try {
		detail.value = await call("stabler.api.reports.customer_balance_detail", {
			company: activeCompany.value,
			customer: row.customer,
		});
	} catch (err) {
		detail.value = null;
		error.value = err?.message || t("Failed to load detail.");
	} finally {
		detailLoading.value = false;
	}
}

onMounted(load);
</script>

<template>
	<div class="page-header mb-3">
		<div class="page-pretitle">{{ t("Reports") }}</div>
		<h2 class="page-title">{{ t("Customer Balance Summary") }}</h2>
	</div>

	<div class="d-flex align-items-center gap-2 flex-wrap mb-3">
		<label class="form-check form-switch m-0">
			<input
				class="form-check-input"
				type="checkbox"
				:checked="onlyWithBalance === 1"
				@change="onlyWithBalance = $event.target.checked ? 1 : 0; load()"
			/>
			<span class="form-check-label">{{ t("Only with balance") }}</span>
		</label>
		<MultiSelectPicker
			v-model="customers"
			search-api="stabler.api.sales.list_customers"
			:extra-params="{ company: activeCompany }"
			id-key="name"
			:display="(r) => r.customer_name || r.name"
			:placeholder="t('Customers')"
			:title="t('Customers')"
			size="sm"
			@update:model-value="load"
		/>
		<div class="ms-auto">
			<label class="form-label small mb-1">{{ t("As of") }}</label>
			<DateInput v-model="asOf" size="sm" @update:model-value="load" />
		</div>
		<button type="button" class="btn btn-sm btn-primary" :disabled="loading" @click="load">
			<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
		</button>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div v-if="report" class="card">
		<div class="card-body">
			<div v-if="report.meta?.basis" class="small fw-semibold mb-1">{{ report.meta.basis }}</div>
			<div v-if="report.meta?.note" class="text-secondary small mb-2">{{ report.meta.note }}</div>
			<ReportTable
				:columns="report.columns"
				:rows="report.rows"
				:totals="report.totals"
				:currency="report.meta?.currency || 'UZS'"
				:language="lang()"
				:loading="loading"
				export-name="customer_balance_summary"
				report-key="customer_balance_summary"
				:export-filters="exportFilters"
				server-sort
				:sort-by="sortBy"
				:sort-dir="sortDir"
				@sort="onSort"
				@drill="onDrill"
			/>
		</div>
	</div>

	<!-- Ledger drill -->
	<div v-if="detailOpen" class="card mt-3">
		<div class="card-header">
			<div class="card-title">
				<i class="ti ti-list me-1"></i>{{ t("Ledger") }} · {{ detail?.meta?.title || detailCustomer }}
			</div>
			<button type="button" class="btn btn-sm btn-ghost-secondary ms-auto" @click="detailOpen = false">
				<i class="ti ti-x"></i>
			</button>
		</div>
		<div class="card-body">
			<ReportTable
				v-if="detail"
				:columns="detail.columns"
				:rows="detail.rows"
				:totals="detail.totals"
				:currency="detail.meta?.currency || 'UZS'"
				:language="lang()"
				:loading="detailLoading"
				export-name="customer_ledger"
				report-key="customer_balance_detail"
				:export-filters="detailExportFilters"
			/>
			<div v-else-if="detailLoading" class="text-center py-3"><span class="spinner-border spinner-border-sm"></span></div>
		</div>
	</div>
</template>
