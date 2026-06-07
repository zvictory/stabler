<script setup>
// VoucherDrawer — in-place offcanvas detail for Journal Entry and Payment Entry.
//
// Used by AccountLedger to open a voucher without navigating away.
// Extracts the duplicated drawer markup from JournalEntries.vue / PaymentEntries.vue
// so this codebase has a single canonical drawer implementation.
//
// Props:
//   open    — boolean, whether the drawer is visible
//   loading — boolean, fetching the detail
//   detail  — the loaded detail object (from journal_entry_detail / payment_entry_detail)
//             OR null while loading, OR { error: "..." } on failure
//   currency — company default currency (fallback)
//
// Events:
//   close — user dismissed the drawer
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { formatMoney } from "../composables/money.js";
import { formatDateTime } from "../composables/date.js";
import { t } from "../composables/i18n.js";

const props = defineProps({
	open: { type: Boolean, default: false },
	loading: { type: Boolean, default: false },
	detail: { type: Object, default: null },
	currency: { type: String, default: "USD" },
});

const emit = defineEmits(["close"]);

const session = useSession();
const { user } = storeToRefs(session);

const isJE = computed(() => props.detail?.doctype === "Journal Entry" || props.detail?.accounts !== undefined);
const isPayment = computed(() => !isJE.value && props.detail?.payment_type !== undefined);

const title = computed(() => {
	if (!props.detail) return t("Transaction");
	if (isJE.value) return t("Journal Entry");
	if (isPayment.value) return t("Payment Entry");
	return t("Transaction");
});

// Ref currency for payment allocations (mirrors PaymentEntries.vue:refCurrency computed).
const refCurrency = computed(() => {
	const d = props.detail;
	if (!d) return props.currency;
	const c = d.payment_type === "Receive" ? d.paid_to_account_currency : d.paid_from_account_currency;
	return c || props.currency;
});

const statusBadge = (docstatus) => {
	if (docstatus === 0) return { cls: "bg-yellow-lt", label: t("Draft") };
	if (docstatus === 1) return { cls: "bg-green-lt", label: t("Submitted") };
	if (docstatus === 2) return { cls: "bg-red-lt", label: t("Cancelled") };
	return { cls: "bg-secondary-lt", label: String(docstatus) };
};

const typeBadge = (paymentType) => {
	if (paymentType === "Receive") return { cls: "bg-green-lt", icon: "ti-arrow-down-left" };
	if (paymentType === "Pay") return { cls: "bg-red-lt", icon: "ti-arrow-up-right" };
	return { cls: "bg-secondary-lt", icon: "ti-arrows-exchange" };
};
</script>

<template>
	<div v-if="open" class="offcanvas-backdrop fade show" @click="emit('close')"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: open }"
		tabindex="-1"
		style="visibility: visible; width: 540px"
		:style="{ transform: open ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">{{ title }}</h5>
			<button type="button" class="btn-close" :aria-label='t("Close")' @click="emit('close')"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="loading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>

			<!-- Journal Entry detail -->
			<div v-else-if="detail && isJE">
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
						<div class="datagrid-content">{{ detail.voucher_type || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Status") }}</div>
						<div class="datagrid-content">
							<span class="badge" :class="statusBadge(detail.docstatus).cls">
								{{ statusBadge(detail.docstatus).label }}
							</span>
						</div>
					</div>
					<div v-if="detail.cheque_no" class="datagrid-item">
						<div class="datagrid-title">{{ t("Cheque") }}</div>
						<div class="datagrid-content">{{ detail.cheque_no }} · {{ formatDateTime(detail.cheque_date) }}</div>
					</div>
					<div v-if="detail.user_remark" class="datagrid-item">
						<div class="datagrid-title">{{ t("Remark") }}</div>
						<div class="datagrid-content">{{ detail.user_remark }}</div>
					</div>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Postings") }}</h6>
				<div class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>{{ t("Account") }}</th>
								<th>{{ t("Party") }}</th>
								<th class="text-end">{{ t("Debit") }}</th>
								<th class="text-end">{{ t("Credit") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(a, i) in detail.accounts" :key="i">
								<td>{{ a.account }}</td>
								<td>{{ a.party || "—" }}</td>
								<td class="text-end font-monospace">
									{{ a.debit_in_account_currency
										? formatMoney(a.debit_in_account_currency, a.account_currency || detail.base_currency || currency, user.language)
										: "—" }}
								</td>
								<td class="text-end font-monospace">
									{{ a.credit_in_account_currency
										? formatMoney(a.credit_in_account_currency, a.account_currency || detail.base_currency || currency, user.language)
										: "—" }}
								</td>
							</tr>
						</tbody>
						<tfoot>
							<tr class="fw-bold">
								<td colspan="2">{{ t("Total") }} ({{ detail.base_currency || currency }})</td>
								<td class="text-end font-monospace">{{ formatMoney(detail.total_debit_base, detail.base_currency || currency, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(detail.total_credit_base, detail.base_currency || currency, user.language) }}</td>
							</tr>
						</tfoot>
					</table>
				</div>
			</div>

			<!-- Payment Entry detail -->
			<div v-else-if="detail && isPayment">
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
								<i class="ti me-1" :class="typeBadge(detail.payment_type).icon"></i>
								{{ detail.payment_type }}
							</span>
						</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Status") }}</div>
						<div class="datagrid-content">
							<span class="badge" :class="statusBadge(detail.docstatus).cls">
								{{ statusBadge(detail.docstatus).label }}
							</span>
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
	</div>
</template>
