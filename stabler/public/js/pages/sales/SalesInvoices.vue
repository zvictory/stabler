<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime, todayIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import EmptyState from "../../components/EmptyState.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import { getStatusBadgeClass } from "../../composables/status.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
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

const STATUSES = ["", "Paid", "Unpaid", "Overdue", "Partly Paid", "Return", "Credit Note Issued", "Draft"];
// Computed so the t()-translated labels re-render on locale change ("" = All).
const statusOptions = computed(() =>
	STATUSES.map((s) => ({ value: s, label: s ? t(s) : t("All") }))
);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sales.list_sales_invoices", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			status: status.value || undefined,
			search: search.value || undefined,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load invoices.");
	} finally {
		loading.value = false;
	}
}

function openInvoice(name) {
	router.push("/sales/invoices/" + name);
}

// Group totals by transaction currency — UZS and USD must never share a sum.
const totalsByCurrency = computed(() => {
	const m = new Map();
	for (const r of rows.value) {
		const ccy = r.currency || currency.value;
		const bucket = m.get(ccy) || { currency: ccy, count: 0, grand: 0, outstanding: 0 };
		bucket.count += 1;
		bucket.grand += Number(r.grand_total || 0);
		bucket.outstanding += Number(r.outstanding_amount || 0);
		m.set(ccy, bucket);
	}
	return Array.from(m.values());
});
const totalCount = computed(() => rows.value.length);

onMounted(() => {
	// Back-compat: a stale `?open=<name>` link now lands on the routed page.
	const openName = route.query?.open;
	if (openName) {
		router.replace("/sales/invoices/" + String(openName));
		return;
	}
	load();
});
watch([fromDate, toDate, status], load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Invoice number or customer…')"
			:count="totalCount"
			@search="load"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2">
					<DateInput v-model="fromDate" size="sm" style="width: 110px" />
					<span class="text-secondary small">—</span>
					<DateInput v-model="toDate" size="sm" style="width: 110px" />
					<Select v-model="status" size="sm" :options="statusOptions" style="width: 160px" />
					<router-link to="/sales/returns/new" class="btn btn-sm btn-outline-secondary">
						<i class="ti ti-receipt-refund me-1"></i>{{ t("New Return") }}
					</router-link>
				</div>
			</template>

			<template #summary>
				<div class="d-flex gap-3 small text-secondary align-items-center flex-wrap">
					<div>{{ t("Count") }}: <strong class="font-monospace text-body">{{ totalCount }}</strong></div>
					<div v-for="b in totalsByCurrency" :key="b.currency" class="d-flex gap-2 align-items-center">
						<span class="badge bg-secondary-lt text-secondary">{{ b.currency }}</span>
						<span>{{ t("Total") }}: <strong class="font-monospace text-body">{{ formatMoney(b.grand, b.currency, user.language) }}</strong></span>
						<span>{{ t("Outstanding") }}: <strong class="text-red font-monospace">{{ formatMoney(b.outstanding, b.currency, user.language) }}</strong></span>
					</div>
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!loading && !rows.length"
			icon="ti-file-invoice"
			accentIcon="ti-arrow-right"
			tone="primary"
			:title='t("No invoices in this range")'
			:subtitle="t('Sales Invoices are created from submitted Sales Orders. Open a Sales Order and use Create Invoice.')"
		>
			<template #actions>
				<router-link to="/sales/orders" class="btn btn-outline-secondary btn-sm">
					<i class="ti ti-clipboard-check me-1"></i>{{ t("Go to Sales Orders") }}
				</router-link>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>#</th>
						<th>{{ t("Date") }}</th>
						<th>{{ t("Due") }}</th>
						<th>{{ t("Customer") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
						<th class="text-end">{{ t("Outstanding") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="5" :cols="7" />
				<tbody v-else>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openInvoice(r.name)">
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ formatDateTime(r.posting_date) }}</td>
						<td>{{ formatDateTime(r.due_date) }}</td>
						<td>
							<div class="fw-semibold">{{ r.customer_name || r.customer }}</div>
						</td>
						<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency || currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.outstanding_amount, r.currency || currency, user.language) }}</td>
						<td><span class="badge" :class="getStatusBadgeClass('Sales Invoice', r.status)">{{ t(r.status) }}</span></td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
