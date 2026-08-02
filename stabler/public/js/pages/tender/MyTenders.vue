<script setup>
// Sourcing window — "my tenders": the tender pipeline with landed cost, PO count
// and deadline risk. Entry point into the per-tender sourcing/PO tools.
import { computed, onMounted, ref, watch } from "vue";
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
const data = ref({ rows: [], currency: "" });

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.tender.sourcing_my_tenders", { company: activeCompany.value });
	} catch (err) {
		toast.error(err?.message || t("Could not load your tenders."));
	} finally {
		loading.value = false;
	}
}
onMounted(load);
useAutoRefresh(load);

const ccy = computed(() => data.value?.currency || "");
const rows = computed(() => data.value?.rows || []);
const filters = computed(() => tenderRouteFilters(route.query));

// Funnel stage filter: the dashboard number and this list come from the SAME
// server classification (tender_funnel.rows), so they can never disagree.
// Note for non-oversight users: my-tenders shows only assigned tenders, so
// they may see a subset of the director's number — by design.
const funnelStage = computed(() => String(route.query.funnel_stage || ""));
const funnelDeals = ref(null); // Set of deal names for the active stage
const FUNNEL_STAGE_LABELS = computed(() => ({
	seen: t("Under review"), go: t("GO — awaiting sourcing"),
	sourcing: t("Collecting quotations"), priced: t("Priced — ready to bid"),
	submitted: t("Bid submitted"), won: t("Won"), lost: t("Lost"),
}));

async function loadFunnelStage() {
	if (!funnelStage.value || !activeCompany.value) {
		funnelDeals.value = null;
		return;
	}
	try {
		const r = await call("stabler.api.tender.tender_funnel", { company: activeCompany.value });
		funnelDeals.value = new Set((r?.rows?.[funnelStage.value] || []).map((x) => x.deal));
	} catch {
		funnelDeals.value = null; // filter degrades to "show all" rather than hiding everything
	}
}
watch([funnelStage, activeCompany], loadFunnelStage, { immediate: true });

const filterSummary = computed(() => {
	const parts = activeTenderFilters(filters.value).map(([key, value]) => `${key}: ${value}`);
	if (funnelStage.value) {
		const label = FUNNEL_STAGE_LABELS.value[funnelStage.value] || funnelStage.value;
		parts.unshift(`${t("Stage")}: ${label}`);
	}
	return parts;
});
const filteredRows = computed(() => {
	let out = filterTenderRows(rows.value, filters.value);
	if (funnelStage.value && funnelDeals.value) {
		out = out.filter((r) => funnelDeals.value.has(r.deal));
	}
	return out;
});
const fm = (v) => formatMoney(v, ccy.value, user.value.language);
const riskBadge = (r) => ({ good: "bg-green-lt text-green", warn: "bg-yellow-lt text-yellow", risk: "bg-red-lt text-red" }[r] || "bg-secondary-lt");
const riskLabel = (r) => ({ good: t("On track"), warn: t("Deadline near"), risk: t("At risk"), none: "—" }[r] || "—");
function openDeal(deal) { router.push({ name: "tender-po-control", query: { ...route.query, deal } }); }
function clearFilters() { router.replace({ query: {} }); }
</script>

<template>
	<div class="container-xl py-3">
		<!-- Çubuk sayfa başlığının ÜSTÜNDE: modül navı içeriğin değil ekranın
		     üstünde duruyor (bkz. TenderNav.vue'nun negatif kenar boşluğu ve
		     /tender/desk). Burada başlığın altında kalmıştı, o yüzden tender
		     ekranları arasında gezerken menü satır satır zıplıyordu. -->
		<TenderNav />
		<div class="d-flex align-items-center mb-2 gap-2 flex-wrap"><h2 class="mb-0">{{ t("My tenders") }}</h2><div v-if="filterSummary.length" class="ms-auto d-flex align-items-center gap-2"><span class="text-secondary small">{{ filterSummary.join(" · ") }}</span><button type="button" class="btn btn-sm btn-ghost-secondary" @click="clearFilters">{{ t("Clear filters") }}</button></div></div>
		<div class="card"><div class="card-body p-0">
			<table class="table card-table">
				<thead><tr>
					<th>{{ t("Tender") }}</th><th class="text-end">{{ t("Landed") }}</th>
					<th class="text-end">{{ t("PO count") }}</th><th class="text-nowrap">{{ t("Delivery deadline") }}</th><th>{{ t("Risk") }}</th>
				</tr></thead>
				<tbody>
					<SkeletonRows v-if="loading" :cols="5" :rows="6" />
					<tr v-for="r in filteredRows" :key="r.deal" style="cursor:pointer" @click="openDeal(r.deal)">
						<td class="fw-semibold">{{ r.label }}</td>
						<td class="text-end font-monospace">{{ fm(r.landed) }}</td>
						<td class="text-end">{{ r.po_count }}</td>
						<td class="text-nowrap">{{ r.delivery ? formatDate(r.delivery) : "—" }}</td>
						<td><span class="badge" :class="riskBadge(r.risk)">{{ riskLabel(r.risk) }}</span></td>
					</tr>
				</tbody>
			</table>
			<EmptyState v-if="!loading && !filteredRows.length" icon="ti-list-check" :title="t('No tenders match these filters.')" />
		</div></div>
	</div>
</template>
