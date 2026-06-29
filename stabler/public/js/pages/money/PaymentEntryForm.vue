<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime, todayIso} from "../../composables/date.js";
import { readableRate, formatRate } from "../../composables/fx.js";
import { t } from "../../composables/i18n.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import Typeahead from "../../components/Typeahead.vue";
import Select from "../../components/Select.vue";
import RelatedDocuments from "../../components/RelatedDocuments.vue";
import FormPage from "../../components/form/FormPage.vue";
import { useDocumentForm } from "../../composables/useDocumentForm.js";

const session = useSession();
const router = useRouter();
const route = useRoute();
const { activeCompany, user } = storeToRefs(session);

const today = todayIso();

// Lookups / state
const partyName = ref("");
const partyAccount = ref("");
const partyAccountCurrency = ref("");
const partyDefaultsLoading = ref(false);
const outstanding = ref([]);
const bankAccounts = ref([]);

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const paymentTypeOptions = computed(() => [
	{ value: "Receive", label: t("Receive") },
	{ value: "Pay", label: t("Pay") },
]);

const partyType = computed(() => (form.value.payment_type === "Pay" ? "Supplier" : "Customer"));

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

const cbuRate = ref(1.0);
const rateDate = ref("");

const enteredRate = computed(() => {
	const amt = Number(form.value.amount || 0);
	const bankAmt = Number(form.value.bank_amount || 0);
	if (!amt || !bankAmt) return 0;
	return bankAmt / amt;
});

const rateDeviation = computed(() => {
	if (!cbuRate.value || !enteredRate.value) return 0;
	return Math.abs(enteredRate.value - cbuRate.value) / cbuRate.value;
});

// Readable "1 strong = N weak" quote (always the ≥1 direction, e.g. 1 USD = 12 034 сўм).
const enteredQuote = computed(() => readableRate(enteredRate.value, partyAccountCurrency.value, bankCurrency.value));
const cbuQuote = computed(() => readableRate(cbuRate.value, partyAccountCurrency.value, bankCurrency.value));
const hasWarning = computed(() => showBankAmount.value && rateDeviation.value > 0.05);

watch(
	[() => form.value.bank_account, () => form.value.posting_date, partyAccountCurrency],
	async ([newBank, newDate, partyCcy]) => {
		if (!newBank || !partyCcy) return;
		const bankAcc = bankAccounts.value.find((a) => a.name === newBank);
		if (!bankAcc) return;
		const bankCcy = bankAcc.account_currency;

		if (bankCcy === partyCcy) {
			cbuRate.value = 1.0;
			rateDate.value = "";
			return;
		}

		try {
			let foreign = partyCcy;
			let local = bankCcy;
			if (partyCcy === "UZS" || bankCcy === "UZS") {
				foreign = partyCcy !== "UZS" ? partyCcy : bankCcy;
				local = "UZS";
			}
			const rate = await call("stabler.api.money.get_exchange_rate_for_currencies", {
				from_currency: foreign,
				to_currency: local,
				posting_date: newDate || today,
			});
			cbuRate.value = Number(rate || 1.0);
			rateDate.value = newDate || today;
		} catch (err) {
			cbuRate.value = 1.0;
			rateDate.value = "";
		}
	}
);

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
		references: [],
	};
}

function fromDetail(d) {
	partyName.value = d.party_name || d.party || "";
	partyAccountCurrency.value = d.payment_type === "Receive" ? d.paid_from_account_currency : d.paid_to_account_currency;
	return {
		posting_date: d.posting_date || today,
		payment_type: d.payment_type || "Receive",
		party: d.party || "",
		bank_account: d.payment_type === "Receive" ? d.paid_to : d.paid_from,
		amount: d.payment_type === "Receive" ? Number(d.paid_amount || 0) : Number(d.received_amount || 0),
		bank_amount: d.payment_type === "Receive" ? Number(d.received_amount || 0) : Number(d.paid_amount || 0),
		mode_of_payment: d.mode_of_payment || "",
		reference_no: d.reference_no || "",
		reference_date: d.reference_date || "",
		references: (d.references || []).map((r) => ({
			voucher_type: r.reference_doctype,
			voucher_no: r.reference_name,
			invoice_amount: Number(r.total_amount || 0),
			outstanding_amount: Number(r.outstanding_amount || 0),
			allocated: Number(r.allocated_amount || 0),
		})),
	};
}

