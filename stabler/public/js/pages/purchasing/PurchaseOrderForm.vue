<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { grossRate } from "../../composables/pricing.js";
import { formatDate, formatDateTime, todayIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { itemSearcher } from "../../composables/items.js";
import DateInput from "../../components/DateInput.vue";
import Typeahead from "../../components/Typeahead.vue";
import Select from "../../components/Select.vue";
import RelatedDocuments from "../../components/RelatedDocuments.vue";
import FormPage from "../../components/form/FormPage.vue";
import LineItemsEditor from "../../components/LineItemsEditor.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import { useDocumentForm } from "../../composables/useDocumentForm.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
const route = useRoute();

const today = todayIso();

// Lookups
const warehouses = ref([]);
const warehousesLoading = ref(false);
const priceLists = ref([]);
const currencies = ref([]);
const showDiscounts = ref(false);
const autoSubmit = ref(1);

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const currencySymbol = computed(() => {
	const code = form.value.currency || currency.value;
	return (currencies.value.find((c) => c.name === code) || {}).symbol || "";
});

// Tender (Deal) picker — same idiom as Expenses.vue's kassa tagging: only
// rendered/sent when the tender module is on for this company (KOP-07,
// docs/uat/tender/02-tender-uzmani.md:1027 — no SPA screen wrote
// Purchase Order.custom_crm_deal except the sourcing award bridge).
const tenderOn = computed(() => session.canAccessModule("tender"));
const dealLabel = ref("");

// Same buyer, several tenders (UAT G.7): `organization` alone collapsed every
// deal of one buyer onto one label — five cards all reading "Mikas Savdo". The
// deal's own id is always unique, so it is appended rather than swapped in: a
// rep still recognises the buyer name at a glance, and can now tell the cards
// apart. One function so the search dropdown and the locked label can never
// drift onto two different rules for the same deal.
function dealOptionLabel(d) {
	const primary = d?.organization || d?.lead_name || "";
	return primary ? `${primary} · ${d.name}` : d?.name || "";
}

async function searchDeals(q) {
	const r = await call("stabler.api.crm.list_deals", {
		company: activeCompany.value,
		search: q,
		page_length: 8,
	});
	return (r?.deals || []).map((d) => ({ name: d.name, label: dealOptionLabel(d) }));
}

function pickDeal(item) {
	form.value.deal = item.name;
	dealLabel.value = item.label;
}

function clearDeal() {
	form.value.deal = "";
	dealLabel.value = "";
}

async function loadDealLabel(dealName) {
	if (!dealName) {
		dealLabel.value = "";
		return;
	}
	try {
		const d = await call("stabler.api.crm.get_deal", { name: dealName });
		dealLabel.value = d ? dealOptionLabel(d) : dealName;
	} catch {
		dealLabel.value = dealName;
	}
}

// A PO arriving from a tender screen (e.g. `?deal=<name>`) should prefill —
// but only where the tender module is actually on, so a stray query param
// never surfaces or ships on a tenant that doesn't have the module.
function resolveDealFromQuery(queryDeal, tenderModuleOn) {
	if (!tenderModuleOn || !queryDeal) return "";
	return String(queryDeal);
}

// `tenderOn` reads session module data that is not always resolved by the time
// this component mounts (UAT G.7: opening a `?deal=` link showed no deal in the
// picker) — the boot company and the SPA's active company need not be the same
// on the very first render. So the query is applied the FIRST time tenderOn is
// seen true, whether that is at mount (below) or later (the `watch` beside
// `loadDoc`), and only once: a company switch that flips tenderOn off-and-on
// again must not re-fight a deal the user has since cleared.
//
// That "first time seen true" can land WHILE onMounted's own
// `Promise.all([loadWarehouses(), ...])` is still pending — session boot
// resolving in parallel — i.e. before the create branch below has replaced
// `form.value` with `blankForm()`. Applying the deal there would write onto
// the pre-mount model and latch `queryDealApplied`, and the `blankForm()`
// assignment that follows would silently discard that write with no way left
// to re-apply it. `createFormReady` gates `applyQueryDeal` on the create
// branch having actually run `form.value = blankForm()` first, so the watcher
// can only ever write onto the model the form is actually going to keep.
let queryDealApplied = false;
let createFormReady = false;

async function applyQueryDeal() {
	if (queryDealApplied || docName.value || !tenderOn.value || !createFormReady) return;
	const resolved = resolveDealFromQuery(route.query?.deal, tenderOn.value);
	if (!resolved) return;
	queryDealApplied = true;
	form.value.deal = resolved;
	await loadDealLabel(resolved);
}

async function loadWarehouses() {
	if (!activeCompany.value) return;
	warehousesLoading.value = true;
	try {
		warehouses.value = await call("stabler.api.inventory.list_stock_warehouses", {
			company: activeCompany.value,
		});
	} catch {
		warehouses.value = [];
	} finally {
		warehousesLoading.value = false;
	}
}

async function loadPriceLists() {
	try {
		priceLists.value = await call("stabler.api.sales.list_price_lists", { buying_only: 1 });
	} catch {
		priceLists.value = [];
	}
}

async function loadCurrencies() {
	try {
		currencies.value = await call("stabler.api.sales.list_currencies");
	} catch {
		currencies.value = [];
	}
}

function blankLine() {
	return {
		item_code: "",
		item_name: "",
		custom_line_note: "",
		uom: "",
		qty: 1,
		dimension_mode: "",
		custom_length: null,
		custom_width: null,
		custom_height: null,
		custom_pieces: null,
		rate: 0,
		discount_percentage: 0,
		discount_amount: 0,
		amount: 0,
	};
}

function blankForm() {
	return {
		supplier: "",
		supplier_name: "",
		currency: "",
		price_list: "",
		set_warehouse: "",
		transaction_date: today,
		schedule_date: today,
		remarks: "",
		items: [blankLine()],
		deal: "",
	};
}

// Map detail to our internal form model
function fromDetail(d) {
	// Same two traps as the invoice form, and for the same reasons.
	//
	// A buying price list quoted in the company's base currency arrives on a
	// foreign-currency order converted into the document currency, and ERPNext
	// books the whole gap as a discount — three of the three discounted purchase
	// order lines on anjan read 99.992 % this way. `plr × conversion_rate ≈ rate`
	// is that signature, and nothing else produces it.
	//
	// And the rate column is the PRE-discount price, while the document's `rate`
	// is the post-discount one (api/_pricing.py). Loading one into the other
	// discounts the line a second time on every reopen.
	const cr = d.currency !== d.base_currency ? Number(d.conversion_rate || 0) : 0;
	return {
		supplier: d.supplier,
		supplier_name: d.supplier_name || d.supplier,
		currency: d.currency || "",
		price_list: d.buying_price_list || "",
		set_warehouse: d.set_warehouse || "",
		transaction_date: d.transaction_date || "",
		schedule_date: d.schedule_date || "",
		// Read-only server facts the view reads off the model — `canReceive`,
		// `canCreateInvoice`, the KPI strip, the receipts banner and the receive
		// dialog. `toPayload` never sends them back. Dropping them here left every
		// submitted order without Receive / Create Invoice and with "—" for each
		// KPI (measured 2026-09-05, RU walk, screen 14c).
		docstatus: d.docstatus ?? 0,
		status: d.status || "",
		net_total: Number(d.net_total || 0),
		grand_total: Number(d.grand_total || 0),
		per_received: Number(d.per_received || 0),
		per_billed: Number(d.per_billed || 0),
		purchase_invoices: d.purchase_invoices || [],
		purchase_receipts: d.purchase_receipts || [],
		remarks: d.remarks || d.terms || "",
		items: (d.items || []).map((it) => {
			const rate = Number(it.rate || 0);
			const plr = Number(it.price_list_rate || 0);
			const isArtifact = cr > 0 && plr > 0 && Math.abs(plr * cr - rate) < 1;
			const listRate = isArtifact ? 0 : plr;
			return {
				item_code: it.item_code,
				// The row name is the `po_detail` the receive dialog posts; received_qty
				// is what it subtracts to get the pending qty (and the per-line badge).
				name: it.name,
				received_qty: Number(it.received_qty || 0),
				item_name: it.item_name,
				custom_line_note: it.custom_line_note || "",
				uom: it.uom || "",
				qty: Number(it.qty || 0),
				dimension_mode: it.custom_dimension_mode || "",
				custom_length: it.custom_length ?? null,
				custom_width: it.custom_width ?? null,
				custom_height: it.custom_height ?? null,
				custom_pieces: it.custom_pieces ?? null,
				rate: grossRate({ rate, price_list_rate: listRate }),
				price_list_rate: listRate,
				discount_percentage: isArtifact ? 0 : Number(it.discount_percentage || 0),
				discount_amount: isArtifact ? 0 : Number(it.discount_amount || 0),
				amount: Number(it.amount || 0),
			};
		}),
	};
}

function toPayload(m) {
	const lines = m.items
		.filter((r) => r.item_code)
		.map((r) => ({
			item_code: r.item_code,
			qty: r.qty,
			rate: r.rate,
			custom_line_note: r.custom_line_note || undefined,
			uom: r.uom,
			discount_percentage: r.discount_percentage || 0,
			discount_amount: r.discount_amount || 0,
			custom_length: r.custom_length ?? undefined,
			custom_width: r.custom_width ?? undefined,
			custom_height: r.custom_height ?? undefined,
			custom_pieces: r.custom_pieces ?? undefined,
		}));
	return {
		company: activeCompany.value,
		supplier: m.supplier,
		set_warehouse: m.set_warehouse || undefined,
		transaction_date: m.transaction_date,
		schedule_date: m.schedule_date,
		remarks: m.remarks || undefined,
		items: lines,
		auto_submit: autoSubmit.value,
		currency: m.currency || undefined,
		price_list: m.price_list || undefined,
		deal: tenderOn.value && m.deal ? m.deal : undefined,
	};
}

// Document engine hook
const {
	model: form,
	loading,
	saving: actionRunning,
	loadError,
	error: actionError,
	isCreate,
	editable,
	docstatus,
	status,
	load,
	save,
	submit,
	cancel,
	amend,
	remove,
	can,
} = useDocumentForm({
	doctype: "Purchase Order",
	detailApi: "stabler.api.purchasing.purchase_order_detail",
	createApi: "stabler.api.purchasing.create_purchase_order",
	updateApi: "stabler.api.purchasing.update_purchase_order",
	submitApi: "stabler.api.purchasing.submit_purchase_order",
	cancelApi: "stabler.api.purchasing.cancel_purchase_order",
	amendApi: "stabler.api.purchasing.amend_purchase_order",
	deleteApi: "stabler.api.purchasing.delete_purchase_order",
	blankModel: blankForm,
	toPayload,
	fromDetail,
	backPath: "/purchasing/orders",
});

const docName = computed(() => (route.params.name ? String(route.params.name) : null));

async function loadDoc() {
	if (!docName.value) return;
	await load(docName.value);
	if (form.value) {
		showDiscounts.value = form.value.items.some(
			(l) => Number(l.discount_percentage) > 0 || Number(l.discount_amount) > 0
		);
	}
}

// Lookups and callbacks
function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 10,
	});
}

