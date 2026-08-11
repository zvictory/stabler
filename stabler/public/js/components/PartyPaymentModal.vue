<script setup>
/**
 * PartyPaymentModal — take a payment against a Customer or Supplier
 * (party-level, not invoice-level).
 *
 * On open it loads `party_payment_defaults` (outstanding invoices, party
 * account, cash/bank options) and `list_modes_of_payment`, then lets the
 * operator fill in an amount. On submit it calls `create_payment_entry` to
 * build a Draft and immediately `submit_payment_entry` to post it. If submit
 * throws, the Draft is rolled back server-side (money.py rollback guard) so
 * no orphaned Drafts are left behind.
 *
 * Props:  open, partyType ("Customer"|"Supplier"), party, company
 * Emits:  close, paid(entryName)
 */
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { formatMoney } from "../composables/money.js";
import { formatDate, todayIso } from "../composables/date.js";
import { t } from "../composables/i18n.js";
import { useToast } from "../composables/useToast.js";
import { useTelemetry } from "../composables/useTelemetry.js";
import MoneyInput from "./MoneyInput.vue";
import DateInput from "./DateInput.vue";
import Select from "./Select.vue";

const props = defineProps({
	open: { type: Boolean, required: true },
	partyType: { type: String, required: true }, // "Customer" | "Supplier"
	party: { type: String, required: true },
	partyName: { type: String, default: "" },
	company: { type: String, required: true },
	targetVoucher: { type: String, default: "" },
	accountCurrency: { type: String, default: "" },
});

const emit = defineEmits(["close", "paid"]);

const toast = useToast();
const { user } = storeToRefs(useSession());
const { trackOnce, FUNNEL } = useTelemetry();

const today = todayIso();

const loading = ref(false);
const submitting = ref(false);
const error = ref("");
const defaults = ref(null);
const modes = ref([]);

const form = ref({
	bank_account: "",
	mode_of_payment: "",
	paid_amount: 0,
	posting_date: today,
	reference_no: "",
	reference_date: "",
});

const isReceive = computed(() => props.partyType === "Customer");
const titleVerb = computed(() => (isReceive.value ? t("Receive payment") : t("Pay supplier")));
const ctaVerb = computed(() => (isReceive.value ? t("Receive") : t("Pay")));
const bankLabel = computed(() => (isReceive.value ? t("Deposit to") : t("Pay from")));

const modeOptions = computed(() => [
	{ value: "", label: "—" },
	...modes.value.map((m) => ({ value: m.name, label: m.name })),
]);

const currency = computed(() => defaults.value?.party_account_currency || "");
const outstandingInvoices = computed(() => {
	const invoices = defaults.value?.outstanding_invoices || [];
	if (!props.targetVoucher) return invoices;
	return invoices.filter((invoice) => invoice.voucher_no === props.targetVoucher);
});
const paymentOutstanding = computed(() =>
	outstandingInvoices.value.reduce(
		(sum, invoice) => sum + Number(invoice.outstanding_amount || 0),
		0
	)
);
const cashBankAccounts = computed(() => {
	const accounts = defaults.value?.cash_bank_accounts || [];
	if (!props.accountCurrency) return accounts;
	return accounts.filter((account) => account.account_currency === props.accountCurrency);
});

// Build the oldest-first allocation list for references[].
function buildRefs(invoices, amount) {
	let remaining = amount;
	const refs = [];
	for (const inv of invoices) {
		if (remaining <= 0) break;
		const alloc = Math.min(remaining, Number(inv.outstanding_amount));
		if (alloc <= 0) continue;
		remaining -= alloc;
		refs.push({
			reference_doctype: inv.voucher_type,
			reference_name: inv.voucher_no,
			total_amount: Number(inv.invoice_amount),
			outstanding_amount: Number(inv.outstanding_amount),
			allocated_amount: alloc,
		});
	}
	return refs;
}

const selectedBankAccount = computed(() => {
	if (!defaults.value || !form.value.bank_account) return null;
	return defaults.value.cash_bank_accounts.find((a) => a.name === form.value.bank_account);
});

const needsExchange = computed(() => {
	if (!defaults.value || !selectedBankAccount.value) return false;
	return defaults.value.party_account_currency !== selectedBankAccount.value.account_currency;
});

const exchangeLabel = computed(() => {
	if (!defaults.value || !selectedBankAccount.value) return "";
	const ccy1 = defaults.value.party_account_currency;
	const ccy2 = selectedBankAccount.value.account_currency;
	if (ccy1 === "USD" || ccy2 === "USD") return "1 USD";
	return `1 ${ccy1}`;
});

