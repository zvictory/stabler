<script setup>
// Agreements — the Vehicle Finance agreement list and its read-only preview
// drawer (stabler-l0m.3.9). Source: stabler.api.vehicle_finance.read.agreement_list.
//
// Two things on this page are not cosmetic and are covered by
// tests/vehicleFinanceAgreements.spec.js:
//
// 1. Totals are per currency and never summed. One agreement carries one
//    currency; adding a UZS balance to a USD one produces a number that is not
//    money. The cards are sorted by outstanding so the largest exposure is the
//    one read first — KpiCard promotes lines[0] to the hero value, so ordering
//    here decides which currency becomes the headline.
// 2. The chain badge. Per the ADR (docs/decisions/2026-08-16-restructure-closes-
//    and-reopens.md) a restructure closes the original agreement and opens a
//    successor, and the owner's vote was conditional on the chain position being
//    visible AT A GLANCE — otherwise you still have to hunt for the last closed
//    agreement to learn the history. It renders NOTHING for an agreement that
//    was never restructured: a badge on every row is a badge nobody reads.
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import KpiCard from "../../components/KpiCard.vue";
import StatusBadge from "../../components/StatusBadge.vue";
import AgreementPreviewDrawer from "../../components/AgreementPreviewDrawer.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();

const direction = ref("");
const currencyFilter = ref("");
const paymentStateFilter = ref("");
const search = ref("");

const loading = ref(false);
const error = ref("");
const listing = ref({ rows: [], totals_by_currency: {}, has_more: false });

const directionOptions = computed(() => [
	{ value: "", label: t("All directions") },
	{ value: "Acquisition", label: t("Acquisition") },
	{ value: "Disposition", label: t("Disposition") },
]);

const currencyOptions = computed(() => [
	{ value: "", label: t("All currencies") },
	{ value: "USD", label: t("USD") },
	{ value: "UZS", label: t("UZS") },
]);

// Mirrors the five states _agreement_schedule_state derives (read.py:103-110).
const paymentStateOptions = computed(() => [
	{ value: "", label: t("All payment states") },
	{ value: "Not Started", label: t("Not Started") },
	{ value: "Current", label: t("Current") },
	{ value: "Partial", label: t("Partial") },
	{ value: "Overdue", label: t("Overdue") },
	{ value: "Paid", label: t("Paid") },
]);

// Per-currency portfolio totals for the header. Sorted by outstanding, largest
// first: KpiCard renders lines[0] large, so whichever currency the API happened
// to serialise first would otherwise become the headline figure and a 400 USD
// exposure could outrank a 900,000,000 UZS one.
const agrTotals = computed(() => {
	const byCurrency = listing.value?.totals_by_currency || {};
	return Object.entries(byCurrency)
		.sort((a, b) => (b[1]?.outstanding || 0) - (a[1]?.outstanding || 0))
		.map(([currency, vals]) => ({
			currency,
			lines: [
				formatMoney(vals.outstanding, currency, user.value.language),
				`${t("Total")}: ${formatMoney(vals.total, currency, user.value.language)}`,
				`${t("Paid")}: ${formatMoney(vals.paid, currency, user.value.language)}`,
			],
		}));
});

/**
 * "3/3 · restructured twice", or "" for an agreement that was never restructured.
 *
 * The empty string is the whole point of the guard: a chain of one is the normal
 * case, and a badge that fires on every row stops carrying information.
 *
 * Once/twice are spelled out rather than run through the {n} form because those
 * are overwhelmingly the common counts and "restructured 1 times" is not a
 * sentence in any of the five languages this app ships.
 */
function chainLabel(row) {
	const length = Number(row?.chain_length) || 1;
	if (length <= 1) return "";
	const position = Number(row?.chain_position) || 1;
	const count = Number(row?.restructure_count) || length - 1;
	let phrase;
	if (count === 1) {
		phrase = t("restructured once");
	} else if (count === 2) {
		phrase = t("restructured twice");
	} else {
		phrase = t("restructured {n} times", { n: count });
	}
	return `${position}/${length} · ${phrase}`;
}

