<script setup>
/**
 * Sales Invoice — the modern write screen for order-less (direct) invoicing.
 *
 * MSA sells meat out of a warehouse without ever raising a Sales Order, so the
 * invoice IS the first document. That is why this screen exists next to, rather
 * than inside, the Sales Order form: the modern *experience* was wanted here,
 * the order *concept* was not — no promised date, no stock held back, no pipeline.
 *
 * Two units run side by side and both matter. The money on a line is priced per
 * kilo; the warehouse counts boxes. `boxes x box_kg = qty` keeps them in step,
 * and both halves are sent so the ERP stores what the floor actually counted.
 *
 * Saving a draft and submitting are separate buttons on purpose. A wrong Sales
 * Order is free to delete; a submitted invoice has already written GL entries,
 * stock ledger entries and an e-invoice. One button for both would make an
 * irreversible posting the easiest thing on the screen to hit by accident.
 */
import { ref, computed, onMounted } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { priceListRateForOrder } from "../../composables/fx.js";
import { todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useDocumentForm } from "../../composables/useDocumentForm.js";
import FormPage from "../../components/form/FormPage.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import Typeahead from "../../components/Typeahead.vue";

const route = useRoute();
const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const { confirm } = useConfirm();

/* The gate mirrors what the endpoint enforces — `direct_invoicing` on the
 * company's module flags (sales.py: create_direct_sales_invoice). It is NOT
 * read through canAccessModule(): that key is absent from _MODULE_ROLES, which
 * the role layer reads as admin-only, and it would lock out the very cashiers
 * this screen is for. The role layer still applies through `imports`, the
 * module this capability ships under. */
const roleAllowed = computed(() => session.canAccessModule("imports"));
const companyAllowed = computed(() => {
	const flag = session.modules?.direct_invoicing;
	return flag !== false && flag !== 0;
});
const canInvoice = computed(() => roleAllowed.value && companyAllowed.value);

// The document's own currency, not the session's. A draft denominated in
// anything else would otherwise be displayed in the company default AND
// re-stamped to it on every update, leaving the rates at the old currency's
// magnitude while grand_total and the receivable GL move by the FX factor.
const currency = computed(() => model.value?.currency || session.currency || "USD");

const warehouseOptions = ref([]);
const priceListOptions = ref([]);

// Raised by fetchRate() when a line's price list is quoted in a currency this
// invoice is not written in and no rate could be had for the pair: the line
// keeps its existing rate rather than taking an unconverted number, and the
// cashier is told so instead of being left with a silently wrong price.
const rateWarning = ref(false);

// A row carries both units; `qty` is the kilos the money is priced on.
function blankRow() {
	return {
		item_code: "",
		item_name: "",
		boxes: 0,
		box_kg: 20,
		qty: 0,
		rate: 0,
		uom: "Kg",
		warehouse: "",
	};
}

function blankModel() {
	return {
		customer: "",
		customer_name: "",
		posting_date: todayIso(),
		due_date: todayIso(),
		set_warehouse: "",
		price_list: "",
		currency: "",
		remarks: "",
		items: [blankRow()],
	};
}

// Set for the create-and-submit path only: the create endpoint submits inside
// the same transaction, so the flag rides along on the create payload.
const submitOnCreate = ref(false);

function toPayload(m) {
	return {
		company: activeCompany.value,
		customer: m.customer,
		posting_date: m.posting_date,
		due_date: m.due_date,
		set_warehouse: m.set_warehouse,
		price_list: m.price_list,
		remarks: m.remarks,
		currency: currency.value,
		submit_now: submitOnCreate.value ? 1 : 0,
		items: (m.items || [])
			.filter((r) => r.item_code && Number(r.qty) > 0)
			.map((r) => ({
				item_code: r.item_code,
				qty: Number(r.qty) || 0,
				rate: Number(r.rate) || 0,
				uom: r.uom || undefined,
				warehouse: r.warehouse || undefined,
				boxes: Number(r.boxes) || 0,
				box_kg: Number(r.box_kg) || 0,
			})),
	};
}

