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

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);

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
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load items.");
	} finally {
		loading.value = false;
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

let searchTimer = null;
function onSearchInput() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 250);
}

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
		createOpen.value = false;
		await load();
		if (created?.name) await openDetail(created.name);
	} catch (err) {
		submitError.value = err?.message || t("Failed to create item.");
	} finally {
		submitting.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<div class="card-title m-0">{{ t("Items") }}</div>
			<div class="ms-auto d-flex align-items-center gap-2" style="max-width: 480px; width: 100%">
				<input
					v-model="search"
					type="search"
					class="form-control form-control-sm"
					:placeholder="t('Search item code or name…')"
					@input="onSearchInput"
				/>
				<button type="button" class="btn btn-success btn-sm flex-shrink-0" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New item") }}
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
			icon="ti-box"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No items found')"
			:subtitle="search ? t('Try a different search term or clear the filter.') : t('Create your first item to start tracking stock and price lists.')"
		>
			<template #actions>
				<button v-if="search" type="button" class="btn btn-outline-secondary" @click="search = ''">
					<i class="ti ti-x me-1"></i>{{ t("Clear search") }}
				</button>
				<button type="button" class="btn btn-primary" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New item") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Code") }}</th>
						<th>{{ t("Name") }}</th>
						<th>{{ t("Group") }}</th>
						<th>{{ t("UOM") }}</th>
						<th>{{ t("Type") }}</th>
						<th class="text-end">{{ t("Standard rate") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary">{{ r.item_code }}</td>
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
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: detailOpen }"
		tabindex="-1"
		style="visibility: visible; width: 640px"
		:style="{ transform: detailOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">{{ t("Item") }}</h5>
			<button type="button" class="btn-close" @click="closeDetail" aria-label="Close"></button>
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
						<h3 class="m-0">{{ detail.item_name }}</h3>
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

				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Warehouse balances") }}</h6>
				<div v-if="!detail.balances?.length" class="text-secondary small">
					{{ t("No stock in any warehouse for this company.") }}
				</div>
				<div v-else class="table-responsive">
					<table class="table table-sm table-vcenter">
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
</template>
