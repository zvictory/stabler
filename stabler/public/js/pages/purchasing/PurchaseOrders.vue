<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso, daysAgoIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import { getStatusBadgeClass } from "../../composables/status.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
useEscapeBack(null, "/purchasing"); // ESC → back (general app rule)

const today = todayIso();
const monthAgo = daysAgoIso(90);
const fromDate = ref(monthAgo);
const toDate = ref(today);
const status = ref("");
const limit = ref(100);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const STATUSES = [
	"",
	"Draft",
	"To Receive and Bill",
	"To Bill",
	"To Receive",
	"Completed",
	"Cancelled",
	"Closed",
	"On Hold",
];

const statusOptions = computed(() => STATUSES.map((s) => ({ value: s, label: s || t("All") })));

const search = ref("");
const filteredRows = computed(() => {
	const q = search.value.toLowerCase().trim();
	if (!q) return rows.value;
	return rows.value.filter(r => 
		(r.name || "").toLowerCase().includes(q) ||
		(r.supplier || "").toLowerCase().includes(q) ||
		(r.supplier_name || "").toLowerCase().includes(q)
	);
});

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.purchasing.list_purchase_orders", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			status: status.value || undefined,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load purchase orders.");
	} finally {
		loading.value = false;
	}
}

function openDetail(name) {
	router.push("/purchasing/orders/" + name);
}

function openCreate() {
	router.push("/purchasing/orders/new");
}

// Multi-currency bucket totals
const totalsByCurrency = computed(() => {
	const m = new Map();
	for (const r of filteredRows.value) {
		const ccy = r.currency || currency.value;
		const bucket = m.get(ccy) || { currency: ccy, count: 0, grand: 0 };
		bucket.count += 1;
		bucket.grand += Number(r.grand_total || 0);
		m.set(ccy, bucket);
	}
	return Array.from(m.values());
});

onMounted(load);
watch([fromDate, toDate, status], load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Order number or supplier…')"
			:count="filteredRows.length"
			:primary-label="t('New purchase order')"
			primary-icon="ti-plus"
			@search="load"
			@primary-click="openCreate"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2">
					<DateInput v-model="fromDate" size="sm" style="width: 110px" />
					<span class="text-secondary small">—</span>
					<DateInput v-model="toDate" size="sm" style="width: 110px" />
					<Select v-model="status" size="sm" :options="statusOptions" style="width: 160px" />
				</div>
			</template>

			<template #summary>
				<div class="d-flex gap-3 small text-secondary align-items-center flex-wrap">
					<div>{{ t("Count") }}: <strong class="font-monospace text-body">{{ filteredRows.length }}</strong></div>
					<div v-for="b in totalsByCurrency" :key="b.currency" class="d-flex gap-2 align-items-center">
						<span class="badge bg-secondary-lt text-secondary">{{ b.currency }}</span>
						<span>{{ t("Total") }}: <strong class="font-monospace text-body">{{ formatMoney(b.grand, b.currency, user.language) }}</strong></span>
					</div>
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!loading && !filteredRows.length"
			icon="ti-clipboard-list"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No purchase orders in this range')"
			:subtitle="t('Widen the date range, relax the status filter, or create a new order.')"
		>
			<template #actions>
				<button type="button" class="btn btn-outline-secondary btn-sm" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New purchase order") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">#</th>
						<th class="text-nowrap">{{ t("Order Date") }}</th>
						<th class="text-nowrap">{{ t("Schedule") }}</th>
						<th>{{ t("Supplier") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
						<th class="text-end">{{ t("Received") }}</th>
						<th class="text-end">{{ t("Billed") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="5" :cols="8" />
				<tbody v-else>
					<tr v-for="r in filteredRows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.name }}</td>
						<td class="text-nowrap">{{ formatDate(r.transaction_date) }}</td>
						<td class="text-nowrap">{{ formatDate(r.schedule_date) || "—" }}</td>
						<td>
							<div class="fw-semibold">{{ r.supplier_name || r.supplier }}</div>
						</td>
						<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency || currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ Number(r.per_received || 0).toFixed(0) }}%</td>
						<td class="text-end font-monospace">{{ Number(r.per_billed || 0).toFixed(0) }}%</td>
						<td><span class="badge" :class="getStatusBadgeClass('Purchase Order', r.status)">{{ t(r.status) }}</span></td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
