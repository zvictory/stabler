<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import PaymentModal from "../../components/PaymentModal.vue";
import EmptyState from "../../components/EmptyState.vue";
import Typeahead from "../../components/Typeahead.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();

const today = new Date().toISOString().slice(0, 10);
const monthAgo = new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10);
const fromDate = ref(monthAgo);
const toDate = ref(today);
const status = ref("");
const limit = ref(100);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const STATUSES = ["", "Paid", "Unpaid", "Overdue", "Partly Paid", "Return", "Debit Note Issued", "Draft"];

const statusOptions = computed(() => STATUSES.map((s) => ({ value: s, label: s || t("All") })));

const statusBadge = (s) => {
	const m = {
		Paid: "bg-green-lt",
		Unpaid: "bg-yellow-lt",
		Overdue: "bg-red-lt",
		Return: "bg-secondary-lt",
		"Debit Note Issued": "bg-purple-lt",
		"Partly Paid": "bg-blue-lt",
		Draft: "bg-secondary-lt",
	};
	return m[s] || "bg-secondary-lt";
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.purchasing.list_purchase_invoices", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			status: status.value || undefined,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load bills.");
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.purchasing.purchase_invoice_detail", { name });
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

// Group totals by transaction currency — UZS and USD must never share a sum.
const totalsByCurrency = computed(() => {
	const m = new Map();
	for (const r of rows.value) {
		const ccy = r.currency || currency.value;
		const bucket = m.get(ccy) || { currency: ccy, count: 0, grand: 0, outstanding: 0 };
		bucket.count += 1;
		bucket.grand += Number(r.grand_total || 0);
		bucket.outstanding += Number(r.outstanding_amount || 0);
		m.set(ccy, bucket);
	}
	return Array.from(m.values());
});
const totalCount = computed(() => rows.value.length);

// ──────────────── Create / edit modal ────────────────
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const editingName = ref("");

