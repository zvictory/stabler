<script setup>
import { computed, ref, watch } from "vue";
import { call } from "../api/client.js";
import { t } from "../composables/i18n.js";

const props = defineProps({
	company: { type: String, default: "" },
	period: { type: String, default: "" },     // "yyyy-mm"
	department: { type: String, default: "" },
	search: { type: String, default: "" },
});
const emit = defineEmits(["meta"]);

const loading = ref(false);
const error = ref("");
const data = ref(null);

// code → { label, bg, fg }
const CODES = {
	P: { label: () => t("Present"), bg: "#e7f6ec", fg: "#1f9d54" },
	A: { label: () => t("Absent"), bg: "#fbe9e9", fg: "#d63939" },
	L: { label: () => t("On Leave"), bg: "#e7edfb", fg: "#3b5bdb" },
	H: { label: () => t("Half Day"), bg: "#fdf3e3", fg: "#c07a00" },
	W: { label: () => t("Work From Home"), bg: "#e6f7f4", fg: "#0ca678" },
};

const rows = computed(() => {
	const all = data.value?.rows || [];
	const s = props.search.trim().toLowerCase();
	if (!s) return all;
	return all.filter(
		(r) =>
			(r.employee_name || "").toLowerCase().includes(s) ||
			(r.employee || "").toLowerCase().includes(s) ||
			(r.department || "").toLowerCase().includes(s),
	);
});
const days = computed(() => data.value?.days || []);

function cellOf(row, day) {
	const code = row.cells?.[day];
	return code ? CODES[code] : null;
}
function isLate(row, day) {
	return (row.late || []).includes(day);
}
function cellTitle(row, d) {
	const code = row.cells?.[d.day];
	if (code) {
		let s = CODES[code].label();
		if (isLate(row, d.day)) s += " · " + t("Late");
		return `${row.employee_name} — ${d.date}: ${s}`;
	}
	if (d.is_holiday) return `${d.date}: ${t("Holiday")}`;
	if (d.is_weekend) return `${d.date}: ${t("Weekend")}`;
	return `${row.employee_name} — ${d.date}`;
}

// Group rows by department (roster already sorted by dept from the backend).
const groupedRows = computed(() => {
	const counts = {};
	for (const r of rows.value) {
		const d = r.department || t("No department");
		counts[d] = (counts[d] || 0) + 1;
	}
	const out = [];
	let cur = null;
	for (const r of rows.value) {
		const dept = r.department || t("No department");
		if (dept !== cur) {
			out.push({ type: "group", key: "g:" + dept, dept, count: counts[dept] });
			cur = dept;
		}
		out.push({ type: "emp", key: r.employee, row: r });
	}
	return out;
});

// ── Inline cell editing ──────────────────────────────────────────────────────
const STATUS_BY_CODE = { P: "Present", A: "Absent", L: "On Leave", H: "Half Day", W: "Work From Home" };
const editor = ref({ open: false, x: 0, y: 0, row: null, day: null, date: null });
const saving = ref(false);

function onCellClick(ev, row, d) {
	if (d.is_future || d.is_locked) return;
	editor.value = {
		open: true,
		x: Math.min(ev.clientX, window.innerWidth - 200),
		y: Math.min(ev.clientY, window.innerHeight - 290),
		row, day: d.day, date: d.date,
		isPast: !!(data.value && d.date < data.value.today),
		pending: undefined, // {code} once a change awaits confirmation
	};
}
function closeEditor() {
	editor.value.open = false;
}
// Stage 1: choosing a status. Today applies immediately; a past day asks to confirm.
function requestCode(code) {
	if (editor.value.isPast) editor.value.pending = { code };
	else doApply(code);
}
function cancelPending() {
	editor.value.pending = undefined;
}
function pendingLabel() {
	const c = editor.value.pending?.code;
	return c === null ? t("Clear") : (CODES[c]?.label() || c);
}
function recompute(row) {
	const tot = { present: 0, absent: 0, leave: 0, half: 0, wfh: 0, late: (row.late || []).length };
	for (const day in row.cells) {
		const c = row.cells[day];
		if (c === "P") tot.present++;
		else if (c === "A") tot.absent++;
		else if (c === "L") tot.leave++;
		else if (c === "H") tot.half++;
		else if (c === "W") { tot.wfh++; tot.present++; }
	}
	row.totals = tot;
}
async function doApply(code) {
	const e = editor.value;
	if (!e.row || saving.value) return;
	saving.value = true;
	error.value = "";
	try {
		if (code === null) {
			await call("stabler.api.hr.clear_attendance", { company: props.company, employee: e.row.employee, attendance_date: e.date });
			delete e.row.cells[e.day];
		} else {
			await call("stabler.api.hr.set_attendance", { company: props.company, employee: e.row.employee, attendance_date: e.date, status: STATUS_BY_CODE[code] });
			e.row.cells[e.day] = code;
		}
		e.row.late = (e.row.late || []).filter((d) => d !== e.day);
		recompute(e.row);
		closeEditor();
	} catch (err) {
		error.value = err?.message || t("Failed to save.");
	} finally {
		saving.value = false;
	}
}

