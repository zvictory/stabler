<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import MoneyInput from "../../components/MoneyInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import { useTelemetry } from "../../composables/useTelemetry.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { itemGroupOptions } from "../../composables/itemGroupTree.js";

const session = useSession();
useEscapeBack(() => {
	if (editOpen.value) { closeEdit(); return true; }
	if (priceModalOpen.value) { closePriceModal(); return true; }
	if (createOpen.value) { closeCreate(); return true; }
	if (detailOpen.value) { closeDetail(); return true; }
	return false;
}, "/inventory");

const { trackOnce, trackCta, FUNNEL } = useTelemetry();
const { activeCompany, user } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");

const itemGroupRows = ref([]);
const selectedItemGroup = ref("");
const includeDescendants = ref(true);
const categoryOptions = computed(() => itemGroupOptions(itemGroupRows.value));
const selectedGroupIsGroup = computed(
	() => !!itemGroupRows.value.find((r) => r.name === selectedItemGroup.value)?.is_group
);

async function loadItemGroups() {
	try {
		const data = await call("stabler.api.inventory.list_item_group_tree", {
			company: activeCompany.value,
		});
		itemGroupRows.value = data?.rows || [];
	} catch (err) {
		console.error("Failed to load categories:", err);
	}
}

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);

const itemPrices = ref([]);
const itemPricesLoading = ref(false);
const allPriceLists = ref([]);

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const formatQty = (n, uom) => {
	const v = Number(n || 0);
	return `${v.toLocaleString(user.value.language || "en", { maximumFractionDigits: 3 })} ${uom || ""}`.trim();
};

async function load() {
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.inventory.list_items", {
			search: search.value,
			limit: 100,
			context: "all",
			item_group: selectedItemGroup.value || undefined,
			include_descendants: selectedItemGroup.value && selectedGroupIsGroup.value && includeDescendants.value ? 1 : 0,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load items.");
	} finally {
		loading.value = false;
	}
}

async function loadItemPrices(itemCode) {
	itemPricesLoading.value = true;
	try {
		const [prices, pls] = await Promise.all([
			call("stabler.api.inventory.list_item_prices_for_item", { item_code: itemCode }),
			call("stabler.api.inventory.list_price_lists"),
		]);
		itemPrices.value = prices || [];
		allPriceLists.value = pls || [];
	} catch (err) {
		console.error("Failed to load item prices:", err);
	} finally {
		itemPricesLoading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.inventory.item_detail", {
			name,
			company: activeCompany.value,
		});
		if (detail.value?.item_code) {
			await loadItemPrices(detail.value.item_code);
		}
	} catch (err) {
		detail.value = { error: err?.message || t("Failed to load.") };
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

// Create Item
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const groupOptions = ref([]);
const uomOptions = ref([]);
const optionsLoaded = ref(false);

function blankItem() {
	return {
		item_name: "",
		item_code: "",
		item_group: "",
		stock_uom: "Nos",
		is_stock_item: true,
		is_sales_item: true,
		is_purchase_item: true,
		standard_rate: 0,
		description: "",
		disabled: false,
		weight_per_unit: 0,
		weight_uom: "Kg",
	};
}
const form = ref(blankItem());

async function loadCreateOptions() {
	if (optionsLoaded.value) return;
	try {
		const [groups, uoms] = await Promise.all([
			call("stabler.api.inventory.list_item_groups"),
			call("stabler.api.inventory.list_uoms"),
		]);
		groupOptions.value = groups || [];
		uomOptions.value = uoms || [];
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || t("Failed to load form options.");
	}
}

function openCreate() {
	form.value = blankItem();
	submitError.value = "";
	createOpen.value = true;
	loadCreateOptions();
}

function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}

