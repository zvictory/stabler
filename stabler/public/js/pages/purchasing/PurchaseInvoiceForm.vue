<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { importsApi } from "../../api/imports.js";
import { t } from "../../composables/i18n.js";
import { itemSearcher } from "../../composables/items.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime, todayIso } from "../../composables/date.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import PaymentModal from "../../components/PaymentModal.vue";
import Typeahead from "../../components/Typeahead.vue";
import Select from "../../components/Select.vue";
import RelatedDocuments from "../../components/RelatedDocuments.vue";
import FormPage from "../../components/form/FormPage.vue";
import LineItemsEditor from "../../components/LineItemsEditor.vue";
import { useDocumentForm } from "../../composables/useDocumentForm.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
const route = useRoute();

const today = todayIso();

// Lookups/Refs
const warehouses = ref([]);
const warehousesLoading = ref(false);
const currencies = ref([]);
const priceLists = ref([]);
const taxTemplates = ref([]);
const showDiscounts = ref(false);
const rateHint = ref(null);

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const isForeign = computed(() => !!form.value.currency && form.value.currency !== currency.value);
const modalCurrency = computed(() => form.value.currency || currency.value);

const currencySymbol = computed(() => {
	const code = modalCurrency.value;
	return (currencies.value.find((c) => c.name === code) || {}).symbol || "";
});

const warehouseOptions = computed(() => [
	{ name: "", warehouse_name: warehousesLoading.value ? t("Loading warehouses…") : t("— pick a warehouse —") },
	...warehouses.value,
]);

const currencyOptions = computed(() => [
	{ name: "", _label: `${currency.value} (${t("company currency")})` },
	...currencies.value
		.filter((c) => c.name !== currency.value)
		.map((c) => ({ ...c, _label: c.symbol ? `${c.name} (${c.symbol})` : c.name })),
]);

const priceListOptions = computed(() => [
	{ name: "", _label: t("— auto from supplier —") },
	...priceLists.value.map((pl) => ({ ...pl, _label: `${pl.name} (${pl.currency})` })),
]);

const taxTemplateOptions = computed(() => [
	{ name: "", _label: t("— no tax —") },
	...taxTemplates.value.map((tt) => ({ ...tt, _label: tt.title || tt.name })),
]);

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

async function loadCurrencies() {
	try {
		currencies.value = await call("stabler.api.sales.list_currencies");
	} catch {
		currencies.value = [];
	}
}

async function loadPriceLists() {
	try {
		priceLists.value = await call("stabler.api.sales.list_price_lists", { buying_only: 1 });
	} catch {
		priceLists.value = [];
	}
}

async function loadTaxTemplates() {
	if (!activeCompany.value) return;
	try {
		taxTemplates.value = await call("stabler.api.purchasing.list_purchase_tax_templates", {
			company: activeCompany.value,
		});
	} catch {
		taxTemplates.value = [];
	}
}

async function fetchRateHint() {
	rateHint.value = null;
	if (!isForeign.value) return;
	try {
		const res = await call("stabler.api.purchasing.get_purchase_exchange_rate", {
			company: activeCompany.value,
			currency: form.value.currency,
			posting_date: form.value.posting_date || undefined,
			supplier: form.value.supplier || undefined,
		});
		if (res && Number(res.rate) > 0 && res.source) {
			rateHint.value = res;
			if (!Number(form.value.conversion_rate)) form.value.conversion_rate = Number(res.rate);
		}
	} catch {
		rateHint.value = null;
	}
}

const rateHintLabel = computed(() => {
	if (!rateHint.value) return "";
	const src =
		rateHint.value.source === "last_invoice" ? t("from last bill") : t("from exchange rate records");
	return `${t("Suggested")}: ${formatMoney(rateHint.value.rate, currency.value, user.value.language)} ${src}`;
});

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
		posting_date: today,
		due_date: "",
		bill_no: "",
		bill_date: "",
		remarks: "",
		update_stock: true,
		set_warehouse: "",
		currency: "",
		conversion_rate: 0,
		price_list: "",
		taxes_template: "",
		items: [blankLine()],
	};
}

