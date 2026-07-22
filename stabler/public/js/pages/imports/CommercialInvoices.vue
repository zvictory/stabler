<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import StatusBadge from "../../components/StatusBadge.vue";
import Pagination from "../../components/Pagination.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();

const search = ref("");
const status = ref(route.query.status ? String(route.query.status) : "");
const supplier = ref("");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const suppliers = ref([]);
const total = ref(0);
const limitStart = ref(0);
const pageLength = ref(25);

// Stats strip state
const stats = ref(null);
const statsLoading = ref(false);

const CI_STATUSES = [
	"BOOKED",
	"STUFFED",
	"GATE_IN",
	"ON_BOARD",
	"IN_TRANSIT",
	"DISCHARGED",
	"AVAILABLE",
	"ARRIVED_AT_IRAN",
	"DELIVERED_TO_UZBEKISTAN",
	"Cancelled",
];

const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...CI_STATUSES.map((s) => ({ value: s, label: t(s) })),
]);
const supplierOptions = computed(() => [
	{ value: "", label: t("All suppliers") },
	...suppliers.value.map((s) => ({ value: s.name, label: s.supplier_name || s.name })),
]);

const statsCurrencies = computed(() => [...new Set(rows.value.map((r) => r.currency).filter(Boolean))]);
const statsCurrency = computed(() => (statsCurrencies.value.length === 1 ? statsCurrencies.value[0] : "USD"));

async function loadStats() {
	if (!activeCompany.value) return;
	statsLoading.value = true;
	try {
		stats.value = await call("stabler.api.imports.commercial_invoice_list_stats", {
			company: activeCompany.value,
			status: status.value || undefined,
			supplier: supplier.value || undefined,
			search: search.value || undefined,
		});
	} catch (_err) {
		stats.value = null;
	} finally {
		statsLoading.value = false;
	}
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await importsApi.listCommercialInvoices({
			company: activeCompany.value,
			search: search.value || undefined,
			status: status.value || undefined,
			supplier: supplier.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
		});
		rows.value = res.rows || [];
		total.value = res.total_count || 0;
	} catch (err) {
		error.value = err?.message || t("Failed to load commercial invoices.");
		rows.value = [];
	} finally {
		loading.value = false;
	}
	loadStats();
}

function reload() {
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}

async function loadSuppliers() {
	if (!activeCompany.value) return;
	try {
		suppliers.value = await call("stabler.api.imports.import_suppliers", {
			company: activeCompany.value,
		});
	} catch (_) {
		suppliers.value = [];
	}
}

function openDetail(name) {
	router.push("/imports/commercial-invoices/" + name);
}
function openCreate() {
	router.push("/imports/commercial-invoices/new");
}

const fm = (v, ccy) => formatMoney(v, ccy || "USD", user.value?.language || "en");
const fn = (v) => Math.round(Number(v) || 0).toLocaleString("ru-RU");

onMounted(() => {
	loadSuppliers();
	load();
});
watch([status, supplier], reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, () => {
	loadSuppliers();
	reload();
});
</script>

