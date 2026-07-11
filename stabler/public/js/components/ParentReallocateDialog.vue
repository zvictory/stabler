<script setup>
/**
 * ParentReallocateDialog — move a legacy unallocated advance that was booked
 * directly on a consolidation parent down to its children (plan §2 K2).
 *
 * The operator picks one submitted parent Payment Entry that still carries an
 * unallocated balance, then adds transfer rows (child + amount). On save the
 * backend posts ONE Journal Entry that debits the parent's receivable and
 * credits each chosen child — the source Payment Entry is left untouched so the
 * original audit trail stays intact.
 *
 * Restricted to Accounts Manager / System Manager (also enforced server-side).
 *
 * Props:  open, company, parent, parentName
 * Emits:  close, done(journalEntry)
 */
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { formatMoney } from "../composables/money.js";
import { formatDate } from "../composables/date.js";
import { t } from "../composables/i18n.js";
import { useToast } from "../composables/useToast.js";
import MoneyInput from "./MoneyInput.vue";
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
const payments = ref([]);
const children = ref([]);
const selectedPe = ref("");
const transfers = ref([{ child: "", amount: 0 }]);

const childOptions = computed(() => [
	{ value: "", label: "—" },
	...children.value.map((c) => ({ value: c.name, label: c.customer_name })),
]);

const currentPe = computed(() => payments.value.find((p) => p.name === selectedPe.value) || null);
const unallocated = computed(() => Number(currentPe.value?.unallocated_amount || 0));
const peCurrency = computed(() => currentPe.value?.currency || "");

const totalTransfer = computed(() =>
	transfers.value.reduce((s, r) => s + Number(r.amount || 0), 0)
);
const remaining = computed(() => unallocated.value - totalTransfer.value);
const overAllocated = computed(() => remaining.value < -0.01);

function addRow() {
	transfers.value.push({ child: "", amount: 0 });
}
function removeRow(i) {
	transfers.value.splice(i, 1);
	if (!transfers.value.length) addRow();
}

watch(
	() => props.open,
	async (now) => {
		if (!now) return;
		error.value = "";
		payments.value = [];
		children.value = [];
		selectedPe.value = "";
		transfers.value = [{ child: "", amount: 0 }];
		loading.value = true;
		try {
			const data = await call("stabler.api.sales.parent_unallocated_payments", {
				company: props.company,
				parent: props.parent,
			});
			payments.value = data.rows || [];
			children.value = data.children || [];
			if (payments.value.length) selectedPe.value = payments.value[0].name;
		} catch (err) {
			error.value = err?.message || t("Failed to load payments.");
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
	if (!selectedPe.value) {
		error.value = t("Pick a payment to reallocate.");
		return;
	}
	const rows = transfers.value
		.filter((r) => r.child && Number(r.amount || 0) > 0)
		.map((r) => ({ child: r.child, amount: Number(r.amount) }));
	if (!rows.length) {
		error.value = t("Enter at least one transfer amount.");
		return;
	}
	if (overAllocated.value) {
		error.value = t("Transfers exceed the payment's unallocated amount.");
		return;
	}
	submitting.value = true;
	try {
		const res = await call("stabler.api.sales.reallocate_parent_payment", {
			company: props.company,
			payment_entry: selectedPe.value,
			transfers: JSON.stringify(rows),
		});
		toast.success(t("Reallocated via {je}", { je: res.journal_entry }));
		emit("done", res.journal_entry);
	} catch (err) {
		error.value = err?.message || t("Failed to reallocate payment.");
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
						{{ t("Reallocate advance") }} · <span>{{ parentName || parent }}</span>
					</h5>
					<button type="button" class="btn-close" :disabled="submitting" @click="close"></button>
				</div>
				<div class="modal-body">
					<div class="modal-status bg-primary"></div>
					<div v-if="loading" class="text-center py-4">
						<div class="spinner-border text-primary"></div>
					</div>
					<div v-else-if="error && !payments.length" class="alert alert-danger m-0">{{ error }}</div>
					<div v-else-if="!payments.length" class="text-secondary text-center py-4">
						{{ t("No unallocated payments on this customer.") }}
					</div>
					<div v-else>
						<div class="mb-3">
							<label class="form-label required">{{ t("Payment") }}</label>
							<select v-model="selectedPe" class="form-select" :disabled="submitting">
								<option v-for="p in payments" :key="p.name" :value="p.name">
									{{ p.name }} · {{ formatDate(p.posting_date) }} ·
									{{ formatMoney(p.unallocated_amount, p.currency, user.language) }}
								</option>
							</select>
						</div>

						<div class="datagrid mb-3">
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Unallocated") }}</div>
								<div class="datagrid-content font-monospace">
									{{ formatMoney(unallocated, peCurrency, user.language) }}
								</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Remaining") }}</div>
								<div class="datagrid-content font-monospace" :class="overAllocated ? 'text-red' : ''">
									{{ formatMoney(remaining, peCurrency, user.language) }}
								</div>
							</div>
						</div>

						<div v-if="error" class="alert alert-danger">{{ error }}</div>

						<label class="form-label">{{ t("Transfers to locations") }}</label>
						<div v-for="(row, i) in transfers" :key="i" class="row g-2 align-items-center mb-2">
							<div class="col-6">
								<Select v-model="row.child" :options="childOptions" :disabled="submitting" />
							</div>
							<div class="col-5">
								<MoneyInput
									v-model="row.amount"
									:currency="peCurrency"
									:language="user.language"
									:disabled="submitting"
									size="sm"
								/>
							</div>
							<div class="col-1">
								<button
									type="button"
									class="btn btn-sm btn-ghost-secondary px-1"
									:disabled="submitting"
									@click="removeRow(i)"
								>
									<i class="ti ti-x"></i>
								</button>
							</div>
						</div>
						<button type="button" class="btn btn-sm btn-ghost-secondary" :disabled="submitting" @click="addRow">
							<i class="ti ti-plus me-1"></i>{{ t("Add location") }}
						</button>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="close">
						{{ t("Cancel") }}
					</button>
					<button
						type="button"
						class="btn btn-primary ms-auto"
						:disabled="submitting || loading || !payments.length || overAllocated"
						@click="submit"
					>
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Reallocate") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