async function pickSupplier(s) {
	form.value.supplier = s.name;
	form.value.supplier_name = s.supplier_name;
	if (s.default_currency) form.value.currency = s.default_currency;
}

function clearSupplier() {
	form.value.supplier = "";
	form.value.supplier_name = "";
	form.value.currency = "";
	form.value.price_list = "";
}

const searchItems = itemSearcher("purchase");

// Line Item Editor pick handler
async function handlePickItem({ line, item, field }) {
	if (field === "item") {
		line.item_code = item.item_code || item.name;
		line.item_name = item.item_name;
		line.uom = item.stock_uom || "";
		line.stock_uom = item.stock_uom || "";
		line.rate = Number(item.standard_rate || 0);
	}
}

watch(docName, loadDoc);
// Catches the module flag arriving AFTER mount — see `applyQueryDeal` above.
watch(tenderOn, applyQueryDeal);

onMounted(async () => {
	await Promise.all([loadWarehouses(), loadPriceLists(), loadCurrencies()]);
	// Branch on the route param (present on a hard load), not the composable's
	// isCreate (null-based, true until load() runs) — else direct URL/refresh of an
	// edit route renders a blank "New".
	if (docName.value) {
		await loadDoc();
	} else {
		form.value = blankForm();
		createFormReady = true;
		await applyQueryDeal();
	}
});

