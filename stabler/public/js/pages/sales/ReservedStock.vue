<script setup>
import { ref, computed, onMounted, watch } from "vue";
import { useSession } from "../../stores/session.js";
import { storeToRefs } from "pinia";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import KpiCard from "../../components/KpiCard.vue";

const session = useSession();
const { user, activeCompany } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const kpis = ref(null);
const groups = ref([]);
// Set of "item_code||warehouse" strings that are currently expanded.
const expanded = ref(new Set());

function rowKey(g) {
	return `${g.item_code}||${g.warehouse}`;
}
function toggleExpand(g) {
	const k = rowKey(g);
	if (expanded.value.has(k)) {
		expanded.value.delete(k);
	} else {
		expanded.value.add(k);
	}
	// trigger reactivity on the Set
	expanded.value = new Set(expanded.value);
}
function isExpanded(g) {
	return expanded.value.has(rowKey(g));
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const data = await call("stabler.api.sales.reserved_stock_analysis", {
			company: activeCompany.value,
		});
		kpis.value = data.kpis;
		groups.value = data.groups || [];
		expanded.value = new Set();
	} catch (err) {
		error.value = err?.message || t("Failed to load reserved stock data.");
	} finally {
		loading.value = false;
	}
}

function fmt(val) {
	return formatMoney(val ?? 0, null, user.value?.language);
}

const totalValueFmt = computed(() =>
	kpis.value ? fmt(kpis.value.total_outstanding_value) : "—"
);

function statusTone(status) {
	const map = {
		Reserved: "badge-primary",
		"Partially Reserved": "badge-warning",
		"Partially Delivered": "badge-warning",
		Draft: "badge-secondary",
	};
	return map[status] || "badge-secondary";
}

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<!-- KPI headline row -->
	<div class="row row-cards mb-3">
		<div class="col-6 col-md-3">
			<KpiCard
				:label="t('Reserved value')"
				:value="totalValueFmt"
				icon="ti-lock"
				tone="warning"
				:loading="loading"
				:hint="t('Approx. at current valuation rate')"
			/>
		</div>
		<div class="col-6 col-md-3">
			<KpiCard
				:label="t('Open SREs')"
				:value="kpis ? String(kpis.open_sre_count) : '—'"
				icon="ti-file-check"
				tone="blue"
				:loading="loading"
			/>
		</div>
		<div class="col-6 col-md-3">
			<KpiCard
				:label="t('Item·WH lines')"
				:value="kpis ? String(kpis.item_count) : '—'"
				icon="ti-box"
				tone="primary"
				:loading="loading"
			/>
		</div>
		<div class="col-6 col-md-3">
			<KpiCard
				:label="t('Oldest reservation')"
				:value="kpis?.oldest_reserved_on ? formatDate(kpis.oldest_reserved_on) : '—'"
				icon="ti-calendar"
				tone="secondary"
				:loading="loading"
			/>
		</div>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<!-- Empty state -->
	<div v-else-if="!loading && groups.length === 0" class="text-center text-secondary py-5">
		<i class="ti ti-lock-open fs-2 d-block mb-2"></i>
		{{ t("No open reservations") }}
	</div>

	<!-- Rollup table -->
	<div v-else class="card">
		<div class="table-responsive">
			<table class="table table-sm table-vcenter mb-0">
				<thead>
					<tr>
						<th style="width: 28px"></th>
						<th>{{ t("Item") }}</th>
						<th>{{ t("Warehouse") }}</th>
						<th class="text-end font-monospace">{{ t("Outstanding") }}</th>
						<th class="text-end font-monospace">{{ t("Value (approx.)") }}</th>
						<th class="text-end" style="width: 80px">{{ t("SREs") }}</th>
					</tr>
				</thead>
				<tbody>
					<template v-for="g in groups" :key="rowKey(g)">
						<!-- Summary row -->
						<tr
							class="cursor-pointer"
							style="cursor: pointer"
							@click="toggleExpand(g)"
						>
							<td class="text-center text-secondary">
								<i
									class="ti"
									:class="isExpanded(g) ? 'ti-chevron-down' : 'ti-chevron-right'"
								></i>
							</td>
							<td>
								<div class="fw-semibold">{{ g.item_name }}</div>
								<div class="small text-secondary font-monospace">{{ g.item_code }}</div>
							</td>
							<td class="text-secondary small">{{ g.warehouse }}</td>
							<td class="text-end font-monospace">
								{{ Number(g.total_outstanding).toFixed(2) }}
								<span class="text-secondary small ms-1">{{ g.stock_uom }}</span>
							</td>
							<td class="text-end font-monospace">{{ fmt(g.total_value) }}</td>
							<td class="text-end text-secondary small">{{ g.entries.length }}</td>
						</tr>
						<!-- Expanded SRE detail rows -->
						<template v-if="isExpanded(g)">
							<tr
								v-for="e in g.entries"
								:key="e.sre"
								class="table-active"
								style="font-size: 0.85em"
							>
								<td></td>
								<td colspan="1">
									<div class="font-monospace small text-secondary">{{ e.sre }}</div>
								</td>
								<td>
									<router-link
										:to="'/sales/orders/' + e.sales_order"
										class="fw-semibold text-decoration-none"
									>
										{{ e.sales_order }}
									</router-link>
									<div class="small text-secondary">{{ e.customer_name || e.customer }}</div>
								</td>
								<td class="text-end font-monospace">
									<div>
										{{ t("Rsvd") }}: {{ Number(e.reserved_qty).toFixed(2) }}
									</div>
									<div class="text-secondary">
										{{ t("Deliv") }}: {{ Number(e.delivered_qty).toFixed(2) }}
									</div>
								</td>
								<td class="text-end font-monospace">
									<strong>{{ Number(e.outstanding_qty).toFixed(2) }}</strong>
								</td>
								<td class="text-end">
									<div>
										<span class="badge" :class="statusTone(e.status)">{{ e.status }}</span>
									</div>
									<div class="text-secondary small mt-1">
										{{ e.reserved_on ? formatDateTime(e.reserved_on) : "—" }}
									</div>
								</td>
							</tr>
						</template>
					</template>
				</tbody>
			</table>
		</div>
	</div>
</template>
