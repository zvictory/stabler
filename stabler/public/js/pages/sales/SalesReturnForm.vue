<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { itemSearcher } from "../../composables/items.js";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import FormPage from "../../components/form/FormPage.vue";
import LineItemsEditor from "../../components/LineItemsEditor.vue";
import { useDocumentForm } from "../../composables/useDocumentForm.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();

const today = todayIso();
const warehouses = ref([]);
const warehousesLoading = ref(false);

const currency = computed(() => form.value.currency || session.currency || "UZS");

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

function blankForm() {
	return {
		customer: "",
		customer_name: "",
		warehouse: "",
		posting_date: today,
		currency: "",
		price_list: "",
		items: [blankLine()],
	};
}

function toPayload(m) {
	return {
		company: activeCompany.value,
		customer: m.customer,
		warehouse: m.warehouse,
		posting_date: m.posting_date,
		items: m.items
			.filter((line) => line.item_code && Number(line.qty || 0) > 0)
			.map((line) => ({
				item_code: line.item_code,
				qty: Number(line.qty || 0),
				uom: line.uom || line.stock_uom || undefined,
				rate: Number(line.rate || 0),
			})),
	};
}

// Document engine hook
const {
	model: form,
	loading,
	saving: actionRunning,
	error: actionError,
	isFormValid,
	save,
} = useDocumentForm({
	doctype: "Sales Invoice",
	createApi: "stabler.api.sales.create_direct_sales_return",
	blankModel: blankForm,
	toPayload,
	backPath: "/sales/invoices",
});

const total = computed(() =>
	form.value.items.reduce((sum, line) => sum + Number(line.qty || 0) * Number(line.rate || 0), 0)
);

const creditTotal = computed(() => -Math.abs(total.value || 0));

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

const searchItems = itemSearcher("sales", { warehouse: () => form.value.warehouse });

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

async function handlePickItem({ line, item, index, field }) {
	if (field === "item") {
		await pickItem(line, item);
	}
}

const isFormValidState = ref(true);
function handleValidityChange(valid) {
	isFormValidState.value = valid;
}

async function submitReturn() {
	actionError.value = "";
	if (!form.value.customer) {
		actionError.value = t("Pick a customer.");
		return;
	}
	if (!form.value.warehouse) {
		actionError.value = t("Pick a warehouse.");
		return;
	}
	await save();
}

watch(activeCompany, async () => {
	form.value.warehouse = "";
	warehouses.value = [];
	await loadWarehouses();
});

onMounted(async () => {
	await loadWarehouses();
});
</script>

<template>
	<FormPage
		:title="t('New Sales Return')"
		:doc-name="t('Direct credit note')"
		:loading="loading"
		:error="actionError"
		back-path="/sales/invoices"
	>
		<div class="alert alert-info">
			<i class="ti ti-info-circle me-1"></i>
			{{ t("This creates a submitted credit note (return invoice) and updates inventory automatically.") }}
		</div>

		<!-- Header fields -->
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
			<div class="col-md-3">
				<label class="form-label required">{{ t("Warehouse (returns)") }}</label>
				<Select
					v-model="form.warehouse"
					:options="warehouses"
					value-key="name"
					:disabled="warehousesLoading"
					:placeholder="warehousesLoading ? t('Loading warehouses…') : t('Pick return warehouse')"
				>
					<template #option="{ option }">{{ option.warehouse_name }} ({{ option.name }})</template>
					<template #selected="{ option }">{{ option.warehouse_name }} ({{ option.name }})</template>
				</Select>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Posting date") }}</label>
				<DateInput v-model="form.posting_date" />
			</div>
		</div>

		<div class="datagrid mb-3">
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Total credit value") }}</div>
				<div class="datagrid-content font-monospace fw-bold text-red">
					{{ formatMoney(creditTotal, currency, user.language) }}
				</div>
			</div>
		</div>

		<!-- Items -->
		<h6 class="text-uppercase text-secondary small mb-2">{{ t("Items") }}</h6>
		<LineItemsEditor
			v-if="form"
			:items="form.items"
			:editable="true"
			:currency="currency"
			:search-items="searchItems"
			:blank-line="blankLine"
			@pick-item="handlePickItem"
			@validity-change="handleValidityChange"
		>
			<template #footer-extra>
				<tr>
					<td colspan="2" class="align-middle">
						<span class="badge bg-secondary-lt">{{ form.items.length }} {{ form.items.length === 1 ? t('item') : t('items') }}</span>
					</td>
					<td colspan="3"></td>
					<td class="text-end font-monospace fw-bold py-2 text-red">{{ formatMoney(creditTotal, currency, user.language) }}</td>
				</tr>
			</template>
		</LineItemsEditor>

		<!-- Actions -->
		<template #actions>
			<button
				type="button"
				class="btn btn-link link-secondary"
				:disabled="actionRunning"
				@click="router.push('/sales/invoices')"
			>
				{{ t("Cancel") }}
			</button>
			<button
				type="button"
				class="btn btn-warning ms-auto"
				:disabled="actionRunning || !isFormValidState"
				@click="submitReturn"
			>
				<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
				<i v-else class="ti ti-receipt-refund me-1"></i>{{ t("Create credit note") }}
			</button>
		</template>
	</FormPage>
</template>
