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
import { t } from "../composables/i18n.js";
import MoneyInput from "./MoneyInput.vue";
import DateInput from "./DateInput.vue";
import Select from "./Select.vue";

const props = defineProps({
	open: { type: Boolean, required: true },
	invoiceType: { type: String, required: true }, // "Sales Invoice" | "Purchase Invoice"
	invoiceName: { type: String, default: "" },
	modified: { type: String, default: "" },
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

const modeOptions = computed(() => [
	{ value: "", label: "—" },
	...modes.value.map((m) => ({ value: m.name, label: m.name })),
]);

const isReceive = computed(() => props.invoiceType === "Sales Invoice");
const titleVerb = computed(() => (isReceive.value ? t("Receive payment") : t("Pay supplier")));
const ctaVerb = computed(() => (isReceive.value ? t("Receive") : t("Pay")));
const isAdvance = computed(() => defaults.value && !defaults.value.can_allocate_to_invoice);
const advanceNotice = computed(() =>
	isReceive.value
		? t("This draft invoice has no ledger balance yet. The payment will be submitted as a customer advance.")
		: t("This draft invoice has no ledger balance yet. The payment will be submitted as a supplier advance.")
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
	const outstanding = Number(defaults.value?.outstanding_amount || 0);
	if (amount > outstanding + 0.005) {
		error.value = t("Amount exceeds outstanding ({amount}).", { amount: formatMoney(outstanding, defaults.value?.currency, user.value.language) });
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
			modified: props.modified || undefined,
		});
		emit("paid", created?.name || "");
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
								<div class="datagrid-title">{{ isReceive ? t("Customer") : t("Supplier") }}</div>
								<div class="datagrid-content">{{ defaults.party_name || defaults.party }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ isAdvance ? t("Advance amount") : t("Outstanding") }}</div>
								<div class="datagrid-content font-monospace text-red">
									{{ formatMoney(defaults.outstanding_amount, defaults.currency, user.language) }}
								</div>
							</div>
						</div>

						<div v-if="isAdvance" class="alert alert-info py-2">
							{{ advanceNotice }}
						</div>

						<div v-if="error" class="alert alert-danger">{{ error }}</div>

						<div class="row g-3">
							<div class="col-md-7">
								<label class="form-label required">
									{{ isReceive ? t("Deposit to") : t("Pay from") }}
								</label>
								<Select
									v-model="form.bank_account"
									:options="defaults.cash_bank_accounts"
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
									:currency="defaults.currency"
									:language="user.language"
									:disabled="submitting"
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
							<div class="col-md-4 offset-md-8">
								<label class="form-label">{{ t("Reference date") }}</label>
								<DateInput v-model="form.reference_date" :disabled="submitting" />
							</div>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="close">
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
