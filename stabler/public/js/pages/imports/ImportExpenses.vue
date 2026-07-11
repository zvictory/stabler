<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { useToast } from "../../composables/useToast.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import StatusBadge from "../../components/StatusBadge.vue";
import Pagination from "../../components/Pagination.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const CATEGORIES = ["Border Crossing", "Transport", "Handling", "Storage", "Insurance", "Documentation", "Customs", "Other"];

const search = ref("");
const category = ref("");
const status = ref("");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const total = ref(0);
const limitStart = ref(0);
const pageLength = ref(25);

const costVisible = computed(() => session.costVisible === true);
const categoryOptions = computed(() => [{ value: "", label: t("All categories") }, ...CATEGORIES.map((c) => ({ value: c, label: t(c) }))]);
const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...["Pending", "Partial", "Paid"].map((s) => ({ value: s, label: t(s) })),
]);
const catFormOptions = CATEGORIES.map((c) => ({ value: c, label: t(c) }));

// --- Modal state ---
const modalOpen = ref(false);
const saving = ref(false);
const form = ref(blankForm());

function blankForm() {
	return {
		name: null,
		modified: null,
		category: "Other",
		expense_date: "",
		supplier: "",
		supplier_name: "",
		invoice_reference: "",
		commercial_invoice: "",
		container: "",
		truck: "",
		description: "",
		amount: 0,
		currency: "USD",
		bank_payment: null,
		cash_payment: null,
		status: "Pending",
		purchase_invoice: null,
	};
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await importsApi.listImportExpenses({
			company: activeCompany.value,
			search: search.value || undefined,
			category: category.value || undefined,
			status: status.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
		});
		rows.value = res.rows || [];
		total.value = res.total_count || 0;
	} catch (err) {
		error.value = err?.message || t("Failed to load expenses.");
	} finally {
		loading.value = false;
	}
}

function reload() {
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}

async function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", { company: activeCompany.value, search: q || "", limit: 20 });
}
function pickSupplier(item) {
	form.value.supplier = item.name;
	form.value.supplier_name = item.supplier_name || item.name;
}

function openCreate() {
	form.value = blankForm();
	modalOpen.value = true;
}
async function openEdit(name) {
	try {
		const d = await importsApi.getImportExpense(name);
		form.value = { ...blankForm(), ...d, supplier_name: d.supplier || "" };
		modalOpen.value = true;
	} catch (err) {
		toast.error(err?.message || t("Failed to load the expense."));
	}
}
function closeModal() {
	modalOpen.value = false;
}

function buildValues() {
	const v = {
		category: form.value.category,
		expense_date: form.value.expense_date || undefined,
		supplier: form.value.supplier || undefined,
		invoice_reference: form.value.invoice_reference,
		commercial_invoice: form.value.commercial_invoice || undefined,
		container: form.value.container || undefined,
		truck: form.value.truck || undefined,
		description: form.value.description,
		amount: Number(form.value.amount || 0),
		currency: form.value.currency,
	};
	if (costVisible.value) {
		if (form.value.bank_payment !== null && form.value.bank_payment !== "") v.bank_payment = Number(form.value.bank_payment);
		if (form.value.cash_payment !== null && form.value.cash_payment !== "") v.cash_payment = Number(form.value.cash_payment);
	}
	return v;
}

async function save() {
	if (!form.value.category) {
		toast.error(t("A category is required."));
		return;
	}
	saving.value = true;
	try {
		if (form.value.name) {
			await importsApi.updateImportExpense({ name: form.value.name, values: buildValues(), modified: form.value.modified });
			toast.success(t("Expense saved."));
		} else {
			await importsApi.createImportExpense({ company: activeCompany.value, values: buildValues() });
			toast.success(t("Expense created."));
		}
		modalOpen.value = false;
		await load();
	} catch (err) {
		toast.error(err?.message || t("Save failed."));
	} finally {
		saving.value = false;
	}
}

