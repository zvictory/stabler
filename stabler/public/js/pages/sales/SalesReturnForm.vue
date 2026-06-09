<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import DateInput from "../../components/DateInput.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import FormPage from "../../components/form/FormPage.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();

const today = new Date().toISOString().slice(0, 10);
const warehouses = ref([]);
const warehousesLoading = ref(false);
const submitting = ref(false);
const submitError = ref("");
const form = ref({
	customer: "",
	customer_name: "",
	warehouse: "",
	posting_date: today,
	currency: "",
	price_list: "",
	items: [],
});

const currency = computed(() => form.value.currency || session.currency || "UZS");
const total = computed(() =>
	form.value.items.reduce((sum, line) => sum + Number(line.qty || 0) * Number(line.rate || 0), 0)
);
const creditTotal = computed(() => -Math.abs(total.value || 0));
const canSubmit = computed(
	() =>
		!!activeCompany.value &&
		!!form.value.customer &&
		!!form.value.warehouse &&
		form.value.items.some((line) => line.item_code && Number(line.qty || 0) > 0 && Number(line.rate || 0) >= 0) &&
		!submitting.value
);

function blankLine() {
	return {
		item_code: "",
		item_name: "",
		stock_uom: "",
		uom: "",
		uoms: [],
		qty: 1,
		rate: 0,
	};
}

function addLine() {
	form.value.items.push(blankLine());
}

function removeLine(index) {
	form.value.items.splice(index, 1);
	if (!form.value.items.length) addLine();
}

async function loadWarehouses() {
	if (!activeCompany.value) return;
	warehousesLoading.value = true;
	try {
		warehouses.value = await call("stabler.api.inventory.list_stock_warehouses", {
			company: activeCompany.value,
		});
	} finally {
		warehousesLoading.value = false;
	}
}

function searchCustomers(q) {
	return call("stabler.api.sales.list_customers", {
		company: activeCompany.value,
		search: q,
		limit: 10,
	});
}

async function pickCustomer(customer) {
	form.value.customer = customer.name;
	form.value.customer_name = customer.customer_name;
	try {
		const defaults = await call("stabler.api.sales.get_customer_defaults", {
			company: activeCompany.value,
			customer: customer.name,
		});
		form.value.currency = defaults.default_currency || "";
		form.value.price_list = defaults.resolved_price_list || "";
	} catch {
		// Defaults improve rates but are not required to continue editing.
	}
}

function clearCustomer() {
	form.value.customer = "";
	form.value.customer_name = "";
	form.value.currency = "";
	form.value.price_list = "";
}

function searchItems(q) {
	return call("stabler.api.inventory.list_items", {
		search: q,
		warehouse: form.value.warehouse || undefined,
		limit: 30,
	});
}

function preferredSalesUom(meta) {
	const preferred = meta.sales_uom || meta.default_uom || meta.stock_uom;
	return (meta.uoms || []).find((uom) => uom.uom === preferred) || (meta.uoms || [])[0] || null;
}

async function pickItem(line, item) {
	line.item_code = item.item_code || item.name;
	line.item_name = item.item_name;
	try {
		const meta = await call("stabler.api.sales.item_sales_meta", {
			item_code: line.item_code,
			company: activeCompany.value,
			customer: form.value.customer || undefined,
			price_list: form.value.price_list || undefined,
		});
		line.stock_uom = meta.stock_uom || "";
		line.uoms = meta.uoms || [];
		const preferred = preferredSalesUom(meta);
		line.uom = preferred?.uom || meta.default_uom || meta.stock_uom || "";
		line.rate = Number(meta.price_list_rate || item.standard_rate || 0);
		if (!form.value.currency && meta.currency) form.value.currency = meta.currency;
	} catch {
		line.stock_uom = item.stock_uom || "";
		line.uom = item.stock_uom || "";
		line.rate = Number(item.standard_rate || 0);
	}
}

function clearItem(line) {
	Object.assign(line, blankLine());
}

async function submitReturn() {
	if (!canSubmit.value) return;
	submitting.value = true;
	submitError.value = "";
	try {
		const res = await call("stabler.api.sales.create_direct_sales_return", {
			company: activeCompany.value,
			customer: form.value.customer,
			warehouse: form.value.warehouse,
			posting_date: form.value.posting_date,
			items: form.value.items
				.filter((line) => line.item_code && Number(line.qty || 0) > 0)
				.map((line) => ({
					item_code: line.item_code,
					qty: Number(line.qty || 0),
					uom: line.uom || line.stock_uom || undefined,
					rate: Number(line.rate || 0),
				})),
		});
		if (res?.name) router.push(`/sales/invoices/${res.name}`);
	} catch (err) {
		submitError.value = err?.message || t("Failed to create return.");
	} finally {
		submitting.value = false;
	}
}

watch(activeCompany, async () => {
	form.value.warehouse = "";
	warehouses.value = [];
	await loadWarehouses();
});

onMounted(async () => {
	addLine();
	await loadWarehouses();
});
</script>

