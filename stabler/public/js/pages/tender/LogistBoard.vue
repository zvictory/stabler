<script setup>
// Logistician window — shipments: every tender PO with transport cost, arrival
// ETA, the tender's delivery deadline and a delay-risk status. Read-only.
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
		data.value = await call("stabler.api.tender.logist_board", { company: activeCompany.value });
	} catch (err) {
		toast.error(err?.message || t("Could not load the logistics board."));
	} finally {
		loading.value = false;
	}
}
onMounted(load);

const ccy = computed(() => data.value?.currency || "");
const rows = computed(() => data.value?.rows || []);
const fm = (v) => formatMoney(v, ccy.value, user.value.language);
const stBadge = (s) => ({ delivered: "bg-green-lt text-green", in_transit: "bg-blue-lt text-blue", late: "bg-red-lt text-red" }[s] || "bg-secondary-lt");
const stLabel = (s) => ({ delivered: t("Delivered"), in_transit: t("In transit"), late: t("Delayed") }[s] || s);
function openPo(name) { router.push("/purchasing/orders/" + encodeURIComponent(name)); }
</script>

<template>
	<div class="container-xl py-3">
		<h2 class="mb-2">{{ t("Logistics") }}</h2>
		<TenderNav />
		<div class="card"><div class="card-body p-0">
			<table class="table card-table">
				<thead><tr>
					<th>{{ t("PO") }}</th><th>{{ t("Vendor") }}</th><th>{{ t("Tender") }}</th>
					<th class="text-end">{{ t("Transport") }}</th>
					<th class="text-nowrap">{{ t("PO ETA") }}</th><th class="text-nowrap">{{ t("Delivery deadline") }}</th><th>{{ t("Status") }}</th>
				</tr></thead>
				<tbody>
					<SkeletonRows v-if="loading" :cols="7" :rows="6" />
					<tr v-for="r in rows" :key="r.po" style="cursor:pointer" @click="openPo(r.po)">
						<td class="fw-semibold">{{ r.po }}</td>
						<td>{{ r.supplier_name }}</td>
						<td class="text-secondary">{{ r.deal_label || "—" }}</td>
						<td class="text-end font-monospace">{{ r.transport ? fm(r.transport) : "—" }}</td>
						<td class="text-nowrap">{{ r.eta ? formatDate(r.eta) : "—" }}</td>
						<td class="text-nowrap" :class="r.status === 'late' ? 'text-red' : ''">{{ r.delivery ? formatDate(r.delivery) : "—" }}</td>
						<td><span class="badge" :class="stBadge(r.status)">{{ stLabel(r.status) }}</span></td>
					</tr>
				</tbody>
			</table>
			<EmptyState v-if="!loading && !rows.length" icon="ti-truck-delivery" :title="t('No shipments yet.')" />
		</div></div>
	</div>
</template>
