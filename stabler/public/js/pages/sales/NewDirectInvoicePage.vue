<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter, onBeforeRouteLeave } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import FormPage from "../../components/form/FormPage.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import MoneyInput from "../../components/MoneyInput.vue";

const router = useRouter();
const route = useRoute();
const session = useSession();
const toast = useToast();
const { activeCompany, user } = storeToRefs(session);

const saving = ref(false);
const isSubmitted = ref(false);
const error = ref("");
const isDirty = ref(false);

// Strict Tenant Guard: Direct Sales Invoice is ONLY allowed for MSA
// Direct (order-less) sales invoices are an imports-module capability.
const directInvoiceEnabled = computed(() => session.canAccessModule("imports"));

const customer = ref(String(route.query.new_for || route.query.customer || ""));
const postingDate = ref(todayIso());
const dueDate = ref(todayIso());
const setWarehouse = ref("");
const priceList = ref("");

const customerOptions = ref([]);
const warehouseOptions = ref([]);
const priceListOptions = ref([]);
const itemOptions = ref([]);

const items = ref([
	{ item_code: "", item_name: "", boxes: 0, box_kg: 20, qty: 0, rate: 0, uom: "Kg", warehouse: "" }
]);

const currency = computed(() => session.currency || "USD");

// Railguard: Unsaved changes warning
onBeforeRouteLeave((to, from, next) => {
	if (isDirty.value && !isSubmitted.value) {
		const answer = window.confirm(
			t("You have unsaved changes in this invoice. Are you sure you want to leave?")
		);
		if (!answer) return next(false);
	}
	next();
});

function handleBeforeUnload(e) {
	if (isDirty.value && !isSubmitted.value) {
		e.preventDefault();
		e.returnValue = "";
	}
}

onMounted(async () => {
	window.addEventListener("beforeunload", handleBeforeUnload);
	await Promise.all([loadCustomers(), loadWarehouses(), loadPriceLists(), loadItems()]);
	await updateAllRowRates();
});

onUnmounted(() => {
	window.removeEventListener("beforeunload", handleBeforeUnload);
});

async function loadCustomers(q = "") {
	try {
		const res = await call("stabler.api.sales.list_customers", {
			company: activeCompany.value,
			search: q || "",
			limit: 100,
		});
		customerOptions.value = (res || []).map((c) => ({
			value: c.name,
			label: `${c.customer_name || c.name} (${c.name})`,
		}));
	} catch {
		customerOptions.value = [];
	}
}

async function loadWarehouses() {
	try {
		const res = await call("stabler.api.inventory.list_stock_warehouses", {
			company: activeCompany.value,
		});
		warehouseOptions.value = (res || []).map((w) => ({
			value: w.name,
			label: w.warehouse_name || w.name,
		}));
		if (warehouseOptions.value.length && !setWarehouse.value) {
			setWarehouse.value = warehouseOptions.value[0].value;
		}
	} catch {
		warehouseOptions.value = [];
	}
}

async function loadPriceLists() {
	try {
		const res = await call("stabler.api.sales.list_selling_price_lists");
		priceListOptions.value = (res || []).map((pl) => ({
			value: pl.name,
			label: `${pl.name}${pl.currency ? ` (${pl.currency})` : ""}`,
		}));
		if (priceListOptions.value.length && !priceList.value) {
			priceList.value = priceListOptions.value[0].value;
		}
	} catch {
		priceListOptions.value = [];
	}
}

async function loadItems() {
	try {
		// For MSA: do NOT pass warehouse filter, fetch ALL items regardless of stock availability
		const res = await call("stabler.api.inventory.list_items", {
			context: "all",
			limit: 500,
		});
		itemOptions.value = (res || []).map((it) => ({
			value: it.name || it.item_code,
			label: `${it.name} - ${it.item_name || it.name}`,
			raw: it,
		}));
	} catch {
		itemOptions.value = [];
	}
}

