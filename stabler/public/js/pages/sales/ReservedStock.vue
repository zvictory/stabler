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

// Page is scoped to this warehouse only — backend filters accordingly.
const LOCKED_WAREHOUSE = "Tayyor Mahsulot - A";

const loading = ref(false);
const error = ref("");
const kpis = ref(null);
const groups = ref([]);
const groupBy = ref("item"); // "item" | "so"
// Set of row keys that are currently expanded.
const expanded = ref(new Set());

// SO-based grouping derived from item groups
const soGroups = computed(() => {
	const map = new Map();
	for (const g of groups.value) {
		for (const e of g.entries) {
			if (!e.sales_order) continue;
			if (!map.has(e.sales_order)) {
				map.set(e.sales_order, {
					sales_order: e.sales_order,
					customer: e.customer,
					customer_name: e.customer_name,
					so_date: e.so_date,
					so_creation: e.so_creation,
					so_modified: e.so_modified,
					total_value: 0,
					entries: [],
				});
			}
			const sg = map.get(e.sales_order);
			sg.entries.push({ ...e, item_name: g.item_name, stock_uom: g.stock_uom });
			sg.total_value += Number(e.outstanding_value || 0);
		}
	}
	return [...map.values()].sort((a, b) => (b.so_creation || "").localeCompare(a.so_creation || ""));
});

