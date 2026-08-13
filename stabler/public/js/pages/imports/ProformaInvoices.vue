<script setup>
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useToast } from "../../composables/useToast.js";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import KpiCard from "../../components/KpiCard.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();

const rows = ref([]);
const loading = ref(false);
const search = ref("");
const statusFilter = ref(String(route.query.status || "").trim());
const groupFilter = ref("");
const supplierFilter = ref("");

// Supplier filter scoped to the import (meat) vendors only — those that appear
// on Proforma/Commercial invoices, not the whole Supplier master.
const suppliers = ref([]);
const supplierOptions = computed(() => [
	{ value: "", label: t("All suppliers") },
	...suppliers.value.map((s) => ({ value: s.name, label: s.supplier_name || s.name })),
]);
async function loadSuppliers() {
	if (!activeCompany.value) return;
	try {
		suppliers.value = await call("stabler.api.imports.import_suppliers", {
			company: activeCompany.value,
		});
	} catch (_err) {
		suppliers.value = [];
	}
}

const STATUSES = [
	{ value: "", label: t("All statuses") },
	{ value: "DRAFT", label: "DRAFT" },
	{ value: "CONFIRMED", label: "CONFIRMED" },
	{ value: "SUPERSEDED_BY_CI", label: "SUPERSEDED_BY_CI" },
	{ value: "CANCELLED", label: "CANCELLED" },
];

// ---- PI Groups (filter + per-row badge) ----
const piGroups = ref([]);
const groupOptions = computed(() => [
	{ value: "", label: t("All PI groups") },
	// Sentinel understood by the backend as "belongs to no group at all" — the
	// ungrouped rows are the newest ones, so they own the first screen.
	{ value: "__none__", label: t("No PI group") },
	...piGroups.value.map((g) => ({ value: g.name, label: g.title || g.name })),
]);
const groupsByName = computed(() => {
	const m = {};
	for (const g of piGroups.value) m[g.name] = g.title || g.name;
	return m;
});
// Prefer whatever the backend already resolved per row (pi_group_code /
// pi_group_title, once the list endpoint adds them); fall back to the
// PI Groups reference list; fall back to the raw link value.
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

// Smart-list cell helpers.
function refMain(r) {
	return (r && (r.supplier_pi_ref || r.name)) || "";
}
function grp(v) {
	// Follow the user's locale like every other number on the page — a hardcoded
	// "ru-RU" here made the table use space separators while the metric cards,
	// which go through formatMoney(user.language), used commas.
	return Math.round(Number(v) || 0).toLocaleString(user.value.language || "ru-RU");
}
/** Short vendor code — "HMA AGRO INDUSTRIES LIMITED" reads as HMA in a table. */
function vendorCode(r) {
	const s = (r && (r.supplier_name || r.supplier)) || "";
	return (s.split(/\s+/)[0] || "").toUpperCase();
}

/** Days since the proforma was raised — how long this has been open. */
function ageDays(r) {
	if (!r.pi_date) return null;
	const d = new Date(r.pi_date + "T00:00:00");
	if (Number.isNaN(d.getTime())) return null;
	return Math.max(0, Math.round((Date.now() - d.getTime()) / 86400000));
}

/**
 * Gap between the agreed price and the documented price. Always a number, so
 * the column stays numeric — a prose "no difference" would break the scan.
 */
function docsGap(r) {
	return Number(r.cash_difference) || 0;
}

function invoicedPct(r) {
	return Math.min(100, Math.round(Number(r.invoiced_pct) || 0));
}

function invoicedBarClass(r) {
	const p = Number(r.invoiced_pct) || 0;
	if (p >= 100) return "bg-success";
	if (p > 0) return "bg-warning";
	return "bg-secondary";
}

// ---- sorting -------------------------------------------------------------
// The proforma list loads in one page (limit 200), so sorting client-side
// orders the whole result rather than a slice. The CI list is paginated and
// therefore sorts on the server instead.
const SORT_KEYS = {
	ref: (r) => String(refMain(r)).toLowerCase(),
	vendor: (r) => vendorCode(r),
	pi_date: (r) => r.pi_date || "",
	item_count: (r) => Number(r.item_count) || 0,
	total_boxes: (r) => Number(r.total_boxes) || 0,
	total_kg: (r) => Number(r.total_kg) || 0,
	agreed_total: (r) => Number(r.agreed_total) || 0,
	invoiced_pct: (r) => Number(r.invoiced_pct) || 0,
	status: (r) => String(r.status || ""),
};

