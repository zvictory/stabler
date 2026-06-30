<script setup>
import { computed, ref, watch } from "vue";
import { call } from "../api/client.js";
import { t } from "../composables/i18n.js";

const props = defineProps({
	employee: { type: String, required: true },
	company: { type: String, required: true },
});

// ERPNext status code → anjan-hr display letter + color (matches the matrix).
const CODES = {
	P: { letter: "K", cls: "text-success" },
	W: { letter: "K", cls: "text-success" },
	H: { letter: "Y", cls: "text-orange" },
	A: { letter: "D", cls: "text-danger" },
	L: { letter: "D", cls: "text-azure" },
};
// Ambiguous: check-in present but no check-out.
const AMBIG_CLS = { letter: "N", cls: "text-secondary" };

function ym(d) {
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
const period = ref(ym(new Date()));
const periodLabel = computed(() => {
	const [y, m] = period.value.split("-").map(Number);
	return new Date(y, m - 1, 1).toLocaleDateString("en", { year: "numeric", month: "long" });
});
const isCurrentOrFuture = computed(() => period.value >= ym(new Date()));
function shift(delta) {
	const [y, m] = period.value.split("-").map(Number);
	period.value = ym(new Date(y, m - 1 + delta, 1));
}

const loading = ref(false);
const data = ref(null);
const row = computed(() => (data.value?.rows || [])[0] || null);
const days = computed(() => data.value?.days || []);
const lateSet = computed(() => new Set(row.value?.late || []));
const ambiguousSet = computed(() => new Set(row.value?.ambiguous || []));

async function load() {
	if (!props.employee || !props.company) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.hr.attendance_matrix", {
			company: props.company, period: period.value, employee: props.employee,
		});
	} catch {
		data.value = null;
	} finally {
		loading.value = false;
	}
}
watch([() => props.employee, () => props.company, period], load, { immediate: true });

// Lay the month's days into weeks (Mon-first), padding the first week.
const weeks = computed(() => {
	const ds = days.value;
	if (!ds.length) return [];
	const firstWd = new Date(ds[0].date).getDay(); // 0=Sun
	const lead = (firstWd + 6) % 7; // Mon-first offset
	const cells = Array(lead).fill(null).concat(ds);
	while (cells.length % 7) cells.push(null);
	const out = [];
	for (let i = 0; i < cells.length; i += 7) out.push(cells.slice(i, i + 7));
	return out;
});

const codeOf = (day) => ambiguousSet.value.has(day) ? AMBIG_CLS : (CODES[row.value?.cells?.[day]] || null);
const dow = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
</script>

<template>
	<div>
		<div class="d-flex align-items-center gap-2 mb-2">
			<div class="btn-group btn-group-sm" role="group">
				<button type="button" class="btn btn-outline-secondary" @click="shift(-1)"><i class="ti ti-chevron-left"></i></button>
				<span class="btn btn-outline-secondary disabled text-dark" style="min-width: 130px">{{ periodLabel }}</span>
				<button type="button" class="btn btn-outline-secondary" :disabled="isCurrentOrFuture" @click="shift(1)"><i class="ti ti-chevron-right"></i></button>
			</div>
			<div v-if="row" class="ms-auto d-flex gap-2 small">
				<span class="badge bg-green-lt">K {{ row.totals.present || 0 }}</span>
				<span class="badge bg-red-lt">D {{ row.totals.absent || 0 }}</span>
				<span class="badge bg-secondary-lt">{{ t("Late") }} {{ (row.late || []).length }}</span>
			</div>
		</div>

		<div v-if="loading" class="text-center py-4"><span class="spinner-border spinner-border-sm text-primary"></span></div>
		<div v-else-if="!row" class="text-secondary small py-3">{{ t("No attendance for this month.") }}</div>
		<table v-else class="table table-bordered text-center mb-0" style="table-layout: fixed">
			<thead>
				<tr>
					<th v-for="d in dow" :key="d" class="small text-secondary py-1">{{ d }}</th>
				</tr>
			</thead>
			<tbody>
				<tr v-for="(week, wi) in weeks" :key="wi">
					<td
						v-for="(cell, ci) in week"
						:key="ci"
						style="height: 46px; vertical-align: top"
						:class="{ 'bg-secondary-lt': cell && cell.is_weekend, 'bg-blue-lt': cell && cell.is_holiday }"
					>
						<template v-if="cell">
							<div class="small text-secondary" :class="{ 'fw-bold text-primary': cell.is_today }">{{ cell.day }}</div>
							<div v-if="codeOf(cell.day)" class="fw-bold" :class="codeOf(cell.day).cls" style="font-size: .95rem">
								{{ codeOf(cell.day).letter }}<sup v-if="lateSet.has(cell.day)" class="text-warning">•</sup>
							</div>
						</template>
					</td>
				</tr>
			</tbody>
		</table>
		<div class="small text-secondary mt-1">
			<span class="text-success">K</span> {{ t("present") }} ·
			<span class="text-orange">Y</span> {{ t("half-day") }} ·
			<span class="text-danger">D</span> {{ t("absent") }} ·
			<span class="text-secondary">N</span> {{ t("ambiguous") }} ·
			<span class="text-warning">•</span> {{ t("late") }}
		</div>
	</div>
</template>
