<script setup>
/**
 * ParentBulkPaymentDialog — take ONE bulk payment on a consolidation parent and
 * split it across the open Sales Invoices of its children (plan §2 K2).
 *
 * The operator can type a lump sum and hit "distribute oldest-first" to FIFO-fill
 * the per-invoice allocation grid, or edit each row by hand. On save the backend
 * groups the allocations by each invoice's real party (child customer) and creates
 * one submitted Payment Entry per child.
 *
 * Props:  open, company, parent, parentName
 * Emits:  close, done(created[])
 */
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { formatMoney } from "../composables/money.js";
import { formatDate, todayIso } from "../composables/date.js";
import { t } from "../composables/i18n.js";
import { useToast } from "../composables/useToast.js";
import MoneyInput from "./MoneyInput.vue";
import DateInput from "./DateInput.vue";
import Select from "./Select.vue";

const props = defineProps({
	open: { type: Boolean, required: true },
	company: { type: String, required: true },
	parent: { type: String, required: true },
	parentName: { type: String, default: "" },
});

const emit = defineEmits(["close", "done"]);

const toast = useToast();
const { user } = storeToRefs(useSession());

const loading = ref(false);
const submitting = ref(false);
const error = ref("");
const rows = ref([]); // each: { ...invoice, alloc }
const modes = ref([]);
const companyCurrency = ref("");
const lumpSum = ref(0);

const form = ref({
	mode_of_payment: "",
	payment_date: todayIso(),
	reference_no: "",
});

const modeOptions = computed(() => [
	{ value: "", label: "—" },
	...modes.value.map((m) => ({ value: m.name, label: m.name })),
]);

// Money totals only make sense within one currency; the legacy MSA chain is all
// UZS. We surface the dominant currency for the summary and show each row's own.
const summaryCurrency = computed(() => rows.value[0]?.currency || companyCurrency.value);

const totalAllocated = computed(() =>
	rows.value.reduce((s, r) => s + Number(r.alloc || 0), 0)
);

const totalOutstanding = computed(() =>
	rows.value.reduce((s, r) => s + Number(r.outstanding || 0), 0)
);

// Distinct child parties among rows with an allocation → number of Payment
// Entries the split will create.
const paymentEntryCount = computed(() => {
	const parties = new Set();
	for (const r of rows.value) if (Number(r.alloc || 0) > 0) parties.add(r.child);
	return parties.size;
});

const hasAllocation = computed(() => rows.value.some((r) => Number(r.alloc || 0) > 0));

function distributeFifo() {
	let remaining = Number(lumpSum.value || 0);
	for (const r of rows.value) {
		if (remaining <= 0) {
			r.alloc = 0;
			continue;
		}
		const take = Math.min(remaining, Number(r.outstanding || 0));
		r.alloc = Math.round(take * 100) / 100;
		remaining -= take;
	}
}