const sortBy = ref("pi_date");
const sortDir = ref("desc");

function toggleSort(key) {
	if (!SORT_KEYS[key]) return;
	if (sortBy.value === key) {
		sortDir.value = sortDir.value === "asc" ? "desc" : "asc";
	} else {
		sortBy.value = key;
		// Text reads best A→Z, magnitudes read best largest-first.
		sortDir.value = key === "ref" || key === "vendor" || key === "status" ? "asc" : "desc";
	}
}

function sortIcon(key) {
	if (sortBy.value !== key) return "";
	return sortDir.value === "asc" ? "ti-arrow-narrow-up" : "ti-arrow-narrow-down";
}

const sortedRows = computed(() => {
	const get = SORT_KEYS[sortBy.value] || SORT_KEYS.pi_date;
	const sign = sortDir.value === "asc" ? 1 : -1;
	return [...rows.value].sort((a, b) => {
		const x = get(a);
		const y = get(b);
		if (x === y) return 0;
		return x > y ? sign : -sign;
	});
});

/** Column totals for the loaded rows — what procurement asks for first. */
const totals = computed(() => {
	const acc = { count: 0, items: 0, boxes: 0, kg: 0, agreed: 0, gap: 0, vendors: new Set() };
	for (const r of rows.value) {
		acc.count += 1;
		acc.items += Number(r.item_count) || 0;
		acc.boxes += Number(r.total_boxes) || 0;
		acc.kg += Number(r.total_kg) || 0;
		acc.agreed += Number(r.agreed_total) || 0;
		acc.gap += Number(r.cash_difference) || 0;
		if (r.supplier) acc.vendors.add(r.supplier);
	}
	return acc;
});

const totalsCurrency = computed(() => {
	const set = new Set(rows.value.map((r) => r.currency).filter(Boolean));
	return set.size === 1 ? [...set][0] : "";
});

async function loadPiGroups() {
	if (!activeCompany.value) return;
	try {
		piGroups.value = await call("stabler.api.imports.list_pi_groups", {
			company: activeCompany.value,
		});
	} catch (_err) {
		piGroups.value = [];
	}
}

// ---- List stats strip ----
const stats = ref(null);
const statsLoading = ref(false);

// The backend sums across whatever rows match the filters. If those rows
// don't all share one currency, a single summed number would be meaningless
// (and per the currency-display rule we must never convert to a base/USD
// figure to paper over that). So: sum + show the original currency only when
// every loaded row agrees on one; otherwise show the plain number with no
// currency symbol and flag it as a mixed-currency total.
const statsCurrencies = computed(() => [...new Set(rows.value.map((r) => r.currency).filter(Boolean))]);
const statsCurrency = computed(() => (statsCurrencies.value.length === 1 ? statsCurrencies.value[0] : ""));
const statsMixedCurrency = computed(() => statsCurrencies.value.length > 1);

async function loadStats() {
	if (!activeCompany.value) return;
	statsLoading.value = true;
	try {
		stats.value = await call("stabler.api.imports.proforma_list_stats", {
			company: activeCompany.value,
			status: statusFilter.value || undefined,
			group: groupFilter.value || undefined,
			supplier: supplierFilter.value || undefined,
			search: search.value || undefined,
		});
	} catch (_err) {
		// Stats strip is supplementary — a failure here shouldn't block the list.
		stats.value = null;
	} finally {
		statsLoading.value = false;
	}
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		rows.value = await call("stabler.api.imports.list_proformas", {
			company: activeCompany.value,
			status: statusFilter.value || undefined,
			search: search.value || undefined,
			group: groupFilter.value || undefined,
			supplier: supplierFilter.value || undefined,
			limit: 200,
		});
	} catch (err) {
		toast.error(err?.message || t("Failed to load proformas."));
		rows.value = [];
	} finally {
		loading.value = false;
	}
	loadStats();
}
onMounted(() => {
	loadPiGroups();
	loadSuppliers();
	load();
});

const fm = (v, ccy) => formatMoney(v, ccy || "", user.value.language);

function openLinkedCis(row) {
	if (!row || !row.name) return;
	router.push({ path: "/imports/commercial-invoices", query: { proforma: row.name } });
}
function filterBySupplier(sup) {
	if (!sup) return;
	search.value = sup;
	load();
}

