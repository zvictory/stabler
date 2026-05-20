<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import MoneyInput from "../../components/MoneyInput.vue";
import PaymentModal from "../../components/PaymentModal.vue";
import EmptyState from "../../components/EmptyState.vue";
import Typeahead from "../../components/Typeahead.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

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
		error.value = err?.message || "Failed to load bills.";
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
		detail.value = { error: err?.message || "Failed to load." };
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

const totals = computed(() => ({
	count: rows.value.length,
	grand: rows.value.reduce((s, r) => s + Number(r.grand_total || 0), 0),
	outstanding: rows.value.reduce((s, r) => s + Number(r.outstanding_amount || 0), 0),
}));

// ──────────────── Create modal ────────────────
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");

function blankLine() {
	return { item_code: "", item_name: "", uom: "", qty: 1, rate: 0 };
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
		items: [blankLine()],
	};
}
const form = ref(blankForm());

const createTotal = computed(() =>
	form.value.items.reduce((s, r) => s + Number(r.qty || 0) * Number(r.rate || 0), 0)
);

function openCreate() {
	form.value = blankForm();
	submitError.value = "";
	createOpen.value = true;
}
function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
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

async function submitDoc() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.purchasing.submit_purchase_invoice", { name: detail.value.name });
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || "Submit failed.";
	} finally {
		actionRunning.value = false;
	}
}

