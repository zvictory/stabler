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
import { useListSelection } from "../../composables/useListSelection.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import StatusBadge from "../../components/StatusBadge.vue";
import StatusIcon from "../../components/StatusIcon.vue";
import SelectionBar from "../../components/SelectionBar.vue";
import FilterChips from "../../components/FilterChips.vue";
import Pagination from "../../components/Pagination.vue";
import KpiCard from "../../components/KpiCard.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
const route = useRoute();

const search = ref(
	String(route.query.search || route.query.ci || route.query.commercial_invoice || "").trim()
);
const status = ref(String(route.query.status || "").trim());
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

// ---- row selection -------------------------------------------------------
// Client-side only: `scope` is the ticked rows when there is a selection and
// the whole page otherwise, so the cards and the footer sum one thing and can
// never disagree about what they are describing.
const { selected, isSelected, toggle, toggleAll, allSelected, clear, hasSelection, scope } =
	useListSelection(rows);

/** Column totals over the current scope — labelled in the footer. */
const totals = computed(() => {
	const acc = { kg: 0, cost: 0, receipts: 0, transit: 0, completed: 0 };
	for (const r of scope.value) {
		acc.kg += Number(r.total_kg) || 0;
		acc.cost += Number(r.transport_cost) || 0;
		acc.receipts += Number(r.receipt_count) || 0;
		// Mirrors truck_list_stats' SQL exactly — a badge that counts a
		// different set of statuses than the global one is worse than no badge.
		if (["DEPARTED_IRAN", "AT_BORDER", "CROSSED_BORDER", "IN_TRANSIT"].includes(r.status)) acc.transit += 1;
		if (["ARRIVED", "UNLOADING", "GRN_CREATED", "COMPLETED"].includes(r.status)) acc.completed += 1;
	}
	return acc;
});

const selCount = computed(() => selected.value.length);
// transport_cost is masked per row for users without cost visibility, exactly
// as the stats endpoint nulls its sum. Summing masked rows would report a hard
// zero, so that card (and the footer cell) stays global instead.
const costVisible = computed(() => !!stats.value && stats.value.transport_cost_sum != null);
const costGlobal = computed(() =>
	costVisible.value ? fm(stats.value.transport_cost_sum, statsCurrency.value) : "—"
);
const kgGlobal = computed(() => fn(stats.value ? stats.value.total_kg_sum : 0));
const countGlobal = computed(() => (stats.value ? stats.value.count : total.value));

// ---- filter chips --------------------------------------------------------
// Derived from the filter ref itself; removing the chip blanks it and the
// existing auto-apply watcher reloads. No second source of filter state.
const filterChips = computed(() =>
	status.value ? [{ key: "status", label: t(status.value), icon: "ti-flag" }] : []
);

function removeChip(key) {
	if (key === "status") status.value = "";
}

function clearFilters() {
	status.value = "";
}

function syncFromQuery() {
	const qSearch = String(route.query.search || route.query.ci || route.query.commercial_invoice || "").trim();
	const qStatus = String(route.query.status || "").trim();

	let changed = false;
	if (qSearch !== search.value) {
		search.value = qSearch;
		changed = true;
	}
	if (qStatus !== status.value) {
		status.value = qStatus;
		changed = true;
	}

	if (changed) {
		reload();
	}
}

onMounted(load);
watch(status, reload);
watch(() => route.query, syncFromQuery, { deep: true });
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, reload);
</script>

