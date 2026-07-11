<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
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
	} finally {
		loading.value = false;
	}
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

onMounted(load);
watch(status, reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, reload);
</script>

<template>
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
						<th class="text-nowrap">{{ t("Truck") }}</th>
						<th>{{ t("Carrier") }}</th>
						<th>{{ t("Warehouse") }}</th>
						<th class="text-nowrap">{{ t("Arrival") }}</th>
						<th class="text-end">{{ t("Weight (kg)") }}</th>
						<th class="text-end">{{ t("Transport cost") }}</th>
						<th class="text-center">{{ t("Receipts") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="text-end" style="width: 48px"></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="9" />
				<tbody v-else>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openForm(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.truck_number || r.name }}</td>
						<td>{{ r.trucking_company || "—" }}</td>
						<td class="small">{{ r.destination_warehouse || "—" }}</td>
						<td class="text-nowrap">{{ formatDate(r.actual_arrival || r.estimated_arrival) }}</td>
						<td class="text-end font-monospace">{{ Number(r.total_kg || 0).toFixed(0) }}</td>
						<td class="text-end font-monospace">
							<span v-if="masked(r.transport_cost)" class="text-secondary">•••</span>
							<span v-else>{{ formatMoney(r.transport_cost, r.transport_currency, user.language) }}</span>
						</td>
						<td class="text-center">{{ r.receipt_count || 0 }}</td>
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
	<div v-if="drawerOpen" class="offcanvas offcanvas-end show d-block" tabindex="-1" style="visibility: visible; width: 460px">
		<div class="offcanvas-header">
			<h2 class="offcanvas-title">{{ detail ? (detail.truck_number || detail.name) : t("Truck") }}</h2>
			<button type="button" class="btn-close" @click="closeDrawer"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-secondary">{{ t("Loading…") }}</div>
			<template v-else-if="detail">
				<div class="mb-3"><StatusBadge doctype="Import Truck" :status="detail.status" /></div>
				<dl class="row mb-2">
					<dt class="col-5 text-secondary">{{ t("Commercial Invoice") }}</dt><dd class="col-7 font-monospace">{{ detail.commercial_invoice || "—" }}</dd>
					<dt class="col-5 text-secondary">{{ t("Carrier") }}</dt><dd class="col-7">{{ detail.trucking_company || "—" }}</dd>
					<dt class="col-5 text-secondary">{{ t("Driver") }}</dt><dd class="col-7">{{ detail.driver_name || "—" }} <span class="text-secondary">{{ detail.driver_phone }}</span></dd>
					<dt class="col-5 text-secondary">{{ t("Warehouse") }}</dt><dd class="col-7">{{ detail.destination_warehouse || "—" }}</dd>
					<dt class="col-5 text-secondary">{{ t("Departure") }}</dt><dd class="col-7">{{ formatDate(detail.departure_date) }}</dd>
					<dt class="col-5 text-secondary">{{ t("Border crossing") }}</dt><dd class="col-7">{{ formatDate(detail.border_crossing_date) }}</dd>
					<dt class="col-5 text-secondary">{{ t("Arrival") }}</dt><dd class="col-7">{{ formatDate(detail.actual_arrival || detail.estimated_arrival) }}</dd>
					<dt class="col-5 text-secondary">{{ t("Cold chain") }}</dt><dd class="col-7 font-monospace">{{ detail.target_temp_min }}°C … {{ detail.target_temp_max }}°C</dd>
					<dt class="col-5 text-secondary">{{ t("Transport cost") }}</dt>
					<dd class="col-7 font-monospace">
						<span v-if="masked(detail.transport_cost)" class="text-secondary">•••</span>
						<span v-else>{{ formatMoney(detail.transport_cost, detail.transport_currency, user.language) }}</span>
					</dd>
					<dt class="col-5 text-secondary">{{ t("Transport PI") }}</dt><dd class="col-7 font-monospace">{{ detail.transport_purchase_invoice || "—" }}</dd>
				</dl>

				<h4 class="mt-3">{{ t("Truck receipts") }}</h4>
				<table class="table table-sm">
					<thead><tr><th>{{ t("Receipt") }}</th><th class="text-nowrap">{{ t("Arrival") }}</th><th>{{ t("PR") }}</th></tr></thead>
					<tbody>
						<tr v-for="rc in detail.receipts" :key="rc.name">
							<td class="font-monospace small">{{ rc.name }}</td>
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
</template>