async function submitCreate() {
	submitError.value = "";
	const name = form.value.item_name.trim();
	if (!name) {
		submitError.value = t("Item name is required.");
		return;
	}
	submitting.value = true;
	try {
		const created = await call("stabler.api.inventory.create_item", {
			item_name: name,
			item_code: form.value.item_code.trim() || undefined,
			item_group: form.value.item_group || undefined,
			stock_uom: form.value.stock_uom || "Nos",
			is_stock_item: form.value.is_stock_item ? 1 : 0,
			is_sales_item: form.value.is_sales_item ? 1 : 0,
			is_purchase_item: form.value.is_purchase_item ? 1 : 0,
			standard_rate: form.value.standard_rate || 0,
			description: form.value.description?.trim() || undefined,
		});
		trackOnce(FUNNEL.FIRST_ITEM);
		createOpen.value = false;
		await load();
		if (created?.name) await openDetail(created.name);
	} catch (err) {
		submitError.value = err?.message || t("Failed to create item.");
	} finally {
		submitting.value = false;
	}
}

// Edit Item
const editOpen = ref(false);
const editSubmitting = ref(false);
const editError = ref("");
const editForm = ref(blankItem());

function openEdit() {
	if (!detail.value) return;
	loadCreateOptions();
	editForm.value = {
		name: detail.value.name,
		item_name: detail.value.item_name || "",
		item_code: detail.value.item_code || "",
		item_group: detail.value.item_group || "",
		stock_uom: detail.value.stock_uom || "Nos",
		is_stock_item: !!detail.value.is_stock_item,
		is_sales_item: !!detail.value.is_sales_item,
		is_purchase_item: !!detail.value.is_purchase_item,
		standard_rate: detail.value.standard_rate || 0,
		description: detail.value.description || "",
		disabled: !!detail.value.disabled,
		weight_per_unit: detail.value.weight_per_unit || 0,
		weight_uom: detail.value.weight_uom || "Kg",
	};
	editError.value = "";
	editOpen.value = true;
}

// The row's Edit button called this and nothing ever defined it: clicking it
// threw `openEditRow is not a function` and the row stayed as it was. Landed in
// 3000476 and invisible until the SFC gate compiled the template.
//
// `openEdit` builds its form out of `detail`, so the row has to be fetched
// first; the drawer that fetch opens is closed again, or it sits underneath the
// modal the click actually asked for.
async function openEditRow(row) {
	await openDetail(row.name);
	detailOpen.value = false;
	if (detail.value && !detail.value.error) openEdit();
}

function closeEdit() {
	if (editSubmitting.value) return;
	editOpen.value = false;
}

async function submitEdit() {
	editError.value = "";
	const name = editForm.value.item_name.trim();
	if (!name) {
		editError.value = t("Item name is required.");
		return;
	}
	editSubmitting.value = true;
	try {
		await call("stabler.api.inventory.update_item", {
			name: editForm.value.name,
			item_name: name,
			item_group: editForm.value.item_group || undefined,
			stock_uom: editForm.value.stock_uom || undefined,
			is_stock_item: editForm.value.is_stock_item ? 1 : 0,
			is_sales_item: editForm.value.is_sales_item ? 1 : 0,
			is_purchase_item: editForm.value.is_purchase_item ? 1 : 0,
			standard_rate: editForm.value.standard_rate || 0,
			description: editForm.value.description?.trim() || undefined,
			disabled: editForm.value.disabled ? 1 : 0,
			weight_per_unit: editForm.value.weight_per_unit || 0,
			weight_uom: editForm.value.weight_uom || undefined,
		});
		editOpen.value = false;
		await load();
		await openDetail(editForm.value.name);
	} catch (err) {
		editError.value = err?.message || t("Failed to update item.");
	} finally {
		editSubmitting.value = false;
	}
}

// Add/Edit Item Price Modal
const priceModalOpen = ref(false);
const priceSubmitting = ref(false);
const priceError = ref("");
const priceForm = ref({
	name: null,
	price_list: "",
	price_list_rate: 0,
	currency: "USD",
});

function openAddPrice() {
	loadCreateOptions();
	priceForm.value = {
		name: null,
		price_list: allPriceLists.value.length ? allPriceLists.value[0].name : "",
		price_list_rate: 0,
		currency: currency.value,
	};
	priceError.value = "";
	priceModalOpen.value = true;
}

function openEditPrice(ip) {
	priceForm.value = {
		name: ip.name,
		price_list: ip.price_list,
		price_list_rate: ip.price_list_rate,
		currency: ip.currency || currency.value,
	};
	priceError.value = "";
	priceModalOpen.value = true;
}

function closePriceModal() {
	if (priceSubmitting.value) return;
	priceModalOpen.value = false;
}

