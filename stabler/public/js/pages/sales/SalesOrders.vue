<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();

const today = new Date().toISOString().slice(0, 10);
const monthAgo = new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10);
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

const statusBadge = (s) => {
	const m = {
		Draft: "bg-secondary-lt",
		"To Deliver and Bill": "bg-yellow-lt",
		"To Bill": "bg-orange-lt",
		"To Deliver": "bg-blue-lt",
		Completed: "bg-green-lt",
		Cancelled: "bg-red-lt",
		Closed: "bg-secondary-lt",
		"On Hold": "bg-purple-lt",
	};
	return m[s] || "bg-secondary-lt";
};

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

function openOrder(name) {
	router.push("/sales/orders/" + name);
}
function newOrder() {
	router.push("/sales/orders/new");
}

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">{{ t("Sales Orders") }}</div>
			<div class="ms-auto d-flex gap-2 align-items-end flex-wrap">
				<div>
					<label class="form-label small mb-1">{{ t("From") }}</label>
					<DateInput v-model="fromDate" size="sm" />
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("To") }}</label>
					<DateInput v-model="toDate" size="sm" />
				</div>
				<div style="min-width: 180px">
					<label class="form-label small mb-1">{{ t("Status") }}</label>
					<Select v-model="status" size="sm" :options="statusOptions" />
				</div>
				<button type="button" class="btn btn-sm btn-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
				</button>
				<button type="button" class="btn btn-sm btn-success" @click="newOrder">
					<i class="ti ti-plus me-1"></i>{{ t("New sales order") }}
				</button>
			</div>
		</div>

		<div v-if="rows.length" class="card-body py-2 border-bottom bg-light">
			<div class="d-flex gap-4 small">
				<div>{{ t("Count") }}: <strong>{{ totals.count }}</strong></div>
				<div>{{ t("Total") }}: <strong class="font-monospace">{{ formatMoney(totals.grand, currency, user.language) }}</strong></div>
			</div>
		</div>

		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-clipboard-check"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No sales orders in this range')"
			:subtitle="t('Widen the date range, relax the status filter, or start a new order.')"
		>
			<template #actions>
				<button type="button" class="btn btn-primary" @click="newOrder">
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
						<th>{{ t("Reserved") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openOrder(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.name }}</td>
						<td class="text-nowrap">{{ formatDateTime(r.transaction_date) }}</td>
						<td>
							<div class="fw-semibold">{{ r.customer_name || r.customer }}</div>
						</td>
						<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency || currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ Number(r.per_delivered || 0).toFixed(0) }}%</td>
						<td class="text-end font-monospace">{{ Number(r.per_billed || 0).toFixed(0) }}%</td>
						<td><span class="badge" :class="statusBadge(r.status)">{{ t(r.status) }}</span></td>
						<td>
							<span v-if="r.has_reservations" class="badge bg-green-lt">
								<i class="ti ti-lock me-1"></i>{{ t("Reserved") }}
							</span>
							<span v-else class="text-secondary small">—</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