function blankLine() {
	return {
		item_code: "",
		item_name: "",
		uom: "",
		qty: 1,
		rate: 0,
		discount_percentage: 0,
		discount_amount: 0,
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
const form = ref(blankForm());

const warehouses = ref([]);
const warehousesLoading = ref(false);
const currencies = ref([]);
const priceLists = ref([]);
const taxTemplates = ref([]);

const isForeign = computed(() => !!form.value.currency && form.value.currency !== currency.value);

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

// Exchange-rate suggestion: ERPNext records first, then the supplier's last bill.
// rate === 0 from the API means "nothing found" — the user must type one.
const rateHint = ref(null);
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
watch(
	() => [form.value.currency, form.value.posting_date],
	() => {
		if (createOpen.value) fetchRateHint();
	}
);

const rateHintLabel = computed(() => {
	if (!rateHint.value) return "";
	const src =
		rateHint.value.source === "last_invoice" ? t("from last bill") : t("from exchange rate records");
	return `${t("Suggested")}: ${formatMoney(rateHint.value.rate, currency.value, user.value.language)} ${src}`;
});

const showDiscounts = ref(false);

function lineAmount(line) {
	const qty = Number(line.qty || 0);
	const rate = Number(line.rate || 0);
	const discPct = Number(line.discount_percentage || 0);
	const discAmt = Number(line.discount_amount || 0);
	if (discPct > 0) return qty * Math.max(rate * (1 - discPct / 100), 0);
	if (discAmt > 0) return qty * Math.max(rate - discAmt, 0);
	return qty * rate;
}

const createTotal = computed(() => form.value.items.reduce((s, r) => s + lineAmount(r), 0));

// Preview of the selected tax template: handles "On Net Total" and "Actual"
// rows; other charge types are computed server-side on save.
const taxPreview = computed(() => {
	if (!form.value.taxes_template) return 0;
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

const modalCurrency = computed(() => form.value.currency || currency.value);

function openCreate() {
	form.value = blankForm();
	editingName.value = "";
	rateHint.value = null;
	submitError.value = "";
	createOpen.value = true;
	loadWarehouses();
	loadCurrencies();
	loadPriceLists();
	loadTaxTemplates();
}
function openEdit() {
	const d = detail.value;
	if (!d || d.docstatus !== 0) return;
	form.value = {
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
		items: (d.items || []).map((it) => ({
			item_code: it.item_code,
			item_name: it.item_name,
			uom: it.uom || "",
			qty: Number(it.qty || 0),
			rate: Number(it.rate || 0),
			discount_percentage: Number(it.discount_percentage || 0),
			discount_amount: Number(it.discount_amount || 0),
		})),
	};
	if (!form.value.items.length) form.value.items = [blankLine()];
	showDiscounts.value = form.value.items.some(
		(r) => Number(r.discount_percentage) > 0 || Number(r.discount_amount) > 0
	);
	editingName.value = d.name;
	rateHint.value = null;
	submitError.value = "";
	closeDetail();
	createOpen.value = true;
	loadWarehouses();
	loadCurrencies();
	loadPriceLists();
	loadTaxTemplates();
}
function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
	editingName.value = "";
}

function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 10,
	});
}
function pickSupplier(s) {
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

function searchItems(q) {
	return call("stabler.api.inventory.list_items", { search: q, limit: 10 });
}
function pickItem(line, item) {
	line.item_code = item.item_code || item.name;
	line.item_name = item.item_name;
	line.uom = item.stock_uom || "";
	line.rate = Number(item.standard_rate || 0);
}
function clearItem(line) {
	line.item_code = "";
	line.item_name = "";
	line.uom = "";
	line.rate = 0;
	line.discount_percentage = 0;
	line.discount_amount = 0;
}
function addLine() {
	form.value.items.push(blankLine());
}
function removeLine(idx) {
	if (form.value.items.length === 1) {
		form.value.items[0] = blankLine();
		return;
	}
	form.value.items.splice(idx, 1);
}

// ──────────────── Submit / payment actions ────────────────
const actionRunning = ref(false);
const actionError = ref("");
const paymentOpen = ref(false);
const PAYABLE_STATUSES = new Set(["Unpaid", "Overdue", "Partly Paid"]);
const canPay = computed(
	() => !!detail.value && detail.value.docstatus === 1 && PAYABLE_STATUSES.has(detail.value.status)
);
const canSubmit = computed(() => !!detail.value && detail.value.docstatus === 0);
const canCancel = computed(() => !!detail.value && detail.value.docstatus === 1);
const canEdit = computed(() => !!detail.value && detail.value.docstatus === 0);
const canDelete = computed(() => !!detail.value && detail.value.docstatus === 0);

async function deleteDoc() {
	if (!detail.value?.name) return;
	if (!window.confirm(t("Delete draft bill {name}? This cannot be undone.").replace("{name}", detail.value.name))) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.purchasing.delete_purchase_invoice", { name: detail.value.name });
		closeDetail();
		await load();
	} catch (err) {
		actionError.value = err?.message || t("Failed to delete bill.");
	} finally {
		actionRunning.value = false;
	}
}

async function submitDoc() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.purchasing.submit_purchase_invoice", { name: detail.value.name });
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || t("Submit failed.");
	} finally {
		actionRunning.value = false;
	}
}

async function cancelDoc() {
	if (!detail.value?.name) return;
	if (!window.confirm(t("Cancel bill {name}? This is reversible only by amendment.").replace("{name}", detail.value.name))) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.purchasing.cancel_purchase_invoice", { name: detail.value.name });
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || t("Cancel failed.");
	} finally {
		actionRunning.value = false;
	}
}

function openPayment() {
	actionError.value = "";
	paymentOpen.value = true;
}
async function onPaid() {
	paymentOpen.value = false;
	if (detail.value?.name) await Promise.all([openDetail(detail.value.name), load()]);
}

