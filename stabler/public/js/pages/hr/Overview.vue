<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const loading = ref(false);
const ov = ref(null);

const currency = computed(() => session.currency);
const money = (v) => formatMoney(v, currency.value, user.value.language);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		ov.value = await call("stabler.api.hr_overview.hr_overview", { company: activeCompany.value });
	} catch {
		ov.value = null;
	} finally {
		loading.value = false;
	}
}
onMounted(load);
watch(activeCompany, load);

const att = computed(() => ov.value?.attendance || {});
const pay = computed(() => ov.value?.payroll || {});
const adv = computed(() => ov.value?.advances || {});
const wf = computed(() => ov.value?.workforce || {});
const canMoney = computed(() => !!ov.value?.can_see_money);

// Action queue — ordered by severity; each row routes to where it gets resolved.
const queue = computed(() => {
	const q = ov.value?.queue || {};
	return [
		{ key: "exc", label: t("Attendance exceptions"), hint: t("Unmatched events, missing punches"), value: q.open_exceptions || 0, icon: "ti-alert-triangle", sev: "danger", to: "/hr/exceptions-queue" },
		{ key: "cor", label: t("Corrections to approve"), hint: t("Some affect this month's pay"), value: q.pending_corrections || 0, icon: "ti-edit", sev: "warning", to: "/hr/corrections" },
		{ key: "base", label: t("Payroll blockers"), hint: t("Staff with base salary = 0"), value: q.base_salary_zero || 0, icon: "ti-cash", sev: "danger", to: "/hr/data-health" },
		{ key: "gap", label: t("Profile gaps"), hint: t("Unassigned dept / position"), value: q.profile_gaps || 0, icon: "ti-user-question", sev: "muted", to: "/hr/data-health" },
	];
});
const queueTotal = computed(() => queue.value.reduce((s, r) => s + (r.value || 0), 0));

const sevPill = (sev, v) => {
	if (!v) return "bg-secondary-lt";
	return { danger: "bg-red-lt", warning: "bg-yellow-lt", muted: "bg-secondary-lt" }[sev] || "bg-secondary-lt";
};
const sevText = (sev, v) => (!v ? "text-secondary" : { danger: "text-danger", warning: "text-warning", muted: "text-secondary" }[sev] || "");

const deltaLabel = computed(() => {
	const d = Number(att.value.present_pct_delta || 0);
	if (!d) return null;
	return { up: d > 0, text: `${d > 0 ? "+" : ""}${d} ${t("pts vs last week")}` };
});

const deptMax = computed(() => Math.max(1, ...(wf.value.by_dept || []).map((d) => d.n)));
const pctOf = (n) => (wf.value.headcount ? Math.round((Number(n || 0) * 100) / wf.value.headcount) : 0);
</script>

