<script setup>
import { ref, computed, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { formatMoney } from "../composables/money.js";
import { todayIso } from "../composables/date.js";
import { t } from "../composables/i18n.js";
import { useToast } from "../composables/useToast.js";
import DateInput from "./DateInput.vue";
import Select from "./Select.vue";
import MoneyInput from "./MoneyInput.vue";

const props = defineProps({
	open: { type: Boolean, default: false },
	initialCustomer: { type: String, default: "" },
	initialCustomerName: { type: String, default: "" },
});

const emit = defineEmits(["close", "created"]);
const router = useRouter();
const session = useSession();
const toast = useToast();
const { activeCompany, user } = storeToRefs(session);

const saving = ref(false);
const error = ref("");

const customer = ref("");
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

watch(
	() => props.open,
	(isOpen) => {
		if (isOpen) {
			error.value = "";
			customer.value = props.initialCustomer || "";
			postingDate.value = todayIso();
			dueDate.value = todayIso();
			items.value = [{ item_code: "", item_name: "", boxes: 0, box_kg: 20, qty: 0, rate: 0, uom: "Kg", warehouse: "" }];
			loadCustomers("");
			loadWarehouses();
			loadPriceLists();
			loadItems();
		}
	},
	{ immediate: true }
);

function onItemSelect(idx, itemCode) {
	const opt = itemOptions.value.find((o) => o.value === itemCode);
	if (opt && opt.raw) {
		const it = opt.raw;
		items.value[idx].item_code = it.name || it.item_code;
		items.value[idx].item_name = it.item_name || it.name;
		items.value[idx].rate = Number(it.standard_rate || it.valuation_rate || 0);
		items.value[idx].uom = it.stock_uom || "Kg";
	}
}

function addRow() {
	items.value.push({ item_code: "", item_name: "", boxes: 0, box_kg: 20, qty: 0, rate: 0, uom: "Kg", warehouse: "" });
}

function removeRow(idx) {
	if (items.value.length > 1) {
		items.value.splice(idx, 1);
	}
}

function onBoxesOrBoxKgChange(row) {
	const b = Number(row.boxes || 0);
	const bk = Number(row.box_kg || 0);
	if (b > 0 && bk > 0) {
		row.qty = Number((b * bk).toFixed(2));
	}
}

function onQtyChange(row) {
	const q = Number(row.qty || 0);
	const b = Number(row.boxes || 0);
	if (b > 0 && q > 0) {
		row.box_kg = Number((q / b).toFixed(2));
	}
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

		toast.success(
			submitNow
				? t("Invoice {0} submitted successfully!", [res.name])
				: t("Draft Invoice {0} created!", [res.name])
		);
		emit("created", res);
		emit("close");
		router.push(`/sales/invoices/${res.name}`);
	} catch (err) {
		error.value = err?.message || t("Failed to save invoice.");
	} finally {
		saving.value = false;
	}
}
</script>

<template>
	<div v-if="open" class="modal modal-blur fade show d-block" tabindex="-1" style="background: rgba(0,0,0,0.5)">
		<div class="modal-dialog modal-xl modal-dialog-centered" role="document">
			<div class="modal-content shadow-lg border-0 rounded-4">
				<!-- Header -->
				<div class="modal-header bg-white border-bottom py-3 px-4">
					<h4 class="modal-title fw-bold text-body m-0 d-flex align-items-center gap-2">
						<i class="ti ti-file-invoice text-success fs-2"></i>{{ t("New Invoice") }}
					</h4>
					<button type="button" class="btn-close" :disabled="saving" @click="emit('close')"></button>
				</div>

				<div class="modal-body p-4 bg-white">
					<div v-if="error" class="alert alert-danger mb-3 py-2">{{ error }}</div>

					<!-- Header Fields Row -->
					<div class="row g-3 mb-3">
						<div class="col-md-4">
							<label class="form-label text-uppercase text-secondary fw-bold small mb-1">{{ t("CUSTOMER") }}</label>
							<Select
								v-model="customer"
								:options="customerOptions"
								:placeholder="t('Select customer…')"
								filterable
							/>
						</div>
						<div class="col-md-4">
							<label class="form-label text-uppercase text-secondary fw-bold small mb-1">{{ t("DATE") }}</label>
							<DateInput v-model="postingDate" />
						</div>
						<div class="col-md-4">
							<label class="form-label text-uppercase text-secondary fw-bold small mb-1">{{ t("DUE DATE") }}</label>
							<DateInput v-model="dueDate" />
						</div>
					</div>

					<!-- Warehouse & Price List Row -->
					<div class="row g-3 mb-4">
						<div class="col-md-6">
							<label class="form-label text-uppercase text-secondary fw-bold small mb-1">{{ t("SOURCE WAREHOUSE") }}</label>
							<Select
								v-model="setWarehouse"
								:options="warehouseOptions"
								:placeholder="t('Select warehouse…')"
							/>
						</div>
						<div class="col-md-6">
							<label class="form-label text-uppercase text-secondary fw-bold small mb-1">{{ t("PRICE LIST") }}</label>
							<Select
								v-model="priceList"
								:options="priceListOptions"
								:placeholder="t('Select price list…')"
							/>
						</div>
					</div>

					<!-- ITEMS Section -->
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
												<MoneyInput v-model="row.rate" :currency="currency" size="sm" class="rounded-3 bg-white" />
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

					<!-- Bottom Summary Card -->
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

				<!-- Footer Buttons -->
				<div class="modal-footer bg-white border-top py-3 px-4 d-flex justify-content-end gap-2">
					<button type="button" class="btn btn-light px-4 rounded-3" :disabled="saving" @click="emit('close')">
						{{ t("Close") }}
					</button>
					<button type="button" class="btn btn-dark px-4 rounded-3" :disabled="saving" @click="saveInvoice(false)">
						<i v-if="saving" class="spinner-border spinner-border-sm me-1"></i>
						<i v-else class="ti ti-file me-1"></i>{{ t("Save Draft") }}
					</button>
					<button type="button" class="btn btn-primary px-4 rounded-3" :disabled="saving" @click="saveInvoice(true)">
						<i v-if="saving" class="spinner-border spinner-border-sm me-1"></i>
						<i v-else class="ti ti-check me-1"></i>{{ t("Submit") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
