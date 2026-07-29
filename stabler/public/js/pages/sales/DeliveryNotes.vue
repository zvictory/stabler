<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import { useSession } from "../../stores/session.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const loading = ref(false);
const detailLoading = ref(false);
const error = ref("");
const rows = ref([]);
const detail = ref(null);
const fromDate = ref(String(route.query.from_date || ""));
const toDate = ref(String(route.query.to_date || ""));
const tenderOnly = computed(() => route.query.tender_only === "1");
const currency = computed(
	() =>
		session.companies.find((company) => company.name === activeCompany.value)?.default_currency ||
		""
);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sales.list_delivery_notes", {
			company: activeCompany.value,
			from_date: fromDate.value || undefined,
			to_date: toDate.value || undefined,
			tender_only: tenderOnly.value ? 1 : undefined,
			limit: 5000,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load delivery notes.");
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.sales.get_delivery_note", {
			name,
			company: activeCompany.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load delivery note.");
	} finally {
		detailLoading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<div class="container-xl py-3">
		<div class="d-flex align-items-center gap-2 mb-3">
			<h2 class="mb-0">{{ t("Delivery Notes") }}</h2>
			<span v-if="tenderOnly" class="badge bg-blue-lt text-blue">{{ t("Tender records") }}</span>
			<span v-if="fromDate || toDate" class="text-secondary small">
				{{ fromDate || "…" }} — {{ toDate || "…" }}
			</span>
		</div>
		<div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>
		<div class="row row-cards">
			<div :class="detail || detailLoading ? 'col-12 col-lg-8' : 'col-12'">
				<div class="card">
					<div class="table-responsive">
						<table class="table table-vcenter card-table table-hover">
							<thead>
								<tr>
									<th>#</th>
									<th>{{ t("Date") }}</th>
									<th>{{ t("Customer") }}</th>
									<th class="text-end">{{ t("Total") }}</th>
									<th>{{ t("Status") }}</th>
								</tr>
							</thead>
							<SkeletonRows v-if="loading" :rows="5" :cols="5" />
							<tbody v-else>
								<tr
									v-for="row in rows"
									:key="row.name"
									style="cursor: pointer"
									@click="openDetail(row.name)"
								>
									<td class="font-monospace text-primary">{{ row.name }}</td>
									<td>{{ formatDate(row.posting_date) }}</td>
									<td>{{ row.customer_name || row.customer }}</td>
									<td class="text-end font-monospace">
										{{ formatMoney(row.grand_total, row.currency || currency, user.language) }}
									</td>
									<td>
										<span class="badge bg-secondary-lt">{{ t(row.status) }}</span>
									</td>
								</tr>
							</tbody>
						</table>
						<EmptyState
							v-if="!loading && !rows.length"
							icon="ti-truck-delivery"
							:title="t('No delivery notes in this range')"
							:subtitle="
								t('The dashboard count and this list use the same tender and period filters.')
							"
						/>
					</div>
				</div>
			</div>
			<div v-if="detail || detailLoading" class="col-12 col-lg-4">
				<div class="card">
					<div class="card-header">
						<h3 class="card-title">{{ detail?.name || t("Delivery Note") }}</h3>
						<button
							type="button"
							class="btn-close ms-auto"
							:aria-label="t('Close')"
							@click="detail = null"
						></button>
					</div>
					<div v-if="detailLoading" class="card-body text-secondary">{{ t("Loading…") }}</div>
					<div v-else-if="detail" class="card-body">
						<dl class="row mb-3">
							<dt class="col-5">{{ t("Customer") }}</dt>
							<dd class="col-7">{{ detail.customer_name || detail.customer }}</dd>
							<dt class="col-5">{{ t("Date") }}</dt>
							<dd class="col-7">{{ formatDate(detail.posting_date) }}</dd>
							<dt class="col-5">{{ t("Total") }}</dt>
							<dd class="col-7 font-monospace">
								{{ formatMoney(detail.grand_total, detail.currency || currency, user.language) }}
							</dd>
						</dl>
						<div
							v-for="item in detail.items"
							:key="`${item.item_code}-${item.against_sales_order}`"
							class="border-top py-2"
						>
							<div class="fw-semibold">{{ item.item_name || item.item_code }}</div>
							<div class="small text-secondary">
								<span class="font-monospace">{{ item.qty }} {{ item.uom }}</span>
								<span v-if="item.against_sales_order"> · {{ item.against_sales_order }}</span>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
