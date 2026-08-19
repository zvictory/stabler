<!--
CalendarMonth — Google-Calendar-style month grid (built from scratch, no lib).

Props:
  month     "yyyy-mm"  — currently displayed month
  events    [{date:"yyyy-mm-dd", label, amount, contractId, currency}]
  currency  string     — for formatMoney display
  language  string     — for formatMoney locale
  emptyText string     — what an empty month says (the grid is not installment-only)

Emits:
  update:month   "yyyy-mm"       — prev/next navigation
  select         {event}         — chip click
  select-day     "yyyy-mm-dd"    — click on the day itself, not on a chip

TZ-safe: all Date construction uses numeric args.
Monday-first 7-col grid.
-->

<script setup>
import { computed } from "vue";
import { t } from "../composables/i18n.js";
import { formatMoney } from "../composables/money.js";

const props = defineProps({
	month: { type: String, required: true },      // "yyyy-mm"
	events: { type: Array, default: () => [] },
	currency: { type: String, default: "USD" },
	language: { type: String, default: "en" },
	emptyText: { type: String, default: "" },
});

const emit = defineEmits(["update:month", "select", "select-day"]);

const WEEKDAYS = [t("Mon"), t("Tue"), t("Wed"), t("Thu"), t("Fri"), t("Sat"), t("Sun")];
const MAX_CHIPS = 3;

// ── Month parsing (never parse ISO strings — always use numeric Date) ─────────
const parsed = computed(() => {
	const [y, m] = props.month.split("-").map(Number);
	return { year: y, month: m }; // month is 1-based
});

const monthLabel = computed(() => {
	const { year, month } = parsed.value;
	// Use numeric Date constructor — TZ-safe
	const d = new Date(year, month - 1, 1);
	return d.toLocaleString("default", { month: "long", year: "numeric" });
});

// ── Calendar grid ─────────────────────────────────────────────────────────────
const grid = computed(() => {
	const { year, month } = parsed.value;
	// Days in month: day 0 of the NEXT month
	const daysInMonth = new Date(year, month, 0).getDate();
	// 0=Sun, 1=Mon, …, 6=Sat — for first day of month
	const firstWeekday = new Date(year, month - 1, 1).getDay();
	// Monday-first: offset = (firstWeekday + 6) % 7
	const leadingBlanks = (firstWeekday + 6) % 7;

	const pad = (n) => String(n).padStart(2, "0");
	const today = new Date();
	const todayKey = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;

	// Map events by date key
	const byDate = {};
	for (const ev of props.events) {
		if (!byDate[ev.date]) byDate[ev.date] = [];
		byDate[ev.date].push(ev);
	}

	const cells = [];

	// Leading blank cells
	for (let i = 0; i < leadingBlanks; i++) {
		cells.push({ blank: true });
	}

	// Day cells
	for (let day = 1; day <= daysInMonth; day++) {
		const key = `${year}-${pad(month)}-${pad(day)}`;
		const dayEvents = byDate[key] || [];
		const visible = dayEvents.slice(0, MAX_CHIPS);
		const overflow = dayEvents.length - visible.length;
		cells.push({
			blank: false,
			day,
			key,
			isToday: key === todayKey,
			isPast: key < todayKey,
			events: visible,
			overflow,
		});
	}

	// Split into weeks (rows of 7)
	const weeks = [];
	for (let i = 0; i < cells.length; i += 7) {
		weeks.push(cells.slice(i, i + 7));
	}
	// Pad last week with blanks
	const last = weeks[weeks.length - 1];
	while (last.length < 7) last.push({ blank: true });

	return weeks;
});

// ── Navigation (integer month math — no re-parse, no Date parse) ──────────────
function navigate(delta) {
	const { year, month } = parsed.value;
	let newM = month + delta;
	let newY = year;
	if (newM < 1) { newM += 12; newY -= 1; }
	if (newM > 12) { newM -= 12; newY += 1; }
	const pad = (n) => String(n).padStart(2, "0");
	emit("update:month", `${newY}-${pad(newM)}`);
}

const hasEvents = computed(() => props.events.length > 0);

function chipClass(ev) {
	return {
		"calendar-chip--paid": ev.state === "paid",
		"calendar-chip--partial": ev.state === "partial",
		"calendar-chip--overdue": ev.state === "overdue",
		// Money in and money out, for calendars whose rows are not all one way.
		"calendar-chip--inflow": ev.state === "inflow",
		"calendar-chip--outflow": ev.state === "outflow",
		"calendar-chip--upcoming": !ev.state || ev.state === "upcoming",
	};
}
</script>

