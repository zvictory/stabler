<script setup>
/**
 * PaymentModal — shared "receive / pay" against a Sales or Purchase Invoice.
 *
 * Open it by setting `open` to true with a target invoice identity. The
 * component fetches payment_defaults_for_invoice to learn party, bank
 * account options, outstanding amount, and currency, then submits a
 * Payment Entry via create_payment_for_invoice (submit=1 in the same call).
 *
 * Emits `paid` with the created Payment Entry name on success and `close`
 * whenever the user dismisses it. The parent should refresh the invoice
 * detail when `paid` fires so the new status/outstanding is reflected.
 */
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { formatMoney } from "../composables/money.js";
import MoneyInput from "./MoneyInput.vue";

const props = defineProps({
	open: { type: Boolean, required: true },
	invoiceType: { type: String, required: true }, // "Sales Invoice" | "Purchase Invoice"
	invoiceName: { type: String, default: "" },
});

const emit = defineEmits(["close", "paid"]);

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const today = new Date().toISOString().slice(0, 10);

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

const isReceive = computed(() => props.invoiceType === "Sales Invoice");
const titleVerb = computed(() => (isReceive.value ? "Receive payment" : "Pay supplier"));
const ctaVerb = computed(() => (isReceive.value ? "Receive" : "Pay"));

watch(
	() => props.open,
	async (now) => {
		if (!now) return;
		error.value = "";
		defaults.value = null;
		loading.value = true;
		try {
			const [d, m] = await Promise.all([
				call("stabler.api.money.payment_defaults_for_invoice", {
					company: activeCompany.value,
					invoice_type: props.invoiceType,
					invoice_name: props.invoiceName,
				}),
				call("stabler.api.money.list_modes_of_payment", { limit: 100 }),
			]);
			defaults.value = d;
			modes.value = m || [];
			form.value = {
				bank_account: d.suggested_cash_bank_account || "",
				mode_of_payment: "",
				paid_amount: Number(d.outstanding_amount || 0),
				posting_date: today,
				reference_no: "",
				reference_date: "",
			};
		} catch (err) {
			error.value = err?.message || "Failed to load payment defaults.";
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
			? "Pick the account that will receive the funds."
			: "Pick the account funds will be paid from.";
		return;
	}
	const amount = Number(form.value.paid_amount || 0);
	if (!amount || amount <= 0) {
		error.value = "Amount must be greater than zero.";
		return;
	}
	const outstanding = Number(defaults.value?.outstanding_amount || 0);
	if (amount > outstanding + 0.005) {
		error.value = `Amount exceeds outstanding (${formatMoney(outstanding, defaults.value?.currency, user.value.language)}).`;
		return;
	}
	submitting.value = true;
	try {
		const created = await call("stabler.api.money.create_payment_for_invoice", {
			company: activeCompany.value,
			invoice_type: props.invoiceType,
			invoice_name: props.invoiceName,
			bank_account: form.value.bank_account,
			paid_amount: amount,
			posting_date: form.value.posting_date || undefined,
			mode_of_payment: form.value.mode_of_payment || undefined,
			reference_no: form.value.reference_no || undefined,
			reference_date: form.value.reference_date || undefined,
			submit: 1,
		});
		emit("paid", created?.name || "");
	} catch (err) {
		error.value = err?.message || "Failed to record payment.";
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
						{{ titleVerb }} · <span class="font-monospace text-secondary">{{ invoiceName }}</span>
					</h5>
					<button type="button" class="btn-close" :disabled="submitting" @click="close"></button>
				</div>
				<div class="modal-body">
					<div v-if="loading" class="text-center py-4">
						<div class="spinner-border text-primary"></div>
					</div>
					<div v-else-if="error && !defaults" class="alert alert-danger m-0">{{ error }}</div>
					<div v-else-if="defaults">
						<div class="datagrid mb-3">
							<div class="datagrid-item">
								<div class="datagrid-title">{{ isReceive ? "Customer" : "Supplier" }}</div>
								<div class="datagrid-content">{{ defaults.party_name || defaults.party }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">Outstanding</div>
								<div class="datagrid-content font-monospace text-red">
									{{ formatMoney(defaults.outstanding_amount, defaults.currency, user.language) }}
								</div>
							</div>
						</div>

						<div v-if="error" class="alert alert-danger">{{ error }}</div>

						<div class="row g-3">
							<div class="col-md-7">
								<label class="form-label required">
									{{ isReceive ? "Deposit to" : "Pay from" }}
								</label>
								<select v-model="form.bank_account" class="form-select" :disabled="submitting">
									<option value="">— pick account —</option>
									<option
										v-for="a in defaults.cash_bank_accounts"
										:key="a.name"
										:value="a.name"
									>
										{{ a.account_name }} ({{ a.account_type }})
									</option>
								</select>
							</div>
							<div class="col-md-5">
								<label class="form-label">Mode</label>
								<select v-model="form.mode_of_payment" class="form-select" :disabled="submitting">
									<option value="">—</option>
									<option v-for="m in modes" :key="m.name" :value="m.name">
										{{ m.name }}
									</option>
								</select>
							</div>
							<div class="col-md-5">
								<label class="form-label required">Amount</label>
								<MoneyInput
									v-model="form.paid_amount"
									:currency="defaults.currency"
									:language="user.language"
									:disabled="submitting"
								/>
							</div>
							<div class="col-md-3">
								<label class="form-label">Date</label>
								<input
									v-model="form.posting_date"
									type="date"
									class="form-control"
									:disabled="submitting"
								/>
							</div>
							<div class="col-md-4">
								<label class="form-label">Reference #</label>
								<input
									v-model="form.reference_no"
									type="text"
									class="form-control"
									placeholder="cheque / txn id"
									:disabled="submitting"
								/>
							</div>
							<div class="col-md-4 offset-md-8">
								<label class="form-label">Reference date</label>
								<input
									v-model="form.reference_date"
									type="date"
									class="form-control"
									:disabled="submitting"
								/>
							</div>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="close">
						Cancel
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
