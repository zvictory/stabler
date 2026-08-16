<script setup>
// AgreementPreviewDrawer — read-only preview of one Vehicle Agreement (stabler-l0m.3.9).
//
// Follows VoucherDrawer's contract (open / loading / detail + a `close` emit)
// rather than the inline-offcanvas markup older pages hand-roll, because the
// newer components in this codebase have moved that way.
//
// READ ONLY, and the badge in the header says so out loud. Every money movement
// happens on a full page — a drawer that could take a payment would let someone
// collect against the wrong agreement while skim-reading a list.
//
// It is fed from two places on purpose:
//   row    — the agreement_list row the drawer was opened from. It already
//            carries total / paid / outstanding / next_due / payment_state, so
//            the four summary figures need no round trip and cannot disagree
//            with the row the user just clicked.
//   detail — agreement_detail, fetched on open, for the one thing the list row
//            does not carry: the individual open schedule rows.
//
// Props:
//   open    — boolean, whether the drawer is visible
//   loading — boolean, fetching `detail`
//   row     — the agreement_list row, or null
//   detail  — the agreement_detail payload, null while loading, or { error: "…" }
//   canOpenAgreement — whether a full agreement page exists to navigate to
//
// Events:
//   close          — user dismissed the drawer
//   open-agreement — user asked for the full page
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { formatMoney } from "../composables/money.js";
import { formatDate } from "../composables/date.js";
import { t } from "../composables/i18n.js";
import StatusBadge from "./StatusBadge.vue";

const props = defineProps({
	open: { type: Boolean, default: false },
	loading: { type: Boolean, default: false },
	row: { type: Object, default: null },
	detail: { type: Object, default: null },
	canOpenAgreement: { type: Boolean, default: false },
});

const emit = defineEmits(["close", "open-agreement"]);

const session = useSession();
const { user } = storeToRefs(session);

const currency = computed(() => props.row?.currency || "");

// Only the rows that still owe money. A settled row is history, and the point of
// a preview is "what is left", not "what happened".
const openRows = computed(() => {
	const rows = props.detail?.schedule_rows;
	if (!Array.isArray(rows)) return [];
	return rows.filter((r) => Number(r.outstanding) > 0);
});
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
			<div>
				<h5 class="offcanvas-title font-monospace mb-1">{{ row?.name || t("Agreement") }}</h5>
				<span class="badge bg-secondary-lt">{{ t("Read only") }}</span>
			</div>
			<button type="button" class="btn-close" :aria-label='t("Close")' @click="emit('close')"></button>
		</div>

		<div class="offcanvas-body">
			<div v-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>

			<template v-else-if="row">
				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Total") }}</div>
						<div class="datagrid-content font-monospace">
							{{ formatMoney(row.total_contract_price, currency, user.language) }}
						</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Outstanding") }}</div>
						<div class="datagrid-content font-monospace">
							{{ formatMoney(row.outstanding, currency, user.language) }}
						</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Next due") }}</div>
						<div class="datagrid-content font-monospace">
							{{ row.next_due ? formatDate(row.next_due) : "—" }}
						</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Health") }}</div>
						<div class="datagrid-content">
							<StatusBadge doctype="Vehicle Finance Payment Health" :status="row.payment_state" />
						</div>
					</div>
				</div>

				<div class="subheader mb-2">{{ t("Open rows") }}</div>

				<div v-if="loading" class="placeholder-glow">
					<div v-for="i in 3" :key="i" class="mb-2">
						<span class="placeholder col-12 py-2 rounded d-block"></span>
					</div>
				</div>

				<table v-else-if="openRows.length" class="table table-sm table-vcenter">
					<thead>
						<tr>
							<th class="text-nowrap">{{ t("Seq") }}</th>
							<th class="text-nowrap">{{ t("Due") }}</th>
							<th></th>
							<th class="text-end text-nowrap">{{ t("Outstanding") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in openRows" :key="r.row_name">
							<td class="font-monospace text-secondary">{{ r.sequence }}</td>
							<td class="font-monospace text-nowrap">{{ formatDate(r.due_date) }}</td>
							<td>
								<StatusBadge doctype="Vehicle Finance Payment Health" :status="r.payment_health" />
							</td>
							<td class="text-end font-monospace">
								{{ formatMoney(r.outstanding, currency, user.language) }}
							</td>
						</tr>
					</tbody>
				</table>

				<p v-else class="text-secondary small mb-0">{{ t("Nothing left to pay on this agreement.") }}</p>
			</template>
		</div>

		<div class="offcanvas-footer border-top p-3 d-flex justify-content-end gap-2">
			<button type="button" class="btn btn-outline-secondary" @click="emit('close')">
				{{ t("Close") }}
			</button>
			<button
				v-if="canOpenAgreement"
				type="button"
				class="btn btn-primary"
				@click="emit('open-agreement')"
			>
				{{ t("Open agreement") }}
			</button>
		</div>
	</div>
</template>
