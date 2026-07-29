<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso, daysAgoIso} from "../../composables/date.js";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import { getStatusBadgeClass } from "../../composables/status.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
useEscapeBack(null, "/purchasing"); // ESC → back (general app rule)

const today = todayIso();
const monthAgo = daysAgoIso(90);
const fromDate = ref(String(route.query.from_date || monthAgo));
const toDate = ref(String(route.query.to_date || today));
const tenderOnly = computed(() => route.query.tender_only === "1");
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

const STATUSES = ["", "Paid", "Unpaid", "Overdue", "Partly Paid", "Return", "Debit Note Issued", "Draft"];

const statusOptions = computed(() => STATUSES.map((s) => ({ value: s, label: s || t("All") })));

const search = ref("");
const filteredRows = computed(() => {
	const q = search.value.toLowerCase().trim();
	if (!q) return rows.value;
	return rows.value.filter(r => 
		(r.name || "").toLowerCase().includes(q) ||
		(r.supplier || "").toLowerCase().includes(q) ||
		(r.supplier_name || "").toLowerCase().includes(q) ||
		(r.bill_no || "").toLowerCase().includes(q)
	);
});

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.purchasing.list_purchase_invoices", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			status: status.value || undefined,
			limit: tenderOnly.value ? 5000 : limit.value,
			tender_only: tenderOnly.value ? 1 : undefined,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load bills.");
	} finally {
		loading.value = false;
	}
}

function openDetail(name) {
	router.push("/purchasing/invoices/" + name);
}

function openCreate() {
	router.push("/purchasing/invoices/new");
}

// Group totals by transaction currency
const totalsByCurrency = computed(() => {
	const m = new Map();
	for (const r of filteredRows.value) {
		const ccy = r.currency || currency.value;
		const bucket = m.get(ccy) || { currency: ccy, count: 0, grand: 0, outstanding: 0 };
		bucket.count += 1;
		bucket.grand += Number(r.grand_total || 0);
		bucket.outstanding += Number(r.outstanding_amount || 0);
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
			:placeholder="t('Bill number or supplier…')"
			:count="filteredRows.length"
			:primary-label="t('New purchase invoice')"
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
					<span v-if="tenderOnly" class="badge bg-blue-lt text-blue">{{ t("Tender records") }}</span>
				</div>
			</template>

			<template #summary>
				<div class="d-flex gap-3 small text-secondary align-items-center flex-wrap">
					<div>{{ t("Count") }}: <strong class="font-monospace text-body">{{ filteredRows.length }}</strong></div>
					<div v-for="b in totalsByCurrency" :key="b.currency" class="d-flex gap-2 align-items-center">
						<span class="badge bg-secondary-lt text-secondary">{{ b.currency }}</span>
						<span>{{ t("Total") }}: <strong class="font-monospace text-body">{{ formatMoney(b.grand, b.currency, user.language) }}</strong></span>
						<span class="ms-1">{{ t("Outstanding") }}: <strong class="font-monospace text-red">{{ formatMoney(b.outstanding, b.currency, user.language) }}</strong></span>
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
			:title="t('No purchase invoices in this range')"
			:subtitle="t('Widen the date range, relax the status filter, or create a new invoice.')"
		>
			<template #actions>
				<button type="button" class="btn btn-outline-secondary btn-sm" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New purchase invoice") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">#</th>
						<th class="text-nowrap">{{ t("Posting Date") }}</th>
						<th class="text-nowrap">{{ t("Bill No.") }}</th>
						<th>{{ t("Supplier") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
						<th class="text-end">{{ t("Outstanding") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="5" :cols="7" />
				<tbody v-else>
					<tr v-for="r in filteredRows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.name }}</td>
						<td class="text-nowrap">{{ formatDate(r.posting_date) }}</td>
						<td class="text-nowrap">{{ r.bill_no || "—" }}</td>
						<td>
							<div class="fw-semibold">{{ r.supplier_name || r.supplier }}</div>
						</td>
						<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency || currency, user.language) }}</td>
						<td class="text-end font-monospace text-red">{{ formatMoney(r.outstanding_amount, r.currency || currency, user.language) }}</td>
						<td><span class="badge" :class="getStatusBadgeClass('Purchase Invoice', r.status)">{{ t(r.status) }}</span></td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
