<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, language } = storeToRefs(session);
const { confirm } = useConfirm();
const toast = useToast();

// ── Period selector ──────────────────────────────────────────────────────────
function currentPeriod() {
	const d = new Date();
	const yyyy = d.getFullYear();
	const mm = String(d.getMonth() + 1).padStart(2, "0");
	return `${yyyy}-${mm}`;
}

// Build a list of the last 12 months for the <select>.
function buildPeriodOptions() {
	const opts = [];
	const now = new Date();
	for (let i = 0; i < 12; i++) {
		const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
		const yyyy = d.getFullYear();
		const mm = String(d.getMonth() + 1).padStart(2, "0");
		opts.push({ value: `${yyyy}-${mm}`, label: `${yyyy}-${mm}` });
	}
	return opts;
}

const payrollPeriod = ref(currentPeriod());
const periodOptions = buildPeriodOptions();

// ── Readiness panel ──────────────────────────────────────────────────────────
const readinessLoading = ref(false);
const readinessError = ref("");
const readiness = ref(null); // { can_lock, blockers, summary_count }

async function loadReadiness() {
	if (!activeCompany.value || !payrollPeriod.value) return;
	readinessLoading.value = true;
	readinessError.value = "";
	readiness.value = null;
	try {
		readiness.value = await call("stabler.api.hr_payroll.period_readiness", {
			company: activeCompany.value,
			payroll_period: payrollPeriod.value,
		});
	} catch (e) {
		readinessError.value = e?.message || String(e);
	} finally {
		readinessLoading.value = false;
	}
}

// ── Summaries table ──────────────────────────────────────────────────────────
const summariesLoading = ref(false);
const summariesError = ref("");
const summaries = ref([]);

const lang = computed(() => language.value || "en");

const blockerCount = computed(() => readiness.value?.blockers?.length ?? 0);
const summaryCount = computed(() => readiness.value?.summary_count ?? summaries.value.length);

async function loadSummaries() {
	if (!activeCompany.value || !payrollPeriod.value) return;
	summariesLoading.value = true;
	summariesError.value = "";
	try {
		summaries.value = await call("stabler.api.hr_payroll.list_payroll_summaries", {
			company: activeCompany.value,
			payroll_period: payrollPeriod.value,
			limit: 500,
		});
	} catch (e) {
		summariesError.value = e?.message || String(e);
		summaries.value = [];
	} finally {
		summariesLoading.value = false;
	}
}

async function loadAll() {
	await Promise.all([loadReadiness(), loadSummaries()]);
}

// ── Lock period ──────────────────────────────────────────────────────────────
const locking = ref(false);

async function lockPeriod() {
	const ok = await confirm({
		title: t("Lock payroll period"),
		body: t("Lock {0}? No further changes will be allowed once locked.").replace(
			"{0}",
			payrollPeriod.value,
		),
		confirmLabel: t("Lock period"),
	});
	if (!ok) return;
	locking.value = true;
	try {
		await call("stabler.api.hr_payroll.lock_period", {
			company: activeCompany.value,
			payroll_period: payrollPeriod.value,
		});
		toast.success(t("Period locked."));
		await loadAll();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		locking.value = false;
	}
}

watch([activeCompany, payrollPeriod], loadAll);
onMounted(loadAll);
</script>

