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
import { t } from "../composables/i18n.js";
import MoneyInput from "./MoneyInput.vue";
import DateInput from "./DateInput.vue";
import Select from "./Select.vue";

const props = defineProps({
	open: { type: Boolean, required: true },
	partyType: { type: String, required: true }, // "Customer" | "Supplier"
	party: { type: String, required: true },
	company: { type: String, required: true },
});

const emit = defineEmits(["close", "paid"]);

const { user } = storeToRefs(useSession());

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

const isReceive = computed(() => props.partyType === "Customer");
const titleVerb = computed(() => (isReceive.value ? t("Receive payment") : t("Pay supplier")));
const ctaVerb = computed(() => (isReceive.value ? t("Receive") : t("Pay")));
const bankLabel = computed(() => (isReceive.value ? t("Deposit to") : t("Pay from")));

const modeOptions = computed(() => [
	{ value: "", label: "—" },
	...modes.value.map((m) => ({ value: m.name, label: m.name })),
]);

const currency = computed(() => defaults.value?.party_account_currency || "");

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
			form.value = {
				bank_account: d.suggested_cash_bank_account || "",
				mode_of_payment: "",
				paid_amount: Number(d.total_outstanding || 0),
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

	const partyAccount = defaults.value?.party_account || "";
	// For Receive: party owes us → paid_from = AR account, paid_to = bank/cash.
	// For Pay:     we owe party → paid_from = bank/cash,   paid_to = AP account.
	const paidFrom = isReceive.value ? partyAccount : form.value.bank_account;
	const paidTo = isReceive.value ? form.value.bank_account : partyAccount;

	const references = buildRefs(defaults.value?.outstanding_invoices || [], amount);

	submitting.value = true;
	try {
		const created = await call("stabler.api.money.create_payment_entry", {
			company: props.company,
			posting_date: form.value.posting_date,
			payment_type: isReceive.value ? "Receive" : "Pay",
			party_type: props.partyType,
			party: props.party,
			paid_from: paidFrom,
			paid_to: paidTo,
			paid_amount: amount,
			mode_of_payment: form.value.mode_of_payment || undefined,
			reference_no: form.value.reference_no || undefined,
			reference_date: form.value.reference_date || undefined,
			references: references.length ? references : undefined,
		});
		// Submit the Draft immediately (server rolls back on failure — no orphan Drafts).
		await call("stabler.api.money.submit_payment_entry", { name: created.name });
		emit("paid", created.name);
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
						{{ titleVerb }} · <span class="text-secondary">{{ party }}</span>
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
								<div class="datagrid-content">{{ party }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Outstanding") }}</div>
								<div class="datagrid-content font-monospace text-red">
									{{ formatMoney(defaults.total_outstanding, currency, user.language) }}
								</div>
							</div>
						</div>

						<!-- Outstanding invoices summary (collapsed list) -->
						<details v-if="defaults.outstanding_invoices?.length" class="mb-3">
							<summary class="small text-secondary" style="cursor: pointer">
								{{ t("{n} outstanding invoice(s)", { n: defaults.outstanding_invoices.length }) }}
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
										<tr v-for="inv in defaults.outstanding_invoices" :key="inv.voucher_no">
											<td class="font-monospace">{{ inv.voucher_no }}</td>
											<td>{{ inv.posting_date }}</td>
											<td class="text-end font-monospace">{{ formatMoney(inv.outstanding_amount, currency, user.language) }}</td>
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
									:currency="currency"
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