async function load() {
	if (!props.company) return;
	loading.value = true;
	error.value = "";
	try {
		data.value = await call("stabler.api.hr.attendance_matrix", {
			company: props.company,
			period: props.period || undefined,
			department: props.department || undefined,
		});
		emit("meta", { edit_lock_date: data.value.edit_lock_date, today: data.value.today });
	} catch (err) {
		error.value = err?.message || t("Failed to load attendance.");
		data.value = null;
	} finally {
		loading.value = false;
	}
}

function exportCsv() {
	if (!data.value) return;
	const head = [t("Employee"), t("Department"), ...days.value.map((d) => d.day),
		t("Present"), t("Absent"), t("On Leave")];
	const lines = [head.join(",")];
	for (const r of rows.value) {
		const cols = [
			`"${(r.employee_name || "").replace(/"/g, '""')}"`,
			`"${(r.department || "").replace(/"/g, '""')}"`,
			...days.value.map((d) => r.cells?.[d.day] || ""),
			r.totals.present, r.totals.absent, r.totals.leave,
		];
		lines.push(cols.join(","));
	}
	const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
	const a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	a.download = `attendance-${data.value.period}.csv`;
	a.click();
	URL.revokeObjectURL(a.href);
}

function exportXlsx() {
	if (!props.company) return;
	const p = new URLSearchParams({ company: props.company });
	if (props.period) p.set("period", props.period);
	if (props.department) p.set("department", props.department);
	window.open(`/api/method/stabler.api.hr.attendance_matrix_xlsx?${p.toString()}`, "_blank");
}

watch(() => [props.company, props.period, props.department], load, { immediate: true });
defineExpose({ exportCsv, exportXlsx, reload: load });
</script>

