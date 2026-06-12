<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Typeahead from "../../components/Typeahead.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const route = useRoute();
const { activeCompany, user } = storeToRefs(session);

const today = new Date().toISOString().slice(0, 10);
const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
const fromDate = ref(monthAgo);
const toDate = ref(today);
const limit = ref(50);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailActionRunning = ref(false);
const detailActionError = ref("");
const detailEditing = ref(false);
const detail = ref(null);
const detailForm = ref({
	posting_date: "",
	mode_of_payment: "",
	reference_no: "",
	reference_date: "",
	paid_amount: null,
	received_amount: null,
});

const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");

const partyName = ref("");
const partyAccount = ref("");
const partyAccountCurrency = ref("");
const partyDefaultsLoading = ref(false);
const outstanding = ref([]);
const bankAccounts = ref([]);

function blankForm() {
	return {
		posting_date: today,
		payment_type: "Receive",
		party: "",
		bank_account: "",
		amount: null,
		bank_amount: null,
		mode_of_payment: "",
		reference_no: "",
		reference_date: "",
	};
}

const form = ref(blankForm());

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const partyType = computed(() => (form.value.payment_type === "Pay" ? "Supplier" : "Customer"));

const paymentTypeOptions = computed(() => [
	{ value: "Receive", label: t("Receive") },
	{ value: "Pay", label: t("Pay") },
]);

const bankCurrency = computed(() => {
	const acct = bankAccounts.value.find((a) => a.name === form.value.bank_account);
	return acct?.account_currency || "";
});

const showBankAmount = computed(
	() =>
		bankCurrency.value &&
		partyAccountCurrency.value &&
		bankCurrency.value !== partyAccountCurrency.value
);

const refCurrency = computed(() => {
	const d = detail.value;
	if (!d) return currency.value;
	const c = d.payment_type === "Receive" ? d.paid_to_account_currency : d.paid_from_account_currency;
	return c || currency.value;
});

const statusBadge = (d) => {
	if (d === 0) return { cls: "bg-yellow-lt", label: t("Draft") };
	if (d === 1) return { cls: "bg-green-lt", label: t("Submitted") };
	if (d === 2) return { cls: "bg-red-lt", label: t("Cancelled") };
	return { cls: "bg-secondary-lt", label: String(d) };
};

const typeBadge = (t) => {
	if (t === "Receive") return { cls: "bg-green-lt", icon: "ti-arrow-down-left" };
	if (t === "Pay") return { cls: "bg-red-lt", icon: "ti-arrow-up-right" };
	return { cls: "bg-secondary-lt", icon: "ti-arrows-exchange" };
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.money.list_payment_entries", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load payment entries.");
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detailActionError.value = "";
	detailEditing.value = false;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.money.payment_entry_detail", { name });
	} catch (err) {
		detail.value = { error: err?.message || t("Failed to load.") };
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	if (detailActionRunning.value) return;
	detailOpen.value = false;
	detailActionError.value = "";
	detailEditing.value = false;
	detail.value = null;
}

async function reloadDetail() {
	if (!detail.value?.name) return;
	detail.value = await call("stabler.api.money.payment_entry_detail", { name: detail.value.name });
}

async function submitDetail() {
	if (!detail.value?.name) return;
	detailActionError.value = "";
	detailActionRunning.value = true;
	try {
		await call("stabler.api.money.submit_payment_entry", { name: detail.value.name });
		await reloadDetail();
		await load();
	} catch (err) {
		detailActionError.value = err?.message || t("Submit failed.");
	} finally {
		detailActionRunning.value = false;
	}
}

function startEditDetail() {
	if (!detail.value || detail.value.docstatus !== 0) return;
	detailActionError.value = "";
	detailForm.value = {
		posting_date: detail.value.posting_date || today,
		mode_of_payment: detail.value.mode_of_payment || "",
		reference_no: detail.value.reference_no || "",
		reference_date: detail.value.reference_date || "",
		paid_amount: Number(detail.value.paid_amount || 0),
		received_amount: Number(detail.value.received_amount || 0),
	};
	detailEditing.value = true;
}

function cancelEditDetail() {
	if (detailActionRunning.value) return;
	detailEditing.value = false;
	detailActionError.value = "";
}

