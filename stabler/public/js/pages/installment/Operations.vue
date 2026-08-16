<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import DateInput from "../../components/DateInput.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import KpiCard from "../../components/KpiCard.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const direction = ref("");
const currencyFilter = ref("");
const search = ref("");
const activeView = ref("critical_overdue");

const VIEW_KEYS = ["critical_overdue", "due_today", "next_7_days", "monitoring"];

const viewMetadata = computed(() => ({
	critical_overdue: {
		title: t("Critical Overdue"),
		note: t("Past escalation threshold or broken promise"),
	},
	due_today: {
		title: t("Due Today"),
		note: t("Installments due today"),
	},
	next_7_days: {
		title: t("Next 7 Days"),
		note: t("Upcoming due within 7 days"),
	},
	monitoring: {
		title: t("Monitoring"),
		note: t("Open follow-up or pending promise"),
	},
}));

const reasonLabels = computed(() => ({
	"Overdue": t("Overdue"),
	"Due today": t("Due today"),
	"Due within 7 days": t("Due within 7 days"),
	"Promise due": t("Promise due"),
	"Promise broken": t("Promise broken"),
	// Monitoring rows carry no date event, so these two are the only thing that
	// explains their presence. Without them the Reason cell renders blank on the
	// rows that need it most.
	"Promise pending": t("Promise pending"),
	"Open follow-up": t("Open follow-up"),
}));

const agreementStatusLabels = computed(() => ({
	"Draft": t("Draft"),
	"Review": t("Review"),
	"Approved": t("Approved"),
	"Active": t("Active"),
	"Restructured": t("Restructured"),
	"Completed": t("Completed"),
	"Terminated": t("Terminated"),
}));

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

const loading = ref(false);
const error = ref("");
const summary = ref(null);
const queueCards = ref({
	critical_overdue: { count: 0, totals_by_currency: {} },
	due_today: { count: 0, totals_by_currency: {} },
	next_7_days: { count: 0, totals_by_currency: {} },
	monitoring: { count: 0, totals_by_currency: {} },
});
const activeQueue = ref({
	rows: [],
	count: 0,
	totals_by_currency: {},
	has_more: false,
});

// KpiCard renders lines[0] as the hero value and the rest as smaller rows, so the
// order is not cosmetic: whichever currency the payload happened to list first
// would otherwise become the headline overdue number. Sort by amount so the
// largest exposure is the one the operator reads.
const overdueOutstandingLines = computed(() => {
	const byCurrency = summary.value?.overdue_outstanding_by_currency || {};
	return Object.entries(byCurrency)
		.sort((a, b) => b[1] - a[1])
		.map(([curr, amt]) => formatMoney(amt, curr, user.value.language));
});

let loadRequestId = 0;

async function load() {
	if (!activeCompany.value) return;
	const reqId = ++loadRequestId;
	loading.value = true;
	error.value = "";

	const comp = activeCompany.value;
	const dir = direction.value || undefined;
	const curr = currencyFilter.value || undefined;

	try {
		const summaryPromise = call("stabler.api.vehicle_finance.read.operations_summary", {
			company: comp,
			direction: dir,
			currency: curr,
		});

		const queueCardPromises = VIEW_KEYS.map((v) =>
			call("stabler.api.vehicle_finance.work.work_queue", {
				company: comp,
				view: v,
				direction: dir,
				currency: curr,
				limit: 1,
			})
		);

		const activeQueuePromise = call("stabler.api.vehicle_finance.work.work_queue", {
			company: comp,
			view: activeView.value,
			direction: dir,
			currency: curr,
			search: search.value || undefined,
			limit: 50,
			start: 0,
		});

		const [summaryRes, ...rest] = await Promise.all([
			summaryPromise,
			...queueCardPromises,
			activeQueuePromise,
		]);

		if (reqId !== loadRequestId) return;

		summary.value = summaryRes || null;

		const cards = {};
		VIEW_KEYS.forEach((v, idx) => {
			const res = rest[idx];
			cards[v] = {
				count: res?.count || 0,
				totals_by_currency: res?.totals_by_currency || {},
			};
		});
		queueCards.value = cards;

		const activeRes = rest[rest.length - 1];
		activeQueue.value = {
			rows: activeRes?.rows || [],
			count: activeRes?.count || 0,
			totals_by_currency: activeRes?.totals_by_currency || {},
			has_more: Boolean(activeRes?.has_more),
		};
	} catch (err) {
		if (reqId !== loadRequestId) return;
		error.value = err?.message || t("Failed to load operations data.");
	} finally {
		if (reqId === loadRequestId) {
			loading.value = false;
		}
	}
}