async function fetchRateForItem(idx, itemCode) {
	if (!itemCode) return;
	try {
		const res = await call("stabler.api.sales.get_item_price", {
			item_code: itemCode,
			company: activeCompany.value,
			customer: customer.value || undefined,
			price_list: priceList.value || undefined,
		});
		if (res && typeof res.price_list_rate === "number" && res.price_list_rate > 0) {
			items.value[idx].rate = Number(res.price_list_rate);
			return;
		}
	} catch (_) {
		/* fallback to standard rate */
	}

	const opt = itemOptions.value.find((o) => o.value === itemCode);
	if (opt && opt.raw) {
		items.value[idx].rate = Number(opt.raw.standard_rate || opt.raw.valuation_rate || 0);
	}
}

async function updateAllRowRates() {
	for (let i = 0; i < items.value.length; i++) {
		if (items.value[i].item_code) {
			await fetchRateForItem(i, items.value[i].item_code);
		}
	}
}

function onItemSelect(idx, itemCode) {
	const opt = itemOptions.value.find((o) => o.value === itemCode);
	if (opt && opt.raw) {
		const it = opt.raw;
		items.value[idx].item_code = it.name || it.item_code;
		items.value[idx].item_name = it.item_name || it.name;
		items.value[idx].uom = it.stock_uom || "Kg";
		fetchRateForItem(idx, items.value[idx].item_code);
	}
	isDirty.value = true;
}

watch(priceList, () => {
	updateAllRowRates();
});

watch(customer, async (newCust) => {
	if (newCust) {
		try {
			const res = await call("stabler.api.sales.get_customer_details", {
				customer: newCust,
				company: activeCompany.value,
			});
			if (res && res.default_price_list) {
				priceList.value = res.default_price_list;
			}
		} catch (_) {}
	}
	updateAllRowRates();
});

function addRow() {
	items.value.push({ item_code: "", item_name: "", boxes: 0, box_kg: 20, qty: 0, rate: 0, uom: "Kg", warehouse: "" });
	isDirty.value = true;
}

function removeRow(idx) {
	if (items.value.length > 1) {
		items.value.splice(idx, 1);
		isDirty.value = true;
	}
}

function onBoxesOrBoxKgChange(row) {
	const b = Number(row.boxes || 0);
	const bk = Number(row.box_kg || 0);
	if (b > 0 && bk > 0) {
		row.qty = Number((b * bk).toFixed(2));
	}
	isDirty.value = true;
}

function onQtyChange(row) {
	const q = Number(row.qty || 0);
	const b = Number(row.boxes || 0);
	if (b > 0 && q > 0) {
		row.box_kg = Number((q / b).toFixed(2));
	}
	isDirty.value = true;
}

const totalBoxes = computed(() => {
	return items.value.reduce((sum, row) => sum + Number(row.boxes || 0), 0);
});

const totalKg = computed(() => {
	return items.value.reduce((sum, row) => sum + Number(row.qty || 0), 0);
});

const totalAmount = computed(() => {
	return items.value.reduce((sum, row) => sum + Number(row.qty || 0) * Number(row.rate || 0), 0);
});

async function saveInvoice(submitNow = false) {
	if (!directInvoiceEnabled.value) {
		error.value = t("Direct Sales Invoicing is only enabled for MSA. For this company, Sales Invoices must be created from a submitted Sales Order.");
		return;
	}
	if (!customer.value) {
		error.value = t("Please select a customer.");
		return;
	}
	const validItems = items.value.filter((it) => it.item_code && Number(it.qty) > 0);
	if (!validItems.length) {
		error.value = t("Please add at least one line item with a valid item and net weight (Qty).");
		return;
	}

	saving.value = true;
	error.value = "";

	try {
		const res = await call("stabler.api.sales.create_direct_sales_invoice", {
			company: activeCompany.value,
			customer: customer.value,
			items: validItems,
			posting_date: postingDate.value,
			due_date: dueDate.value,
			set_warehouse: setWarehouse.value,
			price_list: priceList.value,
			currency: currency.value,
			submit_now: submitNow ? 1 : 0,
		});

		isSubmitted.value = true;
		isDirty.value = false;

		toast.success(
			submitNow
				? t("Direct Invoice {0} submitted successfully!", [res.name])
				: t("Draft Invoice {0} created!", [res.name])
		);
		router.push(`/sales/invoices/${res.name}`);
	} catch (err) {
		error.value = err?.message || t("Failed to save invoice.");
	} finally {
		saving.value = false;
	}
}
</script>

