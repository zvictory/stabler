<script setup>
/**
 * SalesInvoiceForm — full-page view of a single Sales Invoice.
 *
 * Route:
 *   /sales/invoices/:name → fetch sales_invoice_detail, render read-only with
 *                           status-gated actions (Submit / Receive payment /
 *                           Issue credit note / Print / Yuk xati / Cancel /
 *                           Amend / Delete).
 *
 * Replaces the detailOpen offcanvas in SalesInvoices.vue. There is NO create
 * mode: a Sales Invoice is always spawned from a submitted Sales Order via the
 * SO page's "Create Invoice" action — so this page is view + actions only.
 *
 * Linked-doc navigation (return_against, credit notes) pushes a new route
 * instead of swapping drawer content; a watch on route.params.name reloads.
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import PaymentModal from "../../components/PaymentModal.vue";
import RelatedDocuments from "../../components/RelatedDocuments.vue";
import FormPage from "../../components/form/FormPage.vue";

const session = useSession();
const { user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();

const docName = computed(() => String(route.params.name));

const loading = ref(false);
const loadError = ref("");
const detail = ref(null);

async function loadDoc() {
	if (!docName.value) return;
	loading.value = true;
	loadError.value = "";
	detail.value = null;
	try {
		detail.value = await call("stabler.api.sales.sales_invoice_detail", { name: docName.value });
	} catch (err) {
		loadError.value = err?.message || t("Failed to load invoice.");
	} finally {
		loading.value = false;
	}
}

function goToInvoice(name) {
	if (name) router.push("/sales/invoices/" + name);
}

// ──────────────── Status-gated actions ────────────────
const actionRunning = ref(false);
const actionError = ref("");
const PAYABLE_STATUSES = new Set(["Unpaid", "Overdue", "Partly Paid"]);
const canPay = computed(() => {
	if (!detail.value || detail.value.is_return) return false;
	if (detail.value.docstatus === 0) return Number(detail.value.grand_total || 0) > 0;
	return detail.value.docstatus === 1 && PAYABLE_STATUSES.has(detail.value.status);
});
const canSubmit = computed(() => !!detail.value && detail.value.docstatus === 0);
const canCancel = computed(() => !!detail.value && detail.value.docstatus === 1);
const canReturn = computed(
	() =>
		!!detail.value &&
		detail.value.docstatus === 1 &&
		!detail.value.is_return &&
		detail.value.status !== "Return"
);
const canAmend = computed(() => !!detail.value && detail.value.docstatus === 2);
const canDelete = computed(() => !!detail.value && detail.value.docstatus === 0);

async function submitDoc() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.sales.submit_sales_invoice", { name: detail.value.name });
		await loadDoc();
	} catch (err) {
		actionError.value = err?.message || t("Submit failed.");
	} finally {
		actionRunning.value = false;
	}
}

async function cancelDoc() {
	if (!detail.value?.name) return;
	if (!window.confirm(t("Cancel invoice {name}? This is reversible only by amendment.", { name: detail.value.name }))) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.sales.cancel_sales_invoice", { name: detail.value.name });
		await loadDoc();
	} catch (err) {
		actionError.value = err?.message || t("Cancel failed.");
	} finally {
		actionRunning.value = false;
	}
}

async function amendDoc() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		const res = await call("stabler.api.sales.amend_sales_invoice", { name: detail.value.name });
		if (res?.name) router.push("/sales/invoices/" + res.name);
	} catch (err) {
		actionError.value = err?.message || t("Amend failed.");
	} finally {
		actionRunning.value = false;
	}
}

async function deleteDoc() {
	if (!detail.value?.name) return;
	if (!window.confirm(t("Delete invoice {name}?", { name: detail.value.name }) + " " + t("This cannot be undone."))) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.sales.delete_sales_invoice", { name: detail.value.name });
		router.push("/sales/invoices");
	} catch (err) {
		actionError.value = err?.message || t("Delete failed.");
	} finally {
		actionRunning.value = false;
	}
}

// Payment
const paymentOpen = ref(false);
function openPayment() {
	actionError.value = "";
	paymentOpen.value = true;
}
async function onPaid() {
	paymentOpen.value = false;
	await loadDoc();
}

// Return / credit note modal
const returnOpen = ref(false);
const returnLines = ref([]);
const returnSubmitting = ref(false);
const returnError = ref("");

function openReturn() {
	returnError.value = "";
	returnLines.value = (detail.value?.items || []).map((it) => ({
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
		const res = await call("stabler.api.sales.create_sales_return", {
			sales_invoice: detail.value.name,
			posting_date: new Date().toISOString().slice(0, 10),
			item_returns,
			submit: 1,
		});
		returnOpen.value = false;
		if (res?.name) router.push("/sales/invoices/" + res.name);
		else await loadDoc();
	} catch (err) {
		returnError.value = err?.message || t("Failed to create return.");
	} finally {
		returnSubmitting.value = false;
	}
}

// Reload whenever the :name param changes (linked-invoice navigation reuses
// this component instance, so onMounted alone won't refetch).
watch(docName, loadDoc);
onMounted(loadDoc);
</script>

<template>
	<FormPage
		:title="t('Sales Invoice')"
		:doc-name="detail?.name || docName"
		:status="detail?.status || null"
		:docstatus="detail?.docstatus ?? null"
		:loading="loading"
		:error="loadError"
		back-path="/sales/invoices"
	>
		<template v-if="detail">
			<div class="d-flex align-items-center gap-2 mb-3 flex-wrap">
				<span class="text-secondary">{{ detail.customer_name }}</span>
				<span v-if="detail.is_return" class="badge bg-secondary-lt">{{ t("Return") }}</span>
			</div>

			<div v-if="actionError" class="alert alert-danger">{{ actionError }}</div>

			<div v-if="detail.return_against" class="alert alert-info py-2 small">
				<i class="ti ti-corner-down-left me-1"></i>
				{{ t("Credit note for") }}
				<button
					type="button"
					class="badge bg-blue-lt font-monospace border-0"
					style="cursor: pointer"
					@click="goToInvoice(detail.return_against)"
				>{{ detail.return_against }}</button>
			</div>

			<div v-if="detail.credit_notes?.length" class="alert alert-light py-2 small">
				<i class="ti ti-receipt-refund me-1"></i>
				{{ t("Credit notes:") }}
				<button
					v-for="cn in detail.credit_notes"
					:key="cn.name"
					type="button"
					class="badge bg-secondary-lt font-monospace ms-1 border-0"
					style="cursor: pointer"
					@click="goToInvoice(cn.name)"
				>{{ cn.name }}</button>
			</div>

			<!-- ── Header datagrid ── -->
			<div class="datagrid mb-3">
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Posting date") }}</div>
					<div class="datagrid-content">{{ formatDateTime(detail.posting_date) || "—" }}</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Due date") }}</div>
					<div class="datagrid-content">{{ formatDateTime(detail.due_date) || "—" }}</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Customer") }}</div>
					<div class="datagrid-content">
						{{ detail.customer_name }}
						<span class="text-secondary font-monospace small">· {{ detail.customer }}</span>
					</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Currency") }}</div>
					<div class="datagrid-content font-monospace">{{ detail.currency }}</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Net total") }}</div>
					<div class="datagrid-content font-monospace">{{ formatMoney(detail.net_total, detail.currency, user.language) }}</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Grand total") }}</div>
					<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(detail.grand_total, detail.currency, user.language) }}</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Outstanding") }}</div>
					<div class="datagrid-content font-monospace text-red">{{ formatMoney(detail.outstanding_amount, detail.currency, user.language) }}</div>
				</div>
			</div>

			<!-- ── Items ── -->
			<h6 class="text-uppercase text-secondary small mb-2">{{ t("Items") }}</h6>
			<div class="table-responsive">
				<table class="table table-sm table-vcenter">
					<thead>
						<tr>
							<th class="text-end text-secondary" style="width: 36px">#</th>
							<th style="min-width: 220px">{{ t("Item") }}</th>
							<th class="text-end">{{ t("Qty") }}</th>
							<th>{{ t("UOM") }}</th>
							<th class="text-end">{{ t("List rate") }}</th>
							<th class="text-end">{{ t("Disc %") }}</th>
							<th class="text-end">{{ t("Disc") }}</th>
							<th class="text-end">{{ t("Rate") }}</th>
							<th class="text-end">{{ t("Amount") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(it, i) in detail.items" :key="i">
							<td class="text-end text-secondary font-monospace small">{{ i + 1 }}</td>
							<td>
								<div class="fw-semibold">{{ it.item_name || it.item_code }}</div>
								<div class="small text-secondary font-monospace">{{ it.item_code }}</div>
							</td>
							<td class="text-end font-monospace">{{ it.qty }}</td>
							<td>{{ it.uom || "—" }}</td>
							<td class="text-end font-monospace text-secondary small">
								{{ it.price_list_rate > 0 ? formatMoney(it.price_list_rate, detail.currency, user.language) : "—" }}
							</td>
							<td class="text-end font-monospace small">
								{{ it.discount_percentage > 0 ? it.discount_percentage + "%" : "—" }}
							</td>
							<td class="text-end font-monospace small">
								{{ it.discount_amount > 0 ? formatMoney(it.discount_amount, detail.currency, user.language) : "—" }}
							</td>
							<td class="text-end font-monospace">{{ formatMoney(it.rate, detail.currency, user.language) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(it.amount, detail.currency, user.language) }}</td>
						</tr>
					</tbody>
				</table>
			</div>

			<div class="mt-3">
				<label class="form-label">{{ t("Terms / remarks") }}</label>
				<div class="form-control-plaintext py-1">{{ detail.remarks || "—" }}</div>
			</div>

			<RelatedDocuments doctype="Sales Invoice" :name="detail.name" />
		</template>

		<!-- ── Actions ── -->
		<template #actions>
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
				<i class="ti ti-cash me-1"></i>{{ t("Receive payment") }}
			</button>
			<button
				v-if="canReturn"
				type="button"
				class="btn btn-outline-warning"
				:disabled="actionRunning"
				@click="openReturn"
			>
				<i class="ti ti-receipt-refund me-1"></i>{{ t("Issue credit note") }}
			</button>
			<router-link
				v-if="detail"
				:to="'/sales/invoices/' + detail.name + '/print'"
				class="btn btn-outline-secondary"
			>
				<i class="ti ti-printer me-1"></i>{{ t("Print") }}
			</router-link>
			<router-link
				v-if="detail"
				:to="'/sales/invoices/' + detail.name + '/waybill'"
				class="btn btn-outline-secondary"
			>
				<i class="ti ti-truck me-1"></i>{{ t("Yuk xati") }}
			</router-link>
			<button
				v-if="canCancel"
				type="button"
				class="btn btn-outline-danger ms-auto"
				:disabled="actionRunning"
				@click="cancelDoc"
			>
				<i class="ti ti-ban me-1"></i>{{ t("Cancel") }}
			</button>
			<button
				v-if="canAmend"
				type="button"
				class="btn btn-outline-secondary"
				:disabled="actionRunning"
				@click="amendDoc"
			>
				<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
				<i v-else class="ti ti-copy me-1"></i>{{ t("Amend") }}
			</button>
			<button
				v-if="canDelete"
				type="button"
				class="btn btn-outline-danger"
				:class="{ 'ms-auto': !canCancel }"
				:disabled="actionRunning"
				@click="deleteDoc"
			>
				<i class="ti ti-trash me-1"></i>{{ t("Delete") }}
			</button>
		</template>
	</FormPage>

	<PaymentModal
		:open="paymentOpen"
		invoice-type="Sales Invoice"
		:invoice-name="detail?.name || ''"
		@close="paymentOpen = false"
		@paid="onPaid"
	/>

	<!-- Return / credit note modal -->
	<div v-if="returnOpen" class="modal-backdrop fade show" @click="closeReturn"></div>
	<div v-if="returnOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeReturn">
		<div class="modal-dialog modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Issue credit note") }}</h5>
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
						<i v-else class="ti ti-receipt-refund me-1"></i>{{ t("Create credit note") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
