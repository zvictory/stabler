<script setup>
// Sourcing window — "my tenders": the tender pipeline with landed cost, PO count
// and deadline risk. Entry point into the per-tender sourcing/PO tools.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import TenderNav from "./TenderNav.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
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

const ccy = computed(() => data.value?.currency || "");
const rows = computed(() => data.value?.rows || []);
const fm = (v) => formatMoney(v, ccy.value, user.value.language);
const riskBadge = (r) => ({ good: "bg-green-lt text-green", warn: "bg-yellow-lt text-yellow", risk: "bg-red-lt text-red" }[r] || "bg-secondary-lt");
const riskLabel = (r) => ({ good: t("On track"), warn: t("Deadline near"), risk: t("At risk"), none: "—" }[r] || "—");
function openDeal(deal) { router.push("/tender/po-control?deal=" + encodeURIComponent(deal)); }
</script>

<template>
	<div class="container-xl py-3">
		<h2 class="mb-2">{{ t("My tenders") }}</h2>
		<TenderNav />
		<div class="card"><div class="card-body p-0">
			<table class="table card-table">
				<thead><tr>
					<th>{{ t("Tender") }}</th><th class="text-end">{{ t("Landed") }}</th>
					<th class="text-end">{{ t("PO count") }}</th><th class="text-nowrap">{{ t("Delivery deadline") }}</th><th>{{ t("Risk") }}</th>
				</tr></thead>
				<tbody>
					<SkeletonRows v-if="loading" :cols="5" :rows="6" />
					<tr v-for="r in rows" :key="r.deal" style="cursor:pointer" @click="openDeal(r.deal)">
						<td class="fw-semibold">{{ r.label }}</td>
						<td class="text-end font-monospace">{{ fm(r.landed) }}</td>
						<td class="text-end">{{ r.po_count }}</td>
						<td class="text-nowrap">{{ r.delivery ? formatDate(r.delivery) : "—" }}</td>
						<td><span class="badge" :class="riskBadge(r.risk)">{{ riskLabel(r.risk) }}</span></td>
					</tr>
				</tbody>
			</table>
			<EmptyState v-if="!loading && !rows.length" icon="ti-list-check" :title="t('No tenders assigned yet.')" />
		</div></div>
	</div>
</template>
