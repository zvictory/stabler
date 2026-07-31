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
const router = useRouter();
const route = useRoute();

const search = ref(
	String(route.query.search || route.query.ci || route.query.commercial_invoice || route.query.supplier || route.query.proforma || "").trim()
);
const status = ref(String(route.query.status || "").trim());
const blTypeFilter = ref(String(route.query.bl_type || "").trim());
const ciFilter = ref(String(route.query.ci_name || "").trim());
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

const CONTAINER_STATUSES = [
	"BOOKED", "STUFFED", "GATE_IN", "ON_BOARD", "IN_TRANSIT",
	"DISCHARGED", "AVAILABLE", "ARRIVED_AT_IRAN", "DELIVERED_TO_UZBEKISTAN", "Cancelled",
];

const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...CONTAINER_STATUSES.map((s) => ({ value: s, label: t(s) })),
]);

const blTypeOptions = computed(() => [
	{ value: "", label: t("All BL Types") },
	{ value: "ORIGINAL_BL", label: t("Original BL") },
	{ value: "MASTER_BL", label: t("Master BL") },
	{ value: "HOUSE_BL", label: t("House BL") },
	{ value: "TELEX_RELEASE", label: t("Telex Release") },
	{ value: "EXPRESS_BL", label: t("Express BL") },
]);

function formatBlType(val) {
	if (!val) return "";
	switch (val) {
		case "ORIGINAL_BL": return t("Original BL");
		case "MASTER_BL": return t("Master BL");
		case "HOUSE_BL": return t("House BL");
		case "TELEX_RELEASE": return t("Telex Release");
		case "EXPRESS_BL": return t("Express BL");
		default: return val;
	}
}

function blBadgeClass(val) {
	switch (val) {
		case "ORIGINAL_BL": return "bg-blue-lt text-blue";
		case "MASTER_BL": return "bg-azure-lt text-azure";
		case "HOUSE_BL": return "bg-purple-lt text-purple";
		case "TELEX_RELEASE": return "bg-green-lt text-green";
		case "EXPRESS_BL": return "bg-teal-lt text-teal";
		default: return "bg-secondary-lt text-secondary";
	}
}