watch(
	() => props.open,
	async (now) => {
		if (!now) return;
		error.value = "";
		rows.value = [];
		lumpSum.value = 0;
		form.value = { mode_of_payment: "", payment_date: todayIso(), reference_no: "" };
		loading.value = true;
		try {
			const [data, m] = await Promise.all([
				call("stabler.api.sales.parent_open_invoices", {
					company: props.company,
					parent: props.parent,
				}),
				call("stabler.api.money.list_modes_of_payment", { limit: 100 }),
			]);
			companyCurrency.value = data.company_currency || "";
			rows.value = (data.rows || []).map((r) => ({ ...r, alloc: 0 }));
			modes.value = m || [];
		} catch (err) {
			error.value = err?.message || t("Failed to load open invoices.");
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
	if (!form.value.mode_of_payment) {
		error.value = t("Select a payment mode.");
		return;
	}
	const allocations = rows.value
		.filter((r) => Number(r.alloc || 0) > 0)
		.map((r) => ({ invoice: r.invoice, amount: Number(r.alloc) }));
	if (!allocations.length) {
		error.value = t("Enter at least one allocation amount.");
		return;
	}
	submitting.value = true;
	try {
		const res = await call("stabler.api.sales.create_parent_bulk_payment", {
			company: props.company,
			parent: props.parent,
			mode_of_payment: form.value.mode_of_payment,
			payment_date: form.value.payment_date,
			reference_no: form.value.reference_no || undefined,
			allocations: JSON.stringify(allocations),
		});
		const names = (res.created || []).map((c) => c.payment_entry).filter(Boolean);
		const pending = (res.created || []).some((c) => c.pending_approval);
		if (pending) {
			toast.warning(t("Payments saved — some are pending approval before they post."));
		} else {
			toast.success(t("Created {n} payment(s): {names}", { n: names.length, names: names.join(", ") }));
		}
		emit("done", res.created || []);
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
		<div class="modal-dialog modal-dialog-centered modal-lg" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">
						{{ t("Receive payment") }} · <span>{{ parentName || parent }}</span>
					</h5>
					<button type="button" class="btn-close" :disabled="submitting" @click="close"></button>
				</div>
				<div class="modal-body">
					<div class="modal-status bg-primary"></div>
					<div v-if="loading" class="text-center py-4">
						<div class="spinner-border text-primary"></div>
					</div>
					<div v-else-if="error && !rows.length" class="alert alert-danger m-0">{{ error }}</div>
					<div v-else>
						<!-- Auto-distribute row -->
						<div class="row g-2 align-items-end mb-3">
							<div class="col-md-4">
								<label class="form-label">{{ t("Amount") }}</label>
								<MoneyInput
									v-model="lumpSum"
									:currency="summaryCurrency"
									:language="user.language"
									:disabled="submitting"
								/>
							</div>
							<div class="col-md-4">
								<button
									type="button"
									class="btn btn-outline-secondary w-100"
									:disabled="submitting || !rows.length"
									@click="distributeFifo"
								>
									<i class="ti ti-arrows-split-2 me-1"></i>{{ t("Distribute oldest-first") }}
								</button>
							</div>
							<div class="col-md-2">
								<label class="form-label">{{ t("Mode") }}</label>
								<Select v-model="form.mode_of_payment" :options="modeOptions" :disabled="submitting" />
							</div>
							<div class="col-md-2">
								<label class="form-label">{{ t("Date") }}</label>
								<DateInput v-model="form.payment_date" :disabled="submitting" />
							</div>
						</div>

						<div v-if="error" class="alert alert-danger">{{ error }}</div>

						<div v-if="!rows.length" class="text-secondary text-center py-4">
							{{ t("No open invoices for this customer group.") }}
						</div>
						<div v-else class="table-responsive" style="max-height: 22rem; overflow-y: auto">
							<table class="table table-sm table-vcenter">
								<thead>
									<tr>
										<th>{{ t("Location") }}</th>
										<th>{{ t("Invoice") }}</th>
										<th>{{ t("Date") }}</th>
										<th class="text-end">{{ t("Outstanding") }}</th>
										<th style="width: 9rem">{{ t("Allocation") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="r in rows" :key="r.invoice">
										<td class="small">
											{{ r.child_name }}
											<span v-if="r.is_legacy" class="badge bg-yellow-lt text-yellow ms-1">{{ t("Legacy") }}</span>
										</td>
										<td class="font-monospace small">{{ r.invoice }}</td>
										<td class="small">
											{{ formatDate(r.posting_date) }}
											<span v-if="r.days_overdue > 0" class="text-red">· {{ t("{n}d", { n: r.days_overdue }) }}</span>
										</td>
										<td class="text-end font-monospace">{{ formatMoney(r.outstanding, r.currency, user.language) }}</td>
										<td>
											<MoneyInput
												v-model="r.alloc"
												:currency="r.currency"
												:language="user.language"
												:disabled="submitting"
												size="sm"
											/>
										</td>
									</tr>
								</tbody>
								<tfoot>
									<tr class="fw-bold">
										<td colspan="3" class="text-end">{{ t("Total") }}</td>
										<td class="text-end font-monospace">{{ formatMoney(totalOutstanding, summaryCurrency, user.language) }}</td>
										<td class="font-monospace">{{ formatMoney(totalAllocated, summaryCurrency, user.language) }}</td>
									</tr>
								</tfoot>
							</table>
						</div>

						<div class="row g-2 mt-1">
							<div class="col-md-6">
								<label class="form-label">{{ t("Reference #") }}</label>
								<input
									v-model="form.reference_no"
									type="text"
									class="form-control"
									:placeholder="t('cheque / txn id')"
									:disabled="submitting"
								/>
							</div>
							<div class="col-md-6 d-flex align-items-end">
								<div class="text-secondary small">
									{{ t("Will create {n} payment(s).", { n: paymentEntryCount }) }}
								</div>
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
						:disabled="submitting || loading || !hasAllocation"
						@click="submit"
					>
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Receive") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