<template>
	<div class="calendar-month">
		<!-- Header: prev / month-year / next -->
		<div class="d-flex align-items-center justify-content-between mb-2">
			<button type="button" class="btn btn-sm btn-ghost-secondary" @click="navigate(-1)">
				<i class="ti ti-chevron-left"></i>
			</button>
			<span class="fw-semibold">{{ monthLabel }}</span>
			<button type="button" class="btn btn-sm btn-ghost-secondary" @click="navigate(1)">
				<i class="ti ti-chevron-right"></i>
			</button>
		</div>

		<!-- Weekday headers -->
		<div class="calendar-grid calendar-header">
			<div v-for="wd in WEEKDAYS" :key="wd" class="calendar-cell text-secondary small fw-semibold text-center">
				{{ wd }}
			</div>
		</div>

		<!-- Day rows -->
		<div v-for="(week, wi) in grid" :key="wi" class="calendar-grid">
			<div
				v-for="(cell, ci) in week"
				:key="ci"
				class="calendar-cell"
				:class="{ 'calendar-cell--today': !cell.blank && cell.isToday, 'calendar-cell--blank': cell.blank, 'calendar-cell--weekend': !cell.blank && ci >= 5, 'calendar-cell--past': !cell.blank && cell.isPast }"
				@click="!cell.blank && emit('select-day', cell.key)"
			>
				<template v-if="!cell.blank">
					<div class="calendar-day-num small" :class="{ 'fw-bold text-primary': cell.isToday }">
						{{ cell.day }}
					</div>
					<div
						v-for="ev in cell.events"
						:key="ev.contractId + ev.label"
						class="calendar-chip"
						:class="chipClass(ev)"
						@click.stop="emit('select', ev)"
					>
						<span class="text-truncate">{{ ev.label }}</span>
						<span v-if="ev.showAmount !== false" class="ms-auto text-nowrap font-monospace">
							{{ formatMoney(ev.amount, currency) }}
						</span>
					</div>
					<div v-if="cell.overflow > 0" class="calendar-overflow small text-secondary">
						+{{ cell.overflow }} {{ t("more") }}
					</div>
				</template>
			</div>
		</div>

		<div v-if="!hasEvents" class="text-center text-secondary py-3 small">
			{{ emptyText || t("No installments due this month.") }}
		</div>
	</div>
</template>

<style scoped>
.calendar-grid {
	display: grid;
	grid-template-columns: repeat(7, 1fr);
	gap: 2px;
	background: var(--tblr-border-color, #d7dbe0);
	border: 1px solid var(--tblr-border-color, #d7dbe0);
	border-radius: 6px;
	overflow: hidden;
}

.calendar-header {
	background: transparent;
	gap: 0;
	margin-bottom: 1px;
}

.calendar-header .calendar-cell {
	padding: 4px 2px;
}

.calendar-cell {
	background: var(--tblr-card-bg, #fff);
	min-height: 90px;
	padding: 4px;
	vertical-align: top;
	overflow: hidden;
}

.calendar-cell--blank {
	background: var(--tblr-light, #f6f8fb);
	min-height: 90px;
}

.calendar-cell--today {
	background: #eef2ff;
	box-shadow: inset 0 0 0 2px var(--tblr-primary, #206bc4);
}

.calendar-cell--weekend {
	background: #f7f9fc;
}

.calendar-cell--past .calendar-day-num {
	opacity: 0.45;
}

.calendar-cell:hover {
	background: #f1f5fb;
}

.calendar-day-num {
	text-align: right;
	margin-bottom: 2px;
}

.calendar-chip {
	display: flex;
	align-items: center;
	gap: 4px;
	padding: 2px 4px;
	margin-bottom: 2px;
	background: var(--tblr-primary, #206bc4);
	color: #fff;
	border-radius: 3px;
	font-size: 0.72rem;
	cursor: pointer;
	overflow: hidden;
}

.calendar-chip--paid {
	background: var(--tblr-success, #2fb344);
}

.calendar-chip--partial {
	background: var(--tblr-warning, #f59f00);
}

.calendar-chip--overdue {
	background: var(--tblr-danger, #d63939);
}

.calendar-chip--upcoming {
	background: var(--tblr-primary, #206bc4);
}

.calendar-chip--inflow {
	background: var(--tblr-teal, #0ca678);
}

.calendar-chip--outflow {
	background: var(--tblr-orange, #f76707);
}

.calendar-chip:hover {
	opacity: 0.85;
}

.calendar-overflow {
	font-size: 0.7rem;
	padding: 1px 2px;
}
</style>
