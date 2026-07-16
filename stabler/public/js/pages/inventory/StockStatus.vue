<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import EmptyState from "../../components/EmptyState.vue";
import { t } from "../../composables/i18n.js";
import Select from "../../components/Select.vue";
import ItemValuationDrawer from "../../components/ItemValuationDrawer.vue";

const session = useSession();
const route = useRoute();
const router = useRouter();
const { activeCompany, user } = storeToRefs(session);

const warehouseLoading = ref(false);
const stockLoading = ref(false);
const error = ref("");
const stockError = ref("");
const warehouses = ref([]);
const selectedWarehouse = ref("");
const stock = ref(null);
const itemSearch = ref("");
const showOnlyAnomalous = ref(false);

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const stockWarehouses = computed(() => warehouses.value.filter((warehouse) => !warehouse.is_group && !warehouse.disabled));
const warehouseOptions = computed(() =>
	stockWarehouses.value.map((warehouse) => ({
		value: warehouse.name,
		label: warehouse.warehouse_name || warehouse.name,
		stock_value: warehouse.stock_value || 0,
		type: warehouse.warehouse_type || "",
	}))
);
const selectedWarehouseInfo = computed(
	() => stockWarehouses.value.find((warehouse) => warehouse.name === selectedWarehouse.value) || null
);
const stockItems = computed(() => stock.value?.items || []);
const filteredItems = computed(() => {
	let list = stockItems.value;
	if (showOnlyAnomalous.value) {
		const anomalousCodes = new Set(stock.value?.anomalies?.map((a) => a.item_code) || []);
		list = list.filter((item) => anomalousCodes.has(item.item_code));
	}
	const query = itemSearch.value.trim().toLowerCase();
	if (!query) return list;
	return list.filter((item) =>
		`${item.item_code || ""} ${item.item_name || ""} ${item.item_group || ""}`.toLowerCase().includes(query)
	);
});

function getAnomaly(itemCode) {
	return stock.value?.anomalies?.find((a) => a.item_code === itemCode) || null;
}

function formatQty(value, uom) {
	const qty = Number(value || 0).toLocaleString(user.value.language || "en", {
		maximumFractionDigits: 3,
	});
	return `${qty} ${uom || ""}`.trim();
}

function bestWarehouse(rows, requested) {
	if (requested && rows.some((warehouse) => warehouse.name === requested)) return requested;
	const stocked = rows.find((warehouse) => Number(warehouse.stock_value || 0) > 0);
	return stocked?.name || rows[0]?.name || "";
}

async function loadStock() {
	if (!activeCompany.value || !selectedWarehouse.value) {
		stock.value = null;
		return;
	}
	stockLoading.value = true;
	stockError.value = "";
	try {
		stock.value = await call("stabler.api.inventory.warehouse_stock", {
			company: activeCompany.value,
			warehouse: selectedWarehouse.value,
			limit: 500,
		});
	} catch (err) {
		stock.value = null;
		stockError.value = err?.message || t("Failed to load stock status.");
	} finally {
		stockLoading.value = false;
	}
}

async function loadWarehouses() {
	if (!activeCompany.value) return;
	warehouseLoading.value = true;
	error.value = "";
	stockError.value = "";
	try {
		const rows = await call("stabler.api.inventory.list_warehouses", {
			company: activeCompany.value,
		});
		warehouses.value = rows || [];
		const nextWarehouse = bestWarehouse(stockWarehouses.value, route.query.warehouse);
		selectedWarehouse.value = nextWarehouse;
		showOnlyAnomalous.value = false;
		if (nextWarehouse && nextWarehouse !== route.query.warehouse) {
			await router.replace({ path: "/inventory/stock-status", query: { warehouse: nextWarehouse } });
		}
		await loadStock();
	} catch (err) {
		error.value = err?.message || t("Failed to load warehouses.");
		warehouses.value = [];
		stock.value = null;
	} finally {
		warehouseLoading.value = false;
	}
}

async function selectWarehouse(value) {
	selectedWarehouse.value = value || "";
	itemSearch.value = "";
	showOnlyAnomalous.value = false;
	if (selectedWarehouse.value) {
		await router.replace({ path: "/inventory/stock-status", query: { warehouse: selectedWarehouse.value } });
	}
	await loadStock();
}