function toPayload(m) {
	const amt = Number(m.amount);
	const bankAmt = showBankAmount.value ? Number(m.bank_amount) || amt : amt;
	const isReceive = m.payment_type === "Receive";

	if (isCreate.value) {
		const refs = outstanding.value
			.filter((r) => r.allocated > 0)
			.map((r) => ({
				reference_doctype: r.voucher_type,
				reference_name: r.voucher_no,
				total_amount: r.invoice_amount,
				outstanding_amount: r.outstanding_amount,
				allocated_amount: r.allocated,
			}));

		return {
			company: activeCompany.value,
			posting_date: m.posting_date,
			payment_type: m.payment_type,
			party_type: partyType.value,
			party: m.party,
			paid_from: isReceive ? partyAccount.value : m.bank_account,
			paid_to: isReceive ? m.bank_account : partyAccount.value,
			paid_amount: isReceive ? amt : bankAmt,
			received_amount: isReceive ? bankAmt : amt,
			exchange_rate: showBankAmount.value ? Number(enteredRate.value || 1.0) : undefined,
			mode_of_payment: m.mode_of_payment || undefined,
			reference_no: m.reference_no || undefined,
			reference_date: m.reference_date || undefined,
			references: refs,
		};
	} else {
		return {
			posting_date: m.posting_date || null,
			mode_of_payment: m.mode_of_payment || null,
			reference_no: m.reference_no || null,
			reference_date: m.reference_date || null,
			paid_amount: isReceive ? amt : bankAmt,
			received_amount: isReceive ? bankAmt : amt,
		};
	}
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
	doctype: "Payment Entry",
	detailApi: "stabler.api.money.payment_entry_detail",
	createApi: "stabler.api.money.create_payment_entry",
	updateApi: "stabler.api.money.update_payment_entry",
	submitApi: "stabler.api.money.submit_payment_entry",
	cancelApi: "stabler.api.money.cancel_payment_entry",
	deleteApi: "stabler.api.money.delete_payment_entry",
	blankModel: blankForm,
	toPayload,
	fromDetail,
	backPath: "/money/payments",
});

const docName = computed(() => (route.params.name ? String(route.params.name) : null));

async function loadDoc() {
	if (!docName.value) return;
	await load(docName.value);
}

// Lookups and callbacks
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
	actionError.value = "";
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
		actionError.value = err?.message || t("Failed to load party defaults.");
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

watch(
	() => form.value.payment_type,
	() => {
		if (isCreate.value) {
			clearParty();
			form.value.amount = null;
			form.value.bank_amount = null;
		}
	}
);

watch(() => form.value.amount, distributeAmount);
watch(docName, loadDoc);

onMounted(async () => {
	try {
		bankAccounts.value = await call("stabler.api.money.list_cash_bank_accounts", {
			company: activeCompany.value,
		});
		if (bankAccounts.value.length && !form.value.bank_account) {
			form.value.bank_account = bankAccounts.value[0].name;
		}
	} catch {}

	// Branch on the route param (present on a hard load), not the composable's
	// isCreate (null-based, true until load() runs) — else direct URL/refresh of an
	// edit route renders a blank "New".
	if (docName.value) {
		await loadDoc();
	} else {
		form.value = blankForm();
	}
});

// Operations
async function submitCreate() {
	actionError.value = "";
	const f = form.value;
	if (!f.party) return (actionError.value = t("Party is required."));
	if (!f.bank_account) return (actionError.value = t("Bank/cash account is required."));
	if (isCreate.value && !partyAccount.value)
		return (actionError.value = t("Party account not resolved — re-select the party."));

	const amt = Number(f.amount);
	if (!Number.isFinite(amt) || amt <= 0)
		return (actionError.value = t("Amount must be greater than zero."));

	if (isCreate.value) {
		const totalAllocated = outstanding.value.reduce((s, r) => s + (Number(r.allocated) || 0), 0);
		if (totalAllocated > amt + 0.005) {
			return (actionError.value = t("Total allocated cannot exceed the payment amount."));
		}
	}

	await save();
}

async function submitDoc() {
	await submit();
}

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
</script>

