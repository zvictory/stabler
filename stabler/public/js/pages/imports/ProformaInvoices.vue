<script setup>
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useToast } from "../../composables/useToast.js";
import Typeahead from "../../components/Typeahead.vue";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
const toast = useToast();

const rows = ref([]);
const loading = ref(false);
const search = ref("");
const statusFilter = ref("");
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
function refSub(r) {
	// the ERPNext auto name, shown small when the original ref took its place
	return r && r.supplier_pi_ref && r.supplier_pi_ref !== r.name ? r.name : "";
}
function grp(v) {
	// Follow the user's locale like every other number on the page — a hardcoded
	// "ru-RU" here made the table use space separators while the metric cards,
	// which go through formatMoney(user.language), used commas.
	return Math.round(Number(v) || 0).toLocaleString(user.value.language || "ru-RU");
}
function fcl(v) {
	return (Number(v) || 0).toFixed(1);
}

/** One compact metadata line: items, physical, terms, group. Empty parts drop out. */
function metaParts(r) {
	const out = [];
	if (r.item_count) out.push(`${r.item_count} ${t("items")}`);
	if (r.total_boxes) out.push(`${grp(r.total_boxes)} bx`);
	if (r.total_kg) out.push(`${grp(r.total_kg)} kg`);
	// FCL is only meaningful once it has been captured — it was printing "0.0 FCL"
	// on every row, which reads as data rather than as an empty field.
	if (Number(r.total_fcl) > 0) out.push(`${fcl(r.total_fcl)} FCL`);
	if (r.incoterm) out.push(r.incoterm);
	if (r.advance_pct) out.push(`${r.advance_pct}% ${t("advance")}`);
	if (groupLabel(r)) out.push(groupLabel(r));
	return out.join(" · ");
}

