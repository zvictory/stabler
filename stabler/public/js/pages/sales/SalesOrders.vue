<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime, todayIso} from "../../composables/date.js";
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
useEscapeBack(null, "/sales"); // ESC → back (general app rule)

const today = todayIso();
const monthAgo = new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10);
const fromDate = ref(monthAgo);
const toDate = ref(today);
const status = ref("");
const search = ref("");
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
	"To Deliver and Bill",
	"To Bill",
	"To Deliver",
	"Completed",
	"Cancelled",
	"Closed",
	"On Hold",
];

const statusOptions = computed(() =>
	STATUSES.map((s) => ({ value: s, label: s ? t(s) : t("All") }))
);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sales.list_sales_orders", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			status: status.value || undefined,
			search: search.value || undefined,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load sales orders.");
	} finally {
		loading.value = false;
	}
}

const totals = computed(() => ({
	count: rows.value.length,
	grand: rows.value.reduce((s, r) => s + Number(r.grand_total || 0), 0),
}));

const showReservedColumn = computed(() => {
	return rows.value.some((r) => r.reservation_status === "Partially Reserved");
});

function openOrder(name) {
	router.push("/sales/orders/" + name);
}
function newOrder() {
	router.push("/sales/orders/new");
}

watch([fromDate, toDate, status], load);
watch(activeCompany, load);

onMounted(load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('SO number or customer…')"
			:count="totals.count"
			:total-label="t('Total')"
			:total-value="formatMoney(totals.grand, currency, user.language)"
			:primary-label="t('New sales order')"
			primary-icon="ti-plus"
			@search="load"
			@primary-click="newOrder"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2">
					<DateInput v-model="fromDate" size="sm" style="width: 110px" />
					<span class="text-secondary small">—</span>
					<DateInput v-model="toDate" size="sm" style="width: 110px" />
					<Select v-model="status" size="sm" :options="statusOptions" style="width: 160px" />
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!loading && !rows.length"
			icon="ti-clipboard-check"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No sales orders in this range')"
			:subtitle="t('Widen the date range, relax the status filter, or start a new order.')"
		>
			<template #actions>
				<button type="button" class="btn btn-primary btn-sm" @click="newOrder">
					<i class="ti ti-plus me-1"></i>{{ t("New sales order") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">#</th>
						<th class="text-nowrap">{{ t("Date") }}</th>
						<th>{{ t("Customer") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
						<th class="text-end">{{ t("Delivered") }}</th>
						<th class="text-end">{{ t("Billed") }}</th>
						<th>{{ t("Status") }}</th>
						<th v-if="showReservedColumn">{{ t("Reserved") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="5" :cols="showReservedColumn ? 8 : 7" />
				<tbody v-else>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openOrder(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.name }}</td>
						<td class="text-nowrap">{{ formatDateTime(r.transaction_date) }}</td>
						<td>
							<div class="fw-semibold">{{ r.customer_name || r.customer }}</div>
						</td>
						<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency || currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ Number(r.per_delivered || 0).toFixed(0) }}%</td>
						<td class="text-end font-monospace">{{ Number(r.per_billed || 0).toFixed(0) }}%</td>
						<td><span class="badge" :class="getStatusBadgeClass('Sales Order', r.status)">{{ t(r.status) }}</span></td>
						<td v-if="showReservedColumn">
							<span v-if="r.reservation_status === 'Partially Reserved'" class="badge bg-yellow-lt">
								<i class="ti ti-lock-open me-1"></i>{{ t("Partially Reserved") }}
							</span>
							<span v-else class="text-secondary small">—</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