<template>
	<div v-if="loading" class="text-center py-5"><div class="spinner-border text-primary"></div></div>

	<template v-else-if="ov">
		<!-- Header -->
		<div class="d-flex flex-wrap align-items-baseline justify-content-between mb-3 gap-2">
			<div>
				<h2 class="m-0">{{ t("HR overview") }}</h2>
				<div class="text-secondary small">{{ wf.headcount }} {{ t("active staff") }} · {{ wf.joiners_this_month || 0 }} {{ t("joined this month") }}</div>
			</div>
			<span class="badge bg-blue-lt"><i class="ti ti-calendar-month me-1"></i>{{ t("Payroll") }} {{ ov.period }}</span>
		</div>

		<!-- Needs you today -->
		<div class="card mb-3">
			<div class="card-header py-2">
				<h3 class="card-title m-0"><i class="ti ti-inbox me-2"></i>{{ t("Needs you today") }}</h3>
				<span class="ms-auto text-secondary small">{{ queueTotal }} {{ t("items") }}</span>
			</div>
			<div class="list-group list-group-flush">
				<RouterLink v-for="r in queue" :key="r.key" :to="r.to" class="list-group-item list-group-item-action d-flex align-items-center gap-2">
					<i class="ti" :class="[r.icon, sevText(r.sev, r.value)]" style="font-size: 1.3rem"></i>
					<div class="flex-fill">
						<div class="fw-semibold">{{ r.label }}</div>
						<div class="text-secondary small">{{ r.hint }}</div>
					</div>
					<span class="badge" :class="sevPill(r.sev, r.value)">{{ r.value }}</span>
					<i class="ti ti-chevron-right text-secondary"></i>
				</RouterLink>
			</div>
		</div>

		<div class="row g-3 mb-3">
			<!-- Attendance today -->
			<div class="col-lg-6">
				<div class="card h-100">
					<div class="card-body">
						<div class="d-flex justify-content-between align-items-center">
							<span class="text-secondary small">{{ t("Attendance today") }}</span>
							<span v-if="deltaLabel" class="small" :class="deltaLabel.up ? 'text-success' : 'text-danger'">
								<i class="ti" :class="deltaLabel.up ? 'ti-trending-up' : 'ti-trending-down'"></i> {{ deltaLabel.text }}
							</span>
						</div>
						<div class="d-flex align-items-baseline gap-2 my-2">
							<span class="h1 m-0">{{ att.present_pct }}%</span>
							<span class="text-secondary small">{{ t("present") }} · {{ att.present }} / {{ wf.headcount }}</span>
						</div>
						<div class="progress mb-2" style="height: 8px">
							<div class="progress-bar bg-success" :style="{ width: att.present_pct + '%' }"></div>
							<div class="progress-bar bg-warning" :style="{ width: pctOf(att.late) + '%' }"></div>
							<div class="progress-bar bg-danger" :style="{ width: pctOf(att.absent) + '%' }"></div>
						</div>
						<div class="d-flex flex-wrap gap-2 align-items-center">
							<span class="badge bg-green-lt">K · {{ att.present }}</span>
							<span class="badge bg-yellow-lt">{{ t("late") }} {{ att.late }}</span>
							<span class="badge bg-red-lt">D · {{ att.absent }}</span>
							<span class="badge bg-secondary-lt">{{ t("leave") }} {{ att.on_leave }}</span>
							<RouterLink to="/hr/attendance" class="ms-auto small">{{ t("Open matrix") }} <i class="ti ti-arrow-right"></i></RouterLink>
						</div>
					</div>
				</div>
			</div>

			<!-- Payroll this month -->
			<div class="col-lg-6">
				<div class="card h-100">
					<div class="card-body">
						<div class="d-flex justify-content-between align-items-center">
							<span class="text-secondary small">{{ t("Payroll") }} · {{ ov.period }}</span>
							<span v-if="pay.already_locked" class="badge bg-secondary-lt"><i class="ti ti-lock me-1"></i>{{ t("Locked") }}</span>
							<span v-else class="badge" :class="pay.can_lock ? 'bg-green-lt' : 'bg-yellow-lt'">{{ pay.can_lock ? t("Ready") : t("Not ready") }}</span>
						</div>
						<div class="d-flex align-items-baseline gap-2 my-2">
							<span class="h1 m-0">{{ pay.summary_count }}</span>
							<span class="text-secondary small">/ {{ pay.headcount }} {{ t("summaries ready") }}</span>
						</div>
						<div v-if="(pay.blockers || []).length" class="d-flex flex-column gap-1">
							<span v-for="(b, i) in pay.blockers.slice(0, 3)" :key="i" class="small text-warning"><i class="ti ti-alert-circle me-1"></i>{{ b.message }} <span v-if="b.count" class="text-secondary">({{ b.count }})</span></span>
						</div>
						<div v-else class="small text-success"><i class="ti ti-check me-1"></i>{{ t("No blockers") }}</div>
						<div class="mt-2 d-flex gap-3">
							<RouterLink to="/hr/payroll-readiness" class="small">{{ t("Readiness") }} <i class="ti ti-arrow-right"></i></RouterLink>
							<RouterLink to="/hr/payroll-preview" class="small">{{ t("Computed Pay") }} <i class="ti ti-arrow-right"></i></RouterLink>
						</div>
					</div>
				</div>
			</div>
		</div>

		<div class="row g-3">
			<!-- Advances -->
			<div class="col-lg-6">
				<div class="card h-100">
					<div class="card-body">
						<div class="d-flex justify-content-between align-items-center">
							<span class="text-secondary small">{{ t("Advances outstanding") }}</span>
							<RouterLink to="/hr/advances" class="btn btn-sm btn-outline-primary"><i class="ti ti-cash-banknote me-1"></i>{{ t("Pay") }}</RouterLink>
						</div>
						<template v-if="canMoney && adv.configured !== false">
							<div class="d-flex align-items-baseline gap-2 my-2">
								<span class="h1 m-0 font-monospace">{{ money(adv.total) }}</span>
								<span class="text-secondary small">· {{ adv.count }} {{ t("staff") }}</span>
							</div>
							<div v-for="(o, i) in (adv.top || [])" :key="i" class="d-flex justify-content-between border-top py-1 small">
								<span>{{ o.employee_name }}</span><span class="font-monospace">{{ money(o.amount) }}</span>
							</div>
							<div v-if="!(adv.top || []).length" class="text-secondary small mt-2">{{ t("No outstanding advances") }}</div>
						</template>
						<div v-else-if="!canMoney" class="text-secondary small mt-3"><i class="ti ti-lock me-1"></i>{{ t("Hidden for your role") }}</div>
						<div v-else class="text-secondary small mt-3">{{ t("No Employee Advances account configured.") }}</div>
					</div>
				</div>
			</div>

			<!-- Workforce -->
			<div class="col-lg-6">
				<div class="card h-100">
					<div class="card-body">
						<div class="d-flex justify-content-between align-items-center">
							<span class="text-secondary small">{{ t("Workforce") }}</span>
							<RouterLink to="/hr/employees" class="small">{{ t("People") }} <i class="ti ti-arrow-right"></i></RouterLink>
						</div>
						<div class="d-flex align-items-baseline gap-2 my-2">
							<span class="h1 m-0">{{ wf.headcount }}</span>
							<span class="text-secondary small">{{ t("active") }} · {{ (wf.by_dept || []).length }} {{ t("depts") }}</span>
						</div>
						<div class="d-flex flex-column gap-2">
							<div v-for="d in (wf.by_dept || []).slice(0, 4)" :key="d.dept">
								<div class="d-flex justify-content-between small text-secondary"><span class="text-truncate">{{ d.dept }}</span><span>{{ d.n }}</span></div>
								<div class="progress" style="height: 6px"><div class="progress-bar" :style="{ width: Math.round(d.n * 100 / deptMax) + '%' }"></div></div>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</template>

	<div v-else class="alert alert-warning">{{ t("Could not load the HR overview.") }}</div>
</template>