const exchangeRate = ref(1.0);
const cbuRate = ref(1.0);
const rateDate = ref("");
const bankAmount = ref(0);

const rateDeviation = computed(() => {
	if (!cbuRate.value || !exchangeRate.value) return 0;
	return Math.abs(exchangeRate.value - cbuRate.value) / cbuRate.value;
});
const hasWarning = computed(() => rateDeviation.value > 0.05);

watch(
	[() => form.value.bank_account, () => form.value.posting_date],
	async ([newBank, newDate]) => {
		if (!defaults.value || !newBank) return;
		const bankAcc = defaults.value.cash_bank_accounts.find((a) => a.name === newBank);
		if (!bankAcc) return;
		const bankCcy = bankAcc.account_currency;
		const partyCcy = defaults.value.party_account_currency;

		if (bankCcy === partyCcy) {
			exchangeRate.value = 1.0;
			cbuRate.value = 1.0;
			rateDate.value = "";
			return;
		}

		if (newBank === defaults.value.suggested_cash_bank_account && newDate === today) {
			exchangeRate.value = Number(defaults.value.effective_rate || 1.0);
			cbuRate.value = Number(defaults.value.effective_rate || 1.0);
			rateDate.value = defaults.value.rate_date || "";
			bankAmount.value =
				Math.round(Number(form.value.paid_amount || 0) * exchangeRate.value * 100) / 100;
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
			exchangeRate.value = Number(rate || 1.0);
			cbuRate.value = Number(rate || 1.0);
			rateDate.value = newDate || today;
			bankAmount.value =
				Math.round(Number(form.value.paid_amount || 0) * exchangeRate.value * 100) / 100;
		} catch (err) {
			exchangeRate.value = 1.0;
			cbuRate.value = 1.0;
			rateDate.value = "";
		}
	}
);

let isUpdatingPaidAmount = false;
let isUpdatingBankAmount = false;

watch(
	() => form.value.paid_amount,
	(val) => {
		if (!needsExchange.value || isUpdatingBankAmount) return;
		isUpdatingPaidAmount = true;
		bankAmount.value = Math.round(Number(val || 0) * exchangeRate.value * 100) / 100;
		isUpdatingPaidAmount = false;
	}
);

watch(
	() => bankAmount.value,
	(val) => {
		if (!needsExchange.value || isUpdatingPaidAmount) return;
		isUpdatingBankAmount = true;
		form.value.paid_amount = Math.round((Number(val || 0) / exchangeRate.value) * 100) / 100;
		isUpdatingBankAmount = false;
	}
);

watch(
	() => exchangeRate.value,
	(rate) => {
		if (!needsExchange.value) return;
		isUpdatingPaidAmount = true;
		bankAmount.value = Math.round(Number(form.value.paid_amount || 0) * rate * 100) / 100;
		isUpdatingPaidAmount = false;
	}
);

watch(
	() => props.open,
	async (now) => {
		if (!now) return;
		error.value = "";
		defaults.value = null;
		loading.value = true;
		try {
			const [d, m] = await Promise.all([
				call("stabler.api.money.party_payment_defaults", {
					company: props.company,
					party_type: props.partyType,
					party: props.party,
				}),
				call("stabler.api.money.list_modes_of_payment", { limit: 100 }),
			]);
			defaults.value = d;
			modes.value = m || [];
			const invoices = props.targetVoucher
				? (d.outstanding_invoices || []).filter(
						(invoice) => invoice.voucher_no === props.targetVoucher
					)
				: d.outstanding_invoices || [];
			const amount = invoices.reduce(
				(sum, invoice) => sum + Number(invoice.outstanding_amount || 0),
				0
			);
			const accounts = props.accountCurrency
				? (d.cash_bank_accounts || []).filter(
						(account) => account.account_currency === props.accountCurrency
					)
				: d.cash_bank_accounts || [];
			const suggested = accounts.some((account) => account.name === d.suggested_cash_bank_account)
				? d.suggested_cash_bank_account
				: accounts[0]?.name || "";
			form.value = {
				bank_account: suggested,
				mode_of_payment: "",
				paid_amount: amount,
				posting_date: today,
				reference_no: "",
				reference_date: "",
			};
			if (d.needs_exchange) {
				exchangeRate.value = Number(d.effective_rate || 1.0);
				cbuRate.value = Number(d.effective_rate || 1.0);
				rateDate.value = d.rate_date || "";
				bankAmount.value = Math.round(amount * exchangeRate.value * 100) / 100;
			} else {
				exchangeRate.value = 1.0;
				cbuRate.value = 1.0;
				rateDate.value = "";
				bankAmount.value = 0;
			}
		} catch (err) {
			error.value = err?.message || t("Failed to load payment defaults.");
		} finally {
			loading.value = false;
		}
	}
);

