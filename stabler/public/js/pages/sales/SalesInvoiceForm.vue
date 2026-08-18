<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime, todayIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import PaymentModal from "../../components/PaymentModal.vue";
import EdoSubmitModal from "../../components/EdoSubmitModal.vue";
import RelatedDocuments from "../../components/RelatedDocuments.vue";
import FormPage from "../../components/form/FormPage.vue";
import { useDocumentForm } from "../../composables/useDocumentForm.js";
import { useTelemetry } from "../../composables/useTelemetry.js";

const session = useSession();
const { trackOnce, FUNNEL } = useTelemetry();
const { user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();

const docName = computed(() => String(route.params.name));

// Document engine hook
const {
	model: form,
	loading,
	saving: actionRunning,
	loadError,
	error: actionError,
	load,
	submit,
	cancel,
	amend,
	remove,
	can,
} = useDocumentForm({
	doctype: "Sales Invoice",
	detailApi: "stabler.api.sales.sales_invoice_detail",
	submitApi: "stabler.api.sales.submit_sales_invoice",
	cancelApi: "stabler.api.sales.cancel_sales_invoice",
	amendApi: "stabler.api.sales.amend_sales_invoice",
	deleteApi: "stabler.api.sales.delete_sales_invoice",
	blankModel: () => ({}),
	fromDetail: (d) => d,
	backPath: "/sales/invoices",
});

async function loadDoc() {
	if (!docName.value) return;
	await load(docName.value);
}

// Submitting a sales invoice = a "sale". Track the activation funnel once per
// company; submit() returns the result only on success, so failures don't emit.
async function submitSale() {
	const res = await submit();
	if (res) trackOnce(FUNNEL.FIRST_SALE);
}

function goToInvoice(name) {
	if (name) router.push("/sales/invoices/" + name);
}

// Dimensional line summary (e.g. "2.5 × 0.3 × 10 pcs"). Blank for normal items.
function dimSummary(it) {
	const mode = it?.custom_dimension_mode;
	if (!["Linear", "Area", "Volume"].includes(mode)) return "";
	const p = [it.custom_length];
	if (mode === "Area" || mode === "Volume") p.push(it.custom_width);
	if (mode === "Volume") p.push(it.custom_height);
	const dims = p.filter((x) => x != null && x !== "").join(" × ");
	return dims ? `${dims} × ${it.custom_pieces || 1} pcs` : "";
}

// Payment
const paymentOpen = ref(false);
const PAYABLE_STATUSES = new Set(["Unpaid", "Overdue", "Partly Paid"]);
const canPay = computed(() => {
	if (!form.value || form.value.is_return) return false;
	if (form.value.docstatus === 0) return Number(form.value.grand_total || 0) > 0;
	return form.value.docstatus === 1 && PAYABLE_STATUSES.has(form.value.status);
});

function openPayment() {
	actionError.value = "";
	paymentOpen.value = true;
}
async function onPaid() {
	paymentOpen.value = false;
	await loadDoc();
}

// Didox EDO (ЭСФ) — manual submit of a posted invoice
const edoOpen = ref(false);
const canSendEdo = computed(() => Boolean(form.value) && form.value.docstatus === 1 && !form.value.is_return);

// The Edit button routes to the direct-invoice form, which the backend gates on
// `direct_invoicing`. Without the same condition here the six tenants that do not
// own the capability get the button on every draft and land on its refusal banner.
const canDirectInvoice = computed(() => {
	const flag = session.modules?.direct_invoicing;
	return flag !== false && flag !== 0;
});

function openEdo() {
	actionError.value = "";
	edoOpen.value = true;
}
async function onSent() {
	edoOpen.value = false;
	await loadDoc();
}
// On-demand poll of Didox for the counterparty's answer (B4). The hourly
// scheduler already refreshes every open ЭСФ, but a user watching the form
// wants an immediate answer instead of waiting up to an hour.
const edoRefreshing = ref(false);
async function refreshEdo() {
	if (!form.value?.name) return;
	edoRefreshing.value = true;
	try {
		const edo = await call("stabler.api.edo.didox_refresh_status", { name: form.value.name });
		form.value.edo = edo && Object.keys(edo).length ? edo : null;
	} catch (e) {
		actionError.value = e?.message || String(e);
	} finally {
		edoRefreshing.value = false;
	}
}

// Return / credit note modal
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
		const res = await call("stabler.api.sales.create_sales_return", {
			sales_invoice: form.value.name,
			posting_date: todayIso(),
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

const totalsByUom = computed(() => {
	const map = new Map();
	for (const line of form.value?.items || []) {
		if (!line.qty || !line.uom) continue;
		map.set(line.uom, (map.get(line.uom) || 0) + Number(line.qty));
	}
	return [...map.entries()];
});

watch(docName, loadDoc);
onMounted(loadDoc);
</script>

<template>
	<FormPage
		:title="t('Sales Invoice')"
		:doc-name="docName"
		:status="form?.status"
		:docstatus="form?.docstatus"
		:loading="loading"
		:error="loadError"
		:action-error="actionError"
		back-path="/sales/invoices"
	>
		<template v-if="form && form.name">
			<div class="d-flex align-items-center gap-2 mb-3 flex-wrap">
				<span class="text-secondary">{{ form.customer_name }}</span>
				<span v-if="form.is_return" class="badge bg-secondary-lt">{{ t("Return") }}</span>
			</div>

			<div v-if="form.return_against" class="alert alert-info py-2 small">
				<i class="ti ti-corner-down-left me-1"></i>
				{{ t("Credit note for") }}
				<button
					type="button"
					class="badge bg-blue-lt font-monospace border-0"
					style="cursor: pointer"
					@click="goToInvoice(form.return_against)"
				>{{ form.return_against }}</button>
			</div>

			<div v-if="form.credit_notes?.length" class="alert alert-light py-2 small">
				<i class="ti ti-receipt-refund me-1"></i>
				{{ t("Credit notes:") }}
				<button
					v-for="cn in form.credit_notes"
					:key="cn.name"
					type="button"
					class="badge bg-secondary-lt font-monospace ms-1 border-0"
					style="cursor: pointer"
					@click="goToInvoice(cn.name)"
				>{{ cn.name }}</button>
			</div>

			<!-- Header datagrid -->
			<div class="datagrid mb-3">
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Posting date") }}</div>
					<div class="datagrid-content">{{ formatDateTime(form.posting_date) || "—" }}</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Due date") }}</div>
					<div class="datagrid-content">{{ formatDateTime(form.due_date) || "—" }}</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Customer") }}</div>
					<div class="datagrid-content">
						{{ form.customer_name }}
						<span class="text-secondary font-monospace small">· {{ form.customer }}</span>
					</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Currency") }}</div>
					<div class="datagrid-content font-monospace">{{ form.currency }}</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Warehouse") }}</div>
					<div class="datagrid-content">{{ form.set_warehouse_name || form.set_warehouse || "—" }}</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Net total") }}</div>
					<div class="datagrid-content font-monospace">{{ formatMoney(form.net_total, form.currency, user.language) }}</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Grand total") }}</div>
					<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(form.grand_total, form.currency, user.language) }}</div>
				</div>
				<div class="datagrid-item">
					<div class="datagrid-title">{{ t("Outstanding") }}</div>
					<div class="datagrid-content font-monospace text-red">{{ formatMoney(form.outstanding_amount, form.currency, user.language) }}</div>
				</div>
			</div>

			<!-- Items: Genuinely read-only in Stabler as invoices are derived directly from Sales Orders -->
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
						<tr v-for="(it, i) in form.items" :key="i">
							<td class="text-end text-secondary font-monospace small">{{ i + 1 }}</td>
							<td>
								<div class="fw-semibold">{{ it.item_name || it.item_code }}</div>
								<div class="small text-secondary font-monospace">{{ it.item_code }}</div>
								<div v-if="dimSummary(it)" class="small text-secondary">{{ dimSummary(it) }}</div>
							</td>
							<td class="text-end font-monospace">
								{{ it.qty }}<template v-if="it.custom_dimension_mode"> {{ it.stock_uom }}</template>
							</td>
							<td>{{ it.uom || "—" }}</td>
							<td class="text-end font-monospace text-secondary small">
								{{ it.price_list_rate > 0 ? formatMoney(it.price_list_rate, form.currency, user.language) : "—" }}
							</td>
							<td class="text-end font-monospace small">
								{{ it.discount_percentage > 0 ? it.discount_percentage + "%" : "—" }}
							</td>
							<td class="text-end font-monospace small">
								{{ it.discount_amount > 0 ? formatMoney(it.discount_amount, form.currency, user.language) : "—" }}
							</td>
							<td class="text-end font-monospace">{{ formatMoney(it.rate, form.currency, user.language) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(it.amount, form.currency, user.language) }}</td>
						</tr>
					</tbody>
					<tfoot>
						<tr>
							<td colspan="9" class="pt-2 pb-0">
								<span class="badge bg-secondary-lt">{{ form.items.length }} {{ form.items.length === 1 ? t('item') : t('items') }}</span>
								<span v-for="[uom, qty] in totalsByUom" :key="uom" class="badge bg-blue-lt ms-1 font-monospace">{{ qty }} {{ uom }}</span>
							</td>
						</tr>
					</tfoot>
				</table>
			</div>

			<div class="mt-3">
				<label class="form-label">{{ t("Terms / remarks") }}</label>
				<div class="form-control-plaintext py-1">{{ form.remarks || "—" }}</div>
			</div>

			<RelatedDocuments doctype="Sales Invoice" :name="form.name" />
		</template>

		<!-- Actions -->
		<template #actions>
			<button
				v-if="can.submit"
				type="button"
				class="btn btn-primary"
				:disabled="actionRunning"
				@click="submitSale"
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
				v-if="form"
				:to="'/sales/invoices/' + form.name + '/print'"
				class="btn btn-outline-secondary"
			>
				<i class="ti ti-printer me-1"></i>{{ t("Print") }}
			</router-link>
			<router-link
				v-if="form"
				:to="'/sales/invoices/' + form.name + '/waybill'"
				class="btn btn-outline-secondary"
			>
				<i class="ti ti-truck me-1"></i>{{ t("Yuk xati") }}
			</router-link>
			<!-- i18n harvest anchors for the dynamic t(form.edo.status) badge below
			     (harvest.py only sees literal t("...")):
			     t("Draft"); t("Signed"); t("Sent"); t("Accepted"); t("Rejected"); t("Error") -->
			<span
				v-if="form && form.edo"
				class="badge align-self-center"
				:class="getStatusBadgeClass('EDO Status', form.edo.status)"
			>
				<i class="ti ti-file-certificate me-1"></i>{{ t("Didox") }}: {{ t(form.edo.status) }}
			</span>
			<button
				v-if="form && form.edo && form.edo.status === 'Sent'"
				type="button"
				class="btn btn-outline-secondary align-self-center"
				:disabled="edoRefreshing"
				:title="t('Refresh')"
				@click="refreshEdo"
			>
				<span v-if="edoRefreshing" class="spinner-border spinner-border-sm"></span>
				<i v-else class="ti ti-refresh"></i>
			</button>
			<button
				v-if="canSendEdo"
				type="button"
				class="btn btn-outline-secondary"
				:disabled="actionRunning"
				@click="openEdo"
			>
				<i class="ti ti-file-certificate me-1"></i>{{ t("Send to Didox") }}
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
				v-if="can.delete && canDirectInvoice"
				type="button"
				class="btn btn-outline-secondary"
				:disabled="actionRunning"
				@click="router.push(`/sales/invoices/${form.name}/edit`)"
			>
				<i class="ti ti-edit me-1"></i>{{ t("Edit") }}
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
	</FormPage>

	<PaymentModal
		:open="paymentOpen"
		invoice-type="Sales Invoice"
		:invoice-name="form?.name || ''"
		:modified="form?.modified || ''"
		@close="paymentOpen = false"
		@paid="onPaid"
	/>

	<EdoSubmitModal
		:open="edoOpen"
		:invoice-name="form?.name || ''"
		@close="edoOpen = false"
		@sent="onSent"
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
