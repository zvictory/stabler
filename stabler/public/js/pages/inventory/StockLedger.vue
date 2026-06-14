<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime, todayIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const today = todayIso();
const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
const fromDate = ref(monthAgo);
const toDate = ref(today);
const itemCode = ref("");
const warehouse = ref("");
const limit = ref(200);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const formatQty = (n, uom) => {
	const v = Number(n || 0);
	const sign = v > 0 ? "+" : "";
	return `${sign}${v.toLocaleString(user.value.language || "en", { maximumFractionDigits: 3 })} ${uom || ""}`.trim();
};

const voucherBadge = (vt) => {
	const m = {
		"Stock Entry": "bg-blue-lt",
		"Purchase Receipt": "bg-green-lt",
		"Delivery Note": "bg-orange-lt",
		"Purchase Invoice": "bg-purple-lt",
		"Sales Invoice": "bg-cyan-lt",
		"Stock Reconciliation": "bg-yellow-lt",
	};
	return m[vt] || "bg-secondary-lt";
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.inventory.stock_ledger", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			item_code: itemCode.value || undefined,
			warehouse: warehouse.value || undefined,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load stock ledger.");
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">{{ t("Stock Ledger") }}</div>
			<div class="ms-auto d-flex gap-2 align-items-end flex-wrap">
				<div>
					<label class="form-label small mb-1">{{ t("From") }}</label>
					<DateInput v-model="fromDate" size="sm" />
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("To") }}</label>
					<DateInput v-model="toDate" size="sm" />
				</div>
				<div style="min-width: 160px">
					<label class="form-label small mb-1">{{ t("Item") }}</label>
					<input v-model="itemCode" type="search" class="form-control form-control-sm" :placeholder="t('Item code')" />
				</div>
				<div style="min-width: 160px">
					<label class="form-label small mb-1">{{ t("Warehouse") }}</label>
					<input v-model="warehouse" type="search" class="form-control form-control-sm" :placeholder="t('Warehouse')" />
				</div>
				<button type="button" class="btn btn-sm btn-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
				</button>
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
			icon="ti-list-details"
			accentIcon="ti-filter"
			tone="info"
			compact
			:title="t('No stock moves in this range')"
			:subtitle="t('Widen the date range or clear filters to see stock activity.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Date") }}</th>
						<th>{{ t("Voucher") }}</th>
						<th>{{ t("Item") }}</th>
						<th>{{ t("Warehouse") }}</th>
						<th class="text-end">{{ t("Movement") }}</th>
						<th class="text-end">{{ t("Balance") }}</th>
						<th class="text-end">{{ t("Value Δ") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ formatDateTime(`${r.posting_date} ${r.posting_time}`) }}</td>
						<td>
							<span class="badge me-1" :class="voucherBadge(r.voucher_type)">{{ r.voucher_type }}</span>
							<div class="small font-monospace text-primary">{{ r.voucher_no }}</div>
						</td>
						<td>
							<div class="fw-semibold">{{ r.item_name || r.item_code }}</div>
							<div class="small text-secondary font-monospace">{{ r.item_code }}</div>
						</td>
						<td class="small">{{ r.warehouse }}</td>
						<td
							class="text-end font-monospace"
							:class="Number(r.actual_qty) >= 0 ? 'text-green' : 'text-red'"
						>
							{{ formatQty(r.actual_qty, r.stock_uom) }}
						</td>
						<td class="text-end font-monospace">{{ formatQty(r.qty_after_transaction, "") }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.stock_value_difference, currency, user.language) }}</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
