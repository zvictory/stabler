<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
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
const router = useRouter();

const search = ref("");
const status = ref("");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const total = ref(0);
const limitStart = ref(0);
const pageLength = ref(25);

// Metric strip state
const stats = ref(null);
const statsLoading = ref(false);

const detail = ref(null);
const detailLoading = ref(false);
const drawerOpen = ref(false);

const TRUCK_STATUSES = [
	"PENDING", "DEPARTED_IRAN", "AT_BORDER", "CROSSED_BORDER", "IN_TRANSIT",
	"ARRIVED", "UNLOADING", "GRN_CREATED", "COMPLETED", "Cancelled",
];
const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...TRUCK_STATUSES.map((s) => ({ value: s, label: t(s) })),
]);

const statsCurrencies = computed(() => [...new Set(rows.value.map((r) => r.transport_currency).filter(Boolean))]);
const statsCurrency = computed(() => (statsCurrencies.value.length === 1 ? statsCurrencies.value[0] : "USD"));

async function loadStats() {
	if (!activeCompany.value) return;
	statsLoading.value = true;
	try {
		stats.value = await call("stabler.api.imports.truck_list_stats", {
			company: activeCompany.value,
			status: status.value || undefined,
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
		const res = await importsApi.listImportTrucks({
			company: activeCompany.value,
			search: search.value || undefined,
			status: status.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
		});
		rows.value = res.rows || [];
		total.value = res.total_count || 0;
	} catch (err) {
		error.value = err?.message || t("Failed to load trucks.");
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
function openForm(name) {
	router.push("/imports/trucks/" + name);
}
function openCreate() {
	router.push("/imports/trucks/new");
}

async function openDrawer(name) {
	drawerOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await importsApi.getImportTruck(name);
	} catch (err) {
		error.value = err?.message || t("Failed to load the truck.");
		drawerOpen.value = false;
	} finally {
		detailLoading.value = false;
	}
}
function closeDrawer() {
	drawerOpen.value = false;
	detail.value = null;
}

const masked = (v) => v === null || v === undefined;
const fm = (v, ccy) => formatMoney(v, ccy || "USD", user.value?.language || "en");
const fn = (v) => Math.round(Number(v) || 0).toLocaleString("ru-RU");

onMounted(load);
watch(status, reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, reload);
</script>

<template>
	<div>
		<!-- Metric Strip -->
		<div class="row row-cards mb-3">
			<div class="col-sm-6 col-lg-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Transport Cost Total") }}</div>
						<div class="h2 mb-0 font-monospace text-primary fw-bold">
							<span v-if="statsLoading" class="placeholder col-6">&nbsp;</span>
							<span v-else>{{ stats && stats.transport_cost_sum != null ? fm(stats.transport_cost_sum, statsCurrency) : "—" }}</span>
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Total Weight Transported") }}</div>
						<div class="h2 mb-0 font-monospace text-azure fw-bold">
							<span v-if="statsLoading" class="placeholder col-6">&nbsp;</span>
							<span v-else>{{ fn(stats ? stats.total_kg_sum : 0) }} kg</span>
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Truck Fleet Active") }}</div>
						<div class="h2 mb-0 font-monospace">
							<span v-if="statsLoading" class="placeholder col-4">&nbsp;</span>
							<span v-else>{{ stats ? stats.count : total }}</span>
						</div>
						<div v-if="!statsLoading" class="text-secondary small mt-1">
							{{ t("In Transit") }}: <span class="font-monospace fw-semibold">{{ stats ? stats.in_transit_count : 0 }}</span> ·
							{{ t("Completed") }}: <span class="font-monospace fw-semibold">{{ stats ? stats.completed_count : 0 }}</span>
						</div>
					</div>
				</div>
			</div>
		</div>

		<div class="card">
			<ListToolbar
				v-model="search"
				:placeholder="t('Truck, driver or CI… ⌘K')"
				:count="total"
				:primary-label="t('New truck')"
				primary-icon="ti-plus"
				@search="reload"
				@primary-click="openCreate"
			>
				<template #filters>
					<Select v-model="status" size="sm" :options="statusOptions" style="width: 180px" />
				</template>
			</ListToolbar>

			<div v-if="error" class="card-body"><div class="alert alert-danger m-0">{{ error }}</div></div>
			<EmptyState
				v-else-if="!loading && !rows.length"
				icon="ti-truck"
				tone="purple"
				:title="t('No trucks')"
				:subtitle="t('Relax the filters to see trucks.')"
			/>
			<div v-else class="table-responsive">
				<table class="table table-vcenter card-table table-hover">
					<thead>
						<tr>
							<th class="text-nowrap">{{ t("Truck / Plate") }}</th>
							<th>{{ t("Carrier & Driver") }}</th>
							<th>{{ t("CI & Warehouse") }}</th>
							<th class="text-nowrap">{{ t("Arrival / Dates") }}</th>
							<th class="text-end">{{ t("Weight (kg)") }}</th>
							<th class="text-end">{{ t("Transport Cost") }}</th>
							<th class="text-center">{{ t("Receipts") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end" style="width: 48px"></th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="6" :cols="9" />
					<tbody v-else>
						<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openForm(r.name)">
							<td>
								<div class="font-monospace text-primary fw-bold" style="font-size: 0.95rem">
									<i class="ti ti-truck me-1"></i>{{ r.truck_number || r.name }}
								</div>
								<div v-if="r.truck_number && r.truck_number !== r.name" class="small text-secondary font-monospace">
									Ref: {{ r.name }}
								</div>
							</td>
							<td>
								<div class="fw-semibold text-dark">{{ r.trucking_company || "—" }}</div>
								<div v-if="r.driver_name" class="small text-secondary">
									{{ r.driver_name }} <span v-if="r.driver_phone">({{ r.driver_phone }})</span>
								</div>
							</td>
							<td>
								<div class="font-monospace fw-semibold text-primary">{{ r.commercial_invoice || "—" }}</div>
								<div class="small text-secondary"><i class="ti ti-building-warehouse me-1"></i>{{ r.destination_warehouse || "—" }}</div>
							</td>
							<td class="text-nowrap">
								<div class="fw-medium">{{ formatDate(r.actual_arrival || r.estimated_arrival) }}</div>
								<div v-if="r.departure_date" class="small text-secondary font-monospace">
									Dep: {{ formatDate(r.departure_date) }}
								</div>
							</td>
							<td class="text-end font-monospace fw-semibold text-nowrap">{{ fn(r.total_kg) }} kg</td>
							<td class="text-end font-monospace text-nowrap">
								<span v-if="masked(r.transport_cost)" class="text-secondary">•••</span>
								<span v-else class="fw-bold text-primary">{{ fm(r.transport_cost, r.transport_currency) }}</span>
							</td>
							<td class="text-center">
								<span class="badge bg-azure-lt font-monospace">{{ r.receipt_count || 0 }} Receipts</span>
							</td>
							<td><StatusBadge doctype="Import Truck" :status="r.status" /></td>
							<td class="text-end">
								<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Quick view')" @click.stop="openDrawer(r.name)">
									<i class="ti ti-eye"></i>
								</button>
							</td>
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

		<!-- Detail drawer (read-only) -->
		<div v-if="drawerOpen" class="offcanvas offcanvas-end show d-block" tabindex="-1" style="visibility: visible; width: 500px">
			<div class="offcanvas-header">
				<h2 class="offcanvas-title font-monospace"><i class="ti ti-truck me-2"></i>{{ detail ? (detail.truck_number || detail.name) : t("Truck") }}</h2>
				<button type="button" class="btn-close" @click="closeDrawer"></button>
			</div>
			<div class="offcanvas-body">
				<div v-if="detailLoading" class="text-secondary">{{ t("Loading…") }}</div>
				<template v-else-if="detail">
					<div class="mb-3"><StatusBadge doctype="Import Truck" :status="detail.status" /></div>
					<dl class="row mb-3">
						<dt class="col-5 text-secondary">{{ t("Commercial Invoice") }}</dt><dd class="col-7 font-monospace fw-bold text-primary">{{ detail.commercial_invoice || "—" }}</dd>
						<dt class="col-5 text-secondary">{{ t("Carrier / Transport") }}</dt><dd class="col-7 fw-semibold">{{ detail.trucking_company || "—" }}</dd>
						<dt class="col-5 text-secondary">{{ t("Driver") }}</dt><dd class="col-7">{{ detail.driver_name || "—" }} <span class="text-secondary">{{ detail.driver_phone }}</span></dd>
						<dt class="col-5 text-secondary">{{ t("Destination Warehouse") }}</dt><dd class="col-7">{{ detail.destination_warehouse || "—" }}</dd>
						<dt class="col-5 text-secondary">{{ t("Departure (Iran)") }}</dt><dd class="col-7">{{ formatDate(detail.departure_date) }}</dd>
						<dt class="col-5 text-secondary">{{ t("Border Crossing") }}</dt><dd class="col-7">{{ formatDate(detail.border_crossing_date) }}</dd>
						<dt class="col-5 text-secondary">{{ t("Arrival Date") }}</dt><dd class="col-7 fw-semibold">{{ formatDate(detail.actual_arrival || detail.estimated_arrival) }}</dd>
						<dt class="col-5 text-secondary">{{ t("Cold Chain Range") }}</dt><dd class="col-7 font-monospace text-azure fw-bold">{{ detail.target_temp_min }}°C … {{ detail.target_temp_max }}°C</dd>
						<dt class="col-5 text-secondary">{{ t("Transport Cost") }}</dt>
						<dd class="col-7 font-monospace fw-bold text-primary">
							<span v-if="masked(detail.transport_cost)" class="text-secondary">•••</span>
							<span v-else>{{ fm(detail.transport_cost, detail.transport_currency) }}</span>
						</dd>
						<dt class="col-5 text-secondary">{{ t("Transport PI Link") }}</dt><dd class="col-7 font-monospace">{{ detail.transport_purchase_invoice || "—" }}</dd>
					</dl>

					<h4 class="mt-3"><i class="ti ti-clipboard-check me-1"></i>{{ t("Truck Receipts & QC Inspection") }}</h4>
					<table class="table table-sm">
						<thead><tr><th>{{ t("Receipt Ref") }}</th><th class="text-nowrap">{{ t("Arrival") }}</th><th>{{ t("PR Reference") }}</th></tr></thead>
						<tbody>
							<tr v-for="rc in detail.receipts" :key="rc.name">
								<td class="font-monospace small fw-bold text-primary">{{ rc.name }}</td>
								<td class="text-nowrap">{{ formatDate(rc.arrival_date) }}</td>
								<td class="font-monospace small">{{ rc.purchase_receipt || "—" }}</td>
							</tr>
							<tr v-if="!detail.receipts.length"><td colspan="3" class="text-secondary text-center">{{ t("No receipts yet.") }}</td></tr>
						</tbody>
					</table>
				</template>
			</div>
		</div>
		<div v-if="drawerOpen" class="offcanvas-backdrop fade show" @click="closeDrawer"></div>
	</div>
</template>
