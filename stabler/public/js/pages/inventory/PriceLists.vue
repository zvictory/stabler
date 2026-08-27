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
import { useEscapeBack } from "../../composables/useEscapeBack.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
useEscapeBack(() => { if (createPlOpen.value) { closeCreatePl(); return true; } return false; }, "/inventory");

const loading = ref(false);
const error = ref("");
const priceLists = ref([]);
const selectedPriceList = ref("");
const items = ref([]);
const search = ref("");
const selectedGroup = ref("");
const groupOptions = ref([]);

const saving = ref(false);
const saveSuccess = ref("");
const dirtyMap = ref({}); // item_code -> new rate

const baseCurrency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const activePlCurrency = computed(() => {
	const pl = priceLists.value.find((p) => p.name === selectedPriceList.value);
	return pl?.currency || baseCurrency.value;
});

async function loadPriceLists() {
	loading.value = true;
	error.value = "";
	try {
		const [pls, groups] = await Promise.all([
			call("stabler.api.inventory.list_price_lists"),
			call("stabler.api.inventory.list_item_groups"),
		]);
		priceLists.value = pls || [];
		groupOptions.value = groups || [];
		if (priceLists.value.length && !selectedPriceList.value) {
			selectedPriceList.value = priceLists.value[0].name;
		}
	} catch (err) {
		error.value = err?.message || t("Failed to load price lists.");
	} finally {
		loading.value = false;
	}
}

async function loadMatrix() {
	if (!selectedPriceList.value) return;
	loading.value = true;
	error.value = "";
	dirtyMap.value = {};
	saveSuccess.value = "";
	try {
		const res = await call("stabler.api.inventory.get_price_list_matrix", {
			price_list: selectedPriceList.value,
			item_group: selectedGroup.value || undefined,
			search: search.value || undefined,
			limit: 250,
		});
		items.value = (res?.items || []).map((row) => ({
			...row,
			edit_rate: row.price_list_rate !== null && row.price_list_rate !== undefined ? row.price_list_rate : 0,
		}));
	} catch (err) {
		error.value = err?.message || t("Failed to load price list matrix.");
	} finally {
		loading.value = false;
	}
}

let searchTimer = null;
function onSearchInput() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(loadMatrix, 250);
}

function onRateChange(itemCode, newRate) {
	dirtyMap.value[itemCode] = Number(newRate || 0);
}

const hasChanges = computed(() => Object.keys(dirtyMap.value).length > 0);

async function saveChanges() {
	if (!hasChanges.value || !selectedPriceList.value) return;
	saving.value = true;
	error.value = "";
	saveSuccess.value = "";
	try {
		const priceUpdates = Object.entries(dirtyMap.value).map(([item_code, price_list_rate]) => ({
			item_code,
			price_list_rate,
			currency: activePlCurrency.value,
		}));
		const res = await call("stabler.api.inventory.bulk_update_item_prices", {
			price_list: selectedPriceList.value,
			price_updates: priceUpdates,
		});
		// Not `res.updated_count || priceUpdates.length` — `0 || N` announced the
		// number of lines SENT as the number saved whenever the server saved none.
		const saved = Number(res?.updated_count || 0);
		const rejected = res?.rejected || [];
		saveSuccess.value = saved ? t("{0} price(s) updated successfully.", [saved]) : "";
		if (rejected.length) {
			error.value = t("Not saved — a price cannot be negative: {0}", [rejected.join(", ")]);
		}
		dirtyMap.value = {};
		await loadMatrix();
	} catch (err) {
		error.value = err?.message || t("Failed to save price updates.");
	} finally {
		saving.value = false;
	}
}

// Create Price List Modal
const createPlOpen = ref(false);
const plForm = ref({ name: "", currency: "USD", buying: 1, selling: 1 });
const plSubmitting = ref(false);
const plError = ref("");

function openCreatePl() {
	plForm.value = { name: "", currency: baseCurrency.value, buying: 1, selling: 1 };
	plError.value = "";
	createPlOpen.value = true;
}

function closeCreatePl() {
	if (plSubmitting.value) return;
	createPlOpen.value = false;
}

async function submitCreatePl() {
	plError.value = "";
	const name = plForm.value.name.trim();
	if (!name) {
		plError.value = t("Price List name is required.");
		return;
	}
	plSubmitting.value = true;
	try {
		const created = await call("stabler.api.inventory.create_price_list", {
			price_list_name: name,
			currency: plForm.value.currency || "USD",
			buying: plForm.value.buying ? 1 : 0,
			selling: plForm.value.selling ? 1 : 0,
		});
		createPlOpen.value = false;
		await loadPriceLists();
		selectedPriceList.value = created.name;
		await loadMatrix();
	} catch (err) {
		plError.value = err?.message || t("Failed to create price list.");
	} finally {
		plSubmitting.value = false;
	}
}

