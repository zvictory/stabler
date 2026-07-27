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

const search = ref(
	route.query.search
		? String(route.query.search)
		: route.query.proforma
		? String(route.query.proforma)
		: route.query.proforma_invoice
		? String(route.query.proforma_invoice)
		: ""
);
const status = ref(route.query.status ? String(route.query.status) : "");
const supplier = ref("");
const groupFilter = ref("");
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

// ---- PI Groups (filter + per-row badge) — mirrors ProformaInvoices.vue ----
// The CI carries its own import_pi_group link and it is authoritative: a CI may
// sit in a different group than the proforma it was raised from, so neither the
// badge nor the filter derives the group through the PI.
const piGroups = ref([]);
const groupOptions = computed(() => [
	{ value: "", label: t("All PI groups") },
	...piGroups.value.map((g) => ({ value: g.name, label: g.title || g.name })),
]);
const groupsByName = computed(() => {
	const m = {};
	for (const g of piGroups.value) m[g.name] = g.title || g.name;
	return m;
});
function groupLabel(row) {
	if (!row) return "";
	return (
		row.pi_group_code ||
		row.pi_group_title ||
		groupsByName.value[row.import_pi_group] ||
		row.import_pi_group ||
		""
	);
}

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
			group: groupFilter.value || undefined,
		});
	} catch (_err) {
		stats.value = null;
	} finally {
		statsLoading.value = false;
	}
}

// ---- sorting -------------------------------------------------------------
// Server-side: this list is paginated, so sorting the rows already on screen
// would reorder one slice and read as the full ordering.
const SORTABLE = [
	"ci_date",
	"ci_number",
	"supplier",
	"eta",
	"total_boxes",
	"total_kg",
	"agreed_total",
	"cash_difference",
	"container_count",
	"status",
];
const sortBy = ref("ci_date");
const sortDir = ref("desc");

function toggleSort(key) {
	if (!SORTABLE.includes(key)) return;
	if (sortBy.value === key) {
		sortDir.value = sortDir.value === "asc" ? "desc" : "asc";
	} else {
		sortBy.value = key;
		sortDir.value = ["ci_number", "supplier", "status"].includes(key) ? "asc" : "desc";
	}
	reload();
}

function sortIcon(key) {
	if (sortBy.value !== key) return "";
	return sortDir.value === "asc" ? "ti-arrow-narrow-up" : "ti-arrow-narrow-down";
}

/** Short vendor code — the full legal name is noise in a dense table. */
function vendorCode(r) {
	const s = (r && (r.supplier_name || r.supplier)) || "";
	return (s.split(/\s+/)[0] || "").toUpperCase();
}

/** Days until ETA; negative once the date has passed. */
function etaDays(r) {
	if (!r.eta_transit_port) return null;
	const d = new Date(r.eta_transit_port + "T00:00:00");
	if (Number.isNaN(d.getTime())) return null;
	return Math.round((d.getTime() - Date.now()) / 86400000);
}

/** Overdue is red, arriving within a week is amber, anything further is quiet. */
function etaClass(r) {
	const d = etaDays(r);
	if (d === null) return "text-muted";
	if (d < 0) return "text-danger";
	if (d <= 7) return "text-warning";
	return "text-muted";
}

function docsGap(r) {
	return Number(r.cash_difference) || 0;
}

/** Column totals for the current page — labelled as such in the footer. */
const totals = computed(() => {
	const acc = { boxes: 0, kg: 0, agreed: 0, gap: 0, containers: 0, trucks: 0, grn: 0, vendors: new Set() };
	for (const r of rows.value) {
		acc.boxes += Number(r.total_boxes) || 0;
		acc.kg += Number(r.total_kg) || 0;
		acc.agreed += Number(r.agreed_total) || 0;
		acc.gap += Number(r.cash_difference) || 0;
		acc.containers += Number(r.container_count) || 0;
		acc.trucks += Number(r.truck_count) || 0;
		if (r.has_grn) acc.grn += 1;
		if (r.supplier) acc.vendors.add(r.supplier);
	}
	return acc;
});

const totalsCurrency = computed(() => (statsCurrencies.value.length === 1 ? statsCurrencies.value[0] : ""));

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
			group: groupFilter.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
			sort_by: sortBy.value,
			sort_dir: sortDir.value,
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

