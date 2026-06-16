<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import MoneyInput from "../../components/MoneyInput.vue";

const route = useRoute();
const router = useRouter();
const session = useSession();
const { activeCompany, language } = storeToRefs(session);
const toast = useToast();

const isNew = computed(() => route.params.name === "new");
const loading = ref(false);
const saving = ref(false);
const error = ref("");

const lang = computed(() => language.value || "en");

const OT_METHODS = computed(() => [
	{ value: "flat", label: t("Flat fee per step") },
	{ value: "multiplier", label: t("Multiplier (× hourly rate)") },
]);

const WEEKLY_OFF_DAYS_OPTIONS = computed(() => [
	{ value: "0", label: t("Monday") },
	{ value: "1", label: t("Tuesday") },
	{ value: "2", label: t("Wednesday") },
	{ value: "3", label: t("Thursday") },
	{ value: "4", label: t("Friday") },
	{ value: "5", label: t("Saturday") },
	{ value: "6", label: t("Sunday") },
]);

function blank() {
	return {
		name: "",
		rule_set_name: "",
		company: activeCompany.value || "",
		enabled: true,
		is_default: false,
		// Late fee
		grace_min: 5,
		step_min: 15,
		flat_fee_uzs: null,
		step_fee_uzs: null,
		daily_cap_uzs: null,
		// Night & OT
		night_start_hour: 22,
		night_end_hour: 6,
		night_premium_pct: 50,
		ot_method: "flat",
		ot_threshold_min: 480,
		// Half-day
		half_day_min_worked_min: 240,
		// Presence / anchor hours
		anchor_day_h: 8,
		anchor_night_h: 8,
		anchor_office_h: 8,
		anchor_light_h: 4,
		min_worked_for_present_min: 60,
		// Additional
		weekly_off_days: [],
		holiday_ot_premium_pct: 100,
		break_minutes: 60,
		clock_drift_tolerance_min: 3,
		early_leave_deduction_enabled: false,
	};
}

const form = ref(blank());

// weekly_off_days is stored as a JSON string list on the backend; we keep it
// as a JS array locally and serialize on save.
const weeklyOffDaysArr = ref([]);

function toggleWeeklyOff(val) {
	const idx = weeklyOffDaysArr.value.indexOf(val);
	if (idx === -1) {
		weeklyOffDaysArr.value = [...weeklyOffDaysArr.value, val];
	} else {
		weeklyOffDaysArr.value = weeklyOffDaysArr.value.filter((v) => v !== val);
	}
}

async function load() {
	if (isNew.value) {
		form.value = blank();
		weeklyOffDaysArr.value = [];
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		const doc = await call("stabler.api.hr_attendance.get_rule_set", {
			name: route.params.name,
		});
		form.value = { ...blank(), ...doc };
		// Parse weekly_off_days — backend may send a JSON string or an array.
		let days = doc.weekly_off_days;
		if (typeof days === "string") {
			try { days = JSON.parse(days); } catch { days = []; }
		}
		weeklyOffDaysArr.value = Array.isArray(days) ? days.map(String) : [];
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		loading.value = false;
	}
}

async function save() {
	if (!form.value.rule_set_name?.trim()) {
		error.value = t("Rule set name is required.");
		return;
	}
	saving.value = true;
	error.value = "";
	try {
		const payload = {
			...form.value,
			company: form.value.company || activeCompany.value,
			weekly_off_days: JSON.stringify(weeklyOffDaysArr.value),
		};
		const res = await call("stabler.api.hr_attendance.save_rule_set", { payload });
		toast.success(t("Rule set saved."));
		if (isNew.value && res?.name) {
			router.replace(`/hr/attendance-rules/${res.name}`);
		} else {
			await load();
		}
	} catch (e) {
		error.value = e?.message || String(e);
		toast.error(e?.message || String(e));
	} finally {
		saving.value = false;
	}
}

function goBack() {
	router.push("/hr/attendance-rules");
}

onMounted(load);
watch(() => route.params.name, load);
</script>