<template>
	<div>
		<!-- Metric Strip -->
		<div class="row row-deck row-cards mb-3">
			<div class="col-sm-6 col-lg-4">
				<KpiCard
					:label="t('Transport Cost Total')"
					:value="hasSelection && costVisible ? fm(totals.cost, statsCurrency) : costGlobal"
					icon="ti-file-dollar"
					tone="primary"
					:loading="statsLoading"
					:selected="costVisible ? selCount : 0"
					:global-value="costGlobal"
					:global-count="total"
				/>
			</div>
			<div class="col-sm-6 col-lg-4">
				<KpiCard
					:label="t('Total Weight Transported')"
					:value="hasSelection ? fn(totals.kg) : kgGlobal"
					unit="kg"
					icon="ti-scale"
					tone="azure"
					:loading="statsLoading"
					:selected="selCount"
					:global-value="kgGlobal"
					:global-count="total"
				/>
			</div>
			<div class="col-sm-6 col-lg-4">
				<KpiCard
					:label="t('Truck Fleet Active')"
					:value="hasSelection ? scope.length : countGlobal"
					icon="ti-truck"
					tone="purple"
					:loading="statsLoading"
					:selected="selCount"
					:global-value="countGlobal"
					:global-count="total"
					:badges="[
						{
							label: t('In Transit'),
							value: hasSelection ? totals.transit : stats ? stats.in_transit_count : 0,
							tone: 'warning',
						},
						{
							label: t('Completed'),
							value: hasSelection ? totals.completed : stats ? stats.completed_count : 0,
							tone: 'success',
						},
					]"
				/>
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
					<Select v-model="status" size="sm" :options="statusOptions" style="width: 170px" />
				</template>
			</ListToolbar>

			<FilterChips :chips="filterChips" @remove="removeChip" @clear="clearFilters" />
			<SelectionBar :count="selCount" :actions="[]" @clear="clear" />

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
							<th class="text-center" style="width: 36px">
								<input
									class="form-check-input m-0"
									type="checkbox"
									:checked="allSelected"
									:aria-label="t('Select all')"
									@click.stop
									@change="toggleAll"
								/>
							</th>
							<th class="d-none d-md-table-cell text-end text-secondary" style="width: 52px">{{ t("Row") }}</th>
							<th class="text-nowrap">{{ t("Truck / Plate") }}</th>
							<th>{{ t("Carrier & Driver") }}</th>
							<th>{{ t("CI & Warehouse") }}</th>
							<th class="text-nowrap">{{ t("Arrival / Dates") }}</th>
							<th class="text-end">{{ t("Weight (kg)") }}</th>
							<th class="text-end">{{ t("Transport Cost") }}</th>
							<th class="text-center">{{ t("Receipts") }}</th>
							<th class="text-end" style="width: 48px"></th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="6" :cols="10" />
					<tbody v-else>
						<tr
							v-for="(r, index) in rows"
							:key="r.name"
							style="cursor: pointer"
							:class="{ 'table-active': isSelected(r) }"
							@click="openForm(r.name)"
						>
							<!-- @click.stop on the cell keeps a stray click off the row's
							     openForm; the toggle itself hangs on @change only, so it
							     cannot fire twice and cancel itself. -->
							<td class="text-center" @click.stop>
								<input
									class="form-check-input m-0"
									type="checkbox"
									:checked="isSelected(r)"
									:aria-label="r.truck_number || r.name"
									@click.stop
									@change="toggle(r)"
								/>
							</td>
							<td class="d-none d-md-table-cell text-end font-monospace text-secondary truck-num">
								{{ limitStart + index + 1 }}
							</td>
							<td>
								<div class="d-flex align-items-center gap-1">
									<StatusIcon doctype="Import Truck" :status="r.status" />
									<span class="font-monospace text-primary fw-bold" style="font-size: 0.95rem">
										{{ r.truck_number || r.name }}
									</span>
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
							<td class="text-end">
								<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Quick view')" @click.stop="openDrawer(r.name)">
									<i class="ti ti-eye"></i>
								</button>
							</td>
						</tr>
					</tbody>
					<tfoot v-if="!loading && rows.length">
						<tr class="truck-totals">
							<td></td>
							<td class="d-none d-md-table-cell"></td>
							<td class="text-secondary">
								{{ scope.length }} {{ t("trucks") }}
								<div class="text-muted small">
									{{ hasSelection ? t("{count} selected", { count: selCount }) : t("this page only") }}
								</div>
							</td>
							<td colspan="3"></td>
							<td class="text-end font-monospace fw-bold text-nowrap">{{ fn(totals.kg) }} kg</td>
							<td class="text-end font-monospace fw-bold text-nowrap">
								<span v-if="!costVisible" class="text-secondary fw-normal">•••</span>
								<span v-else>{{ fm(totals.cost, statsCurrency) }}</span>
							</td>
							<td class="text-center font-monospace fw-bold">{{ fn(totals.receipts) }}</td>
							<td></td>
						</tr>
					</tfoot>
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

<style scoped>
.truck-num {
	font-variant-numeric: tabular-nums;
}

.truck-totals td {
	border-top: 2px solid var(--tblr-border-color);
	background: var(--tblr-bg-surface-secondary);
}
</style>