<template>
	<FormPage
		:title="t('New Direct Sales Invoice')"
		doc-name="new"
		:loading="false"
		:action-error="error"
		back-path="/sales/invoices"
	>
		<template #actions>
			<div class="d-flex gap-2">
				<button type="button" class="btn btn-light" :disabled="saving" @click="router.push('/sales/invoices')">
					{{ t("Cancel") }}
				</button>
				<button type="button" class="btn btn-dark px-3" :disabled="saving || !directInvoiceEnabled" @click="saveInvoice(false)">
					<i v-if="saving" class="spinner-border spinner-border-sm me-1"></i>
					<i v-else class="ti ti-file me-1"></i>{{ t("Save Draft") }}
				</button>
				<button type="button" class="btn btn-primary px-3" :disabled="saving || !directInvoiceEnabled" @click="saveInvoice(true)">
					<i v-if="saving" class="spinner-border spinner-border-sm me-1"></i>
					<i v-else class="ti ti-check me-1"></i>{{ t("Save & Submit") }}
				</button>
			</div>
		</template>

		<!-- Non-MSA Guard Banner -->
		<div v-if="!directInvoiceEnabled" class="alert alert-warning mb-3 shadow-sm d-flex align-items-center gap-2" role="alert">
			<i class="ti ti-alert-triangle fs-2 text-warning"></i>
			<div>
				<div class="fw-bold">{{ t("Direct Sales Invoicing Restricted") }}</div>
				<div class="small">
					{{ t("Direct Sales Invoicing is only enabled for MSA. For company '{0}', Sales Invoices must be created from a submitted Sales Order.", [activeCompany]) }}
				</div>
			</div>
			<button type="button" class="btn btn-sm btn-outline-dark ms-auto" @click="router.push('/sales/orders')">
				<i class="ti ti-clipboard-check me-1"></i>{{ t("Go to Sales Orders") }}
			</button>
		</div>

		<!-- Main Form Body -->
		<div class="card border-0 shadow-sm rounded-4 mb-3" :class="{ 'opacity-50 pointer-events-none': !directInvoiceEnabled }">
			<div class="card-body p-4 bg-white">
				<!-- Header Fields -->
				<div class="row g-3 mb-3">
					<div class="col-md-4">
						<label class="form-label text-uppercase text-secondary fw-bold small mb-1 required">{{ t("CUSTOMER") }}</label>
						<Select
							v-model="customer"
							:options="customerOptions"
							:placeholder="t('Select customer…')"
							filterable
							@update:model-value="isDirty = true"
						/>
					</div>
					<div class="col-md-4">
						<label class="form-label text-uppercase text-secondary fw-bold small mb-1 required">{{ t("DATE") }}</label>
						<DateInput v-model="postingDate" @update:model-value="isDirty = true" />
					</div>
					<div class="col-md-4">
						<label class="form-label text-uppercase text-secondary fw-bold small mb-1 required">{{ t("DUE DATE") }}</label>
						<DateInput v-model="dueDate" @update:model-value="isDirty = true" />
					</div>
				</div>

				<div class="row g-3 mb-4">
					<div class="col-md-6">
						<label class="form-label text-uppercase text-secondary fw-bold small mb-1">{{ t("SOURCE WAREHOUSE") }}</label>
						<Select
							v-model="setWarehouse"
							:options="warehouseOptions"
							:placeholder="t('Select warehouse…')"
							@update:model-value="isDirty = true"
						/>
					</div>
					<div class="col-md-6">
						<label class="form-label text-uppercase text-secondary fw-bold small mb-1">{{ t("PRICE LIST") }}</label>
						<Select
							v-model="priceList"
							:options="priceListOptions"
							:placeholder="t('Select price list…')"
							@update:model-value="isDirty = true"
						/>
					</div>
				</div>

				<!-- Meat Sales Line Items Table (# | ITEM CODE/NAME | BOXES | BOX KG | TOTAL KG | RATE | AMOUNT) -->
				<div class="mb-3">
					<label class="form-label text-uppercase text-secondary fw-bold small mb-2">{{ t("ITEMS") }}</label>

					<div class="p-3 border rounded-4" style="background-color: #f8fafc;">
						<div class="table-responsive">
							<table class="table table-borderless align-middle m-0">
								<thead>
									<tr class="text-uppercase text-secondary small fw-bold border-bottom">
										<th style="width: 40px" class="text-center">#</th>
										<th style="min-width: 280px">{{ t("ITEM CODE / NAME") }}</th>
										<th style="width: 100px" class="text-center">{{ t("BOXES") }}</th>
										<th style="width: 100px" class="text-center">{{ t("BOX KG") }}</th>
										<th style="width: 110px" class="text-end">{{ t("TOTAL KG") }}</th>
										<th style="width: 130px" class="text-end">{{ t("RATE") }}</th>
										<th style="width: 140px" class="text-end">{{ t("AMOUNT") }}</th>
										<th style="width: 40px"></th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(row, idx) in items" :key="idx" class="border-bottom">
										<td class="text-center text-muted font-monospace fw-bold">{{ idx + 1 }}</td>
										<td>
											<Select
												v-model="row.item_code"
												:options="itemOptions"
												:placeholder="t('Select item…')"
												filterable
												size="sm"
												@update:model-value="(val) => onItemSelect(idx, val)"
											/>
										</td>
										<td>
											<input
												v-model.number="row.boxes"
												type="number"
												min="0"
												class="form-control form-control-sm text-center font-monospace rounded-3 bg-white"
												@input="onBoxesOrBoxKgChange(row)"
											/>
										</td>
										<td>
											<input
												v-model.number="row.box_kg"
												type="number"
												step="0.1"
												min="0"
												class="form-control form-control-sm text-center font-monospace rounded-3 bg-white"
												@input="onBoxesOrBoxKgChange(row)"
											/>
										</td>
										<td class="text-end font-monospace fw-bold h5 m-0 text-body">
											<input
												v-model.number="row.qty"
												type="number"
												step="0.01"
												min="0"
												class="form-control form-control-sm text-end font-monospace rounded-3 bg-white fw-bold"
												@input="onQtyChange(row)"
											/>
										</td>
										<td>
											<MoneyInput v-model="row.rate" :currency="currency" size="sm" class="rounded-3 bg-white" @update:model-value="isDirty = true" />
										</td>
										<td class="text-end font-monospace fw-bold h5 m-0 text-body">
											{{ formatMoney(Number(row.qty || 0) * Number(row.rate || 0), currency, user.language) }}
										</td>
										<td class="text-center">
											<button
												type="button"
												class="btn btn-sm btn-ghost-danger px-1"
												:disabled="items.length <= 1"
												@click="removeRow(idx)"
											>
												<i class="ti ti-trash text-muted"></i>
											</button>
										</td>
									</tr>
								</tbody>
							</table>
						</div>

						<div class="pt-3">
							<button type="button" class="btn btn-sm btn-success-lt fw-bold rounded-3 px-3 py-1 text-success" @click="addRow">
								<i class="ti ti-plus me-1"></i>{{ t("Add Item") }}
							</button>
						</div>
					</div>
				</div>

				<!-- Summary Card -->
				<div class="row justify-content-end mb-2">
					<div class="col-md-5 col-lg-4">
						<div class="bg-light border rounded-4 p-3 text-end shadow-none">
							<div class="d-flex justify-content-between align-items-center mb-1">
								<span class="text-secondary fw-semibold small">{{ t("Total Boxes:") }}</span>
								<span class="font-monospace fw-bold text-body">{{ totalBoxes }}</span>
							</div>
							<div class="d-flex justify-content-between align-items-center mb-2">
								<span class="text-secondary fw-semibold small">{{ t("Total Weight:") }}</span>
								<span class="font-monospace fw-bold h4 m-0 text-body">{{ totalKg.toLocaleString("ru-RU") }} kg</span>
							</div>
							<div class="d-flex justify-content-between align-items-center pt-2 border-top">
								<span class="fw-bold text-body">{{ t("Grand Total:") }}</span>
								<span class="font-monospace fw-bold h3 m-0 text-dark">
									{{ formatMoney(totalAmount, currency, user.language) }}
								</span>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</FormPage>
</template>