// Promise modal state
const selectedRow = ref(null);
const showPromiseModal = ref(false);
const promiseAmount = ref(null);
const promiseDate = ref("");
const promiseNote = ref("");
const submittingPromise = ref(false);
const promiseError = ref("");

function openPromiseModal(r) {
	selectedRow.value = r;
	promiseAmount.value = typeof r.outstanding === "number" ? r.outstanding : Number(r.outstanding || 0);
	promiseDate.value = todayIso();
	promiseNote.value = "";
	promiseError.value = "";
	showPromiseModal.value = true;
}

async function submitPromise() {
	if (!selectedRow.value) return;
	submittingPromise.value = true;
	promiseError.value = "";
	try {
		await call("stabler.api.vehicle_finance.work.record_promise", {
			agreement: selectedRow.value.agreement,
			row_sequence: selectedRow.value.row_sequence,
			amount: promiseAmount.value,
			promise_date: promiseDate.value,
			note: promiseNote.value || undefined,
		});
		showPromiseModal.value = false;
		await load();
	} catch (err) {
		promiseError.value = err?.message || t("Failed to record promise.");
	} finally {
		submittingPromise.value = false;
	}
}

// Follow-up modal state
const showFollowupModal = ref(false);
const followupNote = ref("");
const submittingFollowup = ref(false);
const followupError = ref("");

function openFollowupModal(r) {
	selectedRow.value = r;
	followupNote.value = "";
	followupError.value = "";
	showFollowupModal.value = true;
}

async function submitFollowup() {
	if (!selectedRow.value) return;
	submittingFollowup.value = true;
	followupError.value = "";
	try {
		await call("stabler.api.vehicle_finance.work.log_followup", {
			agreement: selectedRow.value.agreement,
			payload: {
				schedule_row: selectedRow.value.schedule_row,
				row_sequence: selectedRow.value.row_sequence,
				note: followupNote.value,
			},
		});
		showFollowupModal.value = false;
		await load();
	} catch (err) {
		followupError.value = err?.message || t("Failed to log follow-up.");
	} finally {
		submittingFollowup.value = false;
	}
}

watch([direction, currencyFilter, activeView], load);
watch(activeCompany, load);