/**
 * Whether to render "Partial" as a SECOND badge beside the payment state.
 *
 * `payment_state` is derived exclusively and in order (Paid, else Overdue, else
 * Partial, else Current — read.py:103-110), so an overdue agreement that has
 * been partly paid reports "Overdue" and the fact that money already came in is
 * invisible. That fact changes how you talk to the customer, so it gets its own
 * badge — but only when the primary badge is not already saying "Partial",
 * because the same word twice in one cell reads as a rendering bug.
 */
function showsPartial(row) {
	if (row?.payment_state === "Partial") return false;
	return Number(row?.paid) > 0 && Number(row?.outstanding) > 0;
}

let loadRequestId = 0;

async function load() {
	if (!activeCompany.value) return;
	const reqId = ++loadRequestId;
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.vehicle_finance.read.agreement_list", {
			company: activeCompany.value,
			direction: direction.value || undefined,
			currency: currencyFilter.value || undefined,
			payment_state: paymentStateFilter.value || undefined,
			search: search.value || undefined,
			limit: 50,
			start: 0,
		});
		if (reqId !== loadRequestId) return;
		listing.value = {
			rows: res?.rows || [],
			totals_by_currency: res?.totals_by_currency || {},
			has_more: Boolean(res?.has_more),
		};
	} catch (err) {
		if (reqId !== loadRequestId) return;
		error.value = err?.message || t("Failed to load agreements.");
	} finally {
		if (reqId === loadRequestId) {
			loading.value = false;
		}
	}
}

// Auto-apply: filter changes reload immediately, no Apply button (10-frontend.md).
watch([direction, currencyFilter, paymentStateFilter], load);

// --- preview drawer -------------------------------------------------------------

// The full agreement page is slice stabler-l0m.3.10 and does not exist yet.
// Asking the router rather than hardcoding `false` means the two "open" actions
// light up on their own the day that route is registered, and until then this
// page cannot ship a link that goes nowhere.
const canOpenAgreement = computed(() => router.hasRoute("vf-agreement-detail"));

const drawerOpen = ref(false);
const previewRow = ref(null);
const previewDetail = ref(null);
const previewLoading = ref(false);
let previewRequestId = 0;

async function openPreview(row) {
	const reqId = ++previewRequestId;
	previewRow.value = row;
	previewDetail.value = null;
	previewLoading.value = true;
	drawerOpen.value = true;
	try {
		const res = await call("stabler.api.vehicle_finance.read.agreement_detail", {
			agreement: row.name,
		});
		if (reqId !== previewRequestId) return;
		previewDetail.value = res || null;
	} catch (err) {
		if (reqId !== previewRequestId) return;
		previewDetail.value = { error: err?.message || t("Failed to load agreement.") };
	} finally {
		if (reqId === previewRequestId) {
			previewLoading.value = false;
		}
	}
}

function closePreview() {
	previewRequestId += 1;
	drawerOpen.value = false;
	previewRow.value = null;
	previewDetail.value = null;
	previewLoading.value = false;
}

function openAgreement(row) {
	if (!canOpenAgreement.value || !row?.name) return;
	router.push({ name: "vf-agreement-detail", params: { name: row.name } });
}

