<script setup>
/**
 * Generic A/R + A/P aging table.
 * Props decide which endpoint to hit and how to label the party column.
 *
 *   <AgingTable
 *     endpoint="stabler.api.sales.ar_aging"
 *     partyLabel="Customer"
 *     partyKey="customer"
 *     partyNameKey="customer_name"
 *   />
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { formatMoney } from "../composables/money.js";
import { t } from "../composables/i18n.js";
import EmptyState from "./EmptyState.vue";
import DateInput from "./DateInput.vue";

const props = defineProps({
	endpoint: { type: String, required: true },
	partyLabel: { type: String, required: true },
	partyKey: { type: String, required: true },
	partyNameKey: { type: String, required: true },
	heading: { type: String, default: "Aging" },
});

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const today = new Date().toISOString().slice(0, 10);
const asOf = ref(today);

const loading = ref(false);
const error = ref("");
const data = ref({ rows: [], totals: {}, as_of: "" });

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		data.value = await call(props.endpoint, {
			company: activeCompany.value,
			as_of: asOf.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load aging.");
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);

function bucketCls(value, bucket) {
	if (!Number(value)) return "text-secondary";
	if (bucket === "b_90_plus") return "text-red fw-semibold";
	if (bucket === "b_61_90") return "text-orange fw-semibold";
	if (bucket === "b_31_60") return "text-yellow-dark";
	return "";
}
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">{{ heading }}</div>
			<div class="ms-auto d-flex gap-2 align-items-end">
				<div>
					<label class="form-label small mb-1">{{ t("As of") }}</label>
					<DateInput v-model="asOf" size="sm" />
				</div>
				<button type="button" class="btn btn-sm btn-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
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
			v-else-if="!data.rows?.length"
			icon="ti-check"
			accentIcon="ti-sparkles"
			tone="success"
			compact
			:title="t('No outstanding balances')"
			:subtitle="t('All invoices are settled as of {date}.', { date: data.as_of || asOf })"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ partyLabel }}</th>
						<th class="text-end">{{ t("Invoices") }}</th>
						<th class="text-end">{{ t("0–30") }}</th>
						<th class="text-end">{{ t("31–60") }}</th>
						<th class="text-end">{{ t("61–90") }}</th>
						<th class="text-end">{{ t("90+") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in data.rows" :key="r[partyKey]">
						<td>
							<div class="fw-semibold">{{ r[partyNameKey] || r[partyKey] }}</div>
							<div class="small text-secondary font-monospace">{{ r[partyKey] }}</div>
						</td>
						<td class="text-end font-monospace">{{ r.invoice_count }}</td>
						<td class="text-end font-monospace" :class="bucketCls(r.b_0_30, 'b_0_30')">
							{{ formatMoney(r.b_0_30, currency, user.language) }}
						</td>
						<td class="text-end font-monospace" :class="bucketCls(r.b_31_60, 'b_31_60')">
							{{ formatMoney(r.b_31_60, currency, user.language) }}
						</td>
						<td class="text-end font-monospace" :class="bucketCls(r.b_61_90, 'b_61_90')">
							{{ formatMoney(r.b_61_90, currency, user.language) }}
						</td>
						<td class="text-end font-monospace" :class="bucketCls(r.b_90_plus, 'b_90_plus')">
							{{ formatMoney(r.b_90_plus, currency, user.language) }}
						</td>
						<td class="text-end font-monospace fw-bold">
							{{ formatMoney(r.total, currency, user.language) }}
						</td>
					</tr>
				</tbody>
				<tfoot class="table-light">
					<tr class="fw-bold">
						<td>{{ t("Total") }}</td>
						<td></td>
						<td class="text-end font-monospace">{{ formatMoney(data.totals.b_0_30, currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ formatMoney(data.totals.b_31_60, currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ formatMoney(data.totals.b_61_90, currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ formatMoney(data.totals.b_90_plus, currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ formatMoney(data.totals.total, currency, user.language) }}</td>
					</tr>
				</tfoot>
			</table>
		</div>
	</div>
</template>