function fromDetail(d) {
	// Detect phantom discounts: ERPNext stores price_list_rate in base currency for
	// foreign-currency PIs; (plr × conversion_rate ≈ rate) means no real discount was set.
	const cr = d.currency !== d.base_currency ? Number(d.conversion_rate || 0) : 0;
	return {
		supplier: d.supplier,
		supplier_name: d.supplier_name || d.supplier,
		posting_date: d.posting_date || today,
		due_date: d.due_date || "",
		bill_no: d.bill_no || "",
		bill_date: d.bill_date || "",
		remarks: d.remarks || "",
		update_stock: !!d.update_stock,
		set_warehouse: d.set_warehouse || "",
		currency: d.currency === d.base_currency ? "" : d.currency || "",
		conversion_rate: d.currency === d.base_currency ? 0 : Number(d.conversion_rate || 0),
		price_list: d.buying_price_list || "",
		taxes_template: d.taxes_and_charges || "",
		is_return: !!d.is_return,
		return_against: d.return_against || "",
		amended_from: d.amended_from || "",
		debit_notes: d.debit_notes || [],
		net_total: Number(d.net_total || 0),
		total_taxes_and_charges: Number(d.total_taxes_and_charges || 0),
		grand_total: Number(d.grand_total || 0),
		base_net_total: Number(d.base_net_total || 0),
		base_grand_total: Number(d.base_grand_total || 0),
		outstanding_amount: Number(d.outstanding_amount || 0),
		items: (d.items || []).map((it) => {
			const rate = Number(it.rate || 0);
			const plr = Number(it.price_list_rate || 0);
			const isArtifact = cr > 0 && plr > 0 && Math.abs(plr * cr - rate) < 1;
			return {
				item_code: it.item_code,
				item_name: it.item_name,
				custom_line_note: it.custom_line_note || "",
				uom: it.uom || "",
				qty: Number(it.qty || 0),
				dimension_mode: it.custom_dimension_mode || "",
				custom_length: it.custom_length ?? null,
				custom_width: it.custom_width ?? null,
				custom_height: it.custom_height ?? null,
				custom_pieces: it.custom_pieces ?? null,
				rate,
				price_list_rate: isArtifact ? 0 : plr,
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
		posting_date: m.posting_date,
		due_date: m.due_date || undefined,
		bill_no: m.bill_no || undefined,
		bill_date: m.bill_date || undefined,
		remarks: m.remarks || undefined,
		update_stock: m.update_stock ? 1 : 0,
		set_warehouse: m.update_stock ? m.set_warehouse : undefined,
		currency: m.currency || undefined,
		conversion_rate: isForeign.value ? Number(m.conversion_rate || 0) : undefined,
		price_list: m.price_list || undefined,
		taxes_template: m.taxes_template || undefined,
		items: lines,
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
	modified,
	load,
	save,
	submit,
	cancel,
	amend,
	remove,
	can,
} = useDocumentForm({
	doctype: "Purchase Invoice",
	detailApi: "stabler.api.purchasing.purchase_invoice_detail",
	createApi: "stabler.api.purchasing.create_purchase_invoice",
	updateApi: "stabler.api.purchasing.update_purchase_invoice",
	submitApi: "stabler.api.purchasing.submit_purchase_invoice",
	cancelApi: "stabler.api.purchasing.cancel_purchase_invoice",
	amendApi: "stabler.api.purchasing.amend_purchase_invoice",
	deleteApi: "stabler.api.purchasing.delete_purchase_invoice",
	blankModel: blankForm,
	toPayload,
	fromDetail,
	backPath: "/purchasing/invoices",
});

watch(
	() => [form.value.currency, form.value.posting_date],
	() => {
		if (editable.value) fetchRateHint();
	}
);

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

// Import attribution (W1) — hand-link this draft bill to a Commercial Invoice,
// Import Container or Import Truck. Attribution only: never touches cost lines,
// the landed cost voucher or any amount field. The server is the sole gate —
// this panel only reflects `bill_import_link_state`, it never guesses.
const linkState = ref(null);
const linkStateLoading = ref(false);
const linkActionRunning = ref(false);
const linkError = ref("");

const showLinkPanel = computed(
	() => !!linkState.value && (linkState.value.eligible || linkState.value.linked)
);

const linkedRefs = computed(() => {
	const refs = linkState.value?.refs || {};
	const out = [];
	if (refs.custom_commercial_invoice) out.push({ label: t("Commercial Invoice"), name: refs.custom_commercial_invoice });
	if (refs.custom_import_container) out.push({ label: t("Import Container"), name: refs.custom_import_container });
	if (refs.custom_import_truck) out.push({ label: t("Import Truck"), name: refs.custom_import_truck });
	return out;
});

async function fetchLinkState() {
	if (!docName.value) {
		linkState.value = null;
		return;
	}
	linkStateLoading.value = true;
	linkError.value = "";
	try {
		linkState.value = await importsApi.billImportLinkState(docName.value);
	} catch (err) {
		linkState.value = null;
		linkError.value = err?.message || t("Failed to load import attribution.");
	} finally {
		linkStateLoading.value = false;
	}
}

// `modified` bumps after every save/submit/cancel (the composable re-loads the
// doc on each), which is the only moment a supplier or docstatus change could
// have actually landed on the server — so it is the right refetch trigger,
// not a raw watch on the in-memory form fields.
watch([docName, modified], fetchLinkState);

const linkKind = ref("commercial_invoice");
const linkKindOptions = computed(() => [
	{ name: "commercial_invoice", _label: t("Commercial Invoice") },
	{ name: "import_container", _label: t("Import Container") },
	{ name: "import_truck", _label: t("Import Truck") },
]);
const linkTargetPlaceholder = computed(() => {
	if (linkKind.value === "import_container") return t("Search container…");
	if (linkKind.value === "import_truck") return t("Search truck…");
	return t("Search commercial invoice…");
});

const linkTargetName = ref("");
const linkTargetLabel = ref("");

function clearLinkTarget() {
	linkTargetName.value = "";
	linkTargetLabel.value = "";
}

watch(linkKind, clearLinkTarget);

function searchLinkTargets(q) {
	const params = { company: activeCompany.value, search: q, limit_page_length: 10 };
	if (linkKind.value === "import_container") {
		return importsApi.listImportContainers(params).then((r) => r.rows || []);
	}
	if (linkKind.value === "import_truck") {
		return importsApi.listImportTrucks(params).then((r) => r.rows || []);
	}
	return importsApi.listCommercialInvoices(params).then((r) => r.rows || []);
}

function pickLinkTarget(item) {
	linkTargetName.value = item.name;
	if (linkKind.value === "import_container") linkTargetLabel.value = item.container_number || item.name;
	else if (linkKind.value === "import_truck") linkTargetLabel.value = item.truck_number || item.name;
	else linkTargetLabel.value = item.ci_number || item.name;
}

async function linkTarget() {
	if (!linkTargetName.value) return;
	linkActionRunning.value = true;
	linkError.value = "";
	try {
		const payload = { purchase_invoice: docName.value };
		if (linkKind.value === "import_container") payload.import_container = linkTargetName.value;
		else if (linkKind.value === "import_truck") payload.import_truck = linkTargetName.value;
		else payload.commercial_invoice = linkTargetName.value;
		await importsApi.setBillImportRefs(payload);
		clearLinkTarget();
		await fetchLinkState();
	} catch (err) {
		linkError.value = err?.message || t("Failed to link.");
	} finally {
		linkActionRunning.value = false;
	}
}

async function unlinkTarget() {
	linkActionRunning.value = true;
	linkError.value = "";
	try {
		await importsApi.clearBillImportRefs(docName.value);
		await fetchLinkState();
	} catch (err) {
		linkError.value = err?.message || t("Failed to unlink.");
	} finally {
		linkActionRunning.value = false;
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
	if (s.default_currency && s.default_currency !== currency.value) {
		form.value.currency = s.default_currency;
	}
	fetchRateHint();
}

function clearSupplier() {
	form.value.supplier = "";
	form.value.supplier_name = "";
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

onMounted(async () => {
	await Promise.all([loadWarehouses(), loadCurrencies(), loadPriceLists(), loadTaxTemplates()]);
	// Branch on the route param (present synchronously on a hard load), NOT the
	// composable's isCreate — that is null-based and always true until load() runs,
	// so on a direct URL or refresh the edit form would wrongly render a blank "New".
	if (docName.value) {
		await loadDoc();
	} else {
		form.value = blankForm();
	}
});

// Payments
const paymentOpen = ref(false);
const PAYABLE_STATUSES = new Set(["Unpaid", "Overdue", "Partly Paid"]);
const canPay = computed(() => {
	return (
		!isCreate.value &&
		form.value &&
		form.value.docstatus === 1 &&
		PAYABLE_STATUSES.has(form.value.status)
	);
});

function openPayment() {
	actionError.value = "";
	paymentOpen.value = true;
}

async function onPaid() {
	paymentOpen.value = false;
	await loadDoc();
}

// Debit note (purchase return) modal
const returnOpen = ref(false);
const returnLines = ref([]);
const returnSubmitting = ref(false);
const returnError = ref("");

const canReturn = computed(
	() =>
		!!form.value &&
		form.value.docstatus === 1 &&
		!form.value.is_return &&
		form.value.status !== "Return"
);

function openReturn() {
	returnError.value = "";
	returnLines.value = (form.value?.items || []).map((it) => ({
		item_code: it.item_code,
		item_name: it.item_name || it.item_code,
		max_qty: Number(it.qty || 0),
		return_qty: Number(it.qty || 0),
	}));
	returnOpen.value = true;
}
function closeReturn() {
	if (returnSubmitting.value) return;
	returnOpen.value = false;
}
async function submitReturn() {
	returnError.value = "";
	returnSubmitting.value = true;
	try {
		const item_returns = returnLines.value
			.filter((r) => Number(r.return_qty) > 0)
			.map((r) => ({ item_code: r.item_code, qty: Number(r.return_qty) }));
		if (!item_returns.length) {
			returnError.value = t("Enter at least one return qty.");
			return;
		}
		const res = await call("stabler.api.purchasing.create_purchase_return", {
			purchase_invoice: form.value.name,
			posting_date: todayIso(),
			item_returns,
			submit: 1,
		});
		returnOpen.value = false;
		if (res?.name) router.push("/purchasing/invoices/" + res.name);
		else await loadDoc();
	} catch (err) {
		returnError.value = err?.message || t("Failed to create debit note.");
	} finally {
		returnSubmitting.value = false;
	}
}

function goToInvoice(name) {
	if (name) router.push("/purchasing/invoices/" + name);
}

// Calculations
const createTotal = computed(() => {
	if (!form.value) return 0;
	return form.value.items.reduce((s, r) => {
		const qty = Number(r.qty || 0);
		const rate = Number(r.rate || 0);
		const discPct = Number(r.discount_percentage || 0);
		const discAmt = Number(r.discount_amount || 0);
		let amt = qty * rate;
		if (discPct > 0) {
			amt = qty * Math.max(rate * (1 - discPct / 100), 0);
		} else if (discAmt > 0) {
			amt = qty * Math.max(rate - discAmt, 0);
		}
		return s + amt;
	}, 0);
});

const taxPreview = computed(() => {
	if (!form.value || !form.value.taxes_template) return 0;
	const tpl = taxTemplates.value.find((tt) => tt.name === form.value.taxes_template);
	if (!tpl) return 0;
	let total = 0;
	for (const row of tpl.taxes || []) {
		if (row.charge_type === "On Net Total") total += (createTotal.value * Number(row.rate || 0)) / 100;
		else if (row.charge_type === "Actual") total += Number(row.tax_amount || 0);
	}
	return total;
});

const grandPreview = computed(() => createTotal.value + taxPreview.value);
const baseGrandPreview = computed(() =>
	isForeign.value ? grandPreview.value * Number(form.value.conversion_rate || 0) : 0
);

// totalsByUom handled by LineItemsEditor.vue

// Inline validations for editor state check
const isFormValid = ref(true);

function handleValidityChange(valid) {
	isFormValid.value = valid;
}

async function submitCreate() {
	actionError.value = "";
	if (!form.value.supplier) {
		actionError.value = t("Pick a supplier.");
		return;
	}
	if (form.value.update_stock && !form.value.set_warehouse) {
		actionError.value = t("Pick a warehouse to receive stock into.");
		return;
	}
	if (isForeign.value && !(Number(form.value.conversion_rate) > 0)) {
		actionError.value = t("Exchange rate must be greater than zero.");
		return;
	}

	await save();
}

async function submitDoc() {
	await submit();
}
</script>

<template>
	<FormPage
		:title="isCreate ? t('New Purchase Invoice') : t('Purchase Invoice')"
		:doc-name="docName"
		:status="status"
		:docstatus="docstatus"
		:loading="loading"
		:error="loadError"
		:action-error="actionError"
		back-path="/purchasing/invoices"
	>
		<!-- Supplier subtitle + return badge -->
		<div v-if="!isCreate" class="d-flex align-items-center gap-2 mb-3 flex-wrap">
			<span class="text-secondary">{{ form.supplier_name }}</span>
			<span v-if="form.is_return" class="badge bg-secondary-lt">{{ t("Return") }}</span>
		</div>

		<!-- Return_against banner -->
		<div v-if="form.return_against" class="alert alert-info py-2 small">
			<i class="ti ti-corner-down-left me-1"></i>
			{{ t("Debit note for") }}
			<button
				type="button"
				class="badge bg-blue-lt font-monospace border-0"
				style="cursor: pointer"
				@click="goToInvoice(form.return_against)"
			>{{ form.return_against }}</button>
		</div>

		<!-- Linked debit notes banner -->
		<div v-if="form.debit_notes?.length" class="alert alert-light py-2 small">
			<i class="ti ti-receipt-refund me-1"></i>
			{{ t("Debit notes:") }}
			<button
				v-for="dn in form.debit_notes"
				:key="dn.name"
				type="button"
				class="badge bg-secondary-lt font-monospace ms-1 border-0"
				style="cursor: pointer"
				@click="goToInvoice(dn.name)"
			>{{ dn.name }}</button>
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
				<label class="form-label">{{ t("Warehouse") }}</label>
				<Select
					v-if="editable && form.update_stock"
					v-model="form.set_warehouse"
					:options="warehouseOptions"
					value-key="name"
					:disabled="warehousesLoading"
				>
					<template #option="{ option: w }">
						<span v-if="w.name">{{ w.warehouse_name }} ({{ w.name }})</span>
						<span v-else>{{ w.warehouse_name }}</span>
					</template>
					<template #selected="{ option: w }">
						<span v-if="w.name">{{ w.warehouse_name }} ({{ w.name }})</span>
						<span v-else>{{ w.warehouse_name }}</span>
					</template>
				</Select>
				<div v-else class="form-control-plaintext font-monospace py-1">{{ form.set_warehouse || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Posting date") }}</label>
				<DateInput v-if="editable" v-model="form.posting_date" />
				<div v-else class="form-control-plaintext py-1">{{ formatDateTime(form.posting_date) || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Due date") }}</label>
				<DateInput v-if="editable" v-model="form.due_date" />
				<div v-else class="form-control-plaintext py-1">{{ formatDateTime(form.due_date) || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Bill No.") }}</label>
				<input v-if="editable" v-model="form.bill_no" type="text" class="form-control" />
				<div v-else class="form-control-plaintext py-1">{{ form.bill_no || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Bill Date") }}</label>
				<DateInput v-if="editable" v-model="form.bill_date" />
				<div v-else class="form-control-plaintext py-1">{{ formatDate(form.bill_date) || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Currency") }}</label>
				<Select
					v-if="editable"
					v-model="form.currency"
					:options="currencyOptions"
					value-key="name"
					label-key="_label"
				/>
				<div v-else class="form-control-plaintext font-monospace py-1">{{ form.currency || currency }}</div>
			</div>
			<div class="col-md-3" v-if="isForeign">
				<label class="form-label">{{ t("Exchange rate") }}</label>
				<MoneyInput v-if="editable" v-model="form.conversion_rate" />
				<div v-else class="form-control-plaintext py-1">{{ form.conversion_rate }}</div>
				<div v-if="editable && rateHintLabel" class="form-hint text-secondary">{{ rateHintLabel }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Price list") }}</label>
				<Select
					v-if="editable"
					v-model="form.price_list"
					:options="priceListOptions"
					value-key="name"
					label-key="_label"
				/>
				<div v-else class="form-control-plaintext py-1">{{ form.price_list || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Tax template") }}</label>
				<Select
					v-if="editable"
					v-model="form.taxes_template"
					:options="taxTemplateOptions"
					value-key="name"
					label-key="_label"
				/>
				<div v-else class="form-control-plaintext py-1">{{ form.taxes_template || "—" }}</div>
			</div>
			<div class="col-md-3 align-self-end" v-if="editable">
				<div class="form-check form-switch mb-2">
					<input class="form-check-input" type="checkbox" id="piUpdateStock" v-model="form.update_stock" />
					<label class="form-check-label" for="piUpdateStock">{{ t("Update stock") }}</label>
				</div>
			</div>
		</div>

		<!-- Import attribution (W1) — attribution only, never a cost/valuation write -->
		<div v-if="showLinkPanel" class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Import attribution") }}</h3>
			</div>
			<div class="card-body">
				<div v-if="linkStateLoading" class="text-secondary small">
					<span class="spinner-border spinner-border-sm me-1"></span>{{ t("Loading…") }}
				</div>
				<template v-else>
					<div v-if="linkError" class="alert alert-danger py-2 small mb-2">{{ linkError }}</div>

					<div v-if="linkState?.linked" class="d-flex align-items-center gap-2 flex-wrap">
						<span class="text-secondary small">{{ t("Linked to") }}:</span>
						<span v-for="r in linkedRefs" :key="r.name" class="badge bg-blue-lt font-monospace">{{ r.label }}: {{ r.name }}</span>
						<button
							v-if="linkState.can_unlink"
							type="button"
							class="btn btn-outline-danger btn-sm ms-auto"
							:disabled="linkActionRunning"
							@click="unlinkTarget"
						>
							<span v-if="linkActionRunning" class="spinner-border spinner-border-sm me-1"></span>
							{{ t("Unlink") }}
						</button>
					</div>

					<div v-else-if="linkState?.eligible" class="row g-2 align-items-end">
						<div class="col-md-4">
							<label class="form-label small">{{ t("Attribute to") }}</label>
							<Select v-model="linkKind" :options="linkKindOptions" value-key="name" label-key="_label" />
						</div>
						<div class="col-md-6">
							<label class="form-label small">&nbsp;</label>
							<Typeahead
								v-model="linkTargetName"
								:search="searchLinkTargets"
								:display="linkTargetLabel"
								:placeholder="linkTargetPlaceholder"
								:no-results-text="t('No matches found')"
								size="sm"
								@pick="pickLinkTarget"
								@clear="clearLinkTarget"
							>
								<template #option="{ item }">
									<div v-if="linkKind === 'import_container'">
										<div class="fw-semibold">{{ item.container_number || item.name }}</div>
										<div class="small text-secondary">{{ item.ci_number || "—" }} · {{ item.name }}</div>
									</div>
									<div v-else-if="linkKind === 'import_truck'">
										<div class="fw-semibold">{{ item.truck_number || item.name }}</div>
										<div class="small text-secondary">{{ item.trucking_company || "—" }} · {{ item.name }}</div>
									</div>
									<div v-else>
										<div class="fw-semibold">{{ item.ci_number || item.name }}</div>
										<div class="small text-secondary">{{ item.supplier_name || item.supplier || "—" }} · {{ item.name }}</div>
									</div>
								</template>
							</Typeahead>
						</div>
						<div class="col-md-2">
							<button
								type="button"
								class="btn btn-primary w-100"
								:disabled="!linkTargetName || linkActionRunning"
								@click="linkTarget"
							>
								<span v-if="linkActionRunning" class="spinner-border spinner-border-sm me-1"></span>
								{{ t("Link") }}
							</button>
						</div>
					</div>
				</template>
			</div>
		</div>

		<!-- Preview Grid -->
		<div class="datagrid mb-3">
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Net total") }}</div>
				<div class="datagrid-content font-monospace">{{ formatMoney(isCreate ? createTotal : form.net_total, modalCurrency, user.language) }}</div>
			</div>
			<div class="datagrid-item" v-if="isCreate || form.taxes_and_charges">
				<div class="datagrid-title">{{ t("Tax amount") }}</div>
				<div class="datagrid-content font-monospace">{{ formatMoney(isCreate ? taxPreview : form.total_taxes_and_charges, modalCurrency, user.language) }}</div>
			</div>
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Grand total") }}</div>
				<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(isCreate ? grandPreview : form.grand_total, modalCurrency, user.language) }}</div>
			</div>
			<div class="datagrid-item" v-if="isForeign">
				<div class="datagrid-title">{{ t("Grand total") }} ({{ currency }})</div>
				<div class="datagrid-content font-monospace text-secondary">{{ formatMoney(isCreate ? baseGrandPreview : form.base_grand_total, currency, user.language) }}</div>
			</div>
			<div class="datagrid-item" v-if="!isCreate">
				<div class="datagrid-title">{{ t("Outstanding") }}</div>
				<div class="datagrid-content font-monospace text-red fw-bold">{{ formatMoney(form.outstanding_amount, modalCurrency, user.language) }}</div>
			</div>
		</div>

		<!-- Items -->
		<div class="d-flex align-items-center mb-2">
			<h6 class="text-uppercase text-secondary small mb-0">{{ t("Items") }}</h6>
			<div v-if="editable" class="form-check form-switch ms-auto mb-0">
				<input class="form-check-input" type="checkbox" id="piShowDisc" v-model="showDiscounts" />
				<label class="form-check-label small text-secondary" for="piShowDisc">{{ t("Show discounts") }}</label>
			</div>
		</div>

		<!-- Editable: full inline editor with discount toggles -->
		<LineItemsEditor
			v-if="form && editable"
			:items="form.items"
			:editable="editable"
			:currency="modalCurrency"
			:currency-symbol="currencySymbol"
			:search-items="searchItems"
			:blank-line="blankLine"
			@pick-item="handlePickItem"
			@validity-change="handleValidityChange"
		>
			<template #header-extra>
				<th v-if="!editable" class="text-end" style="width: 120px;">{{ t("List rate") }}</th>
				<th v-if="showDiscounts" style="width: 80px;">%</th>
				<th v-if="showDiscounts" style="width: 130px;">{{ t("Disc") }}</th>
			</template>

			<template #row-extra="{ line }">
				<td v-if="!editable" class="align-top text-end font-monospace text-secondary small py-2">
					{{ line.price_list_rate > 0 ? formatMoney(line.price_list_rate, modalCurrency, user.language) : "—" }}
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
						{{ line.discount_amount > 0 ? formatMoney(line.discount_amount, modalCurrency, user.language) : "—" }}
					</div>
				</td>
			</template>

			<template #footer-extra="{ totalsByUom: tUoms }">
				<tr>
					<td colspan="2" class="align-middle">
						<span class="badge bg-secondary-lt">{{ form.items.length }} {{ form.items.length === 1 ? t('item') : t('items') }}</span>
						<span v-for="[uom, qty] in tUoms" :key="uom" class="badge bg-blue-lt ms-1 font-monospace">{{ qty }} {{ uom }}</span>
					</td>
					<td colspan="3"></td>
					<td v-if="!editable" colspan="1"></td>
					<td v-if="showDiscounts" colspan="2"></td>
					<td class="text-end font-monospace fw-bold py-2">{{ formatMoney(createTotal, modalCurrency, user.language) }}</td>
				</tr>
			</template>
		</LineItemsEditor>

		<!-- Read-only: striped table mirroring the Sales Invoice view -->
		<div v-else-if="form" class="table-responsive">
			<table class="table table-sm table-vcenter">
				<thead>
					<tr>
						<th style="width: 36px;">#</th>
						<th>{{ t("Item") }}</th>
						<th class="text-end" style="width: 80px;">{{ t("Qty") }}</th>
						<th style="width: 70px;">{{ t("UOM") }}</th>
						<th class="text-end" style="width: 120px;">{{ t("List rate") }}</th>
						<th class="text-end" style="width: 70px;">{{ t("Disc %") }}</th>
						<th class="text-end" style="width: 120px;">{{ t("Disc") }}</th>
						<th class="text-end" style="width: 120px;">{{ t("Rate") }}</th>
						<th class="text-end" style="width: 120px;">{{ t("Amount") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="(it, idx) in form.items" :key="idx">
						<td class="text-secondary font-monospace small">{{ idx + 1 }}</td>
						<td>
							<div class="fw-semibold">{{ it.item_code }}</div>
							<div class="small text-secondary">{{ it.item_name }}</div>
						</td>
						<td class="text-end font-monospace">{{ it.qty }}</td>
						<td class="text-secondary small">{{ it.uom || "—" }}</td>
						<td class="text-end font-monospace text-secondary small">{{ it.price_list_rate > 0 ? formatMoney(it.price_list_rate, modalCurrency, user.language) : "—" }}</td>
						<td class="text-end font-monospace small">{{ it.discount_percentage > 0 ? it.discount_percentage + "%" : "—" }}</td>
						<td class="text-end font-monospace small">{{ it.discount_amount > 0 ? formatMoney(it.discount_amount, modalCurrency, user.language) : "—" }}</td>
						<td class="text-end font-monospace">{{ formatMoney(it.rate, modalCurrency, user.language) }}</td>
						<td class="text-end font-monospace fw-semibold">{{ formatMoney(Number(it.amount || 0), modalCurrency, user.language) }}</td>
					</tr>
				</tbody>
				<tfoot>
					<tr>
						<td colspan="2">
							<span class="badge bg-secondary-lt">{{ form.items.length }} {{ form.items.length === 1 ? t('item') : t('items') }}</span>
						</td>
						<td colspan="6"></td>
						<td class="text-end font-monospace fw-bold py-2">{{ formatMoney(form.net_total, modalCurrency, user.language) }}</td>
					</tr>
				</tfoot>
			</table>
		</div>

		<div class="mt-3">
			<label class="form-label">{{ t("Terms / remarks") }}</label>
			<textarea v-if="editable" v-model="form.remarks" class="form-control" rows="2"></textarea>
			<div v-else class="form-control-plaintext py-1">{{ form.remarks || "—" }}</div>
		</div>

		<RelatedDocuments v-if="!isCreate && form" doctype="Purchase Invoice" :name="docName" />

		<!-- Actions -->
		<template #actions>
			<template v-if="isCreate">
				<button type="button" class="btn btn-link link-secondary" :disabled="actionRunning" @click="router.push('/purchasing/invoices')">{{ t("Cancel") }}</button>
				<button type="button" class="btn btn-outline-primary ms-auto" :disabled="actionRunning || !isFormValid" @click="submitCreate">
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Save as draft") }}
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
					v-if="canPay"
					type="button"
					class="btn btn-success"
					:disabled="actionRunning"
					@click="openPayment"
				>
					<i class="ti ti-cash me-1"></i>{{ t("Make payment") }}
				</button>
				<button
					v-if="canReturn"
					type="button"
					class="btn btn-outline-warning"
					:disabled="actionRunning"
					@click="openReturn"
				>
					<i class="ti ti-receipt-refund me-1"></i>{{ t("Issue debit note") }}
				</button>
				<router-link
					v-if="form && !isCreate"
					:to="'/purchasing/invoices/' + form.name + '/print'"
					class="btn btn-outline-secondary"
				>
					<i class="ti ti-printer me-1"></i>{{ t("Print") }}
				</router-link>
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
					:class="{ 'ms-auto': !can.cancel && !can.amend }"
					:disabled="actionRunning"
					@click="remove"
				>
					<i class="ti ti-trash me-1"></i>{{ t("Delete") }}
				</button>
			</template>
		</template>
	</FormPage>

	<PaymentModal
		:open="paymentOpen"
		invoice-type="Purchase Invoice"
		:invoice-name="form?.name || ''"
		:modified="form?.modified || ''"
		@close="paymentOpen = false"
		@paid="onPaid"
	/>

	<!-- Debit note modal -->
	<div v-if="returnOpen" class="modal-backdrop fade show" @click="closeReturn"></div>
	<div v-if="returnOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeReturn">
		<div class="modal-dialog modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Issue debit note") }}</h5>
					<button type="button" class="btn-close" @click="closeReturn" :disabled="returnSubmitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="returnError" class="alert alert-danger">{{ returnError }}</div>
					<p class="small text-secondary">{{ t("Enter the quantity to return for each line. Leave 0 to exclude a line.") }}</p>
					<table class="table table-sm table-no-stripe">
						<thead>
							<tr>
								<th>{{ t("Item") }}</th>
								<th class="text-end">{{ t("Original qty") }}</th>
								<th class="text-end" style="width: 110px">{{ t("Return qty") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(r, i) in returnLines" :key="i">
								<td>
									<div class="fw-semibold small">{{ r.item_name }}</div>
									<div class="small text-secondary font-monospace">{{ r.item_code }}</div>
								</td>
								<td class="text-end font-monospace">{{ r.max_qty }}</td>
								<td>
									<input
										v-model.number="r.return_qty"
										type="number"
										step="any"
										inputmode="decimal"
										:min="0"
										:max="r.max_qty"
										class="form-control form-control-sm font-monospace text-end"
										:disabled="returnSubmitting"
									/>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" @click="closeReturn" :disabled="returnSubmitting">
						{{ t("Cancel") }}
					</button>
					<button type="button" class="btn btn-warning ms-auto" @click="submitReturn" :disabled="returnSubmitting">
						<span v-if="returnSubmitting" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-receipt-refund me-1"></i>{{ t("Create debit note") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