async function saveDetail() {
	if (!detail.value?.name) return;
	detailActionError.value = "";
	const paid = Number(detailForm.value.paid_amount);
	const received = Number(detailForm.value.received_amount);
	if (!Number.isFinite(paid) || paid <= 0) {
		detailActionError.value = t("Paid amount must be greater than zero.");
		return;
	}
	if (!Number.isFinite(received) || received <= 0) {
		detailActionError.value = t("Received amount must be greater than zero.");
		return;
	}
	detailActionRunning.value = true;
	try {
		detail.value = await call("stabler.api.money.update_payment_entry", {
			name: detail.value.name,
			posting_date: detailForm.value.posting_date || null,
			mode_of_payment: detailForm.value.mode_of_payment || null,
			reference_no: detailForm.value.reference_no || null,
			reference_date: detailForm.value.reference_date || null,
			paid_amount: paid,
			received_amount: received,
		});
		detailEditing.value = false;
		await load();
	} catch (err) {
		detailActionError.value = err?.message || t("Save failed.");
	} finally {
		detailActionRunning.value = false;
	}
}

async function cancelDetail() {
	if (!detail.value?.name) return;
	if (!window.confirm(t("Cancel payment {name}?", { name: detail.value.name }))) return;
	detailActionError.value = "";
	detailActionRunning.value = true;
	try {
		await call("stabler.api.money.cancel_payment_entry", { name: detail.value.name });
		await reloadDetail();
		await load();
	} catch (err) {
		detailActionError.value = err?.message || t("Cancel failed.");
	} finally {
		detailActionRunning.value = false;
	}
}

async function deleteDetail() {
	if (!detail.value?.name) return;
	if (!window.confirm(t("Delete payment {name}?", { name: detail.value.name }))) return;
	detailActionError.value = "";
	detailActionRunning.value = true;
	try {
		await call("stabler.api.money.delete_payment_entry", { name: detail.value.name });
		closeDetail();
		await load();
	} catch (err) {
		detailActionError.value = err?.message || t("Delete failed.");
	} finally {
		detailActionRunning.value = false;
	}
}

function searchParty(q) {
	if (partyType.value === "Customer") {
		return call("stabler.api.sales.list_customers", {
			company: activeCompany.value,
			search: q,
			limit: 10,
		});
	}
	return call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 10,
	});
}

async function pickParty(p) {
	form.value.party = p.name;
	partyName.value =
		partyType.value === "Customer" ? p.customer_name || p.name : p.supplier_name || p.name;
	partyDefaultsLoading.value = true;
	outstanding.value = [];
	partyAccount.value = "";
	partyAccountCurrency.value = "";
	submitError.value = "";
	try {
		const d = await call("stabler.api.money.party_payment_defaults", {
			company: activeCompany.value,
			party_type: partyType.value,
			party: p.name,
		});
		partyAccount.value = d.party_account || "";
		partyAccountCurrency.value = d.party_account_currency || "";
		bankAccounts.value = d.cash_bank_accounts || [];
		if (!form.value.bank_account && d.suggested_cash_bank_account) {
			form.value.bank_account = d.suggested_cash_bank_account;
		}
		outstanding.value = (d.outstanding_invoices || []).map((r) => ({ ...r, allocated: 0 }));
		distributeAmount();
	} catch (err) {
		submitError.value = err?.message || t("Failed to load party defaults.");
	} finally {
		partyDefaultsLoading.value = false;
	}
}

function clearParty() {
	form.value.party = "";
	partyName.value = "";
	partyAccount.value = "";
	partyAccountCurrency.value = "";
	outstanding.value = [];
}

function distributeAmount() {
	let remaining = Number(form.value.amount) || 0;
	for (const row of outstanding.value) {
		if (remaining <= 0) {
			row.allocated = 0;
		} else {
			const alloc = Math.min(remaining, row.outstanding_amount);
			row.allocated = Math.round(alloc * 100) / 100;
			remaining = Math.round((remaining - alloc) * 100) / 100;
		}
	}
}

async function openCreate() {
	form.value = blankForm();
	partyName.value = "";
	partyAccount.value = "";
	partyAccountCurrency.value = "";
	outstanding.value = [];
	submitError.value = "";
	createOpen.value = true;
	try {
		bankAccounts.value = await call("stabler.api.money.list_cash_bank_accounts", {
			company: activeCompany.value,
		});
		if (bankAccounts.value.length && !form.value.bank_account) {
			form.value.bank_account = bankAccounts.value[0].name;
		}
	} catch {}
}

function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}

watch(
	() => form.value.payment_type,
	() => {
		clearParty();
		form.value.amount = null;
		form.value.bank_amount = null;
	},
);