<template>
	<FormPage
		:title="isCreate ? t('New payment') : t('Payment Entry')"
		:doc-name="docName"
		:status="status"
		:docstatus="docstatus"
		:loading="loading"
		:error="actionError"
		back-path="/money/payments"
	>
		<!-- Header fields -->
		<div class="row g-3 mb-3">
			<div class="col-md-4">
				<label class="form-label">{{ t("Posting date") }}</label>
				<DateInput v-if="editable" v-model="form.posting_date" />
				<div v-else class="form-control-plaintext py-1">{{ formatDate(form.posting_date) || "—" }}</div>
			</div>
			<div class="col-md-4">
				<label class="form-label">{{ t("Payment type") }}</label>
				<Select v-if="editable && isCreate" v-model="form.payment_type" :options="paymentTypeOptions" />
				<div v-else class="form-control-plaintext py-1">
					<span class="badge" :class="typeBadge(form.payment_type).cls">
						<i class="ti me-1" :class="typeBadge(form.payment_type).icon"></i>{{ form.payment_type }}
					</span>
				</div>
			</div>
			<div class="col-md-4">
				<label class="form-label">{{ t("Mode of payment") }}</label>
				<input v-if="editable" v-model="form.mode_of_payment" type="text" class="form-control" :placeholder='t("Cash, Bank, …")' />
				<div v-else class="form-control-plaintext py-1">{{ form.mode_of_payment || "—" }}</div>
			</div>

			<div class="col-12" v-if="isCreate">
				<label class="form-label">
					{{ partyType }}
					<span v-if="partyDefaultsLoading" class="spinner-border spinner-border-sm ms-2"></span>
				</label>
				<Typeahead
					v-if="editable"
					v-model="form.party"
					:search="searchParty"
					:display="partyName"
					:placeholder='t("Search {type} name…", { type: partyType.toLowerCase() })'
					open-on-focus
					@pick="pickParty"
					@clear="clearParty"
				>
					<template #option="{ item }">
						<div class="fw-semibold">
							{{ partyType === "Customer" ? item.customer_name || item.name : item.supplier_name || item.name }}
						</div>
						<div class="small text-secondary">{{ item.name }}</div>
					</template>
				</Typeahead>
				<div v-else class="form-control-plaintext fw-semibold py-1">
					{{ partyName }}
					<span class="text-secondary fw-normal font-monospace small">· {{ form.party }}</span>
				</div>
			</div>
			<div class="col-12" v-else>
				<label class="form-label">{{ t("Party") }}</label>
				<div class="form-control-plaintext fw-semibold py-1">
					{{ partyName }}
					<span class="text-secondary fw-normal font-monospace small">· {{ form.party }}</span>
				</div>
			</div>

			<div class="col-12" v-if="isCreate">
				<label class="form-label">
					{{ form.payment_type === "Receive" ? t("Deposit to") : t("Pay from") }}
				</label>
				<Select
					v-if="editable"
					v-model="form.bank_account"
					:options="bankAccounts"
					value-key="name"
					:placeholder="t('— select account —')"
				>
					<template #option="{ option }">
						{{ option.account_name }}<template v-if="option.account_currency"> ({{ option.account_currency }})</template>
					</template>
					<template #selected="{ option }">
						{{ option.account_name }}<template v-if="option.account_currency"> ({{ option.account_currency }})</template>
					</template>
				</Select>
				<div v-else class="form-control-plaintext font-monospace py-1">{{ form.bank_account || "—" }}</div>
			</div>
			<div class="col-12" v-else>
				<label class="form-label">
					{{ form.payment_type === "Receive" ? t("Deposit to") : t("Pay from") }}
				</label>
				<div class="form-control-plaintext font-monospace py-1">{{ form.bank_account || "—" }}</div>
			</div>

			<div class="col-md-6">
				<label class="form-label">
					{{ form.payment_type === "Receive" ? t("Received amount") : t("Paid amount") }}
					<span v-if="partyAccountCurrency" class="text-secondary ms-1 small">{{ partyAccountCurrency }}</span>
				</label>
				<MoneyInput
					v-if="editable"
					v-model="form.amount"
					:currency="partyAccountCurrency || currency"
					:language="user.language"
					:placeholder='t("0.00")'
				/>
				<div v-else class="form-control-plaintext font-monospace py-1">{{ formatMoney(form.amount, partyAccountCurrency || currency, user.language) }}</div>
			</div>

			<template v-if="showBankAmount || (!isCreate && form.bank_amount !== form.amount)">
				<div class="col-md-6">
					<label class="form-label">
						{{ t("Bank amount") }}
						<span class="text-secondary ms-1 small">{{ bankCurrency }}</span>
					</label>
					<MoneyInput
						v-if="editable && isCreate"
						v-model="form.bank_amount"
						:currency="bankCurrency"
						:language="user.language"
						:placeholder='t("0.00")'
					/>
					<div v-else class="form-control-plaintext font-monospace py-1">{{ formatMoney(form.bank_amount, bankCurrency, user.language) }}</div>
					<div v-if="editable && isCreate && form.amount && form.bank_amount && enteredQuote" class="form-hint text-secondary">
						1 {{ enteredQuote.strong }} = {{ formatRate(enteredQuote.value, user.language) }} {{ enteredQuote.weak }}
						<span v-if="rateDate && cbuQuote" class="ms-1">
							({{ t("CBU:") }} {{ formatRate(cbuQuote.value, user.language) }})
						</span>
					</div>
					<div v-if="hasWarning" class="alert alert-warning py-1 px-2 mt-1 small">
						<i class="ti ti-alert-triangle me-1"></i>
						{{ t("Entered rate deviates by {pct}% from CBU rate.", { pct: (rateDeviation * 100).toFixed(1) }) }}
					</div>
				</div>
			</template>

			<div class="col-md-6">
				<label class="form-label">{{ t("Reference no.") }}</label>
				<input v-if="editable" v-model="form.reference_no" type="text" class="form-control" :placeholder='t("Cheque / transfer ref")' />
				<div v-else class="form-control-plaintext py-1">{{ form.reference_no || "—" }}</div>
			</div>
			<div class="col-md-6">
				<label class="form-label">{{ t("Reference date") }}</label>
				<DateInput v-if="editable" v-model="form.reference_date" />
				<div v-else class="form-control-plaintext py-1">{{ formatDate(form.reference_date) || "—" }}</div>
			</div>
		</div>

		<!-- Outstanding or allocations -->
		<template v-if="isCreate && outstanding.length">
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
							<td class="text-secondary small">{{ formatDate(row.posting_date) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(row.outstanding_amount, partyAccountCurrency || currency, user.language) }}</td>
							<td class="text-end">
								<MoneyInput
									v-model="row.allocated"
									:currency="partyAccountCurrency || currency"
									:language="user.language"
									size="sm"
									:placeholder='t("0.00")'
								/>
							</td>
						</tr>
					</tbody>
					<tfoot>
						<tr>
							<td colspan="2" class="text-secondary small">{{ t("Total allocated") }}</td>
							<td></td>
							<td class="text-end font-monospace fw-semibold">
								{{ formatMoney(outstanding.reduce((s, r) => s + (Number(r.allocated) || 0), 0), partyAccountCurrency || currency, user.language) }}
							</td>
						</tr>
					</tfoot>
				</table>
			</div>
		</template>
		<template v-else-if="!isCreate && form.references?.length">
			<hr class="my-3" />
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
						<tr v-for="(r, i) in form.references" :key="i">
							<td>
								<div class="fw-semibold">{{ r.voucher_no }}</div>
								<div class="small text-secondary">{{ r.voucher_type }}</div>
							</td>
							<td class="text-end font-monospace">{{ formatMoney(r.invoice_amount, partyAccountCurrency || currency, user.language) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(r.outstanding_amount, partyAccountCurrency || currency, user.language) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(r.allocated, partyAccountCurrency || currency, user.language) }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</template>

		<RelatedDocuments v-if="!isCreate && form" doctype="Payment Entry" :name="docName" />

		<!-- Actions -->
		<template #actions>
			<template v-if="isCreate">
				<button type="button" class="btn btn-link link-secondary" :disabled="actionRunning" @click="router.push('/money/payments')">{{ t("Cancel") }}</button>
				<button type="button" class="btn btn-outline-primary ms-auto" :disabled="actionRunning" @click="submitCreate">
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Save as draft") }}
				</button>
			</template>
			<template v-else>
				<button
					v-if="can.save"
					type="button"
					class="btn btn-outline-primary"
					:disabled="actionRunning"
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