async function loadStats() {
	if (!activeCompany.value) return;
	statsLoading.value = true;
	try {
		stats.value = await call("stabler.api.imports.container_list_stats", {
			company: activeCompany.value,
			status: status.value || undefined,
			bl_type: blTypeFilter.value || undefined,
			commercial_invoice: ciFilter.value || undefined,
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
		const res = await importsApi.listImportContainers({
			company: activeCompany.value,
			search: search.value || undefined,
			status: status.value || undefined,
			bl_type: blTypeFilter.value || undefined,
			commercial_invoice: ciFilter.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
		});
		rows.value = res.rows || [];
		total.value = res.total_count || 0;
	} catch (err) {
		error.value = err?.message || t("Failed to load containers.");
		rows.value = [];
	} finally {
		loading.value = false;
	}
	loadStats();
}

function vendorCode(r) {
	const s = (r && (r.supplier_name || r.supplier)) || "";
	return (s.split(/\s+/)[0] || "").toUpperCase();
}

function reload() {
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}
function openForm(name) {
	if (!name) return;
	router.push("/imports/containers/" + name);
}
function openCi(name) {
	if (!name) return;
	router.push("/imports/commercial-invoices/" + name);
}
function openPi(name) {
	if (!name) return;
	router.push("/imports/proformas/" + name);
}
function filterBySupplier(sup) {
	if (!sup) return;
	search.value = sup;
	reload();
}
function filterByTransporter(tr) {
	if (!tr) return;
	search.value = tr;
	reload();
}
function filterByBl(bl) {
	if (!bl) return;
	search.value = bl;
	reload();
}
function openCreate() {
	router.push("/imports/containers/new");
}
function openLedger(name) {
	router.push("/imports/containers/" + name + "/ledger");
}

async function openDrawer(name) {
	drawerOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await importsApi.getImportContainer(name);
	} catch (err) {
		error.value = err?.message || t("Failed to load the container.");
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

function onSearchChange(val) {
	search.value = val || "";
	router.replace({
		query: {
			...route.query,
			search: search.value || undefined,
		},
	});
}

function syncFromQuery() {
	const qSearch = String(route.query.search || route.query.ci || route.query.commercial_invoice || route.query.supplier || route.query.proforma || "").trim();
	const qStatus = String(route.query.status || "").trim();
	const qBlType = String(route.query.bl_type || "").trim();

	if (qSearch !== search.value) search.value = qSearch;
	if (qStatus !== status.value) status.value = qStatus;
	if (qBlType !== blTypeFilter.value) blTypeFilter.value = qBlType;
}

onMounted(() => {
	syncFromQuery();
	load();
});
watch([search, status, blTypeFilter, ciFilter], reload);
watch(() => route.query, syncFromQuery, { immediate: true, deep: true });
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, reload);
</script>

<template>
	<div>
		<!-- Metric Strip -->
		<div class="row row-cards mb-3">
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="d-flex align-items-center">
							<div class="subheader me-auto">{{ t("Total FCL (Containers)") }}</div>
							<div class="avatar bg-primary-lt text-primary rounded"><i class="ti ti-box-seam fs-2"></i></div>
						</div>
						<div class="h1 mb-0 font-monospace text-primary fw-bold">
							<span v-if="statsLoading" class="placeholder col-6">&nbsp;</span>
							<span v-else>{{ stats ? stats.count : total }}</span>
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="d-flex align-items-center">
							<div class="subheader me-auto">{{ t("Total Boxes") }}</div>
							<div class="avatar bg-orange-lt text-orange rounded"><i class="ti ti-package fs-2"></i></div>
						</div>
						<div class="h1 mb-0 font-monospace text-orange fw-bold">
							<span v-if="statsLoading" class="placeholder col-6">&nbsp;</span>
							<span v-else>{{ fn(stats ? stats.total_boxes_sum : 0) }}</span>
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="d-flex align-items-center">
							<div class="subheader me-auto">{{ t("Total Weight (KG)") }}</div>
							<div class="avatar bg-azure-lt text-azure rounded"><i class="ti ti-weight fs-2"></i></div>
						</div>
						<div class="h1 mb-0 font-monospace text-azure fw-bold">
							<span v-if="statsLoading" class="placeholder col-6">&nbsp;</span>
							<span v-else>{{ fn(stats ? stats.total_kg_sum : 0) }} <span class="fs-4 text-muted fw-normal">kg</span></span>
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="d-flex align-items-center">
							<div class="subheader me-auto">{{ t("Transit & Delivery") }}</div>
							<div class="avatar bg-green-lt text-green rounded"><i class="ti ti-truck-delivery fs-2"></i></div>
						</div>
						<div v-if="!statsLoading" class="mt-1">
							<span class="badge bg-warning-lt text-warning me-2"><i class="ti ti-transit me-1"></i>Transit: {{ stats ? stats.in_transit_count : 0 }}</span>
							<span class="badge bg-success-lt text-success"><i class="ti ti-check me-1"></i>Delivered: {{ stats ? stats.delivered_count : 0 }}</span>
						</div>
						<div v-else class="placeholder col-8">&nbsp;</div>
					</div>
				</div>
			</div>
		</div>

		<div class="card">
			<ListToolbar
				v-model="search"
				:placeholder="t('Container, CI, BL, vessel, supplier… ⌘K')"
				:count="total"
				:primary-label="t('New container')"
				primary-icon="ti-plus"
				@search="onSearchChange"
				@update:model-value="onSearchChange"
				@primary-click="openCreate"
			>
				<template #filters>
					<div class="d-flex align-items-center gap-2">
						<Select v-model="status" size="sm" :options="statusOptions" style="width: 170px" />
						<Select v-model="blTypeFilter" size="sm" :options="blTypeOptions" style="width: 150px" />
					</div>
				</template>
			</ListToolbar>

			<div v-if="error" class="card-body"><div class="alert alert-danger m-0">{{ error }}</div></div>
			<EmptyState
				v-else-if="!loading && !rows.length"
				icon="ti-box"
				tone="info"
				:title="t('No containers found')"
				:subtitle="t('Relax the search filters or add a new container.')"
			/>
			<div v-else class="table-responsive">
				<table class="table table-vcenter card-table table-hover align-middle">
					<thead>
						<tr>
							<th class="text-nowrap" style="min-width: 140px">{{ t("Container & Specs") }}</th>
							<th style="min-width: 170px">{{ t("CI / Vendor & PI") }}</th>
							<th style="min-width: 200px">{{ t("Transporter & Freight Cost") }}</th>
							<th style="min-width: 140px">{{ t("BL / Type") }}</th>
							<th style="min-width: 180px">{{ t("Vessel & Schedule") }}</th>
							<th style="min-width: 130px">{{ t("Status") }}</th>
							<th style="min-width: 160px">{{ t("Route") }}</th>
							<th class="text-end" style="min-width: 130px">{{ t("Weight & Boxes") }}</th>
							<th class="text-end" style="width: 100px">{{ t("Actions") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="6" :cols="9" />
					<tbody v-else>
						<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openForm(r.name)">
							<td>
								<div
									class="font-monospace text-primary fw-bold text-decoration-underline-hover"
									style="font-size: 0.95rem; cursor: pointer"
									:title="t('View container detail')"
									@click.stop="openForm(r.name)"
								>
									{{ r.container_number || r.name }}
								</div>
								<div class="mt-1 d-flex align-items-center gap-1">
									<span v-if="r.container_size" class="small text-secondary font-monospace badge bg-light text-dark">{{ r.container_size }}</span>
									<span v-if="r.seal_number" class="small font-monospace text-muted ms-1" :title="t('Seal Number')">
										<i class="ti ti-lock me-1"></i>{{ r.seal_number }}
									</span>
								</div>
							</td>
							<td>
								<div v-if="r.proforma_invoice" class="mb-1">
									<span
										class="badge bg-purple-lt font-monospace"
										style="font-size: 0.75rem; cursor: pointer"
										:title="t('Open Proforma Invoice: ') + r.proforma_invoice"
										@click.stop="openPi(r.proforma_invoice)"
									>
										<i class="ti ti-file-dollar me-1"></i>{{ r.proforma_invoice }}
									</span>
								</div>
								<div
									class="font-monospace fw-bold text-dark text-decoration-underline-hover"
									style="cursor: pointer"
									:title="t('Open Commercial Invoice: ') + (r.commercial_invoice || '')"
									@click.stop="openCi(r.commercial_invoice)"
								>
									<i class="ti ti-file-check me-1 text-primary"></i>{{ r.ci_number || r.commercial_invoice || "—" }}
								</div>
								<div class="mt-1">
									<span
										v-if="r.supplier_name || r.supplier"
										class="badge bg-secondary-lt text-dark font-monospace"
										style="font-size: 0.78rem; cursor: pointer"
										:title="t('Filter by supplier: ') + (r.supplier_name || r.supplier)"
										@click.stop="filterBySupplier(r.supplier || r.supplier_name)"
									>
										{{ vendorCode(r) }}
									</span>
									<span v-else class="text-secondary small">—</span>
								</div>
							</td>
							<td>
								<div
									class="d-flex align-items-center gap-1 font-monospace fw-bold text-dark"
									:style="{ cursor: r.transporter ? 'pointer' : 'default' }"
									:title="r.transporter ? t('Filter by transporter: ') + r.transporter : ''"
									@click.stop="r.transporter && filterByTransporter(r.transporter)"
								>
									<i class="ti ti-truck text-primary me-1"></i>
									<span v-if="r.transporter" class="text-decoration-underline-hover">{{ r.transporter }}</span>
									<span v-else class="text-muted fw-normal opacity-50">— {{ t("No Transporter") }}</span>
								</div>
								<div class="mt-1 d-flex align-items-center gap-2 text-nowrap">
									<span v-if="r.transport_cost > 0" class="font-monospace fw-bold text-success fs-3">
										{{ fm(r.transport_cost, r.transport_currency) }}
									</span>
									<span v-else class="text-muted small opacity-50">—</span>
									<span v-if="r.vehicle_number" class="badge bg-light text-muted font-monospace small" :title="t('Vehicle / Truck')">
										<i class="ti ti-steering-wheel me-1"></i>{{ r.vehicle_number }}
									</span>
								</div>
								<div v-if="r.transport_cost > 0" class="mt-1 font-monospace small">
									<span v-if="(r.paid_cash + r.paid_bank) >= r.transport_cost" class="badge bg-success-lt text-success">
										<i class="ti ti-check me-1"></i>{{ t("Paid") }}
									</span>
									<span v-else class="badge bg-warning-lt text-warning">
										{{ t("Paid") }}: {{ fm(r.paid_cash + r.paid_bank, r.transport_currency) }}
									</span>
								</div>
							</td>
							<td>
								<div
									class="font-monospace fw-semibold text-dark"
									:style="{ cursor: r.bl_number ? 'pointer' : 'default' }"
									:title="r.bl_number ? t('Filter by BL: ') + r.bl_number : ''"
									@click.stop="r.bl_number && filterByBl(r.bl_number)"
								>
									{{ r.bl_number || "—" }}
								</div>
								<div v-if="r.bl_type" class="mt-1">
									<span class="badge" :class="blBadgeClass(r.bl_type)" style="font-size: 0.7rem">
										{{ formatBlType(r.bl_type) }}
									</span>
								</div>
							</td>
							<td>
								<div class="fw-semibold text-dark text-nowrap" :title="r.vessel || ''">
									<i class="ti ti-ship me-1 text-secondary"></i>{{ r.vessel || "—" }}
									<span v-if="r.voyage" class="small text-muted font-monospace ms-1">/ {{ r.voyage }}</span>
								</div>
								<div class="small text-secondary font-monospace text-nowrap mt-1">
									<span>ETD: {{ r.etd ? formatDate(r.etd) : "—" }}</span> · 
									<span>ETA: {{ formatDate(r.eta || r.eta_transit_port) || "—" }}</span>
								</div>
								<div v-if="r.cut_off || r.gate_open" class="small text-muted font-monospace text-nowrap mt-1">
									<span v-if="r.cut_off">Cut Off: {{ formatDate(r.cut_off) }}</span>
									<span v-if="r.gate_open" class="ms-2">Open: {{ formatDate(r.gate_open) }}</span>
								</div>
							</td>
							<td>
								<StatusBadge doctype="Import Container" :status="r.status" />
							</td>
							<td>
								<div v-if="r.port_of_loading || r.port_of_discharge" class="small font-monospace text-nowrap">
									<span class="fw-semibold text-dark">{{ r.port_of_loading || "—" }}</span>
									<i class="ti ti-arrow-right mx-1 text-primary"></i>
									<span class="fw-semibold text-dark">{{ r.port_of_discharge || "—" }}</span>
								</div>
								<div v-else class="text-secondary small">—</div>
							</td>
							<td class="text-end text-nowrap">
								<div class="font-monospace fw-bold text-azure">{{ fn(r.total_kg) }} <span class="small font-monospace text-muted">kg</span></div>
								<div class="font-monospace text-orange small mt-1">{{ fn(r.total_boxes) }} <span class="small font-monospace text-muted">bx</span></div>
							</td>
							<td class="text-end text-nowrap" @click.stop>
								<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Cost ledger')" @click="openLedger(r.name)">
									<i class="ti ti-report-money"></i>
								</button>
								<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm ms-1" :title="t('Quick view')" @click="openDrawer(r.name)">
									<i class="ti ti-eye"></i>
								</button>
								<button type="button" class="btn btn-ghost-primary btn-icon btn-sm ms-1" :title="t('Edit container')" @click="openForm(r.name)">
									<i class="ti ti-pencil"></i>
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
		<div v-if="drawerOpen" class="offcanvas offcanvas-end show d-block" tabindex="-1" style="visibility: visible; width: 520px">
			<div class="offcanvas-header">
				<h2 class="offcanvas-title font-monospace">{{ detail ? (detail.container_number || detail.name) : t("Container") }}</h2>
				<button type="button" class="btn-close" @click="closeDrawer"></button>
			</div>
			<div class="offcanvas-body">
				<div v-if="detailLoading" class="text-secondary">{{ t("Loading…") }}</div>
				<template v-else-if="detail">
					<div class="mb-3 d-flex align-items-center gap-2">
						<StatusBadge doctype="Import Container" :status="detail.status" />
						<span v-if="detail.bl_type" class="badge" :class="blBadgeClass(detail.bl_type)">{{ formatBlType(detail.bl_type) }}</span>
					</div>
					<dl class="row mb-3">
						<dt class="col-5 text-secondary">{{ t("Commercial Invoice") }}</dt><dd class="col-7 font-monospace fw-bold text-primary">{{ detail.commercial_invoice || "—" }}</dd>
						<dt class="col-5 text-secondary">{{ t("Supplier") }}</dt><dd class="col-7">{{ detail.supplier || "—" }}</dd>
						<dt class="col-5 text-secondary">{{ t("Type / size") }}</dt><dd class="col-7">{{ detail.container_type }} · {{ detail.container_size || "40ft" }}</dd>
						<dt class="col-5 text-secondary">{{ t("Seal number") }}</dt><dd class="col-7 font-monospace">{{ detail.seal_number || "—" }}</dd>
						<dt class="col-5 text-secondary">{{ t("Gate-in date") }}</dt><dd class="col-7">{{ formatDate(detail.gate_in_date) }}</dd>
						<dt class="col-5 text-secondary">{{ t("Total weight (kg)") }}</dt><dd class="col-7 font-monospace fw-semibold">{{ fn(detail.total_kg) }} kg</dd>
						<dt class="col-5 text-secondary">{{ t("Total boxes") }}</dt><dd class="col-7 font-monospace">{{ fn(detail.total_boxes) }} bx</dd>
						<dt class="col-5 text-secondary">{{ t("Cost total") }}</dt>
						<dd class="col-7 font-monospace fw-bold text-primary">
							<span v-if="masked(detail.total_amount)" class="text-secondary">•••</span>
							<span v-else>{{ fm(detail.total_amount, detail.currency) }}</span>
						</dd>
						<dt class="col-5 text-secondary">{{ t("70% Payment Entry") }}</dt><dd class="col-7 font-monospace">{{ detail.advance_70_payment_entry || "—" }}</dd>
					</dl>

					<h4 class="mt-3"><i class="ti ti-list-details me-1"></i>{{ t("Items Shipped") }}</h4>
					<table class="table table-sm">
						<thead><tr><th>{{ t("Item") }}</th><th class="text-end">{{ t("Boxes") }}</th><th class="text-end">{{ t("Kg") }}</th></tr></thead>
						<tbody>
							<tr v-for="(it, i) in detail.items" :key="i">
								<td class="small">{{ it.item_name || it.item_code }}</td>
								<td class="text-end font-monospace">{{ fn(it.box_qty) }}</td>
								<td class="text-end font-monospace">{{ fn(it.total_kg) }}</td>
							</tr>
							<tr v-if="!detail.items.length"><td colspan="3" class="text-secondary text-center">{{ t("No items.") }}</td></tr>
						</tbody>
					</table>

					<h4 class="mt-3"><i class="ti ti-receipt me-1"></i>{{ t("Landed Cost Lines") }}</h4>
					<table class="table table-sm">
						<thead><tr><th>{{ t("Component") }}</th><th class="text-end">{{ t("Amount") }}</th></tr></thead>
						<tbody>
							<tr v-for="(cl, i) in detail.cost_lines" :key="i">
								<td class="small">{{ cl.cost_component }}</td>
								<td class="text-end font-monospace">
									<span v-if="masked(cl.amount)" class="text-secondary">•••</span>
									<span v-else>{{ fm(cl.amount, cl.currency) }}</span>
								</td>
							</tr>
							<tr v-if="!detail.cost_lines.length"><td colspan="2" class="text-secondary text-center">{{ t("No cost lines.") }}</td></tr>
						</tbody>
					</table>
				</template>
			</div>
		</div>
		<div v-if="drawerOpen" class="offcanvas-backdrop fade show" @click="closeDrawer"></div>
	</div>
</template>
