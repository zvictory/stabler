<script setup>
/**
 * The journal entry a remittance stage is about to write, shown before it writes it.
 *
 * Every screen this replaces asked a cashier to commit to a posting they could not
 * see. Payout had a two-row "Effect / Amount" table with no debit or credit column,
 * no total and no visible equality — the balance was *implied* by printing the same
 * figure twice. Refund and New Transfer had nothing at all.
 *
 * WHY THE BASE COLUMN IS THE ONE THAT CLOSES. A cross-currency entry does not
 * balance per currency and is not meant to: the sender's cash leg is in one
 * currency, the receiver's obligation in another. It balances in the company's base
 * currency, which is what `debit`/`credit` hold. So the account-currency columns are
 * what the cashier recognises, and the base columns are the only place the reader
 * can see the entry close. Both are shown, and the totals row carries only the base
 * pair, because a base total is the only total that means anything.
 *
 * The rows come from `remittance_queries.posting_preview`, which builds them with
 * the poster's own `build_legs`. This component therefore holds NO arithmetic — it
 * sums the base columns for the totals line and nothing else. Anything it computed
 * would be a second opinion about a journal entry, and the day it disagreed with the
 * ledger would be a day somebody counted cash against it.
 */
import { computed } from "vue";
import { t } from "../composables/i18n.js";
import { formatMoney } from "../composables/money.js";

const props = defineProps({
	rows: { type: Array, default: () => [] },
	baseCurrency: { type: String, default: "" },
	totalDebit: { type: Number, default: 0 },
	totalCredit: { type: Number, default: 0 },
	balanced: { type: Boolean, default: false },
	loading: { type: Boolean, default: false },
	error: { type: String, default: "" },
});

const hasRows = computed(() => props.rows.length > 0);

/** Blank rather than 0,00: a zero in a debit cell reads as a posted zero. */
function money(amount, currency) {
	return Number(amount) ? formatMoney(amount, currency) : "";
}
</script>

<template>
	<div>
		<div class="text-secondary small mb-1">{{ t("This will post") }}</div>

		<div v-if="error" class="alert alert-warning py-2 mb-2 small">{{ error }}</div>

		<div v-else-if="loading" class="placeholder-glow mb-2">
			<div class="placeholder col-12 mb-1"></div>
			<div class="placeholder col-9"></div>
		</div>

		<div v-else-if="hasRows" class="table-responsive mb-2">
			<table class="table table-sm table-no-stripe mb-0">
				<thead>
					<tr>
						<th>{{ t("Account") }}</th>
						<th class="text-end">{{ t("Debit") }}</th>
						<th class="text-end">{{ t("Credit") }}</th>
						<th class="text-end">{{ t("Debit ({currency})", { currency: baseCurrency }) }}</th>
						<th class="text-end">{{ t("Credit ({currency})", { currency: baseCurrency }) }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="(row, index) in rows" :key="`${row.account}-${index}`">
						<td class="small">
							<div>{{ row.account }}</div>
							<div class="text-secondary" style="font-size: 0.75rem">{{ row.currency }}</div>
						</td>
						<td class="text-end font-monospace small">
							{{ money(row.debit_in_account_currency, row.currency) }}
						</td>
						<td class="text-end font-monospace small">
							{{ money(row.credit_in_account_currency, row.currency) }}
						</td>
						<td class="text-end font-monospace small">{{ money(row.debit, baseCurrency) }}</td>
						<td class="text-end font-monospace small">{{ money(row.credit, baseCurrency) }}</td>
					</tr>
				</tbody>
				<tfoot>
					<tr class="fw-semibold">
						<td class="small">{{ t("Total") }}</td>
						<!-- Deliberately empty: per-currency columns do not add up across
						     currencies, and a column of mixed units with a total under it
						     would be a lie that looks like arithmetic. -->
						<td></td>
						<td></td>
						<td class="text-end font-monospace small">
							{{ formatMoney(totalDebit, baseCurrency) }}
						</td>
						<td class="text-end font-monospace small">
							{{ formatMoney(totalCredit, baseCurrency) }}
						</td>
					</tr>
				</tfoot>
			</table>
		</div>

		<div v-if="hasRows && !loading && !error" class="form-text mb-3">
			<span v-if="balanced" class="text-success">
				<i class="ti ti-check me-1"></i
				>{{ t("Debits equal credits in {currency}.", { currency: baseCurrency }) }}
			</span>
			<span v-else class="text-danger">
				<i class="ti ti-alert-triangle me-1"></i
				>{{ t("This entry does not balance. Do not hand over cash — report it.") }}
			</span>
			<div class="mt-1">
				{{
					t(
						"{currency} figures use the rate frozen when this transfer was registered, not today's — that is the rate the ledger holds.",
						{ currency: baseCurrency }
					)
				}}
			</div>
		</div>
	</div>
</template>