const canSupersede = (row) => ["DRAFT", "CONFIRMED"].includes(row.status);
</script>

<template>
	<!-- Stats strip -->
	<div class="row row-deck row-cards mb-3">
		<div class="col-sm-6 col-lg-3">
			<KpiCard
				:label="t('Agreed total')"
				:value="fm(stats && stats.agreed_total_sum, statsCurrency)"
				icon="ti-file-dollar"
				tone="primary"
				:loading="statsLoading"
				:hint="!statsLoading && statsMixedCurrency ? t('Mixed currencies — sum shown without symbol') : ''"
			/>
		</div>
		<div class="col-sm-6 col-lg-3">
			<KpiCard
				:label="t('Docs total')"
				:value="stats && stats.docs_total_sum != null ? fm(stats.docs_total_sum, statsCurrency) : '—'"
				icon="ti-file-text"
				tone="azure"
				:loading="statsLoading"
				:hint="!statsLoading && statsMixedCurrency ? t('Mixed currencies — sum shown without symbol') : ''"
			/>
		</div>
		<div class="col-sm-6 col-lg-3">
			<KpiCard
				:label="t('Cash Difference')"
				:value="stats && stats.cash_difference_sum != null ? fm(stats.cash_difference_sum, statsCurrency) : '—'"
				icon="ti-arrows-diff"
				tone="orange"
				value-tone="orange"
				:loading="statsLoading"
				:hint="!statsLoading && statsMixedCurrency ? t('Mixed currencies — sum shown without symbol') : ''"
			/>
		</div>
		<div class="col-sm-6 col-lg-3">
			<KpiCard
				:label="t('Proforma Invoices')"
				:value="stats ? stats.count : rows.length"
				icon="ti-files"
				tone="primary"
				:loading="statsLoading"
				:badges="[
					{ label: t('Draft'), value: stats ? stats.draft_count : 0, tone: 'secondary' },
					{ label: t('Confirmed'), value: stats ? stats.confirmed_count : 0, tone: 'azure' },
				]"
			/>
		</div>
	</div>

	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<div class="card-title m-0">{{ t("Proforma Invoices") }}</div>
			<button type="button" class="btn btn-outline-secondary btn-sm ms-auto" @click="router.push('/imports/pi-groups')">
				<i class="ti ti-tags me-1"></i>{{ t("PI Groups") }}
			</button>
			<button type="button" class="btn btn-outline-secondary btn-sm" @click="router.push('/imports/advances')">
				<i class="ti ti-cash me-1"></i>{{ t("PI Advances") }}
			</button>
			<button type="button" class="btn btn-primary btn-sm" @click="router.push('/imports/proformas/new')">
				<i class="ti ti-plus me-1"></i>{{ t("New Proforma") }}
			</button>
		</div>

		<ListToolbar v-model="search" :placeholder="t('PI no or supplier') + '  ⌘K'" :count="rows.length" @search="load">
			<template #filters>
				<Select v-model="statusFilter" size="sm" style="width: 180px" :options="STATUSES" value-key="value" label-key="label" @change="load" />
				<Select v-model="supplierFilter" size="sm" style="width: 200px" :options="supplierOptions" value-key="value" label-key="label" @change="load" />
				<Select v-model="groupFilter" size="sm" style="width: 180px" :options="groupOptions" value-key="value" label-key="label" @change="load" />
			<!-- colspan-bumped -->