function fromDetail(d) {
	return {
		customer: d.customer || "",
		customer_name: d.customer_name || "",
		posting_date: d.posting_date || todayIso(),
		due_date: d.due_date || todayIso(),
		set_warehouse: d.set_warehouse || "",
		price_list: d.price_list || "",
		currency: d.currency || "",
		remarks: d.remarks || "",
		items: (d.items || []).map((it) => ({
			item_code: it.item_code,
			item_name: it.item_name || it.item_code,
			// The doctype stores custom_boxes / custom_box_kg; the screen edits
			// boxes / box_kg. Read them back so a reopened draft still shows what
			// the warehouse counted.
			boxes: Number(it.custom_boxes) || 0,
			box_kg: Number(it.custom_box_kg) || 0,
			qty: Number(it.qty) || 0,
			rate: Number(it.rate) || 0,
			uom: it.uom || "Kg",
			warehouse: it.warehouse || "",
		})),
	};
}

const doc = useDocumentForm({
	doctype: "Sales Invoice",
	detailApi: "stabler.api.sales.sales_invoice_detail",
	createApi: "stabler.api.sales.create_direct_sales_invoice",
	updateApi: "stabler.api.sales.update_sales_invoice",
	submitApi: "stabler.api.sales.submit_sales_invoice",
	cancelApi: "stabler.api.sales.cancel_sales_invoice",
	amendApi: "stabler.api.sales.amend_sales_invoice",
	deleteApi: "stabler.api.sales.delete_sales_invoice",
	blankModel,
	toPayload,
	fromDetail,
	backPath: "/sales/invoices",
});

const { model, loading, saving, loadError, error, isCreate, editable, docstatus, status } = doc;

onMounted(async () => {
	await Promise.all([loadWarehouses(), loadPriceLists()]);
	// Branch on the ROUTE param, not on the engine's isCreate — isCreate is
	// derived from docName, which is null until load() runs, so a direct URL
	// hit or a refresh would otherwise render a blank New form.
	if (route.params.name) {
		await doc.load(route.params.name);
	} else if (route.query.customer || route.query.new_for) {
		model.value.customer = String(route.query.customer || route.query.new_for);
	}
});