// Operations
async function submitCreate({ autoSubmitMode = 1 } = {}) {
	actionError.value = "";
	if (!form.value.supplier) {
		actionError.value = t("Pick a supplier.");
		return;
	}

	autoSubmit.value = autoSubmitMode;
	await save();
}

async function submitDoc() {
	await submit();
}

async function createInvoice() {
	if (!docName.value) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		const res = await call("stabler.api.purchasing.create_purchase_invoice_from_po", {
			name: docName.value,
		});
		if (res?.name) {
			router.push({ path: "/purchasing/invoices", query: { open: res.name } });
		}
	} catch (err) {
		actionError.value = err?.message || t("Failed to create invoice.");
	} finally {
		actionRunning.value = false;
	}
}

// Receive items (Purchase Order -> Purchase Receipt)
const receiveOpen = ref(false);
const receiving = ref(false);
const receiveError = ref("");
const receiveRows = ref([]);

const canReceive = computed(
	() =>
		!isCreate.value &&
		form.value &&
		form.value.docstatus === 1 &&
		Number(form.value.per_received || 0) < 100
);

function openReceive() {
	if (!form.value?.items) return;
	receiveRows.value = form.value.items
		.map((it) => ({
			po_detail: it.name,
			item_code: it.item_code,
			item_name: it.item_name,
			uom: it.uom,
			pending: Math.max(Number(it.qty || 0) - Number(it.received_qty || 0), 0),
		}))
		.filter((r) => r.pending > 0)
		.map((r) => ({ ...r, qty: r.pending }));
	receiveError.value = "";
	receiveOpen.value = true;
}