async function submitCreate() {
	submitError.value = "";
	if (!form.value.supplier) {
		submitError.value = t("Pick a supplier.");
		return;
	}
	const lines = form.value.items
		.filter((r) => r.item_code)
		.map((r) => ({
			item_code: r.item_code,
			qty: r.qty,
			rate: r.rate,
			uom: r.uom,
			discount_percentage: r.discount_percentage || 0,
			discount_amount: r.discount_amount || 0,
		}));
	if (!lines.length) {
		submitError.value = t("Add at least one item line.");
		return;
	}
	for (const [i, r] of lines.entries()) {
		if (!Number(r.qty) || Number(r.qty) <= 0) {
			submitError.value = t("Row {n}: qty must be greater than zero.").replace("{n}", String(i + 1));
			return;
		}
	}
	if (form.value.update_stock && !form.value.set_warehouse) {
		submitError.value = t("Pick a warehouse to receive stock into.");
		return;
	}
	if (isForeign.value && !(Number(form.value.conversion_rate) > 0)) {
		submitError.value = t("Exchange rate must be greater than zero.");
		return;
	}
	const payload = {
		supplier: form.value.supplier,
		posting_date: form.value.posting_date,
		due_date: form.value.due_date || undefined,
		bill_no: form.value.bill_no || undefined,
		bill_date: form.value.bill_date || undefined,
		remarks: form.value.remarks || undefined,
		update_stock: form.value.update_stock ? 1 : 0,
		set_warehouse: form.value.update_stock ? form.value.set_warehouse : undefined,
		currency: form.value.currency || undefined,
		conversion_rate: isForeign.value ? form.value.conversion_rate : undefined,
		price_list: form.value.price_list || undefined,
		taxes_template: form.value.taxes_template || undefined,
		items: lines,
	};
	submitting.value = true;
	try {
		let saved;
		if (editingName.value) {
			saved = await call("stabler.api.purchasing.update_purchase_invoice", {
				name: editingName.value,
				...payload,
			});
		} else {
			saved = await call("stabler.api.purchasing.create_purchase_invoice", {
				company: activeCompany.value,
				...payload,
			});
		}
		createOpen.value = false;
		editingName.value = "";
		await load();
		if (saved?.name) await openDetail(saved.name);
	} catch (err) {
		submitError.value =
			err?.message || (editingName.value ? t("Failed to update bill.") : t("Failed to create bill."));
	} finally {
		submitting.value = false;
	}
}

