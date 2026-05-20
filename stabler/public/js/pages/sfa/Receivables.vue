<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const fallbackCurrency = computed(
	() => session.companyMeta(activeCompany.value)?.default_currency || "UZS"
);
const lang = computed(() => user.value?.language || "en");

const totalOutstanding = computed(() =>
	rows.value.reduce((sum, r) => sum + (Number(r.outstanding_amount) || 0), 0)
);

async function load() {
	if (!activeCompany.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sfa.list_receivables", {
			company: activeCompany.value,
		});
	} catch (e) {
		error.value = e?.message || t("Something went wrong");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Receivables") }}</h3>
			<div v-if="rows.length" class="ms-auto text-secondary">
				{{ t("Total outstanding") }}:
				<strong>{{ formatMoney(totalOutstanding, fallbackCurrency, lang) }}</strong>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-receipt-2"
			:title="t('No receivables')"
			:description="t('All sales invoices for this company are fully paid.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Invoice") }}</th>
						<th>{{ t("Customer") }}</th>
						<th>{{ t("Posting Date") }}</th>
						<th>{{ t("Due Date") }}</th>
						<th class="text-end">{{ t("Grand Total") }}</th>
						<th class="text-end">{{ t("Outstanding") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ r.name }}</td>
						<td>{{ r.customer }}</td>
						<td>{{ r.posting_date || "—" }}</td>
						<td>{{ r.due_date || "—" }}</td>
						<td class="text-end">
							{{ formatMoney(r.grand_total, r.currency || fallbackCurrency, lang) }}
						</td>
						<td class="text-end">
							<strong>
								{{ formatMoney(r.outstanding_amount, r.currency || fallbackCurrency, lang) }}
							</strong>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