async function submitPriceModal() {
	if (!priceForm.value.price_list) {
		priceError.value = t("Price List is required.");
		return;
	}
	priceSubmitting.value = true;
	priceError.value = "";
	try {
		await call("stabler.api.inventory.save_item_price", {
			name: priceForm.value.name || undefined,
			item_code: detail.value.item_code,
			price_list: priceForm.value.price_list,
			price_list_rate: priceForm.value.price_list_rate,
			currency: priceForm.value.currency,
		});
		priceModalOpen.value = false;
		await loadItemPrices(detail.value.item_code);
	} catch (err) {
		priceError.value = err?.message || t("Failed to save price.");
	} finally {
		priceSubmitting.value = false;
	}
}

async function deletePrice(priceName) {
	if (!confirm(t("Are you sure you want to delete this price?"))) return;
	try {
		await call("stabler.api.inventory.delete_item_price", { name: priceName });
		await loadItemPrices(detail.value.item_code);
	} catch (err) {
		alert(err?.message || t("Failed to delete price."));
	}
}

onMounted(() => {
	load();
	loadItemGroups();
});
watch(activeCompany, () => {
	load();
	loadItemGroups();
});
watch(selectedItemGroup, load);
watch(includeDescendants, () => {
	if (selectedGroupIsGroup.value) load();
});
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<div class="card-title m-0">{{ t("Items") }}</div>
			<button type="button" class="btn btn-primary btn-sm ms-auto" @click="openCreate">
				<i class="ti ti-plus me-1"></i>{{ t("New item") }}
			</button>
		</div>
		<ListToolbar v-model="search" :placeholder="t('Search item code or name…')" :count="rows.length" @search="load">
			<template #filters>
				<Select
					v-model="selectedItemGroup"
					:options="categoryOptions"
					clearable
					:placeholder="t('All categories')"
					style="min-width: 200px"
				>
					<template #option="{ option }">
						<span :style="{ paddingLeft: `${option.depth * 0.75}rem` }">{{ option.label }}</span>
					</template>
					<template #selected="{ option }">{{ option.label }}</template>
				</Select>
				<div v-if="selectedItemGroup && selectedGroupIsGroup" class="form-check m-0">
					<input v-model="includeDescendants" class="form-check-input" type="checkbox" id="include_descendants" />
					<label class="form-check-label" for="include_descendants">{{ t("Include subcategories") }}</label>
				</div>
				<router-link to="/inventory/categories" class="btn btn-sm btn-ghost-secondary">
					<i class="ti ti-category-2 me-1"></i>{{ t("Manage categories") }}
				</router-link>
			</template>
		</ListToolbar>
		<div v-if="error && !loading" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!loading && !rows.length"
			icon="ti-box"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No items found')"
			:subtitle="search ? t('Try a different search term or clear the filter.') : t('Create your first item to start tracking stock and price lists.')"
		>
			<template #actions>
				<button v-if="search" type="button" class="btn btn-outline-secondary" @click="search = ''; load()">
					<i class="ti ti-x me-1"></i>{{ t("Clear search") }}
				</button>
				<button type="button" class="btn btn-primary" @click="trackCta('add_first_item'); openCreate()">
					<i class="ti ti-plus me-1"></i>{{ t("New item") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Code") }}</th>
						<th>{{ t("Name") }}</th>
						<th>{{ t("Group") }}</th>
						<th>{{ t("UOM") }}</th>
						<th>{{ t("Type") }}</th>
						<th class="text-end">{{ t("Standard rate") }}</th>
						<th class="text-end" style="width: 130px">{{ t("Actions") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="7" />
				<tbody v-else>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary fw-bold">
							{{ r.item_code }}
							<span v-if="r.disabled" class="badge bg-secondary-lt ms-1">{{ t("Disabled") }}</span>
						</td>
						<td>
							<div class="fw-semibold">{{ r.item_name }}</div>
						</td>
						<td>{{ r.item_group }}</td>
						<td>{{ r.stock_uom }}</td>
						<td>
							<span v-if="r.is_stock_item" class="badge bg-blue-lt me-1">{{ t("Stock") }}</span>
							<span v-if="r.is_purchase_item" class="badge bg-orange-lt me-1">{{ t("Buy") }}</span>
							<span v-if="r.is_sales_item" class="badge bg-green-lt me-1">{{ t("Sell") }}</span>
						</td>
						<td class="text-end font-monospace">{{ formatMoney(r.standard_rate, currency, user.language) }}</td>
						<td class="text-end" @click.stop>
							<button type="button" class="btn btn-icon btn-ghost-primary btn-sm me-1" :title="t('View Item Details')" @click="openDetail(r.name)">
								<i class="ti ti-eye"></i>
							</button>
							<button type="button" class="btn btn-icon btn-ghost-secondary btn-sm" :title="t('Edit Item')" @click="openEditRow(r)">
								<i class="ti ti-edit"></i>
							</button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Detail Offcanvas Drawer -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: detailOpen }"
		tabindex="-1"
		style="visibility: visible; width: 680px"
		:style="{ transform: detailOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header border-bottom">
			<h5 class="offcanvas-title">{{ t("Item Details") }}</h5>
			<div class="ms-auto d-flex align-items-center gap-2">
				<button v-if="detail && !detail.error" type="button" class="btn btn-outline-primary btn-sm" @click="openEdit">
					<i class="ti ti-edit me-1"></i>{{ t("Edit item") }}
				</button>
				<button type="button" class="btn-close" @click="closeDetail" aria-label="Close"></button>
			</div>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<div v-else-if="detail">
				<div class="d-flex align-items-center mb-3 gap-3">
					<img
						v-if="detail.image"
						:src="detail.image"
						class="rounded"
						width="64"
						height="64"
						style="object-fit: cover"
						alt=""
					/>
					<span v-else class="avatar avatar-lg bg-blue-lt">
						<i class="ti ti-box" style="font-size: 1.5rem"></i>
					</span>
					<div class="flex-grow-1">
						<div class="d-flex align-items-center gap-2">
							<h3 class="m-0">{{ detail.item_name }}</h3>
							<span v-if="detail.disabled" class="badge bg-secondary">{{ t("Disabled") }}</span>
						</div>
						<div class="small text-secondary font-monospace">{{ detail.item_code }}</div>
					</div>
				</div>

				<div class="row g-2 mb-3">
					<div class="col-6">
						<div class="card">
							<div class="card-body py-2">
								<div class="small text-secondary">{{ t("On hand") }}</div>
								<div class="h3 m-0 text-blue">{{ formatQty(detail.total_qty, detail.stock_uom) }}</div>
							</div>
						</div>
					</div>
					<div class="col-6">
						<div class="card">
							<div class="card-body py-2">
								<div class="small text-secondary">{{ t("Stock value") }}</div>
								<div class="h3 m-0 text-green">{{ formatMoney(detail.total_value, currency, user.language) }}</div>
							</div>
						</div>
					</div>
				</div>

				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Group") }}</div>
						<div class="datagrid-content">{{ detail.item_group }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Stock UOM") }}</div>
						<div class="datagrid-content">{{ detail.stock_uom }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Standard rate") }}</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.standard_rate, currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Valuation") }}</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.valuation_rate, currency, user.language) }}</div>
					</div>
					<div v-if="detail.weight_per_unit" class="datagrid-item">
						<div class="datagrid-title">{{ t("Weight") }}</div>
						<div class="datagrid-content">{{ detail.weight_per_unit }} {{ detail.weight_uom }}</div>
					</div>
				</div>

				<!-- Price Lists Section -->
				<div class="mb-4">
					<div class="d-flex align-items-center mb-2">
						<h6 class="text-uppercase text-secondary small m-0">{{ t("Price Lists (Item Prices)") }}</h6>
						<button type="button" class="btn btn-outline-secondary btn-xs ms-auto" @click="openAddPrice">
							<i class="ti ti-plus me-1"></i>{{ t("Add Price") }}
						</button>
					</div>

					<div v-if="itemPricesLoading" class="text-center py-2">
						<div class="spinner-border spinner-border-sm text-secondary"></div>
					</div>
					<div v-else-if="!itemPrices.length" class="text-secondary small italic">
						{{ t("No custom price list rates configured for this item.") }}
					</div>
					<div v-else class="table-responsive border rounded">
						<table class="table table-sm table-vcenter m-0">
							<thead>
								<tr>
									<th>{{ t("Price List") }}</th>
									<th class="text-end">{{ t("Rate") }}</th>
									<th style="width: 80px"></th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="ip in itemPrices" :key="ip.name">
									<td class="fw-semibold">
										{{ ip.price_list }}
										<span v-if="ip.selling" class="badge bg-green-lt ms-1">{{ t("Sell") }}</span>
										<span v-if="ip.buying" class="badge bg-orange-lt ms-1">{{ t("Buy") }}</span>
									</td>
									<td class="text-end font-monospace">
										{{ formatMoney(ip.price_list_rate, ip.currency || currency, user.language) }}
									</td>
									<td class="text-end">
										<button type="button" class="btn btn-ghost-primary btn-icon btn-sm me-1" @click="openEditPrice(ip)">
											<i class="ti ti-edit"></i>
										</button>
										<button type="button" class="btn btn-ghost-danger btn-icon btn-sm" @click="deletePrice(ip.name)">
											<i class="ti ti-trash"></i>
										</button>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>

				<!-- Warehouse Balances Section -->
				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Warehouse balances") }}</h6>
				<div v-if="!detail.balances?.length" class="text-secondary small">
					{{ t("No stock in any warehouse for this company.") }}
				</div>
				<div v-else class="table-responsive border rounded">
					<table class="table table-sm table-vcenter m-0">
						<thead>
							<tr>
								<th>{{ t("Warehouse") }}</th>
								<th class="text-end">{{ t("On hand") }}</th>
								<th class="text-end">{{ t("Reserved") }}</th>
								<th class="text-end">{{ t("Projected") }}</th>
								<th class="text-end">{{ t("Value") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(b, i) in detail.balances" :key="i">
								<td>{{ b.warehouse }}</td>
								<td class="text-end font-monospace">{{ formatQty(b.actual_qty, b.stock_uom) }}</td>
								<td class="text-end font-monospace text-secondary">{{ formatQty(b.reserved_qty, "") }}</td>
								<td class="text-end font-monospace">{{ formatQty(b.projected_qty, "") }}</td>
								<td class="text-end font-monospace">{{ formatMoney(Number(b.actual_qty) * Number(b.valuation_rate), currency, user.language) }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</div>
	</div>

	<!-- Modal: New Item -->
	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeCreate">
		<div class="modal-dialog modal-lg modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("New item") }}</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreate" :disabled="submitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
					<div class="row g-3">
						<div class="col-md-8">
							<label class="form-label required">{{ t("Item name") }}</label>
							<input v-model="form.item_name" type="text" class="form-control" autofocus />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Item code") }}</label>
							<input
								v-model="form.item_code"
								type="text"
								class="form-control font-monospace"
								:placeholder="form.item_name || 'auto'"
							/>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Group") }}</label>
							<Select
								v-model="form.item_group"
								:options="groupOptions"
								value-key="name"
								label-key="name"
								:placeholder="t('— default —')"
							/>
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Stock UOM") }}</label>
							<Select
								v-model="form.stock_uom"
								:options="uomOptions"
								value-key="name"
								label-key="name"
							/>
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Standard rate") }}</label>
							<MoneyInput v-model="form.standard_rate" />
						</div>
						<div class="col-12">
							<div class="form-check form-check-inline">
								<input v-model="form.is_stock_item" class="form-check-input" type="checkbox" id="is_stock" />
								<label class="form-check-label" for="is_stock">{{ t("Stock item") }}</label>
							</div>
							<div class="form-check form-check-inline">
								<input v-model="form.is_sales_item" class="form-check-input" type="checkbox" id="is_sales" />
								<label class="form-check-label" for="is_sales">{{ t("Sales item") }}</label>
							</div>
							<div class="form-check form-check-inline">
								<input v-model="form.is_purchase_item" class="form-check-input" type="checkbox" id="is_purchase" />
								<label class="form-check-label" for="is_purchase">{{ t("Purchase item") }}</label>
							</div>
						</div>
						<div class="col-12">
							<label class="form-label">{{ t("Description") }}</label>
							<textarea v-model="form.description" class="form-control" rows="2"></textarea>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="closeCreate">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary ms-auto" :disabled="submitting" @click="submitCreate">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Modal: Edit Item -->
	<div v-if="editOpen" class="modal-backdrop fade show" @click="closeEdit"></div>
	<div v-if="editOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeEdit">
		<div class="modal-dialog modal-lg modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Edit Item") }}</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeEdit" :disabled="editSubmitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="editError" class="alert alert-danger">{{ editError }}</div>
					<div class="row g-3">
						<div class="col-md-8">
							<label class="form-label required">{{ t("Item name") }}</label>
							<input v-model="editForm.item_name" type="text" class="form-control" autofocus />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Item code") }}</label>
							<input v-model="editForm.item_code" type="text" class="form-control font-monospace" disabled />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Group") }}</label>
							<Select
								v-model="editForm.item_group"
								:options="groupOptions"
								value-key="name"
								label-key="name"
							/>
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Stock UOM") }}</label>
							<Select
								v-model="editForm.stock_uom"
								:options="uomOptions"
								value-key="name"
								label-key="name"
							/>
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Standard rate") }}</label>
							<MoneyInput v-model="editForm.standard_rate" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Weight per unit") }}</label>
							<input v-model.number="editForm.weight_per_unit" type="number" step="any" class="form-control font-monospace" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Weight UOM") }}</label>
							<input v-model="editForm.weight_uom" type="text" class="form-control" placeholder="Kg" />
						</div>
						<div class="col-12 d-flex align-items-center justify-content-between pt-2 border-top">
							<div class="d-flex gap-3">
								<div class="form-check form-check-inline">
									<input v-model="editForm.is_stock_item" class="form-check-input" type="checkbox" id="edit_is_stock" />
									<label class="form-check-label" for="edit_is_stock">{{ t("Stock item") }}</label>
								</div>
								<div class="form-check form-check-inline">
									<input v-model="editForm.is_sales_item" class="form-check-input" type="checkbox" id="edit_is_sales" />
									<label class="form-check-label" for="edit_is_sales">{{ t("Sales item") }}</label>
								</div>
								<div class="form-check form-check-inline">
									<input v-model="editForm.is_purchase_item" class="form-check-input" type="checkbox" id="edit_is_purchase" />
									<label class="form-check-label" for="edit_is_purchase">{{ t("Purchase item") }}</label>
								</div>
							</div>
							<div class="form-check form-switch m-0">
								<input v-model="editForm.disabled" class="form-check-input" type="checkbox" id="edit_disabled" />
								<label class="form-check-label text-danger fw-semibold" for="edit_disabled">{{ t("Disabled") }}</label>
							</div>
						</div>
						<div class="col-12">
							<label class="form-label">{{ t("Description") }}</label>
							<textarea v-model="editForm.description" class="form-control" rows="2"></textarea>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="editSubmitting" @click="closeEdit">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary ms-auto" :disabled="editSubmitting" @click="submitEdit">
						<span v-if="editSubmitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save Changes") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Modal: Add/Edit Price List Rate -->
	<div v-if="priceModalOpen" class="modal-backdrop fade show" @click="closePriceModal"></div>
	<div v-if="priceModalOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closePriceModal">
		<div class="modal-dialog modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ priceForm.name ? t("Edit Price") : t("Add Price") }}</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closePriceModal" :disabled="priceSubmitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="priceError" class="alert alert-danger">{{ priceError }}</div>
					<div class="mb-3">
						<label class="form-label required">{{ t("Price List") }}</label>
						<select v-model="priceForm.price_list" class="form-select" :disabled="!!priceForm.name">
							<option v-for="pl in allPriceLists" :key="pl.name" :value="pl.name">
								{{ pl.name }} ({{ pl.currency }})
							</option>
						</select>
					</div>
					<div class="mb-3">
						<label class="form-label required">{{ t("Price List Rate") }}</label>
						<MoneyInput v-model="priceForm.price_list_rate" />
					</div>
					<div class="mb-3">
						<label class="form-label required">{{ t("Currency") }}</label>
						<input v-model="priceForm.currency" type="text" class="form-control text-uppercase" placeholder="USD / UZS" />
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="priceSubmitting" @click="closePriceModal">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary ms-auto" :disabled="priceSubmitting" @click="submitPriceModal">
						<span v-if="priceSubmitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