async function cancelDoc() {
	if (!detail.value?.name) return;
	if (!window.confirm(`Cancel bill ${detail.value.name}? This is reversible only by amendment.`)) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.purchasing.cancel_purchase_invoice", { name: detail.value.name });
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || "Cancel failed.";
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
		submitError.value = "Pick a supplier.";
		return;
	}
	const lines = form.value.items
		.filter((r) => r.item_code)
		.map((r) => ({ item_code: r.item_code, qty: r.qty, rate: r.rate, uom: r.uom }));
	if (!lines.length) {
		submitError.value = "Add at least one item line.";
		return;
	}
	for (const [i, r] of lines.entries()) {
		if (!Number(r.qty) || Number(r.qty) <= 0) {
			submitError.value = `Row ${i + 1}: qty must be greater than zero.`;
			return;
		}
	}
	submitting.value = true;
	try {
		const created = await call("stabler.api.purchasing.create_purchase_invoice", {
			company: activeCompany.value,
			supplier: form.value.supplier,
			posting_date: form.value.posting_date,
			due_date: form.value.due_date || undefined,
			bill_no: form.value.bill_no || undefined,
			bill_date: form.value.bill_date || undefined,
			remarks: form.value.remarks || undefined,
			items: lines,
		});
		createOpen.value = false;
		await load();
		if (created?.name) await openDetail(created.name);
	} catch (err) {
		submitError.value = err?.message || "Failed to create bill.";
	} finally {
		submitting.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">Purchase Invoices</div>
			<div class="ms-auto d-flex gap-2 align-items-end flex-wrap">
				<div>
					<label class="form-label small mb-1">From</label>
					<input v-model="fromDate" type="date" class="form-control form-control-sm" />
				</div>
				<div>
					<label class="form-label small mb-1">To</label>
					<input v-model="toDate" type="date" class="form-control form-control-sm" />
				</div>
				<div style="min-width: 150px">
					<label class="form-label small mb-1">Status</label>
					<select v-model="status" class="form-select form-select-sm">
						<option v-for="s in STATUSES" :key="s" :value="s">{{ s || "All" }}</option>
					</select>
				</div>
				<button type="button" class="btn btn-sm btn-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>Apply
				</button>
				<button type="button" class="btn btn-sm btn-success" @click="openCreate">
					<i class="ti ti-plus me-1"></i>New bill
				</button>
			</div>
		</div>

		<div v-if="rows.length" class="card-body py-2 border-bottom bg-light">
			<div class="d-flex gap-4 small">
				<div>Count: <strong>{{ totals.count }}</strong></div>
				<div>Total: <strong class="font-monospace">{{ formatMoney(totals.grand, currency, user.language) }}</strong></div>
				<div>Payable: <strong class="text-red font-monospace">{{ formatMoney(totals.outstanding, currency, user.language) }}</strong></div>
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
			title="No bills in this range"
			subtitle="Widen the date range, relax the status filter, or log a new bill."
		>
			<template #actions>
				<button type="button" class="btn btn-primary" @click="openCreate">
					<i class="ti ti-plus me-1"></i>New bill
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>#</th>
						<th>Date</th>
						<th>Due</th>
						<th>Supplier</th>
						<th>Bill #</th>
						<th class="text-end">Total</th>
						<th class="text-end">Payable</th>
						<th>Status</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ r.posting_date }}</td>
						<td>{{ r.due_date }}</td>
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
			<h5 class="offcanvas-title">Purchase Invoice</h5>
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
						<i v-else class="ti ti-check me-1"></i>Submit
					</button>
					<button
						v-if="canPay"
						type="button"
						class="btn btn-success"
						:disabled="actionRunning"
						@click="openPayment"
					>
						<i class="ti ti-cash me-1"></i>Pay supplier
					</button>
					<button
						v-if="canCancel"
						type="button"
						class="btn btn-outline-danger ms-auto"
						:disabled="actionRunning"
						@click="cancelDoc"
					>
						<i class="ti ti-ban me-1"></i>Cancel
					</button>
				</div>

				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">Posting date</div>
						<div class="datagrid-content">{{ detail.posting_date }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Due date</div>
						<div class="datagrid-content">{{ detail.due_date || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Bill #</div>
						<div class="datagrid-content font-monospace">{{ detail.bill_no || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Bill date</div>
						<div class="datagrid-content">{{ detail.bill_date || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Currency</div>
						<div class="datagrid-content">{{ detail.currency }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Net total</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.net_total, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Taxes</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.total_taxes_and_charges, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Grand total</div>
						<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(detail.grand_total, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Payable</div>
						<div class="datagrid-content font-monospace text-red">{{ formatMoney(detail.outstanding_amount, detail.currency, user.language) }}</div>
					</div>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2">Items</h6>
				<div class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>Item</th>
								<th class="text-end">Qty</th>
								<th>UOM</th>
								<th class="text-end">Rate</th>
								<th class="text-end">Amount</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(it, i) in detail.items" :key="i">
								<td>
									<div class="fw-semibold">{{ it.item_name || it.item_code }}</div>
									<div class="small text-secondary font-monospace">{{ it.item_code }}</div>
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
					<h6 class="text-uppercase text-secondary small mb-2">Taxes</h6>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th>Description</th>
									<th class="text-end">Rate</th>
									<th class="text-end">Amount</th>
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
					<h5 class="modal-title">New purchase bill</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreate" :disabled="submitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

					<div class="row g-3 mb-3">
						<div class="col-md-6">
							<label class="form-label required">Supplier</label>
							<Typeahead
								v-model="form.supplier"
								:search="searchSuppliers"
								:display="form.supplier_name"
								placeholder="Search supplier name…"
								no-results-text="No suppliers match that name"
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
							<label class="form-label">Posting date</label>
							<input v-model="form.posting_date" type="date" class="form-control" />
						</div>
						<div class="col-md-3">
							<label class="form-label">Due date</label>
							<input v-model="form.due_date" type="date" class="form-control" />
						</div>
						<div class="col-md-6">
							<label class="form-label">Supplier bill #</label>
							<input v-model="form.bill_no" type="text" class="form-control font-monospace" placeholder="Bill / invoice number printed on supplier document" />
						</div>
						<div class="col-md-3">
							<label class="form-label">Bill date</label>
							<input v-model="form.bill_date" type="date" class="form-control" />
						</div>
					</div>

					<h6 class="text-uppercase text-secondary small mb-2">Items</h6>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th style="min-width: 240px">Item</th>
									<th style="width: 110px">Qty</th>
									<th style="width: 90px">UOM</th>
									<th style="width: 160px">Rate</th>
									<th class="text-end" style="width: 140px">Amount</th>
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
											placeholder="Search item…"
											no-results-text="No items match"
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
									<td class="text-end font-monospace">
										{{ formatMoney(Number(line.qty || 0) * Number(line.rate || 0), currency, user.language) }}
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
									<td colspan="6">
										<button type="button" class="btn btn-sm btn-ghost-primary" @click="addLine">
											<i class="ti ti-plus me-1"></i>Add row
										</button>
									</td>
								</tr>
								<tr>
									<td colspan="4" class="text-end text-uppercase small text-secondary">Net total</td>
									<td class="text-end font-monospace fw-bold">{{ formatMoney(createTotal, currency, user.language) }}</td>
									<td></td>
								</tr>
							</tfoot>
						</table>
					</div>

					<div class="mt-3">
						<label class="form-label">Remarks</label>
						<textarea v-model="form.remarks" class="form-control" rows="2"></textarea>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="closeCreate">Cancel</button>
					<button type="button" class="btn btn-primary ms-auto" :disabled="submitting" @click="submitCreate">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						Save as draft
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