onMounted(async () => {
	await load();
	const openName = route.query?.open;
	if (openName) openDetail(String(openName));
});
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">{{ t("Purchase Invoices") }}</div>
			<div class="ms-auto d-flex gap-2 align-items-end flex-wrap">
				<div>
					<label class="form-label small mb-1">{{ t("From") }}</label>
					<DateInput v-model="fromDate" size="sm" />
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("To") }}</label>
					<DateInput v-model="toDate" size="sm" />
				</div>
				<div style="min-width: 150px">
					<label class="form-label small mb-1">{{ t("Status") }}</label>
					<Select v-model="status" size="sm" :options="statusOptions" />
				</div>
				<button type="button" class="btn btn-sm btn-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
				</button>
				<button type="button" class="btn btn-sm btn-success" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New bill") }}
				</button>
			</div>
		</div>

		<div v-if="rows.length" class="card-body py-2 border-bottom bg-light">
			<div class="d-flex gap-4 small">
				<div>{{ t("Count:") }} <strong>{{ totalCount }}</strong></div>
				<div v-for="b in totalsByCurrency" :key="b.currency" class="d-flex gap-3 align-items-center">
					<span class="badge bg-secondary-lt text-secondary">{{ b.currency }}</span>
					<span>{{ t("Total:") }} <strong class="font-monospace">{{ formatMoney(b.grand, b.currency, user.language) }}</strong></span>
					<span>{{ t("Payable:") }} <strong class="text-red font-monospace">{{ formatMoney(b.outstanding, b.currency, user.language) }}</strong></span>
				</div>
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
			icon="ti-receipt"
			accentIcon="ti-plus"
			tone="warning"
			:title='t("No bills in this range")'
			:subtitle='t("Widen the date range, relax the status filter, or log a new bill.")'
		>
			<template #actions>
				<button type="button" class="btn btn-primary" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New bill") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("#") }}</th>
						<th>{{ t("Date") }}</th>
						<th>{{ t("Due") }}</th>
						<th>{{ t("Supplier") }}</th>
						<th>{{ t("Bill #") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
						<th class="text-end">{{ t("Payable") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ formatDateTime(r.posting_date) }}</td>
						<td>{{ formatDateTime(r.due_date) }}</td>
						<td>
							<div class="fw-semibold">{{ r.supplier_name || r.supplier }}</div>
						</td>
						<td class="font-monospace small">{{ r.bill_no || "—" }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency || currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.outstanding_amount, r.currency || currency, user.language) }}</td>
						<td><span class="badge" :class="statusBadge(r.status)">{{ r.status }}</span></td>
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
			<h5 class="offcanvas-title">{{ t("Purchase Invoice") }}</h5>
			<button type="button" class="btn-close" @click="closeDetail" aria-label="Close"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<div v-else-if="detail">
				<div class="d-flex align-items-center mb-3 gap-3">
					<div>
						<h3 class="m-0 font-monospace">{{ detail.name }}</h3>
						<div class="small text-secondary">{{ detail.supplier_name }}</div>
					</div>
					<span class="badge ms-auto" :class="statusBadge(detail.status)">{{ detail.status }}</span>
				</div>

				<div v-if="actionError" class="alert alert-danger">{{ actionError }}</div>

				<div class="btn-list mb-3">
					<button
						v-if="canSubmit"
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
						<i class="ti ti-cash me-1"></i>{{ t("Pay supplier") }}
					</button>
					<button
						v-if="canEdit"
						type="button"
						class="btn btn-outline-primary"
						:disabled="actionRunning"
						@click="openEdit"
					>
						<i class="ti ti-pencil me-1"></i>{{ t("Edit") }}
					</button>
					<button
						v-if="canDelete"
						type="button"
						class="btn btn-outline-danger ms-auto"
						:disabled="actionRunning"
						@click="deleteDoc"
					>
						<i class="ti ti-trash me-1"></i>{{ t("Delete") }}
					</button>
					<button
						v-if="canCancel"
						type="button"
						class="btn btn-outline-danger ms-auto"
						:disabled="actionRunning"
						@click="cancelDoc"
					>
						<i class="ti ti-ban me-1"></i>{{ t("Cancel") }}
					</button>
				</div>

				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Posting date") }}</div>
						<div class="datagrid-content">{{ formatDateTime(detail.posting_date) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Due date") }}</div>
						<div class="datagrid-content">{{ formatDateTime(detail.due_date) || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Bill #") }}</div>
						<div class="datagrid-content font-monospace">{{ detail.bill_no || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Bill date") }}</div>
						<div class="datagrid-content">{{ formatDateTime(detail.bill_date) || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Currency") }}</div>
						<div class="datagrid-content">{{ detail.currency }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Net total") }}</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.net_total, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Taxes") }}</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.total_taxes_and_charges, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Grand total") }}</div>
						<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(detail.grand_total, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Payable") }}</div>
						<div class="datagrid-content font-monospace text-red">{{ formatMoney(detail.outstanding_amount, detail.currency, user.language) }}</div>
					</div>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Items") }}</h6>
				<div class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>{{ t("Item") }}</th>
								<th class="text-end">{{ t("Qty") }}</th>
								<th>{{ t("UOM") }}</th>
								<th class="text-end">{{ t("Rate") }}</th>
								<th class="text-end">{{ t("Amount") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(it, i) in detail.items" :key="i">
								<td>
									<div class="fw-semibold">{{ it.item_name || it.item_code }}</div>
									<div class="small text-secondary font-monospace">{{ it.item_code }}</div>
									<div v-if="it.purchase_order" class="small mt-1">
										<span class="badge bg-blue-lt font-monospace">{{ it.purchase_order }}</span>
									</div>
								</td>
								<td class="text-end font-monospace">{{ it.qty }}</td>
								<td>{{ it.uom || "—" }}</td>
								<td class="text-end font-monospace">{{ formatMoney(it.rate, detail.currency, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(it.amount, detail.currency, user.language) }}</td>
							</tr>
						</tbody>
					</table>
				</div>

				<div v-if="detail.taxes?.length" class="mt-3">
					<h6 class="text-uppercase text-secondary small mb-2">{{ t("Taxes") }}</h6>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th>{{ t("Description") }}</th>
									<th class="text-end">{{ t("Rate") }}</th>
									<th class="text-end">{{ t("Amount") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(t, i) in detail.taxes" :key="i">
									<td>{{ t.description }}</td>
									<td class="text-end font-monospace">{{ t.rate }}%</td>
									<td class="text-end font-monospace">{{ formatMoney(t.tax_amount, detail.currency, user.language) }}</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>
	</div>

	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeCreate">
		<div class="modal-dialog modal-xl modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ editingName ? t("Edit purchase bill") : t("New purchase bill") }}</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreate" :disabled="submitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

					<div class="row g-3 mb-3">
						<div class="col-md-6">
							<label class="form-label required">{{ t("Supplier") }}</label>
							<Typeahead
								v-model="form.supplier"
								:search="searchSuppliers"
								:display="form.supplier_name"
								:placeholder='t("Search supplier name…")'
								:no-results-text='t("No suppliers match that name")'
								:disabled="submitting"
								@pick="pickSupplier"
								@clear="clearSupplier"
							>
								<template #option="{ item }">
									<div class="d-flex align-items-center gap-2">
										<span class="avatar avatar-xs bg-orange-lt">{{ (item.supplier_name || item.name).charAt(0).toUpperCase() }}</span>
										<div>
											<div class="fw-semibold">{{ item.supplier_name }}</div>
											<div class="small text-secondary">{{ item.name }} · {{ item.supplier_group || "—" }}</div>
										</div>
									</div>
								</template>
							</Typeahead>
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Posting date") }}</label>
							<DateInput v-model="form.posting_date" />
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Due date") }}</label>
							<DateInput v-model="form.due_date" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Supplier bill #") }}</label>
							<input v-model="form.bill_no" type="text" class="form-control font-monospace" :placeholder='t("Bill / invoice number printed on supplier document")' />
						</div>
						<div class="col-md-2">
							<label class="form-label">{{ t("Bill date") }}</label>
							<DateInput v-model="form.bill_date" />
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Currency") }}</label>
							<Select
								v-model="form.currency"
								:options="currencyOptions"
								value-key="name"
								label-key="_label"
								:disabled="submitting"
							/>
						</div>
						<div v-if="isForeign" class="col-md-3">
							<label class="form-label required">{{ t("Exchange rate") }}</label>
							<MoneyInput v-model="form.conversion_rate" :disabled="submitting" />
							<div v-if="rateHintLabel" class="form-hint small">{{ rateHintLabel }}</div>
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Price list") }}</label>
							<Select
								v-model="form.price_list"
								:options="priceListOptions"
								value-key="name"
								label-key="_label"
								:disabled="submitting"
							/>
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Tax template") }}</label>
							<Select
								v-model="form.taxes_template"
								:options="taxTemplateOptions"
								value-key="name"
								label-key="_label"
								:disabled="submitting"
							/>
						</div>
						<div v-if="form.update_stock" class="col-md-4">
							<label class="form-label required">{{ t("Warehouse") }}</label>
							<Select
								v-model="form.set_warehouse"
								:options="warehouseOptions"
								value-key="name"
								:disabled="submitting || warehousesLoading"
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
						</div>
						<div class="col-12">
							<label class="form-check form-switch mb-0">
								<input
									v-model="form.update_stock"
									class="form-check-input"
									type="checkbox"
									:disabled="submitting"
								/>
								<span class="form-check-label">{{ t("Receive goods into stock") }}</span>
							</label>
						</div>
					</div>

					<div class="d-flex align-items-center mb-2">
						<h6 class="text-uppercase text-secondary small mb-0">{{ t("Items") }}</h6>
						<div class="form-check form-switch ms-auto mb-0">
							<input class="form-check-input" type="checkbox" id="piShowDisc" v-model="showDiscounts" />
							<label class="form-check-label small text-secondary" for="piShowDisc">{{ t("Show discounts") }}</label>
						</div>
					</div>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th style="min-width: 240px">{{ t("Item") }}</th>
									<th style="width: 110px">{{ t("Qty") }}</th>
									<th style="width: 90px">{{ t("UOM") }}</th>
									<th style="width: 160px">{{ t("Rate") }}</th>
									<th v-if="showDiscounts" style="width: 70px">%</th>
									<th v-if="showDiscounts" style="width: 130px">{{ t("Disc") }}</th>
									<th class="text-end" style="width: 140px">{{ t("Amount") }}</th>
									<th style="width: 40px"></th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(line, idx) in form.items" :key="idx">
									<td>
										<Typeahead
											:model-value="line.item_code"
											:search="searchItems"
											:display="line.item_name || line.item_code"
											:placeholder='t("Search item…")'
											:no-results-text='t("No items match")'
											size="sm"
											menu-min-width="280px"
											:disabled="submitting"
											@pick="(it) => pickItem(line, it)"
											@clear="clearItem(line)"
										>
											<template #option="{ item: it }">
												<div class="fw-semibold small">{{ it.item_name }}</div>
												<div class="small text-secondary font-monospace">{{ it.item_code }} · {{ it.stock_uom || "—" }}</div>
											</template>
										</Typeahead>
									</td>
									<td>
										<input
											v-model.number="line.qty"
											type="number"
											step="any"
											inputmode="decimal"
											class="form-control form-control-sm font-monospace text-end"
										/>
									</td>
									<td><input v-model="line.uom" type="text" class="form-control form-control-sm" /></td>
									<td><MoneyInput v-model="line.rate" /></td>
									<td v-if="showDiscounts">
										<input
											v-model.number="line.discount_percentage"
											type="number"
											step="any"
											min="0"
											max="100"
											inputmode="decimal"
											class="form-control form-control-sm font-monospace text-end"
											placeholder="0"
											:disabled="submitting"
										/>
									</td>
									<td v-if="showDiscounts"><MoneyInput v-model="line.discount_amount" size="sm" :disabled="submitting" /></td>
									<td class="text-end font-monospace">
										{{ formatMoney(lineAmount(line), modalCurrency, user.language) }}
									</td>
									<td>
										<button type="button" class="btn btn-sm btn-icon btn-ghost-danger" @click="removeLine(idx)" :disabled="submitting">
											<i class="ti ti-trash"></i>
										</button>
									</td>
								</tr>
							</tbody>
							<tfoot>
								<tr>
									<td :colspan="showDiscounts ? 8 : 6">
										<button type="button" class="btn btn-sm btn-ghost-primary" @click="addLine">
											<i class="ti ti-plus me-1"></i>{{ t("Add row") }}
										</button>
									</td>
								</tr>
								<tr>
									<td :colspan="showDiscounts ? 6 : 4" class="text-end text-uppercase small text-secondary">{{ t("Net total") }}</td>
									<td class="text-end font-monospace fw-bold">{{ formatMoney(createTotal, modalCurrency, user.language) }}</td>
									<td></td>
								</tr>
								<tr v-if="form.taxes_template">
									<td :colspan="showDiscounts ? 6 : 4" class="text-end text-uppercase small text-secondary">{{ t("Taxes") }}</td>
									<td class="text-end font-monospace">{{ formatMoney(taxPreview, modalCurrency, user.language) }}</td>
									<td></td>
								</tr>
								<tr v-if="form.taxes_template || isForeign">
									<td :colspan="showDiscounts ? 6 : 4" class="text-end text-uppercase small text-secondary">{{ t("Grand total") }}</td>
									<td class="text-end font-monospace fw-bold">{{ formatMoney(grandPreview, modalCurrency, user.language) }}</td>
									<td></td>
								</tr>
								<tr v-if="isForeign && Number(form.conversion_rate) > 0">
									<td :colspan="showDiscounts ? 6 : 4" class="text-end small text-secondary">≈ {{ currency }}</td>
									<td class="text-end font-monospace text-secondary">{{ formatMoney(baseGrandPreview, currency, user.language) }}</td>
									<td></td>
								</tr>
							</tfoot>
						</table>
					</div>

					<div class="mt-3">
						<label class="form-label">{{ t("Remarks") }}</label>
						<textarea v-model="form.remarks" class="form-control" rows="2"></textarea>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="closeCreate">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary ms-auto" :disabled="submitting" @click="submitCreate">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ editingName ? t("Save changes") : t("Save as draft") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<PaymentModal
		:open="paymentOpen"
		invoice-type="Purchase Invoice"
		:invoice-name="detail?.name || ''"
		@close="paymentOpen = false"
		@paid="onPaid"
	/>
</template>