<template>
	<div>
		<div v-if="error" class="alert alert-danger">{{ error }}</div>
		<div v-else-if="loading" class="text-center py-5"><div class="spinner-border text-primary"></div></div>
		<template v-else-if="data">
			<!-- Legend -->
			<div class="d-flex flex-wrap align-items-center gap-3 mb-2 small">
				<span v-for="(c, k) in CODES" :key="k" class="d-inline-flex align-items-center gap-1">
					<span class="att-key" :style="{ background: c.bg, color: c.fg }">{{ k }}</span>
					<span class="text-secondary">{{ c.label() }}</span>
				</span>
				<span class="d-inline-flex align-items-center gap-1">
					<span class="att-key att-late">P<i></i></span><span class="text-secondary">{{ t("Late") }}</span>
				</span>
				<span class="d-inline-flex align-items-center gap-1">
					<span class="att-key att-weekend"></span><span class="text-secondary">{{ t("Weekend") }}</span>
				</span>
				<span v-if="data.edit_lock_date" class="d-inline-flex align-items-center gap-1 text-secondary">
					<i class="ti ti-lock"></i> {{ t("Locked on/before") }} {{ data.edit_lock_date }}
				</span>
				<div class="ms-auto d-flex gap-2">
					<button type="button" class="btn btn-sm btn-outline-success" @click="exportXlsx">
						<i class="ti ti-file-spreadsheet me-1"></i>{{ t("Excel") }}
					</button>
					<button type="button" class="btn btn-sm btn-outline-secondary" @click="exportCsv">
						<i class="ti ti-download me-1"></i>{{ t("CSV") }}
					</button>
				</div>
			</div>

			<div class="att-wrap">
				<table class="att-table">
					<thead>
						<tr>
							<th class="att-emp att-sticky-l">{{ t("Employee") }}</th>
							<th class="att-tot att-sticky-l2 text-center" :title="t('Present')">P</th>
							<th class="att-tot att-sticky-l3 text-center" :title="t('Absent')">A</th>
							<th class="att-tot att-sticky-l4 text-center" :title="t('On Leave')">L</th>
							<th
								v-for="d in days"
								:key="d.day"
								class="att-day text-center"
								:class="{ 'att-col-weekend': d.is_weekend, 'att-col-today': d.is_today, 'att-col-holiday': d.is_holiday }"
							>
								<div class="att-daynum">{{ d.day }}</div>
								<div class="att-dow">{{ d.weekday }}</div>
							</th>
						</tr>
					</thead>
					<tbody>
						<template v-for="item in groupedRows" :key="item.key">
							<tr v-if="item.type === 'group'" class="att-group">
								<td class="att-group-cell att-sticky-l" :colspan="days.length + 4">
									{{ item.dept }} <span class="text-secondary">· {{ item.count }}</span>
								</td>
							</tr>
							<tr v-else>
								<td class="att-emp att-sticky-l">
									<div class="fw-semibold text-truncate">{{ item.row.employee_name }}</div>
									<div class="text-secondary text-truncate" style="font-size:.7rem">{{ item.row.designation || item.row.department || "—" }}</div>
								</td>
								<td class="att-tot att-sticky-l2 text-center fw-semibold" style="color:#1f9d54">{{ item.row.totals.present || "" }}</td>
								<td class="att-tot att-sticky-l3 text-center fw-semibold" style="color:#d63939">{{ item.row.totals.absent || "" }}</td>
								<td class="att-tot att-sticky-l4 text-center fw-semibold" style="color:#3b5bdb">{{ item.row.totals.leave || "" }}</td>
								<td
									v-for="d in days"
									:key="d.day"
									class="att-cell"
									:class="{ 'att-col-weekend': d.is_weekend, 'att-col-today': d.is_today, 'att-col-holiday': d.is_holiday, 'att-editable': !d.is_future && !d.is_locked, 'att-locked': d.is_locked }"
									:title="cellTitle(item.row, d)"
									@click="onCellClick($event, item.row, d)"
								>
									<span
										v-if="cellOf(item.row, d.day)"
										class="att-key"
										:class="{ 'att-late': isLate(item.row, d.day) }"
										:style="{ background: cellOf(item.row, d.day).bg, color: cellOf(item.row, d.day).fg }"
									>{{ item.row.cells[d.day] }}<i v-if="isLate(item.row, d.day)"></i></span>
									<span v-else-if="d.is_future" class="att-empty"></span>
									<span v-else-if="!d.is_weekend && !d.is_holiday" class="att-none">·</span>
								</td>
							</tr>
						</template>
						<tr v-if="!rows.length">
							<td :colspan="days.length + 4" class="text-center text-secondary py-4">{{ t("No employees.") }}</td>
						</tr>
					</tbody>
				</table>
			</div>
			<div class="text-secondary small mt-2">{{ rows.length }} {{ t("employees") }} · {{ data.period }}</div>

			<div v-if="editor.open" class="att-pop-backdrop" @click="closeEditor"></div>
			<div v-if="editor.open" class="att-pop" :style="{ left: editor.x + 'px', top: editor.y + 'px' }">
				<div class="att-pop-title">
					{{ editor.row.employee_name }} · {{ editor.date }}
					<span v-if="editor.isPast" class="att-pop-past"><i class="ti ti-history"></i> {{ t("Past day") }}</span>
				</div>
				<div v-if="!editor.pending" class="att-pop-actions">
					<button v-for="(c, code) in CODES" :key="code" type="button" class="att-pop-btn" :disabled="saving" @click="requestCode(code)">
						<span class="att-key" :style="{ background: c.bg, color: c.fg }">{{ code }}</span>
						<span>{{ c.label() }}</span>
					</button>
					<button type="button" class="att-pop-btn att-pop-clear" :disabled="saving" @click="requestCode(null)">
						<i class="ti ti-eraser"></i><span>{{ t("Clear") }}</span>
					</button>
				</div>
				<div v-else class="att-pop-confirm">
					<div class="small text-secondary">{{ t("Editing a past day") }}.</div>
					<div class="small mt-1">{{ editor.date }} → <b>{{ pendingLabel() }}</b></div>
					<div class="d-flex gap-2 mt-2">
						<button type="button" class="btn btn-sm btn-outline-secondary flex-fill" :disabled="saving" @click="cancelPending">{{ t("Back") }}</button>
						<button type="button" class="btn btn-sm btn-primary flex-fill" :disabled="saving" @click="doApply(editor.pending.code)">{{ t("Confirm") }}</button>
					</div>
				</div>
			</div>
		</template>
	</div>