onMounted(load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Agreement, vehicle, VIN, party…')"
			:count="listing.rows.length"
			@search="load"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2">
					<Select v-model="direction" size="sm" :options="directionOptions" style="width: 150px" />
					<Select v-model="currencyFilter" size="sm" :options="currencyOptions" style="width: 140px" />
					<Select v-model="paymentStateFilter" size="sm" :options="paymentStateOptions" style="width: 170px" />
				</div>
			</template>
		</ListToolbar>

		<div class="text-secondary small px-3 py-2 border-bottom bg-white">
			{{ t("Search covers agreement ID, vehicle, VIN and party.") }}
			{{ t("One currency per agreement — totals are listed per currency, never summed.") }}
		</div>

		<div v-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>

		<template v-else>
			<div v-if="agrTotals.length" class="p-3 border-bottom">
				<div class="row row-cards">
					<div v-for="bucket in agrTotals" :key="bucket.currency" class="col-sm-6 col-lg-3">
						<KpiCard :label="bucket.currency" :lines="bucket.lines" icon="ti-cash" tone="primary" />
					</div>
				</div>
			</div>

			<div class="table-responsive">
				<table class="table table-vcenter card-table table-hover">
					<thead>
						<tr>
							<th class="text-nowrap">№</th>
							<th>{{ t("Vehicle / VIN") }}</th>
							<th>{{ t("Party") }}</th>
							<th class="text-nowrap">{{ t("Direction") }}</th>
							<th class="text-nowrap">{{ t("Type") }}</th>
							<th>{{ t("Agreement") }}</th>
							<th class="text-nowrap">{{ t("Next due") }}</th>
							<th class="text-end">{{ t("Total") }}</th>
							<th class="text-end">{{ t("Paid") }}</th>
							<th class="text-end">{{ t("Outstanding") }}</th>
							<th class="text-nowrap">{{ t("Payment state") }}</th>
							<th>{{ t("Owner") }}</th>
							<th></th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="5" :cols="13" />
					<tbody v-else-if="listing.rows.length">
						<tr v-for="(r, idx) in listing.rows" :key="r.name">
							<td class="font-monospace text-secondary text-nowrap">{{ idx + 1 }}</td>
							<td>
								<div v-if="r.vehicle_unit" class="fw-semibold">{{ r.vehicle_unit }}</div>
								<div v-if="r.serial_no" class="small text-secondary font-monospace">{{ r.serial_no }}</div>
								<div v-if="!r.vehicle_unit && !r.serial_no">—</div>
							</td>
							<td>
								<div class="fw-semibold">{{ r.party_name || r.party || "—" }}</div>
							</td>
							<td class="text-nowrap">{{ r.direction ? t(r.direction) : "—" }}</td>
							<td class="text-nowrap">{{ r.settlement_mode ? t(r.settlement_mode) : "—" }}</td>
							<td>
								<div class="font-monospace">{{ r.name }}</div>
								<div class="d-flex align-items-center gap-1 mt-1">
									<StatusBadge doctype="Vehicle Agreement" :status="r.agreement_status" />
								</div>
								<div v-if="chainLabel(r)" class="small text-secondary font-monospace mt-1">
									{{ chainLabel(r) }}
								</div>
							</td>
							<td class="text-nowrap font-monospace">
								{{ r.next_due ? formatDate(r.next_due) : "—" }}
							</td>
							<td class="text-end font-monospace">
								{{ formatMoney(r.total_contract_price, r.currency, user.language) }}
							</td>
							<td class="text-end font-monospace">
								{{ formatMoney(r.paid, r.currency, user.language) }}
							</td>
							<td class="text-end font-monospace">
								{{ formatMoney(r.outstanding, r.currency, user.language) }}
							</td>
							<td class="text-nowrap">
								<div class="d-flex align-items-center gap-1">
									<StatusBadge doctype="Vehicle Finance Payment Health" :status="r.payment_state" />
									<span v-if="showsPartial(r)" class="badge bg-yellow-lt">{{ t("Partial") }}</span>
								</div>
							</td>
							<td>{{ r.owner_user || "—" }}</td>
							<td class="text-end">
								<div class="btn-list flex-nowrap justify-content-end">
									<button
										type="button"
										class="btn btn-sm btn-outline-secondary"
										@click.stop="openPreview(r)"
									>
										{{ t("Preview") }}
									</button>
									<button
										v-if="canOpenAgreement"
										type="button"
										class="btn btn-sm btn-outline-primary"
										@click.stop="openAgreement(r)"
									>
										{{ t("Open") }}
									</button>
								</div>
							</td>
						</tr>
					</tbody>
				</table>

				<EmptyState
					v-if="!loading && !listing.rows.length"
					icon="ti-file-text"
					accent-icon="ti-search"
					tone="primary"
					:title="t('No agreements match these filters')"
					:subtitle="t('Search covers agreement ID, vehicle, VIN and party.')"
				/>

				<div v-if="!loading && listing.has_more" class="px-3 py-2 text-secondary small border-top">
					{{ t("Showing the first {n} — narrow the search to see the rest.", { n: listing.rows.length }) }}
				</div>
			</div>
		</template>

		<AgreementPreviewDrawer
			:open="drawerOpen"
			:loading="previewLoading"
			:row="previewRow"
			:detail="previewDetail"
			:can-open-agreement="canOpenAgreement"
			@close="closePreview"
			@open-agreement="openAgreement(previewRow)"
		/>
	</div>
</template>