function closeReceive() {
	if (receiving.value) return;
	receiveOpen.value = false;
}

async function submitReceive() {
	receiveError.value = "";
	const lines = receiveRows.value
		.filter((r) => Number(r.qty) > 0)
		.map((r) => ({ po_detail: r.po_detail, qty: Math.min(Number(r.qty), r.pending) }));
	if (!lines.length) {
		receiveError.value = t("Enter a quantity for at least one row.");
		return;
	}
	receiving.value = true;
	try {
		const res = await call("stabler.api.purchasing.create_purchase_receipt_from_po", {
			name: docName.value,
			items: lines,
		});
		receiveOpen.value = false;
		if (res?.name) {
			router.push({ path: "/purchasing/receipts", query: { open: res.name } });
		}
	} catch (err) {
		receiveError.value = err?.message || t("Failed to create receipt.");
	} finally {
		receiving.value = false;
	}
}

const canCreateInvoice = computed(
	() =>
		!isCreate.value &&
		form.value &&
		form.value.docstatus === 1 &&
		!(form.value.purchase_invoices && form.value.purchase_invoices.length)
);

// Inline validations for editor state check
const isFormValid = ref(true);

function handleValidityChange(valid) {
	isFormValid.value = valid;
}

// Calculations are handled by LineItemsEditor.vue
</script>