function rowKey(g) {
	// Works for both item groups (item_code+warehouse) and SO groups (sales_order).
	return g.sales_order && !g.item_code ? g.sales_order : `${g.item_code}||${g.warehouse}`;
}
function toggleExpand(g) {
	const k = rowKey(g);
	if (expanded.value.has(k)) {
		expanded.value.delete(k);
	} else {
		expanded.value.add(k);
	}
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
			warehouse: LOCKED_WAREHOUSE,
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

const totalQtyFmt = computed(() => {
	if (!kpis.value) return "—";
	const n = Number(kpis.value.total_outstanding_qty ?? 0);
	return n.toLocaleString(user.value?.language ?? "en", {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
	});
});

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
		<div class="col-6 col-md">
			<KpiCard
				:label="t('Reserved qty')"
				:value="totalQtyFmt"
				icon="ti-stack-2"
				tone="teal"
				:loading="loading"
			/>
		</div>
		<div class="col-6 col-md">
			<KpiCard
				:label="t('Open SREs')"
				:value="kpis ? String(kpis.open_sre_count) : '—'"
				icon="ti-file-check"
				tone="blue"
				:loading="loading"
			/>
		</div>
		<div class="col-6 col-md">
			<KpiCard
				:label="t('Item·WH lines')"
				:value="kpis ? String(kpis.item_count) : '—'"
				icon="ti-box"
				tone="primary"
				:loading="loading"
			/>
		</div>
		<div class="col-6 col-md">
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
		<div class="card-header">
			<div class="d-flex align-items-center gap-2 flex-wrap">
				<!-- Group-by toggle -->
				<div class="btn-group btn-group-sm" role="group">
					<input type="radio" class="btn-check" id="gb_item" value="item" v-model="groupBy" autocomplete="off" />
					<label class="btn btn-outline-secondary" for="gb_item">
						<i class="ti ti-box me-1"></i>{{ t("By item") }}
					</label>
					<input type="radio" class="btn-check" id="gb_so" value="so" v-model="groupBy" autocomplete="off" />
					<label class="btn btn-outline-secondary" for="gb_so">
						<i class="ti ti-file-text me-1"></i>{{ t("By order") }}
					</label>
				</div>

				<!-- Warehouse indicator (locked) -->
				<span class="text-secondary small d-flex align-items-center gap-1">
					<i class="ti ti-building-warehouse"></i>
					{{ LOCKED_WAREHOUSE }}
				</span>

				<span class="text-secondary small ms-auto">
					{{ groupBy === "so" ? soGroups.length : groups.length }}
					{{ groupBy === "so" ? t("orders") : t("lines") }}
				</span>
			</div>
		</div>
		<!-- ── Item view ── -->
		<div v-if="groupBy === 'item'" class="table-responsive">
			<table class="table table-sm table-vcenter mb-0">
				<thead>
					<tr>
						<th style="width: 28px"></th>
						<th>{{ t("Item") }}</th>
						<th class="text-end font-monospace">{{ t("Outstanding") }}</th>
						<th class="text-end font-monospace">{{ t("Value (approx.)") }}</th>
						<th class="text-end" style="width: 80px">{{ t("SREs") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-if="groups.length === 0">
						<td colspan="5" class="text-center text-secondary py-4">
							{{ t("No reservations for this warehouse") }}
						</td>
					</tr>
					<template v-for="g in groups" :key="rowKey(g)">
						<tr class="cursor-pointer" style="cursor: pointer" @click="toggleExpand(g)">
							<td class="text-center text-secondary">
								<i class="ti" :class="isExpanded(g) ? 'ti-chevron-down' : 'ti-chevron-right'"></i>
							</td>
							<td>
								<div class="fw-semibold">{{ g.item_name }}</div>
								<div class="small text-secondary font-monospace">{{ g.item_code }}</div>
							</td>
							<td class="text-end font-monospace">
								{{ Number(g.total_outstanding).toFixed(2) }}
								<span class="text-secondary small ms-1">{{ g.stock_uom }}</span>
							</td>
							<td class="text-end font-monospace">{{ fmt(g.total_value) }}</td>
							<td class="text-end text-secondary small">{{ g.entries.length }}</td>
						</tr>
						<template v-if="isExpanded(g)">
							<tr v-for="e in g.entries" :key="e.sre" class="table-active" style="font-size: 0.85em">
								<td class="text-secondary font-monospace small">{{ e.sre }}</td>
								<td>
									<router-link :to="'/sales/orders/' + e.sales_order" class="fw-semibold text-decoration-none">
										{{ e.sales_order }}
									</router-link>
									<div class="small text-secondary">{{ e.customer_name || e.customer }}</div>
									<div class="text-secondary mt-1" style="font-size: 0.75em">
										<span :title="t('Created')">
											<i class="ti ti-calendar-plus me-1"></i>{{ e.so_creation ? formatDate(e.so_creation) : "—" }}
										</span>
										<span class="ms-2" :title="t('Last updated')">
											<i class="ti ti-refresh me-1"></i>{{ e.so_modified ? formatDateTime(e.so_modified) : "—" }}
										</span>
									</div>
								</td>
								<td class="text-end font-monospace">
									<div>{{ t("Rsvd") }}: {{ Number(e.reserved_qty).toFixed(2) }}</div>
									<div class="text-secondary">{{ t("Deliv") }}: {{ Number(e.delivered_qty).toFixed(2) }}</div>
								</td>
								<td class="text-end font-monospace">
									<strong>{{ Number(e.outstanding_qty).toFixed(2) }}</strong>
								</td>
								<td class="text-end">
									<span class="badge" :class="statusTone(e.status)">{{ e.status }}</span>
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

		<!-- ── SO view ── -->
		<div v-else class="table-responsive">
			<table class="table table-sm table-vcenter mb-0">
				<thead>
					<tr>
						<th style="width: 28px"></th>
						<th>{{ t("Sales Order") }}</th>
						<th>{{ t("Customer") }}</th>
						<th class="text-end font-monospace">{{ t("Value (approx.)") }}</th>
						<th class="text-end" style="width: 60px">{{ t("Items") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-if="soGroups.length === 0">
						<td colspan="5" class="text-center text-secondary py-4">{{ t("No open reservations") }}</td>
					</tr>
					<template v-for="sg in soGroups" :key="sg.sales_order">
						<tr class="cursor-pointer" style="cursor: pointer" @click="toggleExpand(sg)">
							<td class="text-center text-secondary">
								<i class="ti" :class="isExpanded(sg) ? 'ti-chevron-down' : 'ti-chevron-right'"></i>
							</td>
							<td>
								<router-link :to="'/sales/orders/' + sg.sales_order" class="fw-semibold text-decoration-none">
									{{ sg.sales_order }}
								</router-link>
								<div class="text-secondary mt-1" style="font-size: 0.75em">
									<span :title="t('Created')">
										<i class="ti ti-calendar-plus me-1"></i>{{ sg.so_creation ? formatDate(sg.so_creation) : "—" }}
									</span>
									<span class="ms-2" :title="t('Last updated')">
										<i class="ti ti-refresh me-1"></i>{{ sg.so_modified ? formatDateTime(sg.so_modified) : "—" }}
									</span>
								</div>
							</td>
							<td>
								<div class="fw-semibold">{{ sg.customer_name || sg.customer }}</div>
								<div class="small text-secondary font-monospace">{{ sg.customer }}</div>
							</td>
							<td class="text-end font-monospace">{{ fmt(sg.total_value) }}</td>
							<td class="text-end text-secondary small">{{ sg.entries.length }}</td>
						</tr>
						<template v-if="isExpanded(sg)">
							<tr v-for="e in sg.entries" :key="e.sre" class="table-active" style="font-size: 0.85em">
								<td></td>
								<td>
									<div class="fw-semibold">{{ e.item_name }}</div>
									<div class="font-monospace small text-secondary">{{ e.item_code }}</div>
								</td>
								<td class="text-secondary small">{{ e.sre }}</td>
								<td class="text-end font-monospace">
									<strong>{{ Number(e.outstanding_qty).toFixed(2) }}</strong>
									<span class="text-secondary small ms-1">{{ e.stock_uom }}</span>
								</td>
								<td class="text-end">
									<span class="badge" :class="statusTone(e.status)">{{ e.status }}</span>
								</td>
							</tr>
						</template>
					</template>
				</tbody>
			</table>
		</div>
	</div>
</template>