// ── Item valuation drill-down ─────────────────────────────────────────────────
const drillOpen = ref(false);
const drillLoading = ref(false);
const drillItem = ref(null);
const drillHistory = ref(null);

async function openItemDrill(item) {
	drillItem.value = item;
	drillOpen.value = true;
	drillLoading.value = true;
	drillHistory.value = null;
	try {
		drillHistory.value = await call("stabler.api.inventory.item_valuation_history", {
			company: activeCompany.value,
			item_code: item.item_code,
			// warehouse intentionally omitted → company-wide history (all warehouses)
		});
	} catch (err) {
		drillHistory.value = { error: err?.message || t("Failed to load valuation history.") };
	} finally {
		drillLoading.value = false;
	}
}

onMounted(loadWarehouses);
watch(activeCompany, loadWarehouses);
watch(
	() => route.query.warehouse,
	async (warehouse) => {
		if (warehouse && warehouse !== selectedWarehouse.value && stockWarehouses.value.some((row) => row.name === warehouse)) {
			selectedWarehouse.value = warehouse;
			itemSearch.value = "";
			await loadStock();
		}
	}
);
</script>

<template>
	<div>
		<div class="card mb-3">
			<div class="card-header d-flex align-items-center gap-2">
				<div class="card-title m-0 d-flex align-items-center gap-2">
					<i class="ti ti-packages text-blue"></i>
					{{ t("Stock Status") }}
				</div>
				<router-link to="/inventory/warehouses" class="btn btn-sm btn-ghost-secondary ms-auto">
					<i class="ti ti-building-warehouse me-1"></i>{{ t("Warehouses") }}
				</router-link>
			</div>
			<div class="card-body">
				<div class="row g-3 align-items-end">
					<div class="col-lg-7">
						<label class="form-label">{{ t("Warehouse") }}</label>
						<Select
							v-model="selectedWarehouse"
							:options="warehouseOptions"
							:disabled="warehouseLoading"
							:placeholder="t('Select warehouse…')"
							@update:modelValue="selectWarehouse"
						>
							<template #option="{ option }">
								<div class="d-flex align-items-center justify-content-between gap-3">
									<span>{{ option.label }}</span>
									<span class="text-secondary font-monospace small">{{ formatMoney(option.stock_value, currency, user.language) }}</span>
								</div>
							</template>
							<template #selected="{ option }">
								{{ option.label }}
							</template>
						</Select>
					</div>
					<div class="col-lg-5">
						<label class="form-label">{{ t("Find item") }}</label>
						<input
							v-model="itemSearch"
							type="search"
							class="form-control"
							:placeholder="t('Item code, name, or group…')"
							:disabled="!stockItems.length"
						/>
					</div>
				</div>
				<div v-if="selectedWarehouseInfo" class="small text-secondary mt-2">
					<span class="font-monospace">{{ selectedWarehouseInfo.name }}</span>
					<span v-if="selectedWarehouseInfo.warehouse_type"> · {{ selectedWarehouseInfo.warehouse_type }}</span>
				</div>
			</div>
		</div>

		<div v-if="warehouseLoading" class="card">
			<div class="card-body text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
		</div>
		<div v-else-if="error" class="alert alert-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!stockWarehouses.length"
			icon="ti-building-warehouse"
			accentIcon="ti-packages"
			tone="info"
			:title="t('No stock warehouses')"
			:subtitle="t('Create an active leaf warehouse before viewing item stock status.')"
		/>
		<div v-else>
			<div class="row row-cards mb-3">
				<div class="col-sm-6 col-xl-3">
					<div class="card">
						<div class="card-body">
							<div class="text-secondary small">{{ t("Items") }}</div>
							<div class="h2 m-0 font-monospace">{{ stock?.item_count || 0 }}</div>
						</div>
					</div>
				</div>
				<div class="col-sm-6 col-xl-3">
					<div class="card">
						<div class="card-body">
							<div class="text-secondary small">{{ t("On hand") }}</div>
							<div class="h2 m-0 font-monospace">{{ formatQty(stock?.total_qty || 0, "") }}</div>
						</div>
					</div>
				</div>
				<div class="col-sm-6 col-xl-3">
					<div class="card">
						<div class="card-body">
							<div class="text-secondary small">{{ t("Free qty") }}</div>
							<div class="h2 m-0 font-monospace">{{ formatQty(stock?.total_free_qty || 0, "") }}</div>
						</div>
					</div>
				</div>
				<div class="col-sm-6 col-xl-3">
					<div class="card">
						<div class="card-body">
							<div class="text-secondary small">{{ t("Stock value") }}</div>
							<div class="h2 m-0 font-monospace">{{ formatMoney(stock?.total_value || 0, currency, user.language) }}</div>
						</div>
					</div>
				</div>
			</div>

			<div v-if="stock?.anomalies?.length" class="alert alert-warning d-flex align-items-center justify-content-between mb-3 py-2 px-3">
				<div>
					<i class="ti ti-alert-triangle text-warning me-2 fs-3"></i>
					<span>
						{{ t("Found {0} stock valuation anomalies (missing costs or suspicious rates).", [stock.anomalies.length]) }}
					</span>
				</div>
				<button
					type="button"
					class="btn btn-sm btn-outline-warning"
					@click="showOnlyAnomalous = !showOnlyAnomalous"
				>
					{{ showOnlyAnomalous ? t("Show all items") : t("Filter warnings") }}
				</button>
			</div>

			<div class="card">
				<div class="card-header">
					<div class="card-title m-0">
						{{ selectedWarehouseInfo?.warehouse_name || selectedWarehouseInfo?.name || t("Warehouse stock") }}
					</div>
					<button type="button" class="btn btn-sm btn-ghost-secondary ms-auto" :disabled="stockLoading" @click="loadStock">
						<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
					</button>
				</div>
				<div v-if="stockLoading" class="card-body text-center py-5">
					<div class="spinner-border text-primary"></div>
				</div>
				<div v-else-if="stockError" class="card-body">
					<div class="alert alert-danger m-0">{{ stockError }}</div>
				</div>
				<EmptyState
					v-else-if="!stockItems.length"
					icon="ti-package-off"
					accentIcon="ti-building-warehouse"
					tone="info"
					:title="t('No stock in this warehouse')"
					:subtitle="t('This warehouse has no current item balances.')"
				/>
				<EmptyState
					v-else-if="!filteredItems.length"
					icon="ti-search"
					accentIcon="ti-filter"
					tone="info"
					:title="t('No matching items')"
					:subtitle="t('Try another item code, name, or group.')"
				/>
				<div v-else class="table-responsive">
					<table class="table table-vcenter card-table">
						<thead>
							<tr>
								<th>{{ t("Item") }}</th>
								<th>{{ t("Group") }}</th>
								<th class="text-end">{{ t("Actual") }}</th>
								<th class="text-end">{{ t("Reserved") }}</th>
								<th class="text-end">{{ t("Free") }}</th>
								<th class="text-end">{{ t("Rate") }}</th>
								<th class="text-end">{{ t("Value") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr
								v-for="item in filteredItems"
								:key="item.item_code"
								style="cursor: pointer"
								@click="openItemDrill(item)"
							>
								<td>
									<div class="fw-semibold">
										{{ item.item_name || item.item_code }}
										<span v-if="getAnomaly(item.item_code)" class="badge bg-red-lt ms-2 font-normal text-capitalize">
											<i class="ti ti-alert-triangle me-1"></i>{{ t("check") }}
										</span>
									</div>
									<div class="small text-secondary font-monospace">{{ item.item_code }}</div>
									<div v-if="getAnomaly(item.item_code)" class="small text-red mt-1">
										{{ getAnomaly(item.item_code).message }}
									</div>
								</td>
								<td class="small text-secondary">{{ item.item_group || "—" }}</td>
								<td class="text-end font-monospace">{{ formatQty(item.actual_qty, item.stock_uom) }}</td>
								<td class="text-end font-monospace text-orange">{{ formatQty(item.reserved_qty, item.stock_uom) }}</td>
								<td class="text-end font-monospace" :class="Number(item.free_qty || 0) < 0 ? 'text-red' : 'text-green'">
									{{ formatQty(item.free_qty, item.stock_uom) }}
								</td>
								<td class="text-end font-monospace">{{ formatMoney(item.valuation_rate, currency, user.language) }}</td>
								<td class="text-end font-monospace fw-semibold">{{ formatMoney(item.stock_value, currency, user.language) }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</div>
		<ItemValuationDrawer
			:open="drillOpen"
			:loading="drillLoading"
			:item="drillItem"
			:history="drillHistory"
			:currency="currency"
			@close="drillOpen = false"
		/>
	</div>
</template>