function close() {
	if (submitting.value) return;
	emit("close");
}

async function submit() {
	error.value = "";
	if (!form.value.bank_account) {
		error.value = isReceive.value
			? t("Pick the account that will receive the funds.")
			: t("Pick the account funds will be paid from.");
		return;
	}
	const amount = Number(form.value.paid_amount || 0);
	if (!amount || amount <= 0) {
		error.value = t("Amount must be greater than zero.");
		return;
	}
	if (props.targetVoucher) {
		if (!outstandingInvoices.value.length) {
			error.value = t("The selected Purchase Invoice no longer has an outstanding balance.");
			return;
		}
		if (Math.abs(amount - paymentOutstanding.value) > 0.01) {
			error.value = t("Pay Remaining must use the selected Purchase Invoice's exact outstanding amount.");
			return;
		}
	}

	const partyAccount = defaults.value?.party_account || "";
	const paidFrom = isReceive.value ? partyAccount : form.value.bank_account;
	const paidTo = isReceive.value ? form.value.bank_account : partyAccount;

	const references = buildRefs(outstandingInvoices.value, amount);

	submitting.value = true;

	let payloadPaidAmount =
		isReceive.value || !needsExchange.value ? amount : Number(bankAmount.value || 0);
	// Supplier Pay with a currency conversion: paid_amount is the bank-currency
	// (cash) leg. If the live exchange UI never computed it (rate didn't load, or
	// the paying account was switched), derive it from amount × rate so we never
	// submit a zero — which the backend rejects with "Paid amount must be greater
	// than zero". The party-currency amount the user typed is kept as received.
	if (!isReceive.value && needsExchange.value && !(payloadPaidAmount > 0)) {
		payloadPaidAmount = Math.round(amount * Number(exchangeRate.value || 1) * 100) / 100;
	}
	const payloadReceivedAmount = isReceive.value ? Number(bankAmount.value || 0) : amount;
	if (!(payloadPaidAmount > 0)) {
		error.value = t(
			"Couldn't work out the cash amount to pay — check the exchange rate and the paying account."
		);
		submitting.value = false;
		return;
	}

	try {
		const created = await call("stabler.api.money.create_payment_entry", {
			company: props.company,
			posting_date: form.value.posting_date,
			payment_type: isReceive.value ? "Receive" : "Pay",
			party_type: props.partyType,
			party: props.party,
			paid_from: paidFrom,
			paid_to: paidTo,
			paid_amount: payloadPaidAmount,
			received_amount: needsExchange.value ? payloadReceivedAmount : undefined,
			exchange_rate: needsExchange.value ? Number(exchangeRate.value || 1.0) : undefined,
			mode_of_payment: form.value.mode_of_payment || undefined,
			reference_no: form.value.reference_no || undefined,
			reference_date: form.value.reference_date || undefined,
			references: references.length ? references : undefined,
			target_purchase_invoice: props.targetVoucher || undefined,
			submit: 1,
		});
		if (created.pending_approval) {
			toast.warning(t("Payment saved — pending approval before it posts."));
		}
		trackOnce(FUNNEL.FIRST_PAYMENT); // activation funnel — fires once per company
		emit("paid", created.name, !!created.pending_approval);
	} catch (err) {
		error.value = err?.message || t("Failed to record payment.");
	} finally {
		submitting.value = false;
	}
}
</script>