onMounted(async () => {
	await loadPriceLists();
	if (selectedPriceList.value) await loadMatrix();
});

watch(selectedPriceList, () => {
	loadMatrix();
});
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center flex-wrap gap-2">
			<div class="d-flex align-items-center gap-2">
				<div class="fw-bold fs-4 me-2">{{ t("Price Lists") }}</div>
				<select v-model="selectedPriceList" class="form-select form-select-sm" style="min-width: 180px">
					<option v-for="pl in priceLists" :key="pl.name" :value="pl.name">
						{{ pl.name }} ({{ pl.currency }})
					</option>
				</select>
				<button type="button" class="btn btn-outline-secondary btn-sm flex-shrink-0" @click="openCreatePl">
					<i class="ti ti-plus me-1"></i>{{ t("New Price List") }}
				</button>
			</div>

			<div class="ms-auto d-flex align-items-center gap-2" style="max-width: 480px; width: 100%">
				<Select
					v-model="selectedGroup"
					:options="groupOptions"
					value-key="name"
					label-key="name"
					:placeholder="t('All Groups')"
					class="form-select-sm"
					style="min-width: 140px"
					@change="loadMatrix"
				/>
				<input
					v-model="search"
					type="search"
					class="form-control form-control-sm"
					:placeholder="t('Search code or name…')"
					@input="onSearchInput"
				/>
				<button
					type="button"
					class="btn btn-success btn-sm flex-shrink-0"
					:disabled="!hasChanges || saving"
					@click="saveChanges"
				>
					<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-check me-1"></i>
					{{ t("Save Changes") }}
				</button>
			</div>
		</div>

		<div v-if="saveSuccess" class="alert alert-success m-3 mb-0 py-2">
			<i class="ti ti-check me-1"></i>{{ saveSuccess }}
		</div>
		<div v-if="error" class="alert alert-danger m-3 mb-0 py-2">{{ error }}</div>

		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>

		<EmptyState
			v-else-if="!items.length"
			icon="ti-tags"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No items found')"
			:subtitle="t('No items match the selected price list or search filter.')"
		/>

		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Code") }}</th>
						<th>{{ t("Name") }}</th>
						<th>{{ t("Group") }}</th>
						<th>{{ t("UOM") }}</th>
						<th class="text-end">{{ t("Standard rate") }}</th>
						<th class="text-end" style="width: 220px">{{ selectedPriceList }} ({{ activePlCurrency }})</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in items" :key="r.item_code">
						<td class="font-monospace text-primary">{{ r.item_code }}</td>
						<td class="fw-semibold">{{ r.item_name }}</td>
						<td>{{ r.item_group }}</td>
						<td>{{ r.stock_uom }}</td>
						<td class="text-end font-monospace text-secondary">
							{{ formatMoney(r.standard_rate, baseCurrency, user.language) }}
						</td>
						<td class="text-end">
							<MoneyInput
								v-model="r.edit_rate"
								@update:modelValue="(val) => onRateChange(r.item_code, val)"
							/>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Modal: Create Price List -->
	<div v-if="createPlOpen" class="modal-backdrop fade show" @click="closeCreatePl"></div>
	<div v-if="createPlOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeCreatePl">
		<div class="modal-dialog modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("New Price List") }}</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreatePl" :disabled="plSubmitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="plError" class="alert alert-danger">{{ plError }}</div>
					<div class="mb-3">
						<label class="form-label required">{{ t("Price List Name") }}</label>
						<input v-model="plForm.name" type="text" class="form-control" autofocus :placeholder="t('e.g. Wholesale UZS')" />
					</div>
					<div class="mb-3">
						<label class="form-label required">{{ t("Currency") }}</label>
						<input v-model="plForm.currency" type="text" class="form-control text-uppercase" placeholder="USD / UZS" />
					</div>
					<div class="d-flex gap-4 mb-2">
						<div class="form-check">
							<input v-model="plForm.selling" class="form-check-input" type="checkbox" id="pl_selling" />
							<label class="form-check-label" for="pl_selling">{{ t("Selling") }}</label>
						</div>
						<div class="form-check">
							<input v-model="plForm.buying" class="form-check-input" type="checkbox" id="pl_buying" />
							<label class="form-check-label" for="pl_buying">{{ t("Buying") }}</label>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="plSubmitting" @click="closeCreatePl">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary ms-auto" :disabled="plSubmitting" @click="submitCreatePl">
						<span v-if="plSubmitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