<template>
	<div class="d-flex flex-column gap-3">

		<!-- Period selector bar -->
		<div class="card">
			<div class="card-body py-2">
				<div class="row g-2 align-items-center">
					<div class="col-auto">
						<label class="form-label mb-0 me-2">{{ t("Payroll period") }}</label>
					</div>
					<div class="col-auto">
						<select
							v-model="payrollPeriod"
							class="form-select form-select-sm"
							style="min-width: 160px;"
						>
							<option v-for="opt in periodOptions" :key="opt.value" :value="opt.value">
								{{ opt.label }}
							</option>
						</select>
					</div>
					<div v-if="summaryCount || blockerCount" class="col-auto ms-auto">
						<span class="text-secondary small">
							<strong class="text-body font-monospace">{{ summaryCount }}</strong>
							{{ t("employees") }}
							<template v-if="blockerCount">
								·
								<strong class="text-danger font-monospace">{{ blockerCount }}</strong>
								{{ t("blocker(s)") }}
							</template>
						</span>
					</div>
				</div>
			</div>
		</div>

		<!-- Readiness panel -->
		<div class="card">
			<div class="card-header">
				<h3 class="card-title">{{ t("Period readiness") }}</h3>
			</div>

			<div v-if="readinessLoading" class="card-body text-center py-4">
				<div class="spinner-border text-primary spinner-border-sm me-2"></div>
				<span class="text-secondary">{{ t("Checking readiness…") }}</span>
			</div>

			<div v-else-if="readinessError" class="alert alert-danger m-3">{{ readinessError }}</div>

			<div v-else-if="readiness" class="card-body">
				<!-- Ready to lock -->
				<div v-if="readiness.can_lock" class="d-flex align-items-center gap-3">
					<div class="flex-grow-1">
						<div class="d-flex align-items-center gap-2">
							<span class="avatar avatar-sm bg-success-lt text-success">
								<i class="ti ti-circle-check"></i>
							</span>
							<div>
								<div class="fw-semibold text-success">{{ t("Ready to lock") }}</div>
								<div class="small text-secondary">
									{{ t("All {0} employee summaries are clean — no unresolved exceptions.").replace("{0}", String(summaryCount)) }}
								</div>
							</div>
						</div>
					</div>
					<button
						type="button"
						class="btn btn-primary"
						:disabled="locking"
						@click="lockPeriod"
					>
						<i class="ti ti-lock me-1"></i>{{ t("Lock period") }}
					</button>
				</div>

				<!-- Blockers -->
				<div v-else>
					<div class="d-flex align-items-center gap-2 mb-3">
						<span class="avatar avatar-sm bg-danger-lt text-danger">
							<i class="ti ti-alert-triangle"></i>
						</span>
						<div>
							<div class="fw-semibold text-danger">{{ t("Not ready to lock") }}</div>
							<div class="small text-secondary">
								{{ t("Resolve all blockers before locking the period.") }}
							</div>
						</div>
					</div>
					<div class="list-group list-group-flush">
						<div
							v-for="(blocker, idx) in readiness.blockers"
							:key="idx"
							class="list-group-item d-flex align-items-center gap-2 px-0"
						>
							<i class="ti ti-point-filled text-danger flex-shrink-0"></i>
							<span class="flex-grow-1">{{ blocker.message }}</span>
							<span
								v-if="blocker.count"
								class="badge bg-red-lt font-monospace"
							>{{ blocker.count }}</span>
						</div>
					</div>
					<div class="mt-3">
						<button
							type="button"
							class="btn btn-outline-secondary"
							disabled
							:title="t('Resolve all blockers first')"
						>
							<i class="ti ti-lock me-1"></i>{{ t("Lock period") }}
						</button>
					</div>
				</div>
			</div>

			<EmptyState
				v-else
				icon="ti-calendar-stats"
				tone="secondary"
				:title="t('No readiness data')"
				:subtitle="t('Select a period and company to check readiness.')"
			/>
		</div>

		<!-- Summaries table -->
		<div class="card">
			<div class="card-header">
				<h3 class="card-title">{{ t("Employee summaries") }}</h3>
			</div>

			<div v-if="summariesError" class="alert alert-danger m-3">{{ summariesError }}</div>

			<div class="table-responsive">
				<table class="table card-table table-vcenter">
					<thead>
						<tr>
							<th>{{ t("Employee") }}</th>
							<th class="text-center">{{ t("Present") }}</th>
							<th class="text-center">{{ t("Absent") }}</th>
							<th class="text-center">{{ t("Late") }}</th>
							<th class="text-end">{{ t("Late deduction") }}</th>
							<th class="text-center">{{ t("OT (min)") }}</th>
							<th class="text-center">{{ t("Exceptions") }}</th>
							<th>{{ t("Status") }}</th>
							<th>{{ t("Locked at") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="summariesLoading" :rows="8" :cols="9" />
					<tbody v-else>
						<tr v-for="r in summaries" :key="r.name">
							<td>
								<div class="fw-medium">{{ r.employee_name }}</div>
								<div class="small text-secondary font-monospace">{{ r.name }}</div>
							</td>
							<td class="text-center font-monospace">{{ r.present_days ?? "—" }}</td>
							<td class="text-center font-monospace">
								<span :class="r.absent_days ? 'text-danger' : ''">
									{{ r.absent_days ?? "—" }}
								</span>
							</td>
							<td class="text-center font-monospace">
								<span :class="r.late_count ? 'text-warning' : ''">
									{{ r.late_count ?? "—" }}
								</span>
							</td>
							<td class="text-end font-monospace">
								{{ r.late_deduction_amount
									? formatMoney(r.late_deduction_amount, "UZS", lang)
									: "—" }}
							</td>
							<td class="text-center font-monospace">
								{{ r.overtime_minutes != null ? r.overtime_minutes : "—" }}
							</td>
							<td class="text-center">
								<span
									v-if="r.unresolved_exceptions_count"
									class="badge bg-red-lt font-monospace"
								>{{ r.unresolved_exceptions_count }}</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td>
								<span class="badge" :class="getStatusBadgeClass('Summary Status', r.status)">
									{{ t(r.status) }}
								</span>
							</td>
							<td class="font-monospace small text-secondary">
								{{ formatDate(r.locked_at) }}
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<EmptyState
				v-if="!summariesLoading && summaries.length === 0"
				icon="ti-report-analytics"
				tone="secondary"
				:title="t('No summaries')"
				:subtitle="t('No payroll summaries found for this period.')"
			/>
		</div>

	</div>
</template>