</template>

<style scoped>
.att-wrap { overflow-x: auto; border: 1px solid var(--tblr-border-color, #e6e7e9); border-radius: 8px; }
.att-table { border-collapse: separate; border-spacing: 0; font-size: 0.78rem; }
.att-table th, .att-table td { border-bottom: 1px solid var(--tblr-border-color, #eef0f3); border-right: 1px solid var(--tblr-border-color, #eef0f3); padding: 2px; background: #fff; }
.att-table thead th { position: sticky; top: 0; z-index: 3; background: #f7f9fc; vertical-align: middle; }
.att-emp { min-width: 168px; max-width: 168px; padding: 4px 8px !important; text-align: left; }
.att-tot { min-width: 28px; max-width: 28px; }
.att-sticky-l { position: sticky; left: 0; z-index: 2; }
.att-sticky-l2 { position: sticky; left: 168px; z-index: 2; }
.att-sticky-l3 { position: sticky; left: 196px; z-index: 2; }
.att-sticky-l4 { position: sticky; left: 224px; z-index: 2; box-shadow: 2px 0 0 var(--tblr-border-color, #e6e7e9); }
.att-table thead .att-sticky-l, .att-table thead .att-sticky-l2, .att-table thead .att-sticky-l3, .att-table thead .att-sticky-l4 { z-index: 4; }
.att-day { min-width: 30px; max-width: 30px; padding: 2px 0 !important; }
.att-daynum { font-weight: 500; line-height: 1.1; }
.att-dow { font-size: 0.6rem; color: var(--tblr-secondary, #6b7689); line-height: 1; }
.att-cell { min-width: 30px; max-width: 30px; height: 30px; text-align: center; vertical-align: middle; }
.att-col-weekend { background: #f3f5f8 !important; }
.att-col-holiday { background: #f4f0fb !important; }
.att-col-today { box-shadow: inset 2px 0 0 var(--tblr-primary, #206bc4), inset -2px 0 0 var(--tblr-primary, #206bc4); }
.att-key { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 5px; font-weight: 600; font-size: 0.72rem; position: relative; }
.att-key.att-late i { position: absolute; top: -2px; right: -2px; width: 7px; height: 7px; border-radius: 50%; background: #f59f00; border: 1px solid #fff; }
.att-key.att-weekend { background: #f3f5f8; width: 22px; height: 22px; }
.att-none { color: #ced4da; }
.att-empty { display: inline-block; width: 22px; height: 22px; }
.att-editable { cursor: pointer; }
.att-editable:hover { outline: 2px solid var(--tblr-primary, #206bc4); outline-offset: -2px; }
.att-group td { background: #eef1f5 !important; }
.att-group-cell { font-weight: 600; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--tblr-secondary, #6b7689); padding: 3px 8px !important; left: 0; }
.att-pop-backdrop { position: fixed; inset: 0; z-index: 1040; }
.att-pop { position: fixed; z-index: 1050; background: #fff; border: 1px solid var(--tblr-border-color, #e6e7e9); border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.12); padding: 6px; min-width: 184px; }
.att-pop-title { font-size: 0.72rem; color: var(--tblr-secondary, #6b7689); padding: 2px 6px 6px; border-bottom: 1px solid var(--tblr-border-color, #eef0f3); margin-bottom: 4px; }
.att-pop-actions { display: flex; flex-direction: column; gap: 2px; }
.att-pop-btn { display: flex; align-items: center; gap: 8px; padding: 5px 6px; border: none; background: transparent; border-radius: 5px; cursor: pointer; font-size: 0.8rem; text-align: left; }
.att-pop-btn:hover { background: var(--tblr-light, #f6f8fb); }
.att-pop-clear { color: var(--tblr-secondary, #6b7689); }
.att-locked { cursor: default; }
.att-locked .att-key { opacity: 0.5; }
.att-pop-past { float: right; color: #c07a00; font-size: 0.68rem; }
.att-pop-confirm { padding: 4px 6px; }
</style>