</template>
		</ListToolbar>

		<div class="table-responsive">
			<table class="table table-vcenter">
				<thead>
					<tr>
						<th style="min-width: 170px" class="pi-sort" @click="toggleSort('ref')">
							{{ t("PI Group / Ref / Vendor") }} <i v-if="sortIcon('ref')" class="ti" :class="sortIcon('ref')"></i>
						</th>
						<th class="text-nowrap pi-sort" @click="toggleSort('pi_date')">
							{{ t("PI Date") }} <i v-if="sortIcon('pi_date')" class="ti" :class="sortIcon('pi_date')"></i>
						</th>
						<th class="text-end pi-sort" @click="toggleSort('item_count')">
							{{ t("Items") }} <i v-if="sortIcon('item_count')" class="ti" :class="sortIcon('item_count')"></i>
						</th>
						<th class="text-end pi-sort" @click="toggleSort('total_boxes')">
							{{ t("Boxes") }} <i v-if="sortIcon('total_boxes')" class="ti" :class="sortIcon('total_boxes')"></i>
						</th>
						<th class="text-end pi-sort" @click="toggleSort('total_kg')">
							kg <i v-if="sortIcon('total_kg')" class="ti" :class="sortIcon('total_kg')"></i>
						</th>
						<th class="text-end text-nowrap pi-sort" @click="toggleSort('agreed_total')">
							{{ t("Agreed / gap") }} <i v-if="sortIcon('agreed_total')" class="ti" :class="sortIcon('agreed_total')"></i>
						</th>
						<th class="text-end pi-sort" @click="toggleSort('shipped_pct')">
							{{ t("Shipped %") }} <i v-if="sortIcon('shipped_pct')" class="ti" :class="sortIcon('shipped_pct')"></i>
						</th>
						<th class="text-end pi-sort" @click="toggleSort('remaining_boxes')">
							{{ t("Remaining bx") }} <i v-if="sortIcon('remaining_boxes')" class="ti" :class="sortIcon('remaining_boxes')"></i>
						</th>
						<th class="text-end pi-sort" @click="toggleSort('over_boxes')">
							{{ t("Over-shipped") }} <i v-if="sortIcon('over_boxes')" class="ti" :class="sortIcon('over_boxes')"></i>
						</th>
						<th style="min-width: 110px" class="pi-sort" @click="toggleSort('invoiced_pct')">
							{{ t("Invoiced %") }} <i v-if="sortIcon('invoiced_pct')" class="ti" :class="sortIcon('invoiced_pct')"></i>
						</th>
						<th class="pi-sort" @click="toggleSort('status')">
							{{ t("Status") }} <i v-if="sortIcon('status')" class="ti" :class="sortIcon('status')"></i>
						</th>
						<th class="w-1"><span class="visually-hidden">{{ t("Actions") }}</span></th>
					</tr>
				</thead>
				<tbody>
					<SkeletonRows v-if="loading" :cols="9" :rows="6" />
					<tr v-for="r in sortedRows" :key="r.name" class="pi-row" style="cursor: pointer" @click="router.push({ name: 'imports-proforma', params: { name: r.name } })">
						<td>
							<div class="mb-1">
								<span
									v-if="groupLabel(r)"
									class="badge bg-purple-lt text-purple font-monospace fw-bold"
									style="font-size: 0.75rem"
									:title="t('PI Group: ') + groupLabel(r)"
								>
									<i class="ti ti-folders me-1"></i>{{ groupLabel(r) }}
								</span>
								<!-- Outline, not a filled grey: the vendor badge below is already
								     filled bg-secondary-lt and the two would read as one block. -->
								<span
									v-else
									class="badge badge-outline text-secondary"
									style="font-size: 0.75rem"
									:title="t('Not assigned to a PI group')"
								>
									<i class="ti ti-folder-off me-1"></i>{{ t("No group") }}
								</span>
							</div>
							<div class="fw-bold text-primary font-monospace" style="font-size: 0.9rem">{{ refMain(r) }}</div>
							<span
								class="badge bg-secondary-lt text-dark font-monospace mt-1"
								style="cursor: pointer"
								:title="t('Filter by supplier: ') + (r.supplier_name || r.supplier)"
								@click.stop="filterBySupplier(r.supplier || r.supplier_name)"
							>
								{{ vendorCode(r) }}
							</span>
						</td>
						<td class="text-nowrap font-monospace pi-num">
							{{ r.pi_date ? formatDate(r.pi_date) : "—" }}
							<div v-if="ageDays(r) !== null" class="text-muted small">{{ ageDays(r) }} {{ t("days") }}</div>
						</td>
						<td class="text-end font-monospace pi-num">{{ r.item_count || 0 }}</td>
						<td class="text-end font-monospace pi-num">{{ grp(r.total_boxes) }}</td>
						<td class="text-end font-monospace pi-num">{{ grp(r.total_kg) }}</td>
						<td class="text-end text-nowrap">
							<div class="fw-bold font-monospace pi-num">{{ fm(r.agreed_total, r.currency) }}</div>
							<div
								class="small font-monospace pi-num"
								:class="docsGap(r) ? 'text-danger' : 'text-muted'"
								:title="t('Gap between the agreed price and the documented price')"
							>
								{{ docsGap(r) ? "−" + fm(docsGap(r), r.currency) : fm(0, r.currency) }}
							</div>
						</td>
						<td class="text-end font-monospace pi-num">
							<span :class="(r.shipped_pct || 0) >= 100 ? 'text-green' : ''">{{ r.shipped_pct || 0 }}%</span>
						</td>
						<td class="text-end font-monospace pi-num">{{ grp(r.remaining_boxes || 0) }}</td>
						<td class="text-end font-monospace pi-num">
							<span v-if="r.over_boxes" class="badge bg-red-lt text-red">+{{ grp(r.over_boxes) }}</span>
							<span v-else class="text-secondary">{{ "—" }}</span>
						</td>
						<td
							class="pi-invoiced-cell"
							style="cursor: pointer"
							:title="t('Click to view linked Commercial Invoices')"
							@click.stop="openLinkedCis(r)"
						>
							<div class="progress" style="height: 5px">
								<div class="progress-bar" :class="invoicedBarClass(r)" :style="{ width: invoicedPct(r) + '%' }"></div>
							</div>
							<div class="text-secondary small mt-1 pi-num d-flex align-items-center justify-content-between">
								<span>{{ invoicedPct(r) }}% · {{ r.ci_count || 0 }} CI</span>
								<i class="ti ti-chevron-right text-primary ms-1" style="font-size: 0.75rem" :title="t('View linked CIs')"></i>
							</div>
						</td>
						<td><span class="badge" :class="getStatusBadgeClass('Proforma Invoice', r.status)">{{ r.status }}</span></td>
						<td class="text-end text-nowrap" @click.stop>
							<button
								v-if="canSupersede(r)"
								type="button"
								class="btn btn-outline-primary btn-sm pi-row-action"
								:title="t('Create Commercial Invoice from this Proforma')"
								@click="router.push({ path: '/imports/commercial-invoices/new', query: { proforma: r.name } })"
							>
								<i class="ti ti-plus me-1"></i>{{ t("Create CI") }}
							</button>
							<button
								v-else-if="r.commercial_invoice"
								type="button"
								class="btn btn-ghost-info btn-sm text-nowrap"
								:title="t('View linked Commercial Invoice')"
								@click="router.push('/imports/commercial-invoices/' + r.commercial_invoice)"
							>
								<i class="ti ti-file-check me-1"></i>{{ r.commercial_invoice }}
							</button>
						</td>
					</tr>
				</tbody>
				<tfoot v-if="!loading && rows.length">
					<tr class="pi-totals">
						<td class="text-secondary">
							{{ totals.count }} PI · {{ totals.vendors.size }} {{ t("vendors") }}
						</td>
						<td></td>
						<td class="text-end font-monospace pi-num">{{ grp(totals.items) }}</td>
						<td class="text-end font-monospace pi-num">{{ grp(totals.boxes) }}</td>
						<td class="text-end font-monospace pi-num fw-bold">{{ grp(totals.kg) }}</td>
						<td class="text-end text-nowrap">
							<div class="fw-bold font-monospace pi-num">{{ fm(totals.agreed, totalsCurrency) }}</div>
							<div class="small font-monospace pi-num" :class="totals.gap ? 'text-danger' : 'text-muted'">
								{{ totals.gap ? "−" + fm(totals.gap, totalsCurrency) : fm(0, totalsCurrency) }}
							</div>
						</td>
						<td colspan="6"></td>
					</tr>
				</tfoot>
			</table>
			<EmptyState v-if="!loading && !rows.length" :title="t('No proformas yet')" :subtitle="t('Create your first proforma invoice.')" />
		</div>
	</div>
</template>

<style scoped>
/* Identifiers and money align only with fixed-width digits. */
.pi-num {
	font-variant-numeric: tabular-nums;
}

/* The row action repeats on every row; fade it back until the row is engaged.
   Only on hover-capable pointers — on touch there is no hover, so it stays
   visible. Focus-within keeps it reachable by keyboard. */
@media (hover: hover) and (pointer: fine) {
	.pi-row-action {
		opacity: 0;
		transition: opacity 0.12s ease-in-out;
	}
	.pi-row:hover .pi-row-action,
	.pi-row:focus-within .pi-row-action {
		opacity: 1;
	}
}

.pi-sort {
	cursor: pointer;
	user-select: none;
}
.pi-sort:hover {
	color: var(--tblr-primary);
}
.pi-totals td {
	border-top: 2px solid var(--tblr-border-color);
	background: var(--tblr-bg-surface-secondary);
}
</style>