<template>
	<div>
		<!-- Header -->
		<div class="d-flex align-items-center gap-2 mb-3">
			<button type="button" class="btn btn-ghost-secondary btn-sm" @click="goBack">
				<i class="ti ti-arrow-left me-1"></i>{{ t("Rule sets") }}
			</button>
			<h3 class="mb-0 ms-2">
				{{ isNew ? t("New rule set") : (form.rule_set_name || t("Rule set")) }}
			</h3>
			<div class="ms-auto d-flex gap-2 align-items-center">
				<label class="form-check form-switch mb-0 d-flex align-items-center gap-2">
					<input
						v-model="form.enabled"
						type="checkbox"
						class="form-check-input"
						role="switch"
					/>
					<span class="form-check-label">{{ t("Enabled") }}</span>
				</label>
				<label class="form-check mb-0 d-flex align-items-center gap-2 ms-3">
					<input v-model="form.is_default" type="checkbox" class="form-check-input" />
					<span class="form-check-label">{{ t("Default") }}</span>
				</label>
				<button
					type="button"
					class="btn btn-primary ms-2"
					:disabled="saving || loading"
					@click="save"
				>
					<i class="ti ti-device-floppy me-1"></i>
					{{ saving ? t("Saving…") : t("Save") }}
				</button>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger mb-3">{{ error }}</div>

		<div v-if="loading" class="card p-4 text-center">
			<div class="spinner-border text-primary mx-auto"></div>
		</div>

		<div v-else class="row g-3">
			<!-- Identity -->
			<div class="col-12">
				<div class="card">
					<div class="card-header">
						<h4 class="card-title mb-0">{{ t("Identity") }}</h4>
					</div>
					<div class="card-body">
						<div class="row g-3">
							<div class="col-md-6">
								<label class="form-label">{{ t("Rule set name") }} *</label>
								<input
									v-model="form.rule_set_name"
									type="text"
									class="form-control"
									:placeholder="t('e.g. Standard 8h shift')"
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Company") }}</label>
								<input
									v-model="form.company"
									type="text"
									class="form-control"
									:placeholder="t('Company')"
								/>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- Late fee section -->
			<div class="col-md-6">
				<div class="card h-100">
					<div class="card-header">
						<h4 class="card-title mb-0">
							<i class="ti ti-clock-x me-2 text-warning"></i>{{ t("Late fee") }}
						</h4>
					</div>
					<div class="card-body">
						<div class="row g-3">
							<div class="col-6">
								<label class="form-label">{{ t("Grace period (min)") }}</label>
								<input
									v-model.number="form.grace_min"
									type="number"
									min="0"
									class="form-control"
								/>
								<div class="form-text">{{ t("Minutes tolerated before late penalty starts.") }}</div>
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Step interval (min)") }}</label>
								<input
									v-model.number="form.step_min"
									type="number"
									min="1"
									class="form-control"
								/>
								<div class="form-text">{{ t("Each additional step charges the step fee.") }}</div>
							</div>
							<div class="col-12">
								<label class="form-label">{{ t("Flat fee (UZS)") }}</label>
								<MoneyInput
									v-model="form.flat_fee_uzs"
									currency="UZS"
									:language="lang"
									:placeholder="t('0')"
								/>
								<div class="form-text">{{ t("Fixed deduction on first late minute past grace.") }}</div>
							</div>
							<div class="col-12">
								<label class="form-label">{{ t("Step fee (UZS)") }}</label>
								<MoneyInput
									v-model="form.step_fee_uzs"
									currency="UZS"
									:language="lang"
									:placeholder="t('0')"
								/>
								<div class="form-text">{{ t("Deducted per each step interval of lateness.") }}</div>
							</div>
							<div class="col-12">
								<label class="form-label">{{ t("Daily cap (UZS)") }}</label>
								<MoneyInput
									v-model="form.daily_cap_uzs"
									currency="UZS"
									:language="lang"
									:placeholder="t('0')"
								/>
								<div class="form-text">{{ t("Maximum late deduction per day (0 = unlimited).") }}</div>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- Night & OT section -->
			<div class="col-md-6">
				<div class="card h-100">
					<div class="card-header">
						<h4 class="card-title mb-0">
							<i class="ti ti-moon me-2 text-purple"></i>{{ t("Night & Overtime") }}
						</h4>
					</div>
					<div class="card-body">
						<div class="row g-3">
							<div class="col-6">
								<label class="form-label">{{ t("Night start (hour)") }}</label>
								<input
									v-model.number="form.night_start_hour"
									type="number"
									min="0"
									max="23"
									class="form-control"
								/>
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Night end (hour)") }}</label>
								<input
									v-model.number="form.night_end_hour"
									type="number"
									min="0"
									max="23"
									class="form-control"
								/>
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Night premium (%)") }}</label>
								<input
									v-model.number="form.night_premium_pct"
									type="number"
									min="0"
									class="form-control"
								/>
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("OT threshold (min)") }}</label>
								<input
									v-model.number="form.ot_threshold_min"
									type="number"
									min="0"
									class="form-control"
								/>
								<div class="form-text">{{ t("Minutes worked before overtime begins.") }}</div>
							</div>
							<div class="col-12">
								<label class="form-label">{{ t("OT method") }}</label>
								<select v-model="form.ot_method" class="form-select">
									<option
										v-for="opt in OT_METHODS"
										:key="opt.value"
										:value="opt.value"
									>
										{{ opt.label }}
									</option>
								</select>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- Half-day / Presence section -->
			<div class="col-md-6">
				<div class="card h-100">
					<div class="card-header">
						<h4 class="card-title mb-0">
							<i class="ti ti-calendar-half me-2 text-orange"></i>{{ t("Half-day & Presence") }}
						</h4>
					</div>
					<div class="card-body">
						<div class="row g-3">
							<div class="col-6">
								<label class="form-label">{{ t("Half-day threshold (min)") }}</label>
								<input
									v-model.number="form.half_day_min_worked_min"
									type="number"
									min="0"
									class="form-control"
								/>
								<div class="form-text">{{ t("Minimum minutes worked to count as half-day.") }}</div>
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Min for present (min)") }}</label>
								<input
									v-model.number="form.min_worked_for_present_min"
									type="number"
									min="0"
									class="form-control"
								/>
								<div class="form-text">{{ t("Minimum minutes worked to count as present.") }}</div>
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Anchor DAY hours (h)") }}</label>
								<input
									v-model.number="form.anchor_day_h"
									type="number"
									min="0"
									step="0.5"
									class="form-control"
								/>
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Anchor NIGHT hours (h)") }}</label>
								<input
									v-model.number="form.anchor_night_h"
									type="number"
									min="0"
									step="0.5"
									class="form-control"
								/>
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Anchor OFFICE hours (h)") }}</label>
								<input
									v-model.number="form.anchor_office_h"
									type="number"
									min="0"
									step="0.5"
									class="form-control"
								/>
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Anchor LIGHT hours (h)") }}</label>
								<input
									v-model.number="form.anchor_light_h"
									type="number"
									min="0"
									step="0.5"
									class="form-control"
								/>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- Additional section -->
			<div class="col-md-6">
				<div class="card h-100">
					<div class="card-header">
						<h4 class="card-title mb-0">
							<i class="ti ti-settings-2 me-2 text-secondary"></i>{{ t("Additional") }}
						</h4>
					</div>
					<div class="card-body">
						<div class="row g-3">
							<div class="col-6">
								<label class="form-label">{{ t("Holiday OT premium (%)") }}</label>
								<input
									v-model.number="form.holiday_ot_premium_pct"
									type="number"
									min="0"
									class="form-control"
								/>
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Break minutes") }}</label>
								<input
									v-model.number="form.break_minutes"
									type="number"
									min="0"
									class="form-control"
								/>
								<div class="form-text">{{ t("Deducted from worked time daily.") }}</div>
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Clock drift tolerance (min)") }}</label>
								<input
									v-model.number="form.clock_drift_tolerance_min"
									type="number"
									min="0"
									class="form-control"
								/>
							</div>
							<div class="col-6 d-flex align-items-end">
								<label class="form-check form-switch mb-0">
									<input
										v-model="form.early_leave_deduction_enabled"
										type="checkbox"
										class="form-check-input"
										role="switch"
									/>
									<span class="form-check-label">{{ t("Early leave deduction") }}</span>
								</label>
							</div>
							<div class="col-12">
								<label class="form-label">{{ t("Weekly off days") }}</label>
								<div class="d-flex flex-wrap gap-2 mt-1">
									<label
										v-for="opt in WEEKLY_OFF_DAYS_OPTIONS"
										:key="opt.value"
										class="form-check mb-0"
									>
										<input
											type="checkbox"
											class="form-check-input"
											:checked="weeklyOffDaysArr.includes(opt.value)"
											@change="toggleWeeklyOff(opt.value)"
										/>
										<span class="form-check-label">{{ opt.label }}</span>
									</label>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