<template>
	<div v-if="open" class="modal-backdrop fade show" @click="close"></div>
	<div v-if="open" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="close">
		<div class="modal-dialog modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">
						{{ titleVerb }} · <span>{{ partyName || party }}</span>
					</h5>
					<button type="button" class="btn-close" :disabled="submitting" @click="close"></button>
				</div>
				<div class="modal-body">
					<div class="modal-status bg-primary"></div>
					<div v-if="loading" class="text-center py-4">
						<div class="spinner-border text-primary"></div>
					</div>
					<div v-else-if="error && !defaults" class="alert alert-danger m-0">{{ error }}</div>
					<div v-else-if="defaults">
						<div class="datagrid mb-3">
							<div class="datagrid-item">
								<div class="datagrid-title">{{ isReceive ? t("Customer") : t("Supplier") }}</div>
								<div class="datagrid-content">
									<span class="fw-medium">{{ partyName || party }}</span>
									<span v-if="partyName" class="text-secondary small font-monospace ms-1">{{
										party
									}}</span>
								</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Outstanding") }}</div>
								<div class="datagrid-content font-monospace text-red">
									{{ formatMoney(paymentOutstanding, currency, user.language) }}
								</div>
							</div>
						</div>

						<details v-if="outstandingInvoices.length" class="mb-3">
							<summary class="small text-secondary" style="cursor: pointer">
								{{ t("{n} outstanding invoice(s)", { n: outstandingInvoices.length }) }}
							</summary>
							<div class="table-responsive mt-2">
								<table class="table table-sm table-no-stripe small">
									<thead>
										<tr>
											<th>{{ t("Invoice") }}</th>
											<th>{{ t("Date") }}</th>
											<th class="text-end">{{ t("Outstanding") }}</th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="inv in outstandingInvoices" :key="inv.voucher_no">
											<td class="font-monospace">{{ inv.voucher_no }}</td>
											<td>{{ formatDate(inv.posting_date) }}</td>
											<td class="text-end font-monospace">
												{{ formatMoney(inv.outstanding_amount, currency, user.language) }}
											</td>
										</tr>
									</tbody>
								</table>
							</div>
						</details>

						<div v-if="error" class="alert alert-danger">{{ error }}</div>

						<div class="row g-3">
							<div class="col-md-7">
								<label class="form-label required">{{ bankLabel }}</label>
								<Select
									v-model="form.bank_account"
									:options="cashBankAccounts"
									value-key="name"
									:placeholder="t('— pick account —')"
									:disabled="submitting"
								>
									<template #option="{ option }">
										{{ option.account_name }} ({{ option.account_type }})
									</template>
									<template #selected="{ option }">
										{{ option.account_name }} ({{ option.account_type }})
									</template>
								</Select>
							</div>
							<div class="col-md-5">
								<label class="form-label">{{ t("Mode") }}</label>
								<Select
									v-model="form.mode_of_payment"
									:options="modeOptions"
									:disabled="submitting"
								/>
							</div>
							<div class="col-md-5">
								<label class="form-label required">{{ t("Amount") }}</label>
								<MoneyInput
									v-model="form.paid_amount"
									:currency="currency"
									:language="user.language"
									:disabled="submitting || Boolean(targetVoucher)"
								/>
							</div>
							<div class="col-md-3">
								<label class="form-label">{{ t("Date") }}</label>
								<DateInput v-model="form.posting_date" :disabled="submitting" />
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Reference #") }}</label>
								<input
									v-model="form.reference_no"
									type="text"
									class="form-control"
									:placeholder="t('cheque / txn id')"
									:disabled="submitting"
								/>
							</div>

							<div v-if="needsExchange" class="col-12 mt-2 pt-2 border-top">
								<div class="row g-2 align-items-center">
									<div class="col-sm-6">
										<label class="form-label required">
											{{ t("Exchange rate ({0})", [exchangeLabel]) }}
										</label>
										<MoneyInput v-model="exchangeRate" :disabled="submitting" size="sm" />
										<div v-if="rateDate" class="text-secondary small mt-1">
											{{ t("CBU rate: {rate} ({date})", { rate: cbuRate, date: rateDate }) }}
										</div>
									</div>
									<div class="col-sm-6">
										<label class="form-label required">
											{{ t("Amount in {0}", [selectedBankAccount.account_currency]) }}
										</label>
										<MoneyInput
											v-model="bankAmount"
											:currency="selectedBankAccount.account_currency"
											:language="user.language"
											:disabled="submitting"
											size="sm"
										/>
									</div>
									<div v-if="hasWarning" class="col-12 mt-1">
										<div class="alert alert-warning py-1 px-2 m-0 small">
											<i class="ti ti-alert-triangle me-1"></i>
											{{
												t("Entered rate deviates by {pct}% from CBU rate.", {
													pct: (rateDeviation * 100).toFixed(1),
												})
											}}
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button
						type="button"
						class="btn btn-link link-secondary"
						:disabled="submitting"
						@click="close"
					>
						{{ t("Cancel") }}
					</button>
					<button
						type="button"
						class="btn btn-primary ms-auto"
						:disabled="submitting || loading || !defaults"
						@click="submit"
					>
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ ctaVerb }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
