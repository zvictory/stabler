<script setup>
// Director window — full tender portfolio: every tender with value, margin,
// Остаток, deadline risk. Read-only overview across all tenders of the company.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useAutoRefresh } from "../../composables/useAutoRefresh.js";
import { useToast } from "../../composables/useToast.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { activeTenderFilters, filterTenderRows, tenderRouteFilters } from "../../composables/tenderBoardFilters.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import TenderNav from "./TenderNav.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
useEscapeBack(null, "/tender/board");

const loading = ref(false);
const data = ref({ rows: [], kpi: {}, currency: "" });
const managers = ref([]);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.tender.tender_director_board", { company: activeCompany.value });
	} catch (err) {
		toast.error(err?.message || t("Could not load the director board."));
	} finally {
		loading.value = false;
	}
}
async function loadManagers() {
	try {
		const r = await call("stabler.api.tender.tender_managers", { company: activeCompany.value });
		managers.value = r?.managers || [];
	} catch { /* assignment is optional */ }
}
async function assign(row, user) {
	try {
		const r = await call("stabler.api.tender.assign_tender", { deal: row.deal, user: user || "" });
		row.assigned_to = r.assigned_to;
		row.assigned_to_name = r.assigned_to_name;
		toast.success(t("Assigned."));
	} catch (err) {
		toast.error(err?.message || t("Could not assign."));
	}
}
onMounted(() => { load(); loadManagers(); });
useAutoRefresh(load);

const ccy = computed(() => data.value?.currency || "");
const kpi = computed(() => data.value?.kpi || {});
const rows = computed(() => data.value?.rows || []);
const filters = computed(() => tenderRouteFilters(route.query));
const filterSummary = computed(() => activeTenderFilters(filters.value).map(([key, value]) => `${key}: ${value}`));
const filteredRows = computed(() => filterTenderRows(rows.value, filters.value));
const fm = (v) => formatMoney(v, ccy.value, user.value.language);
const riskBadge = (r) => ({ good: "bg-green-lt text-green", warn: "bg-yellow-lt text-yellow", risk: "bg-red-lt text-red" }[r] || "bg-secondary-lt");
const riskLabel = (r) => ({ good: t("On track"), warn: t("Deadline near"), risk: t("At risk"), none: "—" }[r] || "—");
const resultBadge = (x) => ({ won: "bg-green-lt text-green", lost: "bg-red-lt text-red", pending: "bg-yellow-lt text-yellow" }[x] || "");
function openDeal(deal) { router.push({ name: "tender-po-control", query: { ...route.query, deal } }); }
function clearFilters() { router.replace({ query: {} }); }
</script>

<template>
	<div class="container-xl py-3">
		<div class="d-flex align-items-center mb-2 gap-2 flex-wrap">
			<h2 class="mb-0">{{ t("Director board") }}</h2>
			<div v-if="filterSummary.length" class="ms-auto d-flex align-items-center gap-2"><span class="text-secondary small">{{ filterSummary.join(" · ") }}</span><button type="button" class="btn btn-sm btn-ghost-secondary" @click="clearFilters">{{ t("Clear filters") }}</button></div>
		</div>
		<TenderNav />

		<!-- KPI -->
		<div class="row g-2 mb-3">
			<div class="col-6 col-md"><div class="card"><div class="card-body py-2 px-3">
				<div class="text-secondary small text-uppercase">{{ t("Active tenders") }}</div><div class="h3 m-0">{{ kpi.count || 0 }}</div></div></div></div>
			<div class="col-6 col-md"><div class="card"><div class="card-body py-2 px-3">
				<div class="text-secondary small text-uppercase">{{ t("Portfolio value") }}</div><div class="h3 m-0 font-monospace">{{ fm(kpi.total_value || 0) }}</div></div></div></div>
			<div class="col-6 col-md"><div class="card"><div class="card-body py-2 px-3">
				<div class="text-secondary small text-uppercase">{{ t("Avg margin") }}</div><div class="h3 m-0 text-green">{{ kpi.avg_margin || 0 }}%</div></div></div></div>
			<div class="col-6 col-md"><div class="card"><div class="card-body py-2 px-3">
				<div class="text-secondary small text-uppercase">{{ t("At risk") }}</div><div class="h3 m-0" :class="kpi.at_risk ? 'text-red' : ''">{{ kpi.at_risk || 0 }}</div></div></div></div>
			<div class="col-6 col-md"><div class="card"><div class="card-body py-2 px-3">
				<div class="text-secondary small text-uppercase">{{ t("Win rate") }}</div>
				<div class="h3 m-0 text-green">{{ kpi.win_rate || 0 }}%</div>
				<div class="text-secondary" style="font-size:11px">{{ kpi.won || 0 }}{{ t("W") }} · {{ kpi.lost || 0 }}{{ t("L") }} · {{ kpi.pending || 0 }}{{ t("P") }}</div>
			</div></div></div>
			<div class="col-6 col-md"><div class="card"><div class="card-body py-2 px-3">
				<div class="text-secondary small text-uppercase">{{ t("Остаток (net remaining)") }}</div><div class="h3 m-0 font-monospace">{{ fm(kpi.total_ostatok || 0) }}</div></div></div></div>
		</div>

		<div class="card">
			<div class="card-body p-0">
				<table class="table card-table">
					<thead><tr>
						<th>{{ t("Tender") }}</th>
						<th class="text-end">{{ t("Value") }}</th>
						<th class="text-end">{{ t("Margin on revenue") }}</th>
						<th class="text-end">{{ t("Landed") }}</th>
						<th class="text-end">{{ t("Остаток (net remaining)") }}</th>
						<th class="text-nowrap">{{ t("Delivery deadline") }}</th>
						<th>{{ t("Risk") }}</th>
						<th style="width:170px">{{ t("Manager") }}</th>
					</tr></thead>
					<tbody>
						<SkeletonRows v-if="loading" :cols="8" :rows="6" />
						<tr v-for="r in filteredRows" :key="r.deal" style="cursor:pointer" @click="openDeal(r.deal)">
							<td>
								<span class="fw-semibold">{{ r.label }}</span>
								<span v-if="r.result" class="badge ms-1" :class="resultBadge(r.result)">{{ t(r.result.charAt(0).toUpperCase() + r.result.slice(1)) }}</span>
								<div class="text-secondary small">{{ r.po_count }} PO · {{ r.so_count }} SO</div>
							</td>
							<td class="text-end font-monospace">{{ fm(r.value) }}</td>
							<td class="text-end font-monospace">{{ r.margin_pct }}%</td>
							<td class="text-end font-monospace text-secondary">{{ fm(r.landed) }}</td>
							<td class="text-end font-monospace fw-semibold">{{ fm(r.ostatok) }}</td>
							<td class="text-nowrap">{{ r.delivery ? formatDate(r.delivery) : "—" }}</td>
							<td><span class="badge" :class="riskBadge(r.risk)">{{ riskLabel(r.risk) }}</span></td>
							<td @click.stop>
								<select class="form-select form-select-sm" :value="r.assigned_to" @change="assign(r, $event.target.value)">
									<option value="">— {{ t("Unassigned") }} —</option>
									<option v-for="m in managers" :key="m.name" :value="m.name">{{ m.full_name }}</option>
								</select>
							</td>
						</tr>
					</tbody>
				</table>
				<EmptyState v-if="!loading && !filteredRows.length" icon="ti-gavel" :title="t('No tenders match these filters.')" :subtitle="t('Clear filters or select another dashboard period.')" />
			</div>
		</div>
	</div>
</template>
