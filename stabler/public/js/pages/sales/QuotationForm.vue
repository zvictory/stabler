<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime, todayIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { itemSearcher } from "../../composables/items.js";
import DateInput from "../../components/DateInput.vue";
import Typeahead from "../../components/Typeahead.vue";
import RelatedDocuments from "../../components/RelatedDocuments.vue";
import FormPage from "../../components/form/FormPage.vue";
import LineItemsEditor from "../../components/LineItemsEditor.vue";
import { useDocumentForm } from "../../composables/useDocumentForm.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
const route = useRoute();

const today = todayIso();

const currency = computed(() => session.currency || "UZS");

function blankLine() {
	return {
		item_code: "",
		item_name: "",
		uom: "",
		qty: 1,
		rate: 0,
		amount: 0,
	};
}

function blankForm() {
	return {
		customer: "",
		customer_name: "",
		transaction_date: today,
		valid_till: "",
		remarks: "",
		items: [blankLine()],
	};
}

function fromDetail(d) {
	return {
		customer: d.customer || d.party_name,
		customer_name: d.customer_name || d.customer || d.party_name,
		transaction_date: d.transaction_date || "",
		valid_till: d.valid_till || "",
		remarks: d.remarks || d.terms || "",
		items: (d.items || []).map((it) => ({
			item_code: it.item_code,
			item_name: it.item_name,
			uom: it.uom || "",
			qty: Number(it.qty || 0),
			rate: Number(it.rate || 0),
			amount: Number(it.amount || 0),
		})),
	};
}

function toPayload(m) {
	return {
		company: activeCompany.value,
		customer: m.customer,
		transaction_date: m.transaction_date,
		valid_till: m.valid_till || undefined,
		remarks: m.remarks || undefined,
		items: m.items
			.filter((r) => r.item_code)
			.map((r) => ({
				item_code: r.item_code,
				qty: r.qty,
				rate: r.rate,
				uom: r.uom || undefined,
			})),
	};
}

// Document engine hook
const {
	model: form,
	loading,
	saving: actionRunning,
	error: actionError,
	isDirty,
	isCreate,
	editable,
	docstatus,
	status,
	load,
	save,
	submit,
	cancel,
	remove,
	can,
} = useDocumentForm({
	doctype: "Quotation",
	detailApi: "stabler.api.sales.quotation_detail",
	createApi: "stabler.api.sales.create_quotation",
	updateApi: "stabler.api.sales.update_quotation",
	submitApi: "stabler.api.sales.submit_quotation",
	cancelApi: "stabler.api.sales.cancel_quotation",
	deleteApi: "stabler.api.sales.delete_quotation",
	blankModel: blankForm,
	toPayload,
	fromDetail,
	backPath: "/sales/quotations",
});

const docName = computed(() => (route.params.name ? String(route.params.name) : null));

async function loadDoc() {
	if (!docName.value) return;
	await load(docName.value);
}

// Lookups
function searchCustomers(q) {
	return call("stabler.api.sales.list_customers", {
		company: activeCompany.value,
		search: q,
		limit: 10,
	});
}

function pickCustomer(c) {
	form.value.customer = c.name;
	form.value.customer_name = c.customer_name;
}

function clearCustomer() {
	form.value.customer = "";
	form.value.customer_name = "";
}

const searchItems = itemSearcher("sales");

async function handlePickItem({ line, item, index, field }) {
	if (field === "item") {
		line.item_code = item.item_code || item.name;
		line.item_name = item.item_name;
		line.uom = item.stock_uom || "";
		line.rate = Number(item.standard_rate || 0);
	}
}

watch(docName, loadDoc);

onMounted(async () => {
	// Branch on the route param (present on a hard load), not the composable's
	// isCreate (null-based, true until load() runs) — else direct URL/refresh of an
	// edit route renders a blank "New".
	if (docName.value) {
		await loadDoc();
	} else {
		form.value = blankForm();
	}
});

// Calculations are handled by LineItemsEditor.vue

// Inline validations
const isFormValid = ref(true);

function handleValidityChange(valid) {
	isFormValid.value = valid;
}