watch(() => form.value.amount, distributeAmount);

async function submitCreate(submitNow = false) {
	submitError.value = "";
	const f = form.value;
	if (!f.posting_date) return (submitError.value = t("Posting date is required."));
	if (!f.party) return (submitError.value = t("Party is required."));
	if (!f.bank_account) return (submitError.value = t("Bank/cash account is required."));
	if (!partyAccount.value)
		return (submitError.value = t("Party account not resolved — re-select the party."));

	const amt = Number(f.amount);
	if (!Number.isFinite(amt) || amt <= 0)
		return (submitError.value = t("Amount must be greater than zero."));

	const bankAmt = showBankAmount.value ? Number(f.bank_amount) || amt : amt;
	const isReceive = f.payment_type === "Receive";

	const refs = outstanding.value
		.filter((r) => r.allocated > 0)
		.map((r) => ({
			reference_doctype: r.voucher_type,
			reference_name: r.voucher_no,
			total_amount: r.invoice_amount,
			outstanding_amount: r.outstanding_amount,
			allocated_amount: r.allocated,
		}));

	const totalAllocated = refs.reduce((s, r) => s + r.allocated_amount, 0);
	if (totalAllocated > amt + 0.005) {
		return (submitError.value = t("Total allocated cannot exceed the payment amount."));
	}

	submitting.value = true;
	try {
		const created = await call("stabler.api.money.create_payment_entry", {
			company: activeCompany.value,
			posting_date: f.posting_date,
			payment_type: f.payment_type,
			party_type: partyType.value,
			party: f.party,
			paid_from: isReceive ? partyAccount.value : f.bank_account,
			paid_to: isReceive ? f.bank_account : partyAccount.value,
			paid_amount: isReceive ? amt : bankAmt,
			received_amount: isReceive ? bankAmt : amt,
			mode_of_payment: f.mode_of_payment || null,
			reference_no: f.reference_no || null,
			reference_date: f.reference_date || null,
			references: refs.length ? refs : null,
		});
		if (submitNow) {
			await call("stabler.api.money.submit_payment_entry", { name: created.name });
		}
		createOpen.value = false;
		await load();
	} catch (err) {
		submitError.value = err?.message || t("Failed to create payment.");
	} finally {
		submitting.value = false;
	}
}