<template>
	<FormPage
		:title="t('New Sales Return')"
		:doc-name="t('Direct credit note')"
		:loading="false"
		:error="''"
		back-path="/sales/invoices"
	>
		<div class="alert alert-info">
			<i class="ti ti-info-circle me-1"></i>
			{{ t("Direct returns create customer credit only. No cash or bank refund is recorded here.") }}
		</div>
		<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

		<div class="row g-3 mb-3">
			<div class="col-md-6">
				<label class="form-label required">{{ t("Customer") }}</label>
				<Typeahead
					v-model="form.customer"
					:search="searchCustomers"
					:display="form.customer_name"
					:placeholder="t('Search customer name…')"
					:no-results-text="t('No customers match that name')"
					open-on-focus
					@pick="pickCustomer"
					@clear="clearCustomer"
				>
					<template #option="{ item }">
						<div class="d-flex align-items-center gap-2">
							<span class="avatar avatar-xs bg-purple-lt">{{ (item.customer_name || item.name).charAt(0).toUpperCase() }}</span>
							<div>
								<div class="fw-semibold">{{ item.customer_name }}</div>
								<div class="small text-secondary">{{ item.name }} · {{ item.customer_group || "—" }}</div>
							</div>
						</div>
					</template>
				</Typeahead>
			</div>
			<div class="col-md-6">
				<label class="form-label required">{{ t("Return warehouse") }}</label>
				<Select
					v-model="form.warehouse"
					:options="warehouses"
					value-key="name"
					:disabled="warehousesLoading"
					:placeholder="warehousesLoading ? t('Loading warehouses…') : t('Pick a warehouse')"
				>
					<template #option="{ option }">{{ option.warehouse_name }} ({{ option.name }})</template>
					<template #selected="{ option }">{{ option.warehouse_name }} ({{ option.name }})</template>
				</Select>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Posting date") }}</label>
				<DateInput v-model="form.posting_date" />
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Currency") }}</label>
				<div class="form-control-plaintext font-monospace fw-semibold py-1">{{ currency }}</div>
			</div>
		</div>

		<div class="d-flex align-items-center mb-2">
			<h6 class="text-uppercase text-secondary small mb-0">{{ t("Returned items") }}</h6>
			<button type="button" class="btn btn-sm btn-outline-primary ms-auto" @click="addLine">
				<i class="ti ti-plus me-1"></i>{{ t("Add item") }}
			</button>
		</div>
		<div class="table-responsive">
			<table class="table table-sm table-vcenter">
				<thead>
					<tr>
						<th class="text-end text-secondary" style="width: 36px">#</th>
						<th style="min-width: 260px">{{ t("Item") }}</th>
						<th style="width: 110px">{{ t("Return qty") }}</th>
						<th style="width: 130px">{{ t("UOM") }}</th>
						<th style="width: 160px">{{ t("Rate") }}</th>
						<th class="text-end" style="width: 150px">{{ t("Credit amount") }}</th>
						<th style="width: 44px"></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="(line, idx) in form.items" :key="idx">
						<td class="text-end text-secondary font-monospace small">{{ idx + 1 }}</td>
						<td>
							<Typeahead
								:model-value="line.item_code"
								:search="searchItems"
								:display="line.item_name || line.item_code"
								:placeholder="t('Search returned item…')"
								:no-results-text="t('No items match')"
								size="sm"
								menu-min-width="280px"
								open-on-focus
								@pick="(item) => pickItem(line, item)"
								@clear="clearItem(line)"
							>
								<template #option="{ item }">
									<div class="fw-semibold small">{{ item.item_name }}</div>
									<div class="small text-secondary font-monospace">{{ item.item_code }} · {{ item.stock_uom || "—" }}</div>
								</template>
							</Typeahead>
						</td>
						<td>
							<input
								v-model.number="line.qty"
								type="number"
								step="any"
								min="0"
								inputmode="decimal"
								class="form-control form-control-sm font-monospace text-end"
								:disabled="submitting"
							/>
						</td>
						<td>
							<Select
								v-model="line.uom"
								:options="line.uoms"
								value-key="uom"
								label-key="uom"
								size="sm"
								:placeholder="line.stock_uom || t('UOM')"
								:disabled="submitting || !line.uoms.length"
							/>
						</td>
						<td>
							<MoneyInput
								v-model="line.rate"
								:currency="currency"
								:language="user.language || 'en'"
								size="sm"
								:min="0"
								:disabled="submitting"
							/>
						</td>
						<td class="text-end font-monospace">
							{{ formatMoney(-(Number(line.qty || 0) * Number(line.rate || 0)), currency, user.language) }}
						</td>
						<td>
							<button type="button" class="btn btn-sm btn-ghost-danger" :disabled="submitting" @click="removeLine(idx)">
								<i class="ti ti-trash"></i>
							</button>
						</td>
					</tr>
				</tbody>
				<tfoot>
					<tr>
						<th colspan="5" class="text-end">{{ t("Customer credit") }}</th>
						<th class="text-end font-monospace text-purple">{{ formatMoney(creditTotal, currency, user.language) }}</th>
						<th></th>
					</tr>
				</tfoot>
			</table>
		</div>

		<div class="small text-secondary">
			<i class="ti ti-package-import me-1"></i>
			{{ t("Submitted returns add stock back into the selected warehouse.") }}
			<span class="ms-2">{{ t("Posting date") }}: {{ formatDateTime(form.posting_date) }}</span>
		</div>

		<template #actions>
			<button type="button" class="btn btn-primary" :disabled="!canSubmit" @click="submitReturn">
				<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
				<i v-else class="ti ti-receipt-refund me-1"></i>{{ t("Create return") }}
			</button>
		</template>
	</FormPage>
</template>