async function loadWarehouses() {
	try {
		const res = await call("stabler.api.inventory.list_stock_warehouses", {
			company: activeCompany.value,
		});
		warehouseOptions.value = (res || []).map((w) => ({
			value: w.name,
			label: w.warehouse_name || w.name,
		}));
		if (warehouseOptions.value.length && !model.value.set_warehouse) {
			model.value.set_warehouse = warehouseOptions.value[0].value;
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
		if (priceListOptions.value.length && !model.value.price_list) {
			model.value.price_list = priceListOptions.value[0].value;
		}
	} catch {
		priceListOptions.value = [];
	}
}

function searchCustomers(q) {
	return call("stabler.api.sales.list_customers", {
		company: activeCompany.value,
		search: q,
		limit: 10,
	});
}

/* `context: "all"` is deliberate and must stay. A meat importer invoices goods
 * that are physically on the dock before any receipt document exists, so a
 * stock-filtered picker would hide exactly the items being sold today. */
function searchItems(q) {
	return call("stabler.api.inventory.list_items", { search: q, context: "all", limit: 20 });
}

async function pickCustomer(c) {
	model.value.customer = c.name;
	model.value.customer_name = c.customer_name || c.name;
	try {
		const res = await call("stabler.api.sales.get_customer_details", {
			customer: c.name,
			company: activeCompany.value,
		});
		if (res && res.default_price_list) model.value.price_list = res.default_price_list;
	} catch {
		// non-fatal — the default price list is a convenience, not a requirement
	}
	await refreshAllRates();
}

function clearCustomer() {
	model.value.customer = "";
	model.value.customer_name = "";
}

/* One rate per currency pair, not one per line. `refreshAllRates` walks every
 * row, and every row of a given invoice is priced off the same list, so without
 * this a twenty-line invoice would fire twenty CBU round trips for the identical
 * question. Clearing it is `refreshAllRates`'s job — that is also the only retry
 * a user can perform after a failed fetch, which is why a failure is cached too:
 * otherwise a CBU outage costs one 5-second timeout per line. */
const rateCache = new Map();

async function pairRate(from, to, date) {
	if (!from || !to || from === to) return 0;
	const key = `${from}>${to}@${date || ""}`;
	if (rateCache.has(key)) return rateCache.get(key);
	let rate = 0;
	try {
		const res = await call("stabler.api.sales.get_currency_exchange_rate", {
			from_currency: from,
			to_currency: to,
			date: date || undefined,
		});
		rate = Number(res?.exchange_rate) > 0 ? Number(res.exchange_rate) : 0;
	} catch {
		rate = 0;
	}
	rateCache.set(key, rate);
	return rate;
}

/* A price list is quoted in its own currency; this invoice is written in
 * another. The rule and its ONLY implementation live in `composables/fx.js` —
 * both Sales Order forms call the same `priceListRateForOrder`. A third copy
 * here is exactly how those two drifted apart, one of them silently wrong.
 *
 * The pair is fetched per price-list currency rather than held on the document
 * the way the Sales Order forms hold theirs, because this screen has no
 * exchange-rate model at all: no currency picker, no rate input, no
 * `conversion_rate` on the payload. Adding one would be a product change nobody
 * asked for. The conversion needs exactly one number — "1 price-list currency =
 * N invoice currency" — so that is all this fetches, in the direction
 * `get_currency_exchange_rate` documents and `priceListRateForOrder` reads.
 *
 * It is keyed off the currency the LOOKUP returned, never the one labelled in
 * the price-list dropdown: `get_item_price` falls back to Standard Selling for
 * an item the chosen list does not carry, and that list can be quoted in a
 * different currency again. */
async function fetchRate(row) {
	if (!row.item_code) return;
	let priced = null;
	try {
		priced = await call("stabler.api.sales.get_item_price", {
			item_code: row.item_code,
			company: activeCompany.value,
			customer: model.value.customer || undefined,
			price_list: model.value.price_list || undefined,
		});
	} catch {
		// no price list entry — the cashier types the rate
		return;
	}
	const from = priced?.currency ? String(priced.currency).trim().toUpperCase() : "";
	const to = String(currency.value || "").trim().toUpperCase();
	const rate = await pairRate(from, to, model.value.posting_date);
	// `priced` goes in whole: whether a price was resolved at all is the helper's
	// decision too, so that "no price found" stays one case and not two.
	const converted = priceListRateForOrder(priced, to, { rate, from, to }, Number(row.rate) || 0);
	if (converted.unconverted) rateWarning.value = true;
	else if (converted.rate) row.rate = converted.rate;
}

async function refreshAllRates() {
	// A full re-price recomputes every line, so any warning left over from the
	// previous price list is stale — and this is the user's retry after a rate
	// fetch that failed.
	rateWarning.value = false;
	rateCache.clear();
	for (const row of model.value.items) {
		if (row.item_code) await fetchRate(row);
	}
}

// There is deliberately no model watcher on the price list. Loading a saved draft
// replaces the whole model, which moves that field and would fire such a watcher
// with the rows already present — rewriting every negotiated rate with today's
// list price merely because the document was opened. Rates are refetched only
// when a person changes the control, or picks a customer (see pickCustomer).

async function pickItem(row, it) {
	row.item_code = it.name || it.item_code;
	row.item_name = it.item_name || row.item_code;
	row.uom = it.stock_uom || "Kg";
	recomputeQty(row);
	await fetchRate(row);
}

function addRow() {
	model.value.items.push(blankRow());
}

function removeRow(idx) {
	if (model.value.items.length > 1) model.value.items.splice(idx, 1);
}

// Boxes and box weight drive the kilos…
function recomputeQty(row) {
	const b = Number(row.boxes || 0);
	const bk = Number(row.box_kg || 0);
	if (b > 0 && bk > 0) row.qty = Number((b * bk).toFixed(2));
}

// …and a corrected weigh-in drives the average box weight back.
function recomputeBoxKg(row) {
	const q = Number(row.qty || 0);
	const b = Number(row.boxes || 0);
	if (b > 0 && q > 0) row.box_kg = Number((q / b).toFixed(2));
}

const totalBoxes = computed(() => model.value.items.reduce((s, r) => s + Number(r.boxes || 0), 0));
const totalKg = computed(() => model.value.items.reduce((s, r) => s + Number(r.qty || 0), 0));
const totalAmount = computed(() =>
	model.value.items.reduce((s, r) => s + Number(r.qty || 0) * Number(r.rate || 0), 0)
);

// Say what is wrong before the server does, in the words of the thing missing.
const validationError = computed(() => {
	if (!model.value.customer) return t("Please select a customer.");
	const valid = model.value.items.filter((r) => r.item_code && Number(r.qty) > 0);
	if (!valid.length) {
		return t("Please add at least one line item with a valid item and net weight (Qty).");
	}
	return "";
});

async function saveDraft() {
	if (validationError.value) {
		error.value = validationError.value;
		return;
	}
	submitOnCreate.value = false;
	await doc.save();
}

async function submitInvoice() {
	if (validationError.value) {
		error.value = validationError.value;
		return;
	}
	if (!isCreate.value) {
		// `update_sales_invoice` never submits — it only persists field edits. So a
		// draft that is already saved needs its own save-then-submit here, exactly
		// as SalesOrderFormModern does. Without the save, submit() sends only
		// {name, modified}; `modified` is unchanged because nothing was written, so
		// the concurrency check passes and the SERVER's pre-edit copy is posted to
		// the GL. The user's typing disappears under a green success toast.
		if (doc.isDirty.value) {
			const saved = await doc.save();
			if (!saved) return;
		}
		// The engine confirms, submits and reloads.
		await doc.submit();
		return;
	}
	const ok = await confirm({
		title: t("Submit document?"),
		body: t("Are you sure you want to submit this document? This will finalize transactions."),
		confirmLabel: t("Submit"),
		cancelLabel: t("Cancel"),
	});
	if (!ok) return;
	submitOnCreate.value = true;
	try {
		await doc.save();
	} finally {
		submitOnCreate.value = false;
	}
}

const pageTitle = computed(() =>
	isCreate.value ? t("New Direct Sales Invoice") : t("Sales Invoice")
);
</script>

<template>
	<FormPage
		:title="pageTitle"
		:doc-name="route.params.name || 'new'"
		:status="status"
		:docstatus="docstatus"
		:loading="loading"
		:error="loadError"
		:action-error="error"
		back-path="/sales/invoices"
	>
		<template #actions>
			<div class="d-flex flex-wrap align-items-center gap-3 w-100">
				<div class="d-flex flex-column">
					<span class="text-secondary small text-uppercase fw-semibold">
						{{ totalBoxes }} {{ t("BOXES") }} ·
						{{ totalKg.toLocaleString(user.language === "en" ? "en-US" : "ru-RU") }} kg
					</span>
					<span class="font-monospace fw-bold h4 m-0 text-body">
						{{ formatMoney(totalAmount, currency, user.language) }}
					</span>
					<!-- The price list is quoted in another currency and there is no rate
					     to convert it with, so the line price was left alone. Beside the
					     total rather than in the row, because the total is the figure the
					     cashier actually reads before submitting. -->
					<span v-if="rateWarning" class="small text-danger fw-semibold">
						<i class="ti ti-alert-triangle me-1"></i>
						{{ t("Exchange rate unavailable — line prices were not converted. Enter the rate manually.") }}
					</span>
				</div>
				<div class="d-flex gap-2 ms-auto">
					<button
						type="button"
						class="btn btn-outline-secondary"
						:disabled="saving || !editable || !canInvoice"
						@click="saveDraft"
					>
						<i v-if="saving" class="spinner-border spinner-border-sm me-1"></i>
						<i v-else class="ti ti-file me-1"></i>{{ t("Save Draft") }}
					</button>
					<button
						type="button"
						class="btn btn-primary px-3"
						:disabled="saving || !editable || !canInvoice"
						@click="submitInvoice"
					>
						<i v-if="saving" class="spinner-border spinner-border-sm me-1"></i>
						<i v-else class="ti ti-check me-1"></i>{{ t("Save & Submit") }}
					</button>
				</div>
			</div>
		</template>

		<div
			v-if="!canInvoice"
			class="alert alert-warning d-flex align-items-center gap-2"
			role="alert"
		>
			<i class="ti ti-alert-triangle fs-2 text-warning"></i>
			<div>
				<div class="fw-bold">{{ t("Direct Sales Invoicing Restricted") }}</div>
				<div class="small">
					{{
						t(
							"Direct Sales Invoicing is not enabled for company {0}. Sales Invoices must be created from a submitted Sales Order.",
							[activeCompany]
						)
					}}
				</div>
			</div>
		</div>

		<div :class="{ 'opacity-50 pe-none': !canInvoice }">
			<div class="row g-3 mb-3">
				<div class="col-md-4">
					<label class="form-label" :class="{ required: editable }">{{ t("CUSTOMER") }}</label>
					<Typeahead
						v-if="editable"
						v-model="model.customer"
						:search="searchCustomers"
						:display="model.customer_name || model.customer"
						:placeholder="t('Search customer name…')"
						open-on-focus
						@pick="pickCustomer"
						@clear="clearCustomer"
					>
						<template #option="{ item }">
							<div>
								<div class="fw-semibold">{{ item.customer_name || item.name }}</div>
								<div class="small text-secondary">{{ item.name }}</div>
							</div>
						</template>
					</Typeahead>
					<div v-else class="form-control-plaintext fw-semibold py-1">
						{{ model.customer_name || model.customer }}
					</div>
				</div>
				<div class="col-md-4">
					<label class="form-label" :class="{ required: editable }">{{ t("DATE") }}</label>
					<DateInput v-model="model.posting_date" :disabled="!editable" />
				</div>
				<div class="col-md-4">
					<label class="form-label" :class="{ required: editable }">{{ t("DUE DATE") }}</label>
					<DateInput v-model="model.due_date" :disabled="!editable" />
				</div>
			</div>

			<div class="row g-3 mb-4">
				<div class="col-md-6">
					<label class="form-label">{{ t("SOURCE WAREHOUSE") }}</label>
					<Select
						v-model="model.set_warehouse"
						:options="warehouseOptions"
						:disabled="!editable"
						:placeholder="t('Select warehouse…')"
					/>
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("PRICE LIST") }}</label>
					<Select
						v-model="model.price_list"
						:options="priceListOptions"
						:disabled="!editable"
						:placeholder="t('Select price list…')"
						@update:model-value="refreshAllRates"
					/>
				</div>
			</div>

			<label class="form-label">{{ t("ITEMS") }}</label>
			<div class="table-responsive border rounded-3">
				<table class="table table-borderless align-middle m-0">
					<thead>
						<tr class="text-uppercase text-secondary small fw-bold border-bottom">
							<th style="width: 40px" class="text-center">#</th>
							<th style="min-width: 260px">{{ t("ITEM CODE / NAME") }}</th>
							<th style="width: 100px" class="text-center">{{ t("BOXES") }}</th>
							<th style="width: 100px" class="text-center">{{ t("BOX KG") }}</th>
							<th style="width: 110px" class="text-end">{{ t("TOTAL KG") }}</th>
							<th style="width: 140px" class="text-end">{{ t("RATE") }}</th>
							<th style="width: 150px" class="text-end">{{ t("AMOUNT") }}</th>
							<th style="width: 40px"></th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(row, idx) in model.items" :key="idx" class="border-bottom">
							<td class="text-center text-muted font-monospace fw-bold">{{ idx + 1 }}</td>
							<td>
								<Typeahead
									v-if="editable"
									v-model="row.item_code"
									:search="searchItems"
									:display="row.item_name || row.item_code"
									:placeholder="t('Select item…')"
									size="sm"
									@pick="(it) => pickItem(row, it)"
								>
									<template #option="{ item }">
										<div>
											<div class="fw-semibold">{{ item.item_name || item.name }}</div>
											<div class="small text-secondary font-monospace">{{ item.name }}</div>
										</div>
									</template>
								</Typeahead>
								<div v-else class="small">
									<div class="fw-semibold">{{ row.item_name }}</div>
									<div class="text-secondary font-monospace">{{ row.item_code }}</div>
								</div>
							</td>
							<td>
								<input
									v-model.number="row.boxes"
									type="number"
									min="0"
									:disabled="!editable"
									class="form-control form-control-sm text-center font-monospace"
									@input="recomputeQty(row)"
								/>
							</td>
							<td>
								<input
									v-model.number="row.box_kg"
									type="number"
									step="0.1"
									min="0"
									:disabled="!editable"
									class="form-control form-control-sm text-center font-monospace"
									@input="recomputeQty(row)"
								/>
							</td>
							<td>
								<input
									v-model.number="row.qty"
									type="number"
									step="0.01"
									min="0"
									:disabled="!editable"
									class="form-control form-control-sm text-end font-monospace fw-bold"
									@input="recomputeBoxKg(row)"
								/>
							</td>
							<td>
								<MoneyInput
									v-model="row.rate"
									:currency="currency"
									:language="user.language"
									:disabled="!editable"
									size="sm"
								/>
							</td>
							<td class="text-end font-monospace fw-bold">
								{{
									formatMoney(Number(row.qty || 0) * Number(row.rate || 0), currency, user.language)
								}}
							</td>
							<td class="text-center">
								<button
									type="button"
									class="btn btn-sm btn-ghost-danger px-1"
									:disabled="!editable || model.items.length <= 1"
									@click="removeRow(idx)"
								>
									<i class="ti ti-trash text-muted"></i>
								</button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<div v-if="editable" class="pt-3">
				<button type="button" class="btn btn-sm btn-outline-secondary" @click="addRow">
					<i class="ti ti-plus me-1"></i>{{ t("Add Item") }}
				</button>
			</div>
		</div>
	</FormPage>
</template>