<template>
	<FormPage
		:title="isCreate ? t('New Purchase Order') : t('Purchase Order')"
		:doc-name="docName"
		:status="status"
		doctype="Purchase Order"
		:docstatus="docstatus"
		:loading="loading"
		:error="loadError"
		:action-error="actionError"
		back-path="/purchasing/orders"
	>
		<!-- Linked Invoices/Receipts Alert -->
		<div v-if="form?.purchase_invoices && form.purchase_invoices.length" class="alert alert-info">
			<div class="fw-semibold mb-1"><i class="ti ti-link me-1"></i>{{ t("Linked invoices") }}</div>
			<div class="small">
				<router-link
					v-for="pi in form.purchase_invoices"
					:key="pi.name"
					:to="{ path: '/purchasing/invoices', query: { open: pi.name } }"
					class="badge bg-blue-lt me-1 font-monospace text-decoration-none"
				>{{ pi.name }}</router-link>
			</div>
		</div>

		<div v-if="form?.purchase_receipts && form.purchase_receipts.length" class="alert alert-info">
			<div class="fw-semibold mb-1"><i class="ti ti-package-import me-1"></i>{{ t("Linked receipts") }}</div>
			<div class="small">
				<router-link
					v-for="pr in form.purchase_receipts"
					:key="pr.name"
					:to="{ path: '/purchasing/receipts', query: { open: pr.name } }"
					class="badge bg-green-lt me-1 font-monospace text-decoration-none"
				>{{ pr.name }}</router-link>
			</div>
		</div>

		<!-- Header fields -->
		<div class="row g-3 mb-3">
			<div class="col-md-6">
				<label class="form-label" :class="{ required: editable }">{{ t("Supplier") }}</label>
				<Typeahead
					v-slot="{ item }"
					v-if="editable"
					v-model="form.supplier"
					:search="searchSuppliers"
					:display="form.supplier_name"
					:placeholder="t('Search supplier name…')"
					:no-results-text="t('No suppliers match that name')"
					open-on-focus
					@pick="pickSupplier"
					@clear="clearSupplier"
				>
					<div class="d-flex align-items-center gap-2">
						<span class="avatar avatar-xs bg-orange-lt">{{ (item.supplier_name || item.name).charAt(0).toUpperCase() }}</span>
						<div>
							<div class="fw-semibold">{{ item.supplier_name }}</div>
							<div class="small text-secondary">{{ item.name }} · {{ item.supplier_group || "—" }}</div>
						</div>
					</div>
				</Typeahead>
				<div v-else class="form-control-plaintext fw-semibold py-1">
					{{ form.supplier_name }}
					<span class="text-secondary fw-normal font-monospace small">· {{ form.supplier }}</span>
				</div>
			</div>
			<div class="col-md-6">
				<label class="form-label">{{ t("Warehouse") }} <span class="text-secondary small">({{ t("optional") }})</span></label>
				<Select
					v-if="editable"
					v-model="form.set_warehouse"
					:options="warehouses"
					value-key="name"
					:disabled="warehousesLoading"
					:placeholder="warehousesLoading ? t('Loading warehouses…') : t('Pick a warehouse')"
				>
					<template #option="{ option }">{{ option.warehouse_name }} ({{ option.name }})</template>
					<template #selected="{ option }">{{ option.warehouse_name }} ({{ option.name }})</template>
				</Select>
				<div v-else class="form-control-plaintext font-monospace py-1">{{ form.set_warehouse || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Order date") }}</label>
				<DateInput v-if="editable" v-model="form.transaction_date" />
				<div v-else class="form-control-plaintext py-1">{{ formatDateTime(form.transaction_date) || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Schedule date") }}</label>
				<DateInput v-if="editable" v-model="form.schedule_date" />
				<div v-else class="form-control-plaintext py-1">{{ formatDate(form.schedule_date) || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Price list") }}</label>
				<Select
					v-if="editable"
					v-model="form.price_list"
					:options="priceLists"
					value-key="name"
					:placeholder="t('— auto from supplier —')"
				>
					<template #option="{ option }">{{ option.name }} ({{ option.currency }})</template>
					<template #selected="{ option }">{{ option.name }} ({{ option.currency }})</template>
				</Select>
				<div v-else class="form-control-plaintext py-1">{{ form.price_list || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Currency") }}</label>
				<div class="form-control-plaintext font-monospace fw-semibold py-1">
					{{ form.currency || currency }}
					<span v-if="currencySymbol" class="text-secondary fw-normal">({{ currencySymbol }})</span>
				</div>
			</div>
		</div>

		<!-- Tender (Deal) picker — only where the tender module is on, and only at
		     create time; the backend has no path to change the link afterwards. -->
		<div v-if="isCreate && tenderOn" class="row g-3 mb-3">
			<div class="col-md-6">
				<label class="form-label">{{ t("Tender (Deal)") }} <span class="text-secondary small">({{ t("optional") }})</span></label>
				<Typeahead
					:model-value="form.deal"
					:display="dealLabel"
					:search="searchDeals"
					:placeholder="t('Search a tender deal…')"
					@pick="pickDeal"
					@clear="clearDeal"
				>
					<template #option="{ item }">{{ item.label }}</template>
				</Typeahead>
			</div>
		</div>

		<!-- Read-only post-submit datagrid (view mode) -->
		<div v-if="!isCreate && form" class="datagrid mb-3">
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Net total") }}</div>
				<div class="datagrid-content font-monospace">{{ formatMoney(form.net_total, form.currency, user.language) }}</div>
			</div>
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Grand total") }}</div>
				<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(form.grand_total, form.currency, user.language) }}</div>
			</div>
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Received") }}</div>
				<div class="datagrid-content font-monospace">{{ Number(form.per_received || 0).toFixed(0) }}%</div>
			</div>
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Billed") }}</div>
				<div class="datagrid-content font-monospace">{{ Number(form.per_billed || 0).toFixed(0) }}%</div>
			</div>
		</div>

		<!-- Items -->
		<div class="d-flex align-items-center mb-2">
			<h6 class="text-uppercase text-secondary small mb-0">{{ t("Items") }}</h6>
			<div class="form-check form-switch ms-auto mb-0">
				<input class="form-check-input" type="checkbox" id="poShowDisc" v-model="showDiscounts" />
				<label class="form-check-label small text-secondary" for="poShowDisc">{{ t("Show discounts") }}</label>
			</div>
		</div>

		<LineItemsEditor
			v-if="form"
			:items="form.items"
			:editable="editable"
			:currency="form.currency || currency"
			:currency-symbol="currencySymbol"
			:search-items="searchItems"
			:blank-line="blankLine"
			@pick-item="handlePickItem"
			@validity-change="handleValidityChange"
		>
			<template #header-extra>
				<th v-if="!editable" class="text-end" style="width: 120px;">{{ t("Received") }}</th>
				<th v-if="!editable" class="text-end" style="width: 120px;">{{ t("List rate") }}</th>
				<th v-if="showDiscounts" style="width: 80px;">%</th>
				<th v-if="showDiscounts" style="width: 130px;">{{ t("Disc") }}</th>
			</template>

			<template #row-extra="{ line }">
				<td v-if="!editable" class="align-top text-end font-monospace py-2">
					<span v-if="Number(line.received_qty || 0) > 0" class="badge bg-blue-lt">{{ Number(line.received_qty).toFixed(2) }}</span>
					<span v-else class="text-secondary">—</span>
				</td>
				<td v-if="!editable" class="align-top text-end font-monospace text-secondary small py-2">
					{{ line.price_list_rate > 0 ? formatMoney(line.price_list_rate, form.currency, user.language) : "—" }}
				</td>
				<td v-if="showDiscounts" class="align-top">
					<input
						v-if="editable"
						v-model.number="line.discount_percentage"
						type="number"
						step="any"
						min="0"
						max="100"
						inputmode="decimal"
						class="form-control font-monospace text-end"
						placeholder="0"
					/>
					<div v-else class="text-end font-monospace small py-2">{{ line.discount_percentage > 0 ? line.discount_percentage + "%" : "—" }}</div>
				</td>
				<td v-if="showDiscounts" class="align-top">
					<MoneyInput
						v-if="editable"
						v-model="line.discount_amount"
					/>
					<div v-else class="text-end font-monospace small py-2">
						{{ line.discount_amount > 0 ? formatMoney(line.discount_amount, form.currency, user.language) : "—" }}
					</div>
				</td>
			</template>

			<template #footer-extra="{ totalsByUom: tUoms, grandTotal }">
				<tr>
					<td colspan="2" class="align-middle">
						<span class="badge bg-secondary-lt">{{ form.items.length }} {{ form.items.length === 1 ? t('item') : t('items') }}</span>
						<span v-for="[uom, qty] in tUoms" :key="uom" class="badge bg-blue-lt ms-1 font-monospace">{{ qty }} {{ uom }}</span>
					</td>
					<td colspan="3"></td>
					<td v-if="!editable" colspan="2"></td>
					<td v-if="showDiscounts" colspan="2"></td>
					<td class="text-end font-monospace fw-bold py-2">{{ formatMoney(grandTotal, form.currency || currency, user.language) }}</td>
				</tr>
			</template>
		</LineItemsEditor>

		<div class="mt-3">
			<label class="form-label">{{ t("Terms / remarks") }}</label>
			<textarea v-if="editable" v-model="form.remarks" class="form-control" rows="2"></textarea>
			<div v-else class="form-control-plaintext py-1">{{ form.remarks || "—" }}</div>
		</div>

		<RelatedDocuments v-if="!isCreate && form" doctype="Purchase Order" :name="docName" />

		<!-- Actions -->
		<template #actions>
			<template v-if="isCreate">
				<button type="button" class="btn btn-link link-secondary" :disabled="actionRunning" @click="router.push('/purchasing/orders')">{{ t("Cancel") }}</button>
				<button type="button" class="btn btn-outline-primary ms-auto" :disabled="actionRunning || !isFormValid" @click="submitCreate({ autoSubmitMode: 0 })">
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Save as draft") }}
				</button>
				<button type="button" class="btn btn-primary" :disabled="actionRunning || !isFormValid" @click="submitCreate({ autoSubmitMode: 1 })">
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Submit") }}
				</button>
			</template>
			<template v-else>
				<button
					v-if="can.save"
					type="button"
					class="btn btn-outline-primary"
					:disabled="actionRunning || !isFormValid"
					@click="save"
				>
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-device-floppy me-1"></i>{{ t("Save changes") }}
				</button>
				<button
					v-if="can.submit"
					type="button"
					class="btn btn-primary"
					:disabled="actionRunning"
					@click="submitDoc"
				>
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-check me-1"></i>{{ t("Submit") }}
				</button>
				<button
					v-if="canReceive"
					type="button"
					class="btn btn-outline-secondary"
					:disabled="actionRunning"
					@click="openReceive"
				>
					<i class="ti ti-package-import me-1"></i>{{ t("Receive") }}
				</button>
				<button
					v-if="canCreateInvoice"
					type="button"
					class="btn btn-success"
					:disabled="actionRunning"
					@click="createInvoice"
				>
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-file-invoice me-1"></i>{{ t("Create Invoice") }}
				</button>
				<button
					v-if="can.cancel"
					type="button"
					class="btn btn-outline-danger ms-auto"
					:disabled="actionRunning"
					@click="cancel"
				>
					<i class="ti ti-ban me-1"></i>{{ t("Cancel") }}
				</button>
				<button
					v-if="can.amend"
					type="button"
					class="btn btn-outline-secondary"
					:disabled="actionRunning"
					@click="amend"
				>
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-copy me-1"></i>{{ t("Amend") }}
				</button>
				<button
					v-if="can.delete"
					type="button"
					class="btn btn-outline-danger"
					:class="{ 'ms-auto': !can.cancel }"
					:disabled="actionRunning"
					@click="remove"
				>
					<i class="ti ti-trash me-1"></i>{{ t("Delete") }}
				</button>
			</template>
		</template>
	</FormPage>

	<!-- Receive / Goods Receipt Modal -->
	<div v-if="receiveOpen" class="modal-backdrop fade show" @click="closeReceive"></div>
	<div v-if="receiveOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeReceive">
		<div class="modal-dialog modal-lg modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Receive goods") }} — <span class="font-monospace">{{ form?.name }}</span></h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeReceive" :disabled="receiving"></button>
				</div>
				<div class="modal-body">
					<div v-if="receiveError" class="alert alert-danger">{{ receiveError }}</div>
					<p class="text-secondary small mb-2">
						{{ t("Adjust quantities for a partial receipt. Rows left at zero are skipped.") }}
					</p>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th>{{ t("Item") }}</th>
									<th class="text-end">{{ t("Pending") }}</th>
									<th>{{ t("UOM") }}</th>
									<th class="text-end" style="width: 140px">{{ t("Receive now") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="r in receiveRows" :key="r.po_detail">
									<td>
										<div class="fw-semibold">{{ r.item_name || r.item_code }}</div>
										<div class="small text-secondary font-monospace">{{ r.item_code }}</div>
									</td>
									<td class="text-end font-monospace">{{ r.pending }}</td>
									<td>{{ r.uom || "—" }}</td>
									<td>
										<input
											v-model.number="r.qty"
											type="number"
											step="any"
											min="0"
											:max="r.pending"
											inputmode="decimal"
											class="form-control form-control-sm font-monospace text-end"
											:disabled="receiving"
										/>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="receiving" @click="closeReceive">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-success" :disabled="receiving" @click="submitReceive">
						<span v-if="receiving" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-package-import me-1"></i>{{ t("Create receipt") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
