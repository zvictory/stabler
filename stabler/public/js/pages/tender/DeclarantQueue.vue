<script setup>
// Declarant window — customs queue: every tender PO awaiting/clearing customs,
// with ТН ВЭД code, customs charge and arrival ETA. Read-only.
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
const data = ref({ rows: [], currency: "" });

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.tender.declarant_queue", { company: activeCompany.value });
	} catch (err) {
		toast.error(err?.message || t("Could not load the customs queue."));
	} finally {
		loading.value = false;
	}
}
onMounted(load);
useAutoRefresh(load);

const ccy = computed(() => data.value?.currency || "");
const rows = computed(() => data.value?.rows || []);
const filters = computed(() => tenderRouteFilters(route.query));
const filterSummary = computed(() => activeTenderFilters(filters.value).map(([key, value]) => `${key}: ${value}`));
const filteredRows = computed(() => filterTenderRows(rows.value, filters.value));
const fm = (v) => formatMoney(v, ccy.value, user.value.language);
const stBadge = (s) => ({ cleared: "bg-green-lt text-green", in_progress: "bg-blue-lt text-blue", pending: "bg-yellow-lt text-yellow" }[s] || "bg-secondary-lt");
const stLabel = (s) => ({ cleared: t("Cleared"), in_progress: t("In progress"), pending: t("Pending") }[s] || s);
function etaText(r) {
	if (r.days_left == null) return "—";
	if (r.days_left < 0) return `${-r.days_left} ${t("days late")}`;
	if (r.days_left === 0) return t("today");
	return `${r.days_left} ${t("days left")}`;
}
function openPo(name) { router.push({ name: "purchasing-order", params: { name }, query: { ...route.query } }); }
function clearFilters() { router.replace({ query: {} }); }
</script>

<template>
	<div class="container-xl py-3">
		<div class="d-flex align-items-center mb-2 gap-2 flex-wrap"><h2 class="mb-0">{{ t("Customs queue") }}</h2><div v-if="filterSummary.length" class="ms-auto d-flex align-items-center gap-2"><span class="text-secondary small">{{ filterSummary.join(" · ") }}</span><button type="button" class="btn btn-sm btn-ghost-secondary" @click="clearFilters">{{ t("Clear filters") }}</button></div></div>
		<TenderNav />
		<div class="card"><div class="card-body p-0">
			<table class="table card-table">
				<thead><tr>
					<th>{{ t("PO") }}</th><th>{{ t("Vendor") }}</th><th>{{ t("Tender") }}</th>
					<th>{{ t("HS code (ТН ВЭД)") }}</th><th class="text-end">{{ t("Customs") }}</th>
					<th class="text-nowrap">{{ t("PO ETA") }}</th><th class="text-nowrap">{{ t("Days left") }}</th><th>{{ t("Status") }}</th>
				</tr></thead>
				<tbody>
					<SkeletonRows v-if="loading" :cols="8" :rows="6" />
					<tr v-for="r in filteredRows" :key="r.po" style="cursor:pointer" @click="openPo(r.po)">
						<td class="fw-semibold">{{ r.po }}</td>
						<td>{{ r.supplier_name }}</td>
						<td class="text-secondary">{{ r.deal_label || "—" }}</td>
						<td class="font-monospace">{{ r.tnved || "—" }}</td>
						<td class="text-end font-monospace">{{ r.customs_total ? fm(r.customs_total) : "—" }}</td>
						<td class="text-nowrap">{{ r.eta ? formatDate(r.eta) : "—" }}</td>
						<td class="text-nowrap" :class="r.days_left != null && r.days_left < 0 ? 'text-red' : (r.days_left != null && r.days_left <= 7 ? 'text-yellow' : '')">{{ etaText(r) }}</td>
						<td><span class="badge" :class="stBadge(r.status)">{{ stLabel(r.status) }}</span></td>
					</tr>
				</tbody>
			</table>
			<EmptyState v-if="!loading && !filteredRows.length" icon="ti-file-invoice" :title="t('No purchase orders match these filters.')" />
		</div></div>
	</div>
</template>
