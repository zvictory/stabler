<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso } from "../../composables/date.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany, language } = storeToRefs(session);

const lang = computed(() => language.value || "en");

// ---- Inputs ----
const date = ref(todayIso());
const hireDate = ref("");
const shift = ref("DAY");
const shiftStartHm = ref("09:00");
const isHoliday = ref(false);
const deviceLateMin = ref(0);
const selectedRuleSet = ref("");

const SHIFTS = computed(() => [
	{ value: "DAY", label: t("Day") },
	{ value: "NIGHT", label: t("Night") },
	{ value: "OFFICE", label: t("Office") },
	{ value: "LIGHT", label: t("Light") },
]);

// Punch list — each entry: { time: "HH:MM", direction: "IN"|"OUT" }
const punches = ref([
	{ time: "09:00", direction: "IN" },
	{ time: "18:00", direction: "OUT" },
]);

function addPunch() {
	punches.value.push({ time: "", direction: "IN" });
}

function removePunch(idx) {
	punches.value = punches.value.filter((_, i) => i !== idx);
}

// ---- Rule set list ----
const ruleSets = ref([]);
const ruleSetsLoading = ref(false);

async function loadRuleSets() {
	if (!activeCompany.value) return;
	ruleSetsLoading.value = true;
	try {
		ruleSets.value = await call("stabler.api.hr_attendance.list_rule_sets", {
			company: activeCompany.value,
		});
		// Auto-select the default or the first available rule set.
		if (!selectedRuleSet.value && ruleSets.value.length > 0) {
			const def = ruleSets.value.find((r) => r.is_default) || ruleSets.value[0];
			selectedRuleSet.value = def.name;
		}
	} catch {
		ruleSets.value = [];
	} finally {
		ruleSetsLoading.value = false;
	}
}

// ---- Simulation ----
const result = ref(null);
const simulating = ref(false);
const simError = ref("");
let debounceTimer = null;

function buildPunchPayload() {
	// Convert local "HH:MM" times to full ISO timestamps on the selected date.
	return punches.value
		.filter((p) => p.time && p.direction)
		.map((p) => ({
			timestamp: `${date.value}T${p.time}:00`,
			direction: p.direction,
		}));
}

async function simulate() {
	if (!date.value || !selectedRuleSet.value || !activeCompany.value) {
		result.value = null;
		return;
	}
	simulating.value = true;
	simError.value = "";
	try {
		const res = await call("stabler.api.hr_attendance.simulate_day", {
			punches: JSON.stringify(buildPunchPayload()),
			date_str: date.value,
			hire_date: hireDate.value || date.value,
			shift: shift.value,
			shift_start_hm: shiftStartHm.value,
			is_holiday: isHoliday.value ? 1 : 0,
			device_late_min: deviceLateMin.value || 0,
			rule_set: selectedRuleSet.value,
			company: activeCompany.value,
		});
		result.value = res;
	} catch (e) {
		simError.value = e?.message || String(e);
		result.value = null;
	} finally {
		simulating.value = false;
	}
}

function scheduleSimulate() {
	clearTimeout(debounceTimer);
	debounceTimer = setTimeout(simulate, 400);
}

// Watch all inputs and auto-recompute (debounced).
watch(
	[date, hireDate, shift, shiftStartHm, isHoliday, deviceLateMin, selectedRuleSet, activeCompany, punches],
	scheduleSimulate,
	{ deep: true },
);

onMounted(async () => {
	await loadRuleSets();
	scheduleSimulate();
});
watch(activeCompany, async () => {
	await loadRuleSets();
	scheduleSimulate();
});

// ---- Result helpers ----
function fmtMin(min) {
	if (min == null || min === "" || !Number.isFinite(Number(min))) return "—";
	const m = Math.round(Number(min));
	if (m < 60) return `${m} ${t("min")}`;
	const h = Math.floor(m / 60);
	const rem = m % 60;
	return rem > 0 ? `${h}h ${rem}${t("min")}` : `${h}h`;
}

function fmtTime(ts) {
	if (!ts) return "—";
	const s = String(ts);
	// If it's a full ISO timestamp, strip the date part.
	const t = s.includes("T") ? s.split("T")[1] : s;
	const m = t.match(/(\d{2}):(\d{2})/);
	return m ? `${m[1]}:${m[2]}` : s;
}

const statusBadgeKey = "Attendance Status";
</script>

