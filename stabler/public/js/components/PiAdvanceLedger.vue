<script setup>
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { formatDate } from "../composables/date.js";
import { formatMoney } from "../composables/money.js";
import { t } from "../composables/i18n.js";

const props = defineProps({
	ledger: { type: Object, required: true },
});

const { user } = storeToRefs(useSession());
const expanded = ref(false);
const rows = computed(() => props.ledger?.rows || []);
const visibleRows = computed(() => {
	if (expanded.value || rows.value.length <= 5) return rows.value;
	return [...rows.value.slice(0, 4), rows.value[rows.value.length - 1]];
});

function money(value) {
	return formatMoney(value || 0, props.ledger.currency, user.value.language);
}

function statusClass(status) {
	if (status === "Posted") return "bg-success-lt text-success";
	if (status === "Planned") return "bg-warning-lt text-warning";
	if (status === "Migration Required") return "bg-danger-lt text-danger";
	return "bg-blue-lt text-blue";
}
</script>

<template>
	<div class="border-bottom">
		<div
			class="p-3 bg-light-subtle d-flex flex-wrap align-items-center justify-content-between gap-2"
		>
			<div>
				<div class="text-secondary small text-uppercase fw-semibold">
					{{ t("PI Advance Ledger") }}
				</div>
				<router-link
					:to="`/imports/proformas/${ledger.proforma_invoice}`"
					class="font-monospace fw-bold"
					>{{ ledger.supplier_pi_ref || ledger.proforma_invoice }}</router-link
				>
			</div>
			<div class="d-flex flex-wrap gap-4 text-end">
				<div>
					<div class="text-secondary small">{{ t("PI Total Cost") }}</div>
					<div class="font-monospace fw-bold">{{ money(ledger.summary.pi_total_cost) }}</div>
				</div>
				<div>
					<div class="text-secondary small">{{ t("Official Docs Total") }}</div>
					<div class="font-monospace fw-bold">{{ money(ledger.docs_total) }}</div>
				</div>
				<div>
					<div class="text-secondary small">{{ t("Cash Difference") }}</div>
					<div class="font-monospace fw-bold">{{ money(ledger.cash_difference) }}</div>
				</div>
				<div>
					<div class="text-secondary small">{{ t("Advance Terms") }}</div>
					<div class="font-monospace fw-bold">{{ ledger.summary.advance_percentage }}%</div>
				</div>
				<div>
					<div class="text-secondary small">{{ t("Advance Paid") }}</div>
					<div class="font-monospace fw-bold text-success">
						{{ money(ledger.summary.advance_paid) }}
					</div>
				</div>
				<div>
					<div class="text-secondary small">{{ t("Advance Allocated") }}</div>
					<div class="font-monospace fw-bold text-orange">
						{{ money(ledger.summary.advance_allocated) }}
					</div>
				</div>
				<div>
					<div class="text-secondary small">{{ t("Advance Reserved") }}</div>
					<div class="font-monospace fw-bold text-warning">
						{{ money(ledger.summary.advance_reserved) }}
					</div>
				</div>
				<div>
					<div class="text-secondary small">{{ t("Free Advance Balance") }}</div>
					<div class="font-monospace fw-bold text-blue">
						{{ money(ledger.summary.advance_available) }}
					</div>
				</div>
				<div>
					<div class="text-secondary small">{{ t("Remaining PI Cost") }}</div>
					<div class="font-monospace fw-bold text-orange">
						{{ money(ledger.summary.remaining_pi_cost) }}
					</div>
				</div>
				<div>
					<div class="text-secondary small">{{ t("Total CI Value Created") }}</div>
					<div class="font-monospace fw-bold">{{ money(ledger.summary.total_ci_amount) }}</div>
				</div>
			</div>
		</div>

		<div class="table-responsive">
			<table class="table table-sm table-vcenter mb-0 text-nowrap">
				<thead>
					<tr>
						<th>{{ t("Date") }}</th>
						<th>{{ t("Entry") }}</th>
						<th>{{ t("Reference") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="text-end">{{ t("PI Total Cost") }}</th>
						<th class="text-end">{{ t("CI Amount") }}</th>
						<th class="text-end">{{ t("Advance In") }}</th>
						<th class="text-end">{{ t("Advance Allocated") }}</th>
						<th class="text-end">{{ t("Advance Balance") }}</th>
						<th class="text-end">{{ t("Remaining PI Cost") }}</th>
						<th class="text-end">{{ t("CI Outstanding") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="row in visibleRows" :key="`${row.entry_type}-${row.reference}`">
						<td>{{ formatDate(row.posting_date) }}</td>
						<td class="fw-semibold">{{ t(row.entry_type) }}</td>
						<td class="font-monospace">{{ row.reference || "—" }}</td>
						<td>
							<span class="badge" :class="statusClass(row.status)">{{ t(row.status) }}</span>
						</td>
						<td class="text-end font-monospace">{{ money(row.pi_total_cost) }}</td>
						<td class="text-end font-monospace">
							{{ row.ci_amount ? money(row.ci_amount) : "—" }}
						</td>
						<td class="text-end font-monospace text-success">
							{{ row.advance_in ? money(row.advance_in) : "—" }}
						</td>
						<td class="text-end font-monospace text-orange">
							{{ row.advance_out ? money(row.advance_out) : "—" }}
						</td>
						<td class="text-end font-monospace fw-bold">
							{{ money(row.running_advance_balance) }}
						</td>
						<td class="text-end font-monospace">{{ money(row.running_pi_cost) }}</td>
						<td class="text-end font-monospace">
							{{ row.ci_outstanding ? money(row.ci_outstanding) : "—" }}
						</td>
					</tr>
					<tr v-if="!rows.length">
						<td colspan="11" class="text-center text-secondary py-3">
							{{ t("No advance ledger movements yet.") }}
						</td>
					</tr>
				</tbody>
			</table>
		</div>
		<div v-if="rows.length > 5" class="p-2 text-center">
			<button type="button" class="btn btn-link btn-sm" @click="expanded = !expanded">
				{{ expanded ? t("Show fewer allocations") : t("Show all allocations") }}
			</button>
		</div>
	</div>
</template>
