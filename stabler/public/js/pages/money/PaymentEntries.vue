<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import EmptyState from "../../components/EmptyState.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const router = useRouter();
const { activeCompany, user } = storeToRefs(session);

const today = todayIso();
const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
const fromDate = ref(monthAgo);
const toDate = ref(today);
const limit = ref(50);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const statusBadge = (d) => {
	if (d === 0) return { cls: "bg-yellow-lt", label: t("Draft") };
	if (d === 1) return { cls: "bg-green-lt", label: t("Submitted") };
	if (d === 2) return { cls: "bg-red-lt", label: t("Cancelled") };
	return { cls: "bg-secondary-lt", label: String(d) };
};

const typeBadge = (t) => {
	if (t === "Receive") return { cls: "bg-green-lt", icon: "ti-arrow-down-left" };
	if (t === "Pay") return { cls: "bg-red-lt", icon: "ti-arrow-up-right" };
	return { cls: "bg-secondary-lt", icon: "ti-arrows-exchange" };
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.money.list_payment_entries", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load payment entries.");
	} finally {
		loading.value = false;
	}
}

function openDetail(name) {
	router.push("/money/payments/" + name);
}

function openCreate() {
	router.push("/money/payments/new");
}

const search = ref("");
const filteredRows = computed(() => {
	const q = search.value.toLowerCase().trim();
	if (!q) return rows.value;
	return rows.value.filter(r => 
		(r.name || "").toLowerCase().includes(q) ||
		(r.party || "").toLowerCase().includes(q) ||
		(r.party_name || "").toLowerCase().includes(q) ||
		(r.reference_no || "").toLowerCase().includes(q)
	);
});

onMounted(load);
watch([fromDate, toDate], load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Payment number, reference or party…')"
			:count="filteredRows.length"
			:primary-label="t('New payment')"
			primary-icon="ti-plus"
			@search="load"
			@primary-click="openCreate"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2">
					<DateInput v-model="fromDate" size="sm" style="width: 110px" />
					<span class="text-secondary small">—</span>
					<DateInput v-model="toDate" size="sm" style="width: 110px" />
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!loading && !filteredRows.length"
			icon="ti-cash"
			accentIcon="ti-plus"
			tone="success"
			:title="t('No payments recorded in this range')"
			:subtitle="t('Widen the date range or create a new payment receipt/payment.')"
		>
			<template #actions>
				<button type="button" class="btn btn-outline-success btn-sm" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New payment") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">#</th>
						<th class="text-nowrap">{{ t("Date") }}</th>
						<th>{{ t("Type") }}</th>
						<th>{{ t("Party") }}</th>
						<th>{{ t("Ref No.") }}</th>
						<th class="text-end">{{ t("Amount") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="5" :cols="7" />
				<tbody v-else>
					<tr v-for="r in filteredRows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.name }}</td>
						<td class="text-nowrap">{{ formatDate(r.posting_date) }}</td>
						<td>
							<span class="badge" :class="typeBadge(r.payment_type).cls">
								<i class="ti me-1" :class="typeBadge(r.payment_type).icon"></i>{{ r.payment_type }}
							</span>
						</td>
						<td>
							<div class="fw-semibold">{{ r.party_name || r.party }}</div>
							<div class="small text-secondary">{{ r.party_type }}</div>
						</td>
						<td>
							<div class="font-monospace small text-truncate" style="max-width: 150px">{{ r.reference_no || "—" }}</div>
						</td>
						<td class="text-end font-monospace">
							{{ formatMoney(r.grand_total, r.party_account_currency || currency, user.language) }}
						</td>
						<td><span class="badge" :class="statusBadge(r.docstatus).cls">{{ statusBadge(r.docstatus).label }}</span></td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