<template>
	<div class="row g-3">
		<!-- Left: input panel -->
		<div class="col-lg-5">
			<div class="card">
				<div class="card-header">
					<h4 class="card-title mb-0">
						<i class="ti ti-player-play me-2 text-primary"></i>{{ t("Simulator inputs") }}
					</h4>
				</div>
				<div class="card-body">
					<div class="row g-3">
						<!-- Date -->
						<div class="col-6">
							<label class="form-label">{{ t("Date") }}</label>
							<DateInput v-model="date" />
						</div>
						<!-- Hire date -->
						<div class="col-6">
							<label class="form-label">{{ t("Hire date") }}</label>
							<DateInput v-model="hireDate" />
						</div>
						<!-- Shift -->
						<div class="col-6">
							<label class="form-label">{{ t("Shift") }}</label>
							<select v-model="shift" class="form-select">
								<option v-for="s in SHIFTS" :key="s.value" :value="s.value">
									{{ s.label }}
								</option>
							</select>
						</div>
						<!-- Shift start -->
						<div class="col-6">
							<label class="form-label">{{ t("Shift start") }}</label>
							<input v-model="shiftStartHm" type="time" class="form-control" />
						</div>
						<!-- Rule set -->
						<div class="col-12">
							<label class="form-label">{{ t("Rule set") }}</label>
							<select
								v-model="selectedRuleSet"
								class="form-select"
								:disabled="ruleSetsLoading"
							>
								<option value="" disabled>{{ t("Pick a rule set…") }}</option>
								<option v-for="rs in ruleSets" :key="rs.name" :value="rs.name">
									{{ rs.rule_set_name }}
									<template v-if="rs.is_default"> ({{ t("default") }})</template>
								</option>
							</select>
						</div>
						<!-- Device late / holiday -->
						<div class="col-6">
							<label class="form-label">{{ t("Device late (min)") }}</label>
							<input
								v-model.number="deviceLateMin"
								type="number"
								min="0"
								class="form-control"
							/>
							<div class="form-text">{{ t("Extra lateness from slow device clock.") }}</div>
						</div>
						<div class="col-6 d-flex align-items-end pb-1">
							<label class="form-check form-switch mb-0">
								<input
									v-model="isHoliday"
									type="checkbox"
									class="form-check-input"
									role="switch"
								/>
								<span class="form-check-label">{{ t("Public holiday") }}</span>
							</label>
						</div>
					</div>

					<!-- Punch list -->
					<div class="mt-3">
						<div class="d-flex align-items-center justify-content-between mb-2">
							<label class="form-label mb-0">{{ t("Punches") }}</label>
							<button
								type="button"
								class="btn btn-sm btn-outline-secondary"
								@click="addPunch"
							>
								<i class="ti ti-plus me-1"></i>{{ t("Add punch") }}
							</button>
						</div>
						<div class="table-responsive">
							<table class="table table-sm table-vcenter mb-0">
								<thead>
									<tr>
										<th>{{ t("Time") }}</th>
										<th>{{ t("Direction") }}</th>
										<th></th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(punch, idx) in punches" :key="idx">
										<td>
											<input
												v-model="punch.time"
												type="time"
												class="form-control form-control-sm font-monospace"
												style="width: 110px"
											/>
										</td>
										<td>
											<select v-model="punch.direction" class="form-select form-select-sm" style="width: 90px">
												<option value="IN">IN</option>
												<option value="OUT">OUT</option>
											</select>
										</td>
										<td>
											<button
												type="button"
												class="btn btn-sm btn-ghost-secondary"
												:title="t('Remove')"
												@click="removePunch(idx)"
											>
												<i class="ti ti-x"></i>
											</button>
										</td>
									</tr>
									<tr v-if="punches.length === 0">
										<td colspan="3" class="text-secondary text-center small py-2">
											{{ t("No punches — employee will be marked absent.") }}
										</td>
									</tr>
								</tbody>
							</table>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Right: result panel -->
		<div class="col-lg-7">
			<div class="card">
				<div class="card-header d-flex align-items-center gap-2">
					<h4 class="card-title mb-0">
						<i class="ti ti-report-analytics me-2 text-success"></i>{{ t("Simulation result") }}
					</h4>
					<span v-if="simulating" class="spinner-border spinner-border-sm text-secondary ms-auto"></span>
				</div>
				<div class="card-body">
					<div v-if="simError" class="alert alert-danger">{{ simError }}</div>

					<!-- No result yet -->
					<div v-else-if="!result && !simulating" class="text-secondary text-center py-4">
						<i class="ti ti-player-play-filled fs-2 d-block mb-2 text-muted"></i>
						{{ t("Fill in the inputs on the left to see the day result.") }}
					</div>

					<!-- Skeleton while loading -->
					<div v-else-if="simulating && !result" class="placeholder-glow">
						<div class="placeholder col-4 mb-2 py-3 rounded"></div>
						<div class="placeholder col-8 mb-2 py-2 rounded"></div>
						<div class="placeholder col-6 mb-2 py-2 rounded"></div>
					</div>

					<!-- Result card -->
					<template v-else-if="result">
						<!-- Top row: date, status, night flag -->
						<div class="d-flex align-items-center gap-2 flex-wrap mb-3">
							<span class="fw-semibold font-monospace">{{ formatDate(result.date) }}</span>
							<span
								class="badge fs-6"
								:class="getStatusBadgeClass('Attendance Status', result.status)"
							>
								{{ t(result.status) }}
							</span>
							<span v-if="result.is_night" class="badge bg-purple-lt">
								<i class="ti ti-moon me-1"></i>{{ t("Night shift") }}
							</span>
							<span v-if="result.payroll_impacting" class="badge bg-orange-lt ms-auto">
								<i class="ti ti-alert-circle me-1"></i>{{ t("Payroll impacting") }}
							</span>
						</div>

						<!-- Grid of key metrics -->
						<div class="row g-2 mb-3">
							<div class="col-6 col-md-3">
								<div class="card card-sm bg-body-secondary border-0">
									<div class="card-body text-center py-2">
										<div class="text-secondary small">{{ t("Entry") }}</div>
										<div class="fw-semibold font-monospace">{{ fmtTime(result.entry) }}</div>
									</div>
								</div>
							</div>
							<div class="col-6 col-md-3">
								<div class="card card-sm bg-body-secondary border-0">
									<div class="card-body text-center py-2">
										<div class="text-secondary small">{{ t("Exit") }}</div>
										<div class="fw-semibold font-monospace">{{ fmtTime(result.exit) }}</div>
									</div>
								</div>
							</div>
							<div class="col-6 col-md-3">
								<div class="card card-sm bg-body-secondary border-0">
									<div class="card-body text-center py-2">
										<div class="text-secondary small">{{ t("Punches") }}</div>
										<div class="fw-semibold font-monospace">{{ result.punch_count ?? "—" }}</div>
									</div>
								</div>
							</div>
							<div class="col-6 col-md-3">
								<div class="card card-sm bg-body-secondary border-0">
									<div class="card-body text-center py-2">
										<div class="text-secondary small">{{ t("Worked") }}</div>
										<div class="fw-semibold font-monospace">{{ fmtMin(result.worked_min) }}</div>
									</div>
								</div>
							</div>
						</div>

						<!-- Late & OT detail -->
						<div class="row g-2 mb-3">
							<div class="col-md-6">
								<div class="d-flex justify-content-between align-items-center border rounded px-3 py-2">
									<div>
										<div class="text-secondary small">{{ t("Late") }}</div>
										<div class="fw-semibold">{{ fmtMin(result.late_min) }}</div>
									</div>
									<div class="text-end">
										<div class="text-secondary small">{{ t("Late fee") }}</div>
										<div
											class="fw-semibold font-monospace"
											:class="result.late_fee_uzs > 0 ? 'text-danger' : ''"
										>
											{{ formatMoney(result.late_fee_uzs ?? 0, "UZS", lang) }}
										</div>
									</div>
								</div>
							</div>
							<div class="col-md-6">
								<div class="d-flex justify-content-between align-items-center border rounded px-3 py-2">
									<div>
										<div class="text-secondary small">{{ t("Overtime") }}</div>
										<div class="fw-semibold">{{ fmtMin(result.overtime_min) }}</div>
									</div>
									<div class="text-end">
										<div class="text-secondary small">{{ t("OT flag") }}</div>
										<div class="fw-semibold">
											{{ result.overtime_min > 0 ? t("Yes") : t("No") }}
										</div>
									</div>
								</div>
							</div>
						</div>

						<!-- Exceptions chips -->
						<div v-if="result.exceptions && result.exceptions.length > 0" class="mt-2">
							<div class="text-secondary small mb-1">{{ t("Exceptions") }}</div>
							<div class="d-flex flex-wrap gap-1">
								<span
									v-for="(ex, i) in result.exceptions"
									:key="i"
									class="badge bg-warning-lt text-warning"
								>
									<i class="ti ti-alert-triangle me-1"></i>{{ t(ex) }}
								</span>
							</div>
						</div>
						<div v-else class="text-secondary small mt-2">
							<i class="ti ti-check-circle text-success me-1"></i>{{ t("No exceptions.") }}
						</div>
					</template>
				</div>
			</div>
		</div>
	</div>
</template>