async function submitCreate() {
	actionError.value = "";
	if (!form.value.customer) {
		actionError.value = t("Pick a customer.");
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
		:title="isCreate ? t('New Quotation') : t('Quotation')"
		:doc-name="docName"
		:status="status"
		:docstatus="docstatus"
		:loading="loading"
		:error="actionError"
		back-path="/sales/quotations"
	>
		<!-- Header fields -->
		<div class="row g-3 mb-3">
			<div class="col-md-6">
				<label class="form-label" :class="{ required: editable }">{{ t("Customer") }}</label>
				<Typeahead
					v-slot="{ item }"
					v-if="editable"
					v-model="form.customer"
					:search="searchCustomers"
					:display="form.customer_name"
					:placeholder="t('Search customer name…')"
					:no-results-text="t('No customers match that name')"
					open-on-focus
					@pick="pickCustomer"
					@clear="clearCustomer"
				>
					<div class="d-flex align-items-center gap-2">
						<span class="avatar avatar-xs bg-purple-lt">{{ (item.customer_name || item.name).charAt(0).toUpperCase() }}</span>
						<div>
							<div class="fw-semibold">{{ item.customer_name }}</div>
							<div class="small text-secondary">{{ item.name }} · {{ item.customer_group || "—" }}</div>
						</div>
					</div>
				</Typeahead>
				<div v-else class="form-control-plaintext fw-semibold py-1">
					{{ form.customer_name }}
					<span class="text-secondary fw-normal font-monospace small">· {{ form.customer }}</span>
				</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Date") }}</label>
				<DateInput v-if="editable" v-model="form.transaction_date" />
				<div v-else class="form-control-plaintext py-1">{{ formatDateTime(form.transaction_date) || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Valid till") }}</label>
				<DateInput v-if="editable" v-model="form.valid_till" />
				<div v-else class="form-control-plaintext py-1">{{ formatDate(form.valid_till) || "—" }}</div>
			</div>
		</div>

		<!-- Read-only post-submit datagrid (view mode) -->
		<div v-if="!isCreate && form" class="datagrid mb-3">
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Grand total") }}</div>
				<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(form.grand_total, currency, user.language) }}</div>
			</div>
		</div>

		<!-- Items -->
		<h6 class="text-uppercase text-secondary small mb-2">{{ t("Items") }}</h6>
		<LineItemsEditor
			v-if="form"
			:items="form.items"
			:editable="editable"
			:currency="currency"
			:search-items="searchItems"
			:blank-line="blankLine"
			@pick-item="handlePickItem"
			@validity-change="handleValidityChange"
		>
			<template #footer-extra="{ totalsByUom: tUoms, grandTotal }">
				<tr>
					<td colspan="2" class="align-middle">
						<span class="badge bg-secondary-lt">{{ form.items.length }} {{ form.items.length === 1 ? t('item') : t('items') }}</span>
						<span v-for="[uom, qty] in tUoms" :key="uom" class="badge bg-blue-lt ms-1 font-monospace">{{ qty }} {{ uom }}</span>
					</td>
					<td colspan="3"></td>
					<td class="text-end font-monospace fw-bold py-2">{{ formatMoney(grandTotal, currency, user.language) }}</td>
				</tr>
			</template>
		</LineItemsEditor>

		<div class="mt-3">
			<label class="form-label">{{ t("Terms / remarks") }}</label>
			<textarea v-if="editable" v-model="form.remarks" class="form-control" rows="2"></textarea>
			<div v-else class="form-control-plaintext py-1">{{ form.remarks || "—" }}</div>
		</div>

		<RelatedDocuments v-if="!isCreate && form" doctype="Quotation" :name="docName" />

		<!-- Actions -->
		<template #actions>
			<template v-if="isCreate">
				<button type="button" class="btn btn-link link-secondary" :disabled="actionRunning" @click="router.push('/sales/quotations')">{{ t("Cancel") }}</button>
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
					v-if="can.cancel"
					type="button"
					class="btn btn-outline-danger ms-auto"
					:disabled="actionRunning"
					@click="cancel"
				>
					<i class="ti ti-ban me-1"></i>{{ t("Cancel") }}
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
</template>