async function loadPiGroups() {
	if (!activeCompany.value) return;
	try {
		piGroups.value = await call("stabler.api.imports.list_pi_groups", {
			company: activeCompany.value,
		});
	} catch (_) {
		piGroups.value = [];
	}
}

function openDetail(name) {
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
function openContainersForCi(row) {
	if (!row) return;
	const query = row.ci_number || row.name;
	router.push({ path: "/imports/containers", query: { search: query } });
}
function openTrucksForCi(row) {
	if (!row) return;
	const query = row.ci_number || row.name;
	router.push({ path: "/imports/trucks", query: { search: query } });
}
function openCreate() {
	router.push("/imports/commercial-invoices/new");
}

const fm = (v, ccy) => formatMoney(v, ccy || "USD", user.value?.language || "en");
const fn = (v) => Math.round(Number(v) || 0).toLocaleString(user.value?.language || "ru-RU");

onMounted(() => {
	loadSuppliers();
	loadPiGroups();
	load();
});
watch([status, supplier, groupFilter], reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(
	() => route.query,
	(q) => {
		const newSearch = q.search ? String(q.search) : q.proforma ? String(q.proforma) : q.proforma_invoice ? String(q.proforma_invoice) : "";
		const newStatus = q.status ? String(q.status) : "";
		if (newSearch !== search.value || newStatus !== status.value) {
			search.value = newSearch;
			status.value = newStatus;
			reload();
		}
	}
);
watch(activeCompany, () => {
	loadSuppliers();
	loadPiGroups();
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
						<Select v-model="groupFilter" size="sm" :options="groupOptions" style="width: 180px" />
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
							<th class="ci-sort" @click="toggleSort('ci_number')">
								{{ t("CI № / vendor") }} <i v-if="sortIcon('ci_number')" class="ti" :class="sortIcon('ci_number')"></i>
							</th>
							<th>{{ t("PI Group / PI ref") }}</th>
							<th class="text-nowrap ci-sort" @click="toggleSort('ci_date')">
								{{ t("Date / ETA") }} <i v-if="sortIcon('ci_date')" class="ti" :class="sortIcon('ci_date')"></i>
							</th>
							<th class="text-end ci-sort" @click="toggleSort('total_boxes')">
								{{ t("Boxes") }} <i v-if="sortIcon('total_boxes')" class="ti" :class="sortIcon('total_boxes')"></i>
							</th>
							<th class="text-end ci-sort" @click="toggleSort('total_kg')">
								kg <i v-if="sortIcon('total_kg')" class="ti" :class="sortIcon('total_kg')"></i>
							</th>
							<th class="text-end text-nowrap ci-sort" @click="toggleSort('agreed_total')">
								{{ t("Agreed / gap") }} <i v-if="sortIcon('agreed_total')" class="ti" :class="sortIcon('agreed_total')"></i>
							</th>
							<th class="text-end text-nowrap ci-sort" @click="toggleSort('container_count')">
								{{ t("Cnt / truck") }} <i v-if="sortIcon('container_count')" class="ti" :class="sortIcon('container_count')"></i>
							</th>
							<th class="text-center">{{ t("GRN") }}</th>
							<th class="ci-sort" @click="toggleSort('status')">
								{{ t("Status") }} <i v-if="sortIcon('status')" class="ti" :class="sortIcon('status')"></i>
							</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="6" :cols="9" />
					<tbody v-else>
						<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
							<td>
								<div class="fw-bold text-primary font-monospace" style="font-size: 0.9rem">
									{{ r.ci_number || r.name }}
								</div>
								<span
									class="badge bg-secondary-lt text-dark font-monospace mt-1"
									style="cursor: pointer"
									:title="t('Filter by supplier: ') + (r.supplier_name || r.supplier)"
									@click.stop="filterBySupplier(r.supplier || r.supplier_name)"
								>
									{{ vendorCode(r) }}
								</span>
							</td>
							<td class="font-monospace small">
								<div v-if="groupLabel(r)" class="mb-1">
									<span
										class="badge bg-purple-lt text-purple font-monospace fw-bold"
										style="font-size: 0.75rem"
										:title="t('PI Group: ') + groupLabel(r)"
									>
										<i class="ti ti-folders me-1"></i>{{ groupLabel(r) }}
									</span>
								</div>
								<span
									v-if="r.proforma_invoice || r.proforma_ref"
									class="badge bg-purple-lt text-purple font-monospace"
									style="cursor: pointer"
									:title="t('Open Proforma Invoice: ') + (r.proforma_invoice || r.proforma_ref)"
									@click.stop="openPi(r.proforma_invoice || r.proforma_ref)"
								>
									<i class="ti ti-file-dollar me-1"></i>{{ r.proforma_ref || r.proforma_invoice }}
								</span>
								<span v-else class="text-muted">{{ t("not linked") }}</span>
							</td>
							<td class="text-nowrap font-monospace ci-num">
								{{ r.ci_date ? formatDate(r.ci_date) : "—" }}
								<div v-if="r.eta_transit_port" class="small" :class="etaClass(r)">
									ETA {{ formatDate(r.eta_transit_port) }}
									<span v-if="etaDays(r) !== null">
										· {{ etaDays(r) < 0 ? -etaDays(r) + " " + t("d late") : etaDays(r) + " " + t("d") }}
									</span>
								</div>
							</td>
							<td class="text-end font-monospace ci-num">{{ fn(r.total_boxes) }}</td>
							<td class="text-end font-monospace ci-num">{{ fn(r.total_kg) }}</td>
							<td class="text-end text-nowrap">
								<div class="fw-bold font-monospace ci-num">{{ fm(r.agreed_total, r.currency) }}</div>
								<div
									class="small font-monospace ci-num"
									:class="docsGap(r) ? 'text-danger' : 'text-muted'"
									:title="t('Gap between the agreed price and the documented price')"
								>
									{{ docsGap(r) ? "−" + fm(docsGap(r), r.currency) : fm(0, r.currency) }}
								</div>
							</td>
							<td class="text-end text-nowrap font-monospace ci-num">
								<span
									style="cursor: pointer"
									class="hover-underline text-primary me-2"
									:title="t('View containers for ') + (r.ci_number || r.name)"
									@click.stop="openContainersForCi(r)"
								>
									<i class="ti ti-box me-1" :title="t('Containers')" aria-hidden="true"></i>{{ r.container_count || 0 }}
								</span>
								<span
									style="cursor: pointer"
									class="hover-underline"
									:class="r.truck_count ? 'text-primary' : 'text-muted'"
									:title="t('View trucks for ') + (r.ci_number || r.name)"
									@click.stop="openTrucksForCi(r)"
								>
									<i
										class="ti ti-truck me-1"
										:class="{ 'text-muted': !r.truck_count }"
										:title="t('Trucks')"
										aria-hidden="true"
									></i><span>{{ r.truck_count || 0 }}</span>
								</span>
							</td>
							<td class="text-center">
								<i v-if="r.has_grn" class="ti ti-check text-green" :title="t('GRN created')"></i>
								<span v-else class="text-muted">—</span>
							</td>
							<td><StatusBadge doctype="Commercial Invoice" :status="r.status" /></td>
						</tr>
					</tbody>
					<tfoot v-if="!loading && rows.length">
						<tr class="ci-totals">
							<td class="text-secondary">
								{{ rows.length }} CI · {{ totals.vendors.size }} {{ t("vendors") }}
								<div class="text-muted small">{{ t("this page only") }}</div>
							</td>
							<td></td>
							<td></td>
							<td class="text-end font-monospace ci-num">{{ fn(totals.boxes) }}</td>
							<td class="text-end font-monospace ci-num fw-bold">{{ fn(totals.kg) }}</td>
							<td class="text-end text-nowrap">
								<div class="fw-bold font-monospace ci-num">{{ fm(totals.agreed, totalsCurrency) }}</div>
								<div class="small font-monospace ci-num" :class="totals.gap ? 'text-danger' : 'text-muted'">
									{{ totals.gap ? "−" + fm(totals.gap, totalsCurrency) : fm(0, totalsCurrency) }}
								</div>
							</td>
							<td class="text-end font-monospace ci-num">{{ totals.containers }} / {{ totals.trucks }}</td>
							<td class="text-center font-monospace ci-num">{{ totals.grn }}</td>
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
	</div>
</template>

<style scoped>
.ci-num {
	font-variant-numeric: tabular-nums;
}
.ci-sort {
	cursor: pointer;
	user-select: none;
}
.ci-sort:hover {
	color: var(--tblr-primary);
}
.ci-totals td {
	border-top: 2px solid var(--tblr-border-color);
	background: var(--tblr-bg-surface-secondary);
}
</style>