onMounted(async () => {
	await load();
	const openName = route.query?.open;
	if (openName) openDetail(String(openName));
});
watch(activeCompany, () => {
	bankAccounts.value = [];
	load();
});
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">{{ t("Payments") }}</div>
			<div class="ms-auto d-flex gap-2 align-items-end">
				<div>
					<label class="form-label small mb-1">{{ t("From") }}</label>
					<DateInput v-model="fromDate" size="sm" />
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("To") }}</label>
					<DateInput v-model="toDate" size="sm" />
				</div>
				<button type="button" class="btn btn-sm btn-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
				</button>
				<button type="button" class="btn btn-sm btn-success" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New payment") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary" role="status"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-cash"
			accentIcon="ti-plus"
			tone="success"
			:title='t("No payments in this range")'
			:subtitle='t("Widen the date range or record a payment receipt or disbursement.")'
		>
			<template #actions>
				<button type="button" class="btn btn-primary" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New payment") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>#</th>
						<th>{{ t("Date") }}</th>
						<th class="w-1">{{ t("Type") }}</th>
						<th>{{ t("Party") }}</th>
						<th>{{ t("Mode") }}</th>
						<th>{{ t("Reference") }}</th>
						<th class="text-end">{{ t("Amount") }}</th>
						<th class="w-1">{{ t("Status") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="r in rows"
						:key="r.name"
						style="cursor: pointer"
						@click="openDetail(r.name)"
					>
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ formatDateTime(r.posting_date) }}</td>
						<td>
							<span class="badge" :class="typeBadge(r.payment_type).cls">
								<i class="ti me-1" :class="typeBadge(r.payment_type).icon"></i>{{ r.payment_type }}
							</span>
						</td>
						<td>
							<div class="fw-semibold">{{ r.party_name || r.party || "—" }}</div>
							<div class="small text-secondary">{{ r.party_type || "" }}</div>
						</td>
						<td>{{ r.mode_of_payment || "—" }}</td>
						<td class="text-truncate" style="max-width: 200px">{{ r.reference_no || "—" }}</td>
						<td class="text-end font-monospace">
							{{ formatMoney(
								r.payment_type === "Receive" ? r.received_amount : r.paid_amount,
								(r.payment_type === "Receive" ? r.paid_to_account_currency : r.paid_from_account_currency) || currency,
								user.language
							) }}
						</td>
						<td>
							<span class="badge" :class="statusBadge(r.docstatus).cls">{{ statusBadge(r.docstatus).label }}</span>
						</td>
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
		style="visibility: visible; width: 540px"
		:style="{ transform: detailOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">{{ t("Payment Entry") }}</h5>
			<button
				type="button"
				class="btn-close"
				:disabled="detailActionRunning"
				@click="closeDetail"
				:aria-label='t("Close")'
			></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<div v-else-if="detail">
				<div v-if="detailActionError" class="alert alert-danger">{{ detailActionError }}</div>
				<div v-if="detailEditing" class="row g-3 mb-3">
					<div class="col-md-6">
						<label class="form-label">{{ t("Posting date") }}</label>
						<DateInput v-model="detailForm.posting_date" :disabled="detailActionRunning" />
					</div>
					<div class="col-md-6">
						<label class="form-label">{{ t("Mode of payment") }}</label>
						<input
							v-model="detailForm.mode_of_payment"
							type="text"
							class="form-control"
							:placeholder='t("Cash, Bank, …")'
							:disabled="detailActionRunning"
						/>
					</div>
					<div class="col-md-6">
						<label class="form-label">{{ t("Paid amount") }}</label>
						<MoneyInput
							v-model="detailForm.paid_amount"
							:currency="detail.paid_from_account_currency || currency"
							:language="user.language"
							:disabled="detailActionRunning"
						/>
					</div>
					<div class="col-md-6">
						<label class="form-label">{{ t("Received amount") }}</label>
						<MoneyInput
							v-model="detailForm.received_amount"
							:currency="detail.paid_to_account_currency || currency"
							:language="user.language"
							:disabled="detailActionRunning"
						/>
					</div>
					<div class="col-md-6">
						<label class="form-label">{{ t("Reference no.") }}</label>
						<input
							v-model="detailForm.reference_no"
							type="text"
							class="form-control"
							:placeholder='t("Cheque / transfer ref")'
							:disabled="detailActionRunning"
						/>
					</div>
					<div class="col-md-6">
						<label class="form-label">{{ t("Reference date") }}</label>
						<DateInput v-model="detailForm.reference_date" :disabled="detailActionRunning" />
					</div>
				</div>
				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Name") }}</div>
						<div class="datagrid-content font-monospace">{{ detail.name }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Posting date") }}</div>
						<div class="datagrid-content">{{ formatDateTime(detail.posting_date) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Type") }}</div>
						<div class="datagrid-content">
							<span class="badge" :class="typeBadge(detail.payment_type).cls">
								<i class="ti me-1" :class="typeBadge(detail.payment_type).icon"></i>{{ detail.payment_type }}
							</span>
						</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Status") }}</div>
						<div class="datagrid-content">
							<span class="badge" :class="statusBadge(detail.docstatus).cls">{{ statusBadge(detail.docstatus).label }}</span>
						</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Party") }}</div>
						<div class="datagrid-content">
							{{ detail.party_name || detail.party || "—" }}
							<div class="small text-secondary">{{ detail.party_type }}</div>
						</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Mode") }}</div>
						<div class="datagrid-content">{{ detail.mode_of_payment || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Paid from") }}</div>
						<div class="datagrid-content">{{ detail.paid_from || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Paid to") }}</div>
						<div class="datagrid-content">{{ detail.paid_to || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Paid amount") }}</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.paid_amount, detail.paid_from_account_currency || currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Received amount") }}</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.received_amount, detail.paid_to_account_currency || currency, user.language) }}</div>
					</div>
					<div v-if="detail.reference_no" class="datagrid-item">
						<div class="datagrid-title">{{ t("Reference") }}</div>
						<div class="datagrid-content">{{ detail.reference_no }} · {{ formatDateTime(detail.reference_date) }}</div>
					</div>
				</div>

				<div v-if="detail.references?.length">
					<h6 class="text-uppercase text-secondary small mb-2">{{ t("Allocated against") }}</h6>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th>{{ t("Document") }}</th>
									<th class="text-end">{{ t("Total") }}</th>
									<th class="text-end">{{ t("Outstanding") }}</th>
									<th class="text-end">{{ t("Allocated") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(r, i) in detail.references" :key="i">
									<td>
										<div class="fw-semibold">{{ r.reference_name }}</div>
										<div class="small text-secondary">{{ r.reference_doctype }}</div>
									</td>
									<td class="text-end font-monospace">{{ formatMoney(r.total_amount, refCurrency, user.language) }}</td>
									<td class="text-end font-monospace">{{ formatMoney(r.outstanding_amount, refCurrency, user.language) }}</td>
									<td class="text-end font-monospace">{{ formatMoney(r.allocated_amount, refCurrency, user.language) }}</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>
		<div v-if="detail && !detail.error" class="offcanvas-footer border-top p-3 d-flex gap-2">
			<button
				v-if="detail.docstatus === 0 && !detailEditing"
				type="button"
				class="btn btn-danger"
				:disabled="detailActionRunning"
				@click="deleteDetail"
			>
				<i class="ti ti-trash me-1"></i>{{ t("Delete") }}
			</button>
			<button
				v-if="detail.docstatus === 0 && !detailEditing"
				type="button"
				class="btn btn-outline-primary"
				:disabled="detailActionRunning"
				@click="startEditDetail"
			>
				<i class="ti ti-edit me-1"></i>{{ t("Edit") }}
			</button>
			<button
				v-if="detailEditing"
				type="button"
				class="btn btn-link link-secondary ms-auto"
				:disabled="detailActionRunning"
				@click="cancelEditDetail"
			>
				{{ t("Cancel") }}
			</button>
			<button
				v-if="detailEditing"
				type="button"
				class="btn btn-primary"
				:disabled="detailActionRunning"
				@click="saveDetail"
			>
				<span v-if="detailActionRunning" class="spinner-border spinner-border-sm me-2"></span>
				<i v-else class="ti ti-device-floppy me-1"></i>
				{{ t("Save") }}
			</button>
			<button
				v-if="detail.docstatus === 1"
				type="button"
				class="btn btn-outline-danger"
				:disabled="detailActionRunning"
				@click="cancelDetail"
			>
				<i class="ti ti-ban me-1"></i>{{ t("Cancel") }}
			</button>
			<button
				v-if="detail.docstatus === 0 && !detailEditing"
				type="button"
				class="btn btn-primary ms-auto"
				:disabled="detailActionRunning"
				@click="submitDetail"
			>
				<span v-if="detailActionRunning" class="spinner-border spinner-border-sm me-2"></span>
				<i v-else class="ti ti-check me-1"></i>
				{{ t("Submit") }}
			</button>
		</div>
	</div>

	<template v-if="createOpen">
		<div class="modal-backdrop fade show" @click="closeCreate"></div>
		<div class="modal fade show d-block" tabindex="-1" role="dialog">
			<div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable" role="document">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("New payment") }}</h5>
						<button type="button" class="btn-close" :aria-label='t("Close")' @click="closeCreate"></button>
					</div>
					<div class="modal-body">
						<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

						<div class="row g-3">
							<div class="col-md-4">
								<label class="form-label">{{ t("Posting date") }}</label>
								<DateInput v-model="form.posting_date" />
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Payment type") }}</label>
								<Select v-model="form.payment_type" :options="paymentTypeOptions" />
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Mode of payment") }}</label>
								<input
									v-model="form.mode_of_payment"
									type="text"
									class="form-control"
									:placeholder='t("Cash, Bank, …")'
								/>
							</div>

							<div class="col-12">
								<label class="form-label">
									{{ partyType }}
									<span
										v-if="partyDefaultsLoading"
										class="spinner-border spinner-border-sm ms-2"
									></span>
								</label>
								<Typeahead
									v-model="form.party"
									:search="searchParty"
									:display="partyName"
									:placeholder='t("Search {type} name…", { type: partyType.toLowerCase() })'
									open-on-focus
									:disabled="submitting"
									@pick="pickParty"
									@clear="clearParty"
								>
									<template #option="{ item }">
										<div class="fw-semibold">
											{{
												partyType === "Customer"
													? item.customer_name || item.name
													: item.supplier_name || item.name
											}}
										</div>
										<div class="small text-secondary">{{ item.name }}</div>
									</template>
								</Typeahead>
							</div>

							<div class="col-12">
								<label class="form-label">
									{{ form.payment_type === "Receive" ? t("Deposit to") : t("Pay from") }}
								</label>
								<Select
									v-model="form.bank_account"
									:disabled="submitting"
									:options="bankAccounts"
									value-key="name"
									:placeholder="t('— select account —')"
								>
									<template #option="{ option }">
										{{ option.account_name
										}}<template v-if="option.account_currency">
											({{ option.account_currency }})</template
										>
									</template>
									<template #selected="{ option }">
										{{ option.account_name
										}}<template v-if="option.account_currency">
											({{ option.account_currency }})</template
										>
									</template>
								</Select>
							</div>

							<div class="col-md-6">
								<label class="form-label">
									{{ form.payment_type === "Receive" ? t("Received amount") : t("Paid amount") }}
									<span v-if="partyAccountCurrency" class="text-secondary ms-1 small">{{
										partyAccountCurrency
									}}</span>
								</label>
								<MoneyInput
									v-model="form.amount"
									:currency="partyAccountCurrency || currency"
									:language="user.language"
									:placeholder='t("0.00")'
									:disabled="submitting"
								/>
							</div>

							<template v-if="showBankAmount">
								<div class="col-md-6">
									<label class="form-label">
										{{ t("Bank amount") }}
										<span class="text-secondary ms-1 small">{{ bankCurrency }}</span>
									</label>
									<MoneyInput
										v-model="form.bank_amount"
										:currency="bankCurrency"
										:language="user.language"
										:placeholder='t("0.00")'
										:disabled="submitting"
									/>
									<div
										v-if="form.amount && form.bank_amount"
										class="form-hint text-secondary"
									>
										{{ t("Rate:") }}
										{{ (Number(form.bank_amount) / Number(form.amount)).toFixed(4) }}
										{{ bankCurrency }}/{{ partyAccountCurrency }}
									</div>
								</div>
							</template>

							<div class="col-md-6">
								<label class="form-label">{{ t("Reference no.") }}</label>
								<input
									v-model="form.reference_no"
									type="text"
									class="form-control"
									:placeholder='t("Cheque / transfer ref")'
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Reference date") }}</label>
								<DateInput v-model="form.reference_date" />
							</div>
						</div>

						<template v-if="outstanding.length">
							<hr class="my-3" />
							<h6 class="text-uppercase text-secondary small mb-2">{{ t("Allocate against") }}</h6>
							<div class="table-responsive">
								<table class="table table-sm table-vcenter">
									<thead>
										<tr>
											<th>{{ t("Document") }}</th>
											<th>{{ t("Date") }}</th>
											<th class="text-end">{{ t("Outstanding") }}</th>
											<th class="text-end" style="width: 160px">{{ t("Allocated") }}</th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="(row, i) in outstanding" :key="i">
											<td>
												<div class="fw-semibold">{{ row.voucher_no }}</div>
												<div class="small text-secondary">{{ row.voucher_type }}</div>
											</td>
											<td class="text-secondary small">
												{{ formatDate(row.posting_date) }}
											</td>
											<td class="text-end font-monospace">
												{{
													formatMoney(
														row.outstanding_amount,
														partyAccountCurrency || currency,
														user.language
													)
												}}
											</td>
											<td class="text-end">
												<MoneyInput
													v-model="row.allocated"
													:currency="partyAccountCurrency || currency"
													:language="user.language"
													size="sm"
													:placeholder='t("0.00")'
													:disabled="submitting"
												/>
											</td>
										</tr>
									</tbody>
									<tfoot>
										<tr>
											<td colspan="2" class="text-secondary small">{{ t("Total allocated") }}</td>
											<td></td>
											<td class="text-end font-monospace fw-semibold">
												{{
													formatMoney(
														outstanding.reduce(
															(s, r) => s + (Number(r.allocated) || 0),
															0
														),
														partyAccountCurrency || currency,
														user.language
													)
												}}
											</td>
										</tr>
									</tfoot>
								</table>
							</div>
						</template>
					</div>
					<div class="modal-footer">
						<button
							type="button"
							class="btn btn-link link-secondary"
							@click="closeCreate"
							:disabled="submitting"
						>
							{{ t("Cancel") }}
						</button>
						<button
							type="button"
							class="btn btn-outline-primary ms-auto"
							@click="submitCreate(false)"
							:disabled="submitting"
						>
							<span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
							<i v-else class="ti ti-device-floppy me-1"></i>
							{{ t("Save as draft") }}
						</button>
						<button
							type="button"
							class="btn btn-primary"
							@click="submitCreate(true)"
							:disabled="submitting"
						>
							<span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
							<i v-else class="ti ti-check me-1"></i>
							{{ t("Save & Submit") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</template>
</template>