<template>
	<div>
		<!-- Metric Strip -->
		<div class="row row-cards mb-3">
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Agreed total") }}</div>
						<div class="h2 mb-0 font-monospace text-primary fw-bold">
							<span v-if="statsLoading" class="placeholder col-6">&nbsp;</span>
							<span v-else>{{ fm(stats && stats.agreed_total_sum, statsCurrency) }}</span>
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Docs total") }}</div>
						<div class="h2 mb-0 font-monospace text-azure fw-bold">
							<span v-if="statsLoading" class="placeholder col-6">&nbsp;</span>
							<span v-else>{{ stats && stats.docs_total_sum != null ? fm(stats.docs_total_sum, statsCurrency) : "—" }}</span>
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Cash Difference") }}</div>
						<div class="h2 mb-0 font-monospace text-warning fw-bold">
							<span v-if="statsLoading" class="placeholder col-6">&nbsp;</span>
							<span v-else>{{ stats && stats.cash_difference_sum != null ? fm(stats.cash_difference_sum, statsCurrency) : "—" }}</span>
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Commercial Invoices") }}</div>
						<div class="h2 mb-0 font-monospace">
							<span v-if="statsLoading" class="placeholder col-4">&nbsp;</span>
							<span v-else>{{ stats ? stats.count : total }}</span>
						</div>
						<div v-if="!statsLoading" class="text-secondary small mt-1">
							{{ t("Transit") }}: <span class="font-monospace fw-semibold">{{ stats ? stats.in_transit_count : 0 }}</span> ·
							{{ t("Delivered") }}: <span class="font-monospace fw-semibold">{{ stats ? stats.delivered_count : 0 }}</span>
						</div>
					</div>
				</div>
			</div>
		</div>

		<div class="card">
			<ListToolbar
				v-model="search"
				:placeholder="t('CI number or supplier… ⌘K')"
				:count="total"
				:primary-label="t('New commercial invoice')"
				primary-icon="ti-plus"
				@search="reload"
				@primary-click="openCreate"
			>
				<template #filters>
					<div class="d-flex align-items-center gap-2">
						<Select v-model="status" size="sm" :options="statusOptions" style="width: 180px" />
						<Select v-model="supplier" size="sm" :options="supplierOptions" style="width: 200px" />
					</div>
				</template>
			</ListToolbar>

			<div v-if="error" class="card-body">
				<div class="alert alert-danger m-0">{{ error }}</div>
			</div>
			<EmptyState
				v-else-if="!loading && !rows.length"
				icon="ti-file-invoice"
				accentIcon="ti-plus"
				tone="primary"
				:title="t('No commercial invoices')"
				:subtitle="t('Relax the filters or create a new commercial invoice.')"
			/>
			<div v-else class="table-responsive">
				<table class="table table-vcenter card-table table-hover">
					<thead>
						<tr>
							<th>{{ t("CI Number & Exporter") }}</th>
							<th class="text-nowrap">{{ t("Date") }}</th>
							<th>{{ t("Incoterm & Logistics") }}</th>
							<th class="text-end">{{ t("Boxes & Weight") }}</th>
							<th class="text-end">{{ t("Pricing") }}</th>
							<th class="text-center">{{ t("Containers / GRN") }}</th>
							<th>{{ t("Status") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="6" :cols="7" />
					<tbody v-else>
						<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
							<td>
								<!-- Main Title: CI Number (e.g. MH/3054/2025-26) -->
								<div class="fw-bold text-primary font-monospace" style="font-size: 0.95rem">
									{{ r.ci_number || r.name }}
								</div>
								<div class="fw-semibold text-dark text-uppercase small mt-1">
									{{ r.supplier_name || r.supplier }}
								</div>
								<div v-if="r.ci_number && r.ci_number !== r.name" class="small text-secondary font-monospace">
									Ref: {{ r.name }}
								</div>
							</td>
							<td class="text-nowrap fw-medium">{{ r.ci_date ? formatDate(r.ci_date) : "—" }}</td>
							<td>
								<div v-if="r.incoterm" class="badge bg-secondary-lt mb-1">{{ r.incoterm }}</div>
								<div v-if="r.eta_transit_port" class="text-secondary small font-monospace">
									Transit ETA: {{ formatDate(r.eta_transit_port) }}
								</div>
							</td>
							<td class="text-end text-nowrap">
								<div class="fw-semibold font-monospace">{{ fn(r.total_boxes) }} <span class="text-secondary small">bx</span></div>
								<div class="text-secondary small font-monospace">{{ fn(r.total_kg) }} kg</div>
							</td>
							<td class="text-end text-nowrap">
								<div class="fw-bold font-monospace text-primary" style="font-size: 0.95rem">
									{{ fm(r.agreed_total, r.currency) }}
								</div>
								<div v-if="r.docs_total != null" class="text-secondary small font-monospace">
									{{ t("Docs") }}: {{ fm(r.docs_total, r.currency) }}
								</div>
								<span v-if="r.cash_difference" class="badge bg-warning-lt text-warning font-monospace mt-1">
									+{{ fm(r.cash_difference, r.currency) }}
								</span>
							</td>
							<td class="text-center">
								<div class="badge bg-azure-lt font-monospace mb-1">
									<i class="ti ti-box me-1"></i>{{ r.container_count || 0 }} Containers
								</div>
								<div>
									<span v-if="r.has_grn" class="badge bg-green-lt text-green"><i class="ti ti-check me-1"></i>GRN Created</span>
									<span v-else class="text-secondary small">—</span>
								</div>
							</td>
							<td><StatusBadge doctype="Commercial Invoice" :status="r.status" /></td>
						</tr>
					</tbody>
				</table>
			</div>
			<Pagination
				v-if="!error && total > 0"
				v-model:limit-start="limitStart"
				v-model:page-length="pageLength"
				:total="total"
				:page-count="rows.length"
			/>
		</div>
	</div>
</template>