onMounted(load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Agreement, party, VIN…')"
			:count="activeQueue.count || 0"
			@search="load"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2">
					<Select v-model="direction" size="sm" :options="directionOptions" style="width: 150px" />
					<Select v-model="currencyFilter" size="sm" :options="currencyOptions" style="width: 140px" />
				</div>
			</template>
		</ListToolbar>

		<div class="text-secondary small px-3 py-2 border-bottom bg-white">
			{{ t("One currency per agreement — totals are listed per currency, never summed.") }}
		</div>

		<div v-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>

		<template v-else>
			<!-- Neutral loading placeholder for top regions when loading -->
			<div v-if="loading" class="p-3 border-bottom placeholder-glow">
				<div class="subheader mb-2"><span class="placeholder col-2"></span></div>
				<div class="row row-cards mb-3">
					<div v-for="i in 4" :key="i" class="col-sm-6 col-lg-3">
						<div class="card card-sm">
							<div class="card-body">
								<span class="placeholder col-6 py-2 rounded mb-2 d-block"></span>
								<span class="placeholder col-8 py-2 rounded d-block"></span>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- Top regions (scorecards, metrics, lifecycle, queues) rendered only when summary is loaded and not loading -->
			<template v-if="summary !== null && !loading">
				<!-- 1. Currency scorecards -->
				<div
					v-if="summary.totals_by_currency && Object.keys(summary.totals_by_currency).length"
					class="p-3 border-bottom"
				>
					<div class="subheader mb-2">{{ t("Currency Scorecards") }}</div>
					<div class="row row-cards">
						<div
							v-for="(val, curr) in summary.totals_by_currency"
							:key="curr"
							class="col-sm-6 col-lg-3"
						>
							<KpiCard
								:label="curr"
								:lines="[
									formatMoney(val.outstanding, curr, user.language),
									`${t('Contract price')}: ${formatMoney(val.total_contract_price, curr, user.language)}`,
								]"
								icon="ti-cash"
								tone="primary"
								:badges="[{ label: t('agreements'), value: val.agreements, tone: 'azure' }]"
							/>
						</div>
					</div>
				</div>

				<!-- 2. Metric cards -->
				<div class="p-3 border-bottom">
					<div class="row row-cards">
						<div class="col-sm-6 col-lg-4">
							<KpiCard
								:label="t('Total Agreements')"
								:value="summary.agreement_count || 0"
								icon="ti-file-text"
								tone="primary"
							/>
						</div>
						<div class="col-sm-6 col-lg-4">
							<KpiCard
								:label="t('Overdue Count')"
								:value="summary.overdue_count || 0"
								value-tone="danger"
								icon="ti-alert-triangle"
								tone="danger"
							/>
						</div>
						<div v-if="overdueOutstandingLines.length" class="col-sm-6 col-lg-4">
							<KpiCard
								:label="t('Overdue Outstanding')"
								:lines="overdueOutstandingLines"
								value-tone="danger"
								icon="ti-cash-off"
								tone="danger"
							/>
						</div>
					</div>
				</div>

				<!-- 3. Portfolio lifecycle strip -->
				<div
					v-if="summary.lifecycle && Object.keys(summary.lifecycle).length"
					class="p-3 border-bottom"
				>
					<div class="subheader mb-2">{{ t("Portfolio Lifecycle") }}</div>
					<div class="d-flex flex-wrap gap-2 align-items-center">
						<div
							v-for="(count, statusKey) in summary.lifecycle"
							:key="statusKey"
							class="badge p-2 d-flex align-items-center gap-2"
							:class="getStatusBadgeClass('Vehicle Agreement', statusKey)"
						>
							<span class="fw-semibold">{{ agreementStatusLabels[statusKey] || statusKey }}</span>
							<span class="badge bg-white text-body font-monospace">{{ count }}</span>
						</div>
					</div>
				</div>

				<!-- 4. Saved views / 5. The four queues -->
				<div class="p-3 border-bottom">
					<div class="subheader mb-2">{{ t("Work Queues") }}</div>
					<div class="row row-cards">
						<div v-for="vKey in VIEW_KEYS" :key="vKey" class="col-sm-6 col-lg-3">
							<div
								class="card card-sm cursor-pointer h-100"
								:class="{ 'border-primary bg-primary-lt': activeView === vKey }"
								style="cursor: pointer"
								@click="activeView = vKey"
							>
								<div class="card-body d-flex flex-column">
									<div class="d-flex align-items-center mb-1">
										<div class="fw-bold me-auto">{{ viewMetadata[vKey].title }}</div>
										<span
											class="badge font-monospace"
											:class="activeView === vKey ? 'bg-primary text-white' : 'bg-secondary-lt'"
										>
											{{ queueCards[vKey]?.count || 0 }}
										</span>
									</div>
									<div class="text-secondary small mb-2">{{ viewMetadata[vKey].note }}</div>
									<div
										v-if="queueCards[vKey]?.totals_by_currency && Object.keys(queueCards[vKey].totals_by_currency).length"
										class="mt-auto small"
									>
										<div
											v-for="(tot, curr) in queueCards[vKey].totals_by_currency"
											:key="curr"
											class="font-monospace text-body"
										>
											{{ formatMoney(tot, curr, user.language) }}
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</template>

			<!-- 6. The work table -->
			<div class="table-responsive">
				<table class="table table-vcenter card-table table-hover">
					<thead>
						<tr>
							<th class="text-nowrap">№</th>
							<th class="text-nowrap">{{ t("Direction") }}</th>
							<th>{{ t("Vehicle / VIN") }}</th>
							<th>{{ t("Party") }}</th>
							<th>{{ t("Agreement") }}</th>
							<th>{{ t("Reason") }}</th>
							<th class="text-end">{{ t("Outstanding") }}</th>
							<th class="text-nowrap">{{ t("Due") }}</th>
							<th>{{ t("Owner") }}</th>
							<th class="text-nowrap">{{ t("Last contact") }}</th>
							<th>{{ t("Next action") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="5" :cols="11" />
					<tbody v-else-if="activeQueue.rows && activeQueue.rows.length">
						<tr v-for="(r, idx) in activeQueue.rows" :key="r.agreement + '-' + r.row_sequence">
							<td class="font-monospace text-secondary text-nowrap">{{ idx + 1 }}</td>
							<td class="text-nowrap">{{ r.direction ? t(r.direction) : "—" }}</td>
							<td>
								<div v-if="r.vehicle_unit" class="fw-semibold">{{ r.vehicle_unit }}</div>
								<div v-if="r.vin" class="small text-secondary font-monospace">{{ r.vin }}</div>
								<div v-if="!r.vehicle_unit && !r.vin">—</div>
							</td>
							<td>
								<div class="fw-semibold">{{ r.party_name || r.party || "—" }}</div>
							</td>
							<td class="font-monospace">{{ r.agreement || "—" }}</td>
							<td>
								<span v-if="r.reason" class="badge bg-secondary-lt">{{ reasonLabels[r.reason] || r.reason }}</span>
								<span v-else>—</span>
							</td>
							<td class="text-end font-monospace">
								{{ formatMoney(r.outstanding, r.currency, user.language) }}
							</td>
							<td class="text-nowrap font-monospace">
								{{ formatDate(r.due_date) }}
							</td>
							<td>{{ r.owner || "—" }}</td>
							<td class="text-nowrap font-monospace">
								{{ formatDate(r.last_contact) }}
							</td>
							<td>
								<div class="d-flex align-items-center justify-content-between flex-wrap gap-1">
									<div>
										<div v-if="r.next_action" class="small">{{ r.next_action }}</div>
										<div v-if="r.next_action_date" class="small text-secondary font-monospace">
											{{ formatDate(r.next_action_date) }}
										</div>
										<div v-if="!r.next_action && !r.next_action_date">—</div>
									</div>
									<div v-if="r.actions && r.actions.length" class="btn-list flex-nowrap ms-auto">
										<button
											v-if="r.actions.includes('record_promise')"
											type="button"
											class="btn btn-sm btn-outline-primary"
											@click.stop="openPromiseModal(r)"
										>
											{{ t("Record promise") }}
										</button>
										<button
											v-if="r.actions.includes('log_followup')"
											type="button"
											class="btn btn-sm btn-outline-secondary"
											@click.stop="openFollowupModal(r)"
										>
											{{ t("Log follow-up") }}
										</button>
									</div>
								</div>
							</td>
						</tr>
					</tbody>
				</table>

				<EmptyState
					v-if="!loading && (!activeQueue.rows || !activeQueue.rows.length)"
					icon="ti-clipboard-check"
					accent-icon="ti-check"
					tone="primary"
					:title="t('Nothing in this view')"
					:subtitle="viewMetadata[activeView] ? viewMetadata[activeView].note : ''"
				>
					<template #actions>
						<button
							type="button"
							class="btn btn-primary btn-sm"
							@click="activeView = 'critical_overdue'"
						>
							{{ t("Back to all work") }}
						</button>
					</template>
				</EmptyState>

				<div v-if="!loading && activeQueue.has_more" class="px-3 py-2 text-secondary small border-top">
					{{ t("showing first {n} of {count}", { n: activeQueue.rows.length, count: activeQueue.count }) }}
				</div>
			</div>
		</template>

		<!-- Promise Modal -->
		<div
			v-if="showPromiseModal"
			class="modal modal-blur fade show d-block"
			tabindex="-1"
			style="background: rgba(0, 0, 0, 0.5)"
		>
			<div class="modal-dialog modal-dialog-centered" role="document">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("Record Promise") }}</h5>
						<button
							type="button"
							class="btn-close"
							:disabled="submittingPromise"
							@click="showPromiseModal = false"
						></button>
					</div>
					<div class="modal-body">
						<div v-if="promiseError" class="alert alert-danger mb-3">{{ promiseError }}</div>
						<div v-if="selectedRow" class="mb-3 p-2 bg-light rounded small">
							<div><strong>{{ t("Agreement") }}:</strong> {{ selectedRow.agreement }}</div>
							<div><strong>{{ t("Party") }}:</strong> {{ selectedRow.party_name || selectedRow.party || "—" }}</div>
							<div><strong>{{ t("Outstanding") }}:</strong> {{ formatMoney(selectedRow.outstanding, selectedRow.currency, user.language) }}</div>
						</div>
						<div class="mb-3">
							<label class="form-label required">{{ t("Promise Amount") }}</label>
							<MoneyInput
								v-model="promiseAmount"
								:currency="selectedRow?.currency"
								:language="user.language"
							/>
						</div>
						<div class="mb-3">
							<label class="form-label required">{{ t("Promise Date") }}</label>
							<DateInput v-model="promiseDate" />
						</div>
						<div class="mb-3">
							<label class="form-label">{{ t("Note") }}</label>
							<textarea
								v-model="promiseNote"
								class="form-control"
								rows="3"
								:placeholder="t('Add optional note…')"
							></textarea>
						</div>
					</div>
					<div class="modal-footer">
						<button
							type="button"
							class="btn btn-link link-secondary"
							:disabled="submittingPromise"
							@click="showPromiseModal = false"
						>
							{{ t("Cancel") }}
						</button>
						<button
							type="button"
							class="btn btn-primary ms-auto"
							:disabled="submittingPromise"
							@click="submitPromise"
						>
							{{ t("Save Promise") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Follow-up Modal -->
		<div
			v-if="showFollowupModal"
			class="modal modal-blur fade show d-block"
			tabindex="-1"
			style="background: rgba(0, 0, 0, 0.5)"
		>
			<div class="modal-dialog modal-dialog-centered" role="document">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("Log Follow-up") }}</h5>
						<button
							type="button"
							class="btn-close"
							:disabled="submittingFollowup"
							@click="showFollowupModal = false"
						></button>
					</div>
					<div class="modal-body">
						<div v-if="followupError" class="alert alert-danger mb-3">{{ followupError }}</div>
						<div v-if="selectedRow" class="mb-3 p-2 bg-light rounded small">
							<div><strong>{{ t("Agreement") }}:</strong> {{ selectedRow.agreement }}</div>
							<div><strong>{{ t("Party") }}:</strong> {{ selectedRow.party_name || selectedRow.party || "—" }}</div>
						</div>
						<div class="mb-3">
							<label class="form-label required">{{ t("Note") }}</label>
							<textarea
								v-model="followupNote"
								class="form-control"
								rows="3"
								:placeholder="t('Log outcome or next action note…')"
							></textarea>
						</div>
					</div>
					<div class="modal-footer">
						<button
							type="button"
							class="btn btn-link link-secondary"
							:disabled="submittingFollowup"
							@click="showFollowupModal = false"
						>
							{{ t("Cancel") }}
						</button>
						<button
							type="button"
							class="btn btn-primary ms-auto"
							:disabled="submittingFollowup"
							@click="submitFollowup"
						>
							{{ t("Save Follow-up") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