onMounted(load);
watch([category, status], reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, reload);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Expense, supplier or CI… ⌘K')"
			:count="total"
			:primary-label="t('New expense')"
			primary-icon="ti-plus"
			@search="reload"
			@primary-click="openCreate"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2">
					<Select v-model="category" size="sm" :options="categoryOptions" style="width: 160px" />
					<Select v-model="status" size="sm" :options="statusOptions" style="width: 130px" />
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body"><div class="alert alert-danger m-0">{{ error }}</div></div>
		<EmptyState
			v-else-if="!loading && !rows.length"
			icon="ti-receipt"
			tone="info"
			:title="t('No import expenses')"
			:subtitle="t('Record border-crossing, handling and other import costs here.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">{{ t("Date") }}</th>
						<th>{{ t("Category") }}</th>
						<th>{{ t("Supplier") }}</th>
						<th>{{ t("Commercial Invoice") }}</th>
						<th class="text-end">{{ t("Amount") }}</th>
						<th>{{ t("Status") }}</th>
						<th>{{ t("Purchase Invoice") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="7" />
				<tbody v-else>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openEdit(r.name)">
						<td class="text-nowrap">{{ formatDate(r.expense_date) }}</td>
						<td>{{ t(r.category) }}</td>
						<td>{{ r.supplier || "—" }}</td>
						<td class="font-monospace small">{{ r.commercial_invoice || "—" }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.amount, r.currency, user.language) }}</td>
						<td><StatusBadge doctype="Import Expense" :status="r.status" /></td>
						<td class="font-monospace small">{{ r.purchase_invoice || "—" }}</td>
					</tr>
				</tbody>
			</table>
		</div>
		<Pagination
			v-if="!error && total > 0"
			v-model:limit-start="limitStart"
			v-model:page-length="pageLength"
			:total="total"
			:page-count="rows.length"
		/>
	</div>

	<!-- Create/edit modal -->
	<div v-if="modalOpen" class="modal modal-blur fade show d-block" tabindex="-1">
		<div class="modal-dialog modal-lg modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ form.name ? t("Edit expense") : t("New expense") }}</h5>
					<button type="button" class="btn-close" @click="closeModal"></button>
				</div>
				<div class="modal-body">
					<div class="row g-3">
						<div class="col-md-4">
							<label class="form-label required">{{ t("Category") }}</label>
							<Select v-model="form.category" :options="catFormOptions" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Date") }}</label>
							<DateInput v-model="form.expense_date" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Supplier") }}</label>
							<Typeahead v-slot="{ item }" v-model="form.supplier" :search="searchSuppliers" :display="form.supplier_name" :placeholder="t('Search supplier…')" open-on-focus @pick="pickSupplier">
								<div class="fw-semibold">{{ item.supplier_name || item.name }}</div>
							</Typeahead>
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Commercial Invoice") }}</label>
							<input v-model="form.commercial_invoice" type="text" class="form-control font-monospace" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Container") }}</label>
							<input v-model="form.container" type="text" class="form-control font-monospace" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Truck") }}</label>
							<input v-model="form.truck" type="text" class="form-control font-monospace" />
						</div>
						<div class="col-md-8">
							<label class="form-label">{{ t("Invoice reference") }}</label>
							<input v-model="form.invoice_reference" type="text" class="form-control" />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Currency") }}</label>
							<input v-model="form.currency" type="text" class="form-control" />
						</div>
						<div class="col-12">
							<label class="form-label">{{ t("Description") }}</label>
							<textarea v-model="form.description" class="form-control" rows="2"></textarea>
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Amount") }}</label>
							<MoneyInput v-model="form.amount" :currency="form.currency" :language="user.language" size="sm" />
						</div>
						<template v-if="costVisible">
							<div class="col-md-4">
								<label class="form-label">{{ t("Bank payment") }}</label>
								<MoneyInput v-model="form.bank_payment" :currency="form.currency" :language="user.language" size="sm" />
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Cash payment") }}</label>
								<MoneyInput v-model="form.cash_payment" :currency="form.currency" :language="user.language" size="sm" />
							</div>
						</template>
						<div v-else class="col-md-8 d-flex align-items-end">
							<span class="text-secondary small"><i class="ti ti-lock me-1"></i>{{ t("Payment split is hidden for your role.") }}</span>
						</div>
						<div v-if="form.purchase_invoice" class="col-12">
							<div class="alert alert-info py-2 mb-0 small"><i class="ti ti-link me-1"></i>{{ t("Linked purchase invoice: {pi}", { pi: form.purchase_invoice }) }}</div>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="closeModal">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="saving" @click="save">
						<i class="ti ti-device-floppy me-1"></i>{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>
	<div v-if="modalOpen" class="modal-backdrop fade show"></div>
</template>