/** Under-declared gap between the agreed price and the documented price. */
function docsGap(r) {
	const gap = Number(r.cash_difference) || 0;
	return gap ? gap : null;
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

// ---- Supersede with a Commercial Invoice ----
const supersedeFor = ref(null); // row being superseded
const supersedeCi = ref("");
const superseding = ref(false);

function openSupersede(row) {
	supersedeFor.value = row;
	supersedeCi.value = "";
}
function searchCIs(q) {
	return call("stabler.api.imports.list_commercial_invoices", {
		company: activeCompany.value,
		search: q,
		limit: 20,
	});
}
async function doSupersede() {
	if (!supersedeCi.value) return;
	superseding.value = true;
	try {
		await call("stabler.api.imports.link_proforma_to_ci", {
			proforma: supersedeFor.value.name,
			commercial_invoice: supersedeCi.value,
			company: activeCompany.value,
		});
		toast.success(t("Proforma linked to Commercial Invoice"));
		supersedeFor.value = null;
		load();
	} catch (err) {
		toast.error(err?.message || t("Could not link the proforma."));
	} finally {
		superseding.value = false;
	}
}

const canSupersede = (row) => ["DRAFT", "CONFIRMED"].includes(row.status);
</script>

<template>
	<!-- Stats strip -->
	<div class="row row-cards mb-3">
		<div class="col-sm-6 col-lg-3">
			<div class="card card-sm">
				<div class="card-body">
					<div class="font-weight-medium text-secondary small">{{ t("Agreed total") }}</div>
					<div class="h2 mb-0 font-monospace">
						<span v-if="statsLoading" class="placeholder col-6">&nbsp;</span>
						<span v-else>{{ fm(stats && stats.agreed_total_sum, statsCurrency) }}</span>
					</div>
					<div v-if="!statsLoading && statsMixedCurrency" class="text-secondary small mt-1">{{ t("Mixed currencies — sum shown without symbol") }}</div>
				</div>
			</div>
		</div>
		<div class="col-sm-6 col-lg-3">
			<div class="card card-sm">
				<div class="card-body">
					<div class="font-weight-medium text-secondary small">{{ t("Docs total") }}</div>
					<div class="h2 mb-0 font-monospace">
						<span v-if="statsLoading" class="placeholder col-6">&nbsp;</span>
						<span v-else>{{ stats && stats.docs_total_sum != null ? fm(stats.docs_total_sum, statsCurrency) : "—" }}</span>
					</div>
					<div v-if="!statsLoading && statsMixedCurrency" class="text-secondary small mt-1">{{ t("Mixed currencies — sum shown without symbol") }}</div>
				</div>
			</div>
		</div>
		<div class="col-sm-6 col-lg-3">
			<div class="card card-sm">
				<div class="card-body">
					<div class="font-weight-medium text-secondary small">{{ t("Cash Difference") }}</div>
					<div class="h2 mb-0 font-monospace">
						<span v-if="statsLoading" class="placeholder col-6">&nbsp;</span>
						<span v-else>{{ stats && stats.cash_difference_sum != null ? fm(stats.cash_difference_sum, statsCurrency) : "—" }}</span>
					</div>
					<div v-if="!statsLoading && statsMixedCurrency" class="text-secondary small mt-1">{{ t("Mixed currencies — sum shown without symbol") }}</div>
				</div>
			</div>
		</div>
		<div class="col-sm-6 col-lg-3">
			<div class="card card-sm">
				<div class="card-body">
					<div class="font-weight-medium text-secondary small">{{ t("Proforma Invoices") }}</div>
					<div class="h2 mb-0 font-monospace">
						<span v-if="statsLoading" class="placeholder col-4">&nbsp;</span>
						<span v-else>{{ stats ? stats.count : rows.length }}</span>
					</div>
					<div v-if="!statsLoading" class="text-secondary small mt-1">
						{{ t("Draft") }}: <span class="font-monospace">{{ stats ? stats.draft_count : 0 }}</span> ·
						{{ t("Confirmed") }}: <span class="font-monospace">{{ stats ? stats.confirmed_count : 0 }}</span>
					</div>
				</div>
			</div>
		</div>
	</div>

	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<div class="card-title m-0">{{ t("Proforma Invoices") }}</div>
			<button type="button" class="btn btn-primary btn-sm ms-auto" @click="router.push('/imports/proformas/new')">
				<i class="ti ti-plus me-1"></i>{{ t("New Proforma") }}
			</button>
		</div>

		<ListToolbar v-model="search" :placeholder="t('PI no or supplier') + '  ⌘K'" :count="rows.length" @search="load">
			<template #filters>
				<Select v-model="statusFilter" size="sm" style="width: 180px" :options="STATUSES" value-key="value" label-key="label" @change="load" />
				<Select v-model="supplierFilter" size="sm" style="width: 200px" :options="supplierOptions" value-key="value" label-key="label" @change="load" />
				<Select v-model="groupFilter" size="sm" style="width: 180px" :options="groupOptions" value-key="value" label-key="label" @change="load" />
			</template>
		</ListToolbar>

		<div class="table-responsive">
			<table class="table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("PI & exporter") }}</th>
						<th class="text-nowrap">{{ t("PI Date") }}</th>
						<th class="text-end text-nowrap">{{ t("Agreed / docs") }}</th>
						<th style="min-width: 120px">{{ t("Invoiced %") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="w-1"><span class="visually-hidden">{{ t("Actions") }}</span></th>
					</tr>
				</thead>
				<tbody>
					<SkeletonRows v-if="loading" :cols="6" :rows="6" />
					<tr v-for="r in rows" :key="r.name" class="pi-row" style="cursor: pointer" @click="router.push({ name: 'imports-proforma', params: { name: r.name } })">
						<td>
							<div class="d-flex align-items-baseline flex-wrap gap-2">
								<span class="fw-bold text-primary font-monospace" style="font-size: 0.95rem">{{ refMain(r) }}</span>
								<span class="text-secondary small">{{ r.supplier_name || r.supplier }}</span>
							</div>
							<div class="text-secondary small mt-1">
								{{ metaParts(r) }}
								<span v-if="refSub(r)" class="text-muted font-monospace ms-1">· {{ refSub(r) }}</span>
							</div>
						</td>
						<td class="text-nowrap font-monospace pi-num">{{ r.pi_date ? formatDate(r.pi_date) : "—" }}</td>
						<td class="text-end text-nowrap">
							<div class="fw-bold font-monospace pi-num">{{ fm(r.agreed_total, r.currency) }}</div>
							<div v-if="docsGap(r)" class="small font-monospace pi-num text-warning">
								−{{ fm(docsGap(r), r.currency) }} {{ t("docs") }}
							</div>
							<div v-else class="small font-monospace pi-num text-secondary">{{ t("docs match") }}</div>
						</td>
						<td>
							<div class="progress" style="height: 5px">
								<div class="progress-bar" :class="invoicedBarClass(r)" :style="{ width: invoicedPct(r) + '%' }"></div>
							</div>
							<div class="text-secondary small mt-1 pi-num">
								{{ invoicedPct(r) }}% · {{ r.ci_count || 0 }} CI
							</div>
						</td>
						<td><span class="badge" :class="getStatusBadgeClass('Proforma Invoice', r.status)">{{ r.status }}</span></td>
						<td class="text-end" @click.stop>
							<button
								v-if="canSupersede(r)"
								type="button"
								class="btn btn-outline-secondary btn-sm pi-row-action"
								@click="openSupersede(r)"
							>
								<i class="ti ti-link me-1"></i>{{ t("Link CI") }}
							</button>
						</td>
					</tr>
				</tbody>
			</table>
			<EmptyState v-if="!loading && !rows.length" :title="t('No proformas yet')" :subtitle="t('Create your first proforma invoice.')" />
		</div>
	</div>

	<!-- Supersede modal -->
	<div v-if="supersedeFor" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
		<div class="modal-dialog modal-dialog-centered">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Link to Commercial Invoice") }}</h5>
					<button type="button" class="btn-close" @click="supersedeFor = null"></button>
				</div>
				<div class="modal-body">
					<p class="text-secondary small">{{ t("Superseding proforma") }} <strong>{{ supersedeFor.name }}</strong>.</p>
					<label class="form-label small mb-1">{{ t("Commercial Invoice") }}</label>
					<Typeahead
						v-model="supersedeCi"
						:search="searchCIs"
						:placeholder="t('Search commercial invoice…')"
						@pick="(ci) => { supersedeCi = ci.name; }"
						@clear="() => { supersedeCi = ''; }"
					>
						<template #option="{ item }">
							<div class="fw-semibold small">{{ item.ci_number || item.name }}</div>
							<div class="text-secondary" style="font-size:0.75rem">{{ item.supplier_name }}</div>
						</template>
					</Typeahead>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="supersedeFor = null">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="superseding || !supersedeCi" @click="doSupersede">
						<span v-if="superseding" class="spinner-border spinner-border-sm me-1"></span>{{ t("Link") }}
					</button>
				</div>
			</div>
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
</style>
