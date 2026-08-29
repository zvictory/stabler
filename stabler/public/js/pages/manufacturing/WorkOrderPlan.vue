<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useWorkOrderStatus } from "../../composables/workOrderStatus.js";
import { todayIso } from "../../composables/date.js";
import { launchBlockers } from "../../composables/launchBlockers.js";
import { loadStockLevels } from "../../composables/stockLevels.js";
import { scheduleLabel, splitStamp } from "../../composables/planSchedule.js";
import { timelineRows } from "../../composables/planTimeline.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";

// Measured on anjan 2026-08-28, and it is why this screen looks poorer than a
// planning board usually does: 0 of 3789 orders carry a planned_end_date and
// 0 submitted BOMs carry an operating cost, so nothing here can draw a bar or
// a load percentage without inventing the number it is drawn from. A cell
// shows the orders and their summed quantity, both typed by a person.
//
// The other measurement that shaped it: `wip_warehouse` is not writable after
// submit while `planned_start_date` is. So an order moves between days and
// never between lines, and the screen says so rather than offering a drag that
// silently writes nothing.
const WINDOW_DAYS = 7;

const router = useRouter();
const session = useSession();
const { activeCompany } = storeToRefs(session);
const { statusLabel, statusBadge } = useWorkOrderStatus();

const loading = ref(false);
const moving = ref("");
const error = ref("");
const notice = ref("");
const startDate = ref(todayIso());
const grid = ref({ lines: [], days: [], cells: [], unscheduled: [], counts: null });
const selected = ref(null);

// Design 1c's grid is a DAY: rows are lines, the axis is the clock. The week
// grid it sits beside answers a different question ("which day does this run")
// and keeps answering it — a day view cannot show next Thursday, and a week
// view cannot show that two orders collide at 14:00.
const mode = ref("week");
const endDate = computed(() =>
	mode.value === "day" ? startDate.value : addDays(startDate.value, WINDOW_DAYS - 1),
);

// The day's orders, flattened back out of the grid the server already builds —
// rather than a second endpoint returning the same rows in another shape.
const dayOrders = computed(() => (grid.value.cells || []).flatMap((c) => c.orders || []));
const timeline = computed(() => timelineRows(dayOrders.value, grid.value.lines || []));
// Whole hours, so the ruler's labels line up with the block edges.
const hourTicks = computed(() => {
	const { from, to } = timeline.value.window;
	return Array.from({ length: to - from + 1 }, (_, i) => from + i);
});
const tickLeft = (hour) => {
	const { from, to } = timeline.value.window;
	return ((hour - from) / (to - from)) * 100;
};
const isEmpty = computed(() => (grid.value.counts?.orders ?? 0) === 0);

function addDays(iso, n) {
	const d = new Date(`${iso}T00:00:00`);
	d.setDate(d.getDate() + n);
	return toIso(d);
}

function toIso(d) {
	const pad = (n) => String(n).padStart(2, "0");
	return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function shiftWindow(n) {
	startDate.value = addDays(startDate.value, n * (mode.value === "day" ? 1 : WINDOW_DAYS));
}

function thisWeek() {
	startDate.value = todayIso();
}

const cellAt = computed(() => {
	const map = new Map();
	for (const c of grid.value.cells) map.set(`${c.line} ${c.day}`, c);
	return map;
});

function cell(line, day) {
	return cellAt.value.get(`${line} ${day}`) || { orders: [], qty: 0 };
}

function dayLabel(iso) {
	const d = new Date(`${iso}T00:00:00`);
	return d.toLocaleDateString(session.user?.language || "en", {
		weekday: "short",
		day: "numeric",
		month: "short",
	});
}

const isToday = (iso) => iso === todayIso();

// A finished order's planned date is the only record of when it ran, so the
// board refuses to move it, and says so on the chip rather than after somebody
// has already dragged it somewhere.
const FROZEN = ["Completed", "Closed", "Cancelled"];
const isFrozen = (order) => FROZEN.includes(order.status);

function pick(order, line) {
	if (isFrozen(order)) {
		notice.value = "";
		error.value = t("{0} is {1}. Its planned date is the record of when it ran.")
			.replace("{0}", order.name)
			.replace("{1}", statusLabel(order.status));
		return;
	}
	error.value = "";
	notice.value = "";
	selected.value = selected.value?.name === order.name ? null : { ...order, line };
	if (selected.value) openSchedule(selected.value);
}

// Design 1c's missing axis, and the reason it is a form rather than a drag: the
// grid needs a position AND a width, and measured on anjan 2026-08-29 neither is
// recorded — 3 464 of 3 799 orders carry a `planned_start_date` within 60s of
// `creation` (ERPNext's default, not a plan) and 0 carry a `planned_end_date`.
// A drag can move a block that already has a width. Nothing here has one yet, so
// the first thing needed is somewhere to type the hours.
const sched = ref({ day: "", start: "", end: "", nextDay: false });
const schedSaving = ref(false);

function openSchedule(order) {
	const start = splitStamp(order.planned_start_date);
	const end = splitStamp(order.planned_end_date);
	sched.value = {
		day: start.day,
		start: start.time,
		end: end.time,
		// Reconstructed from the dates rather than remembered: an overnight
		// window is the only case where the two days differ, and reading it back
		// wrong would silently pull the end a day earlier on the next save.
		nextDay: Boolean(end.day && start.day && end.day !== start.day),
	};
}

async function saveSchedule() {
	const order = selected.value;
	if (!order || !sched.value.day || !sched.value.start) return;
	schedSaving.value = true;
	error.value = "";
	notice.value = "";
	try {
		// Composed here, validated on the server. `schedule_window` refuses an end
		// that is not after the start, so a planner who typed 06:00 meaning
		// tomorrow and forgot the box below gets a sentence rather than a bar of
		// negative width.
		const endDay = sched.value.nextDay ? addDays(sched.value.day, 1) : sched.value.day;
		await call("stabler.api.manufacturing.set_work_order_schedule", {
			name: order.name,
			planned_start_date: `${sched.value.day} ${sched.value.start}`,
			// Blank clears it, which is the only way to take back a mistyped end.
			planned_end_date: sched.value.end ? `${endDay} ${sched.value.end}` : "",
		});
		notice.value = t("Hours saved for {0}").replace("{0}", order.name);
		selected.value = null;
		await load();
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		schedSaving.value = false;
	}
}

// A target square only exists on the selected order's own line. The line is a
// column ERPNext will not write after submit; offering the move and failing
// afterwards would teach the planner to distrust the whole board.
function isTarget(line, day) {
	if (!selected.value) return false;
	if (selected.value.line !== line) return false;
	return String(selected.value.planned_start_date || "").slice(0, 10) !== day;
}

async function moveTo(line, day) {
	if (!isTarget(line, day)) return;
	const order = selected.value;
	moving.value = order.name;
	error.value = "";
	try {
		await call("stabler.api.manufacturing.reschedule_work_order", {
			name: order.name,
			planned_start_date: day,
		});
		notice.value = t("{0} moved to {1}").replace("{0}", order.name).replace("{1}", dayLabel(day));
		selected.value = null;
		await load();
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		moving.value = "";
	}
}

// Design 1c's «ЧТО МЕШАЕТ ЗАПУСКУ». Not filtered by the window above, and that
// is deliberate: a material missing today blocks the order that was supposed to
// start today whichever week the planner happens to be looking at. Paging the
// panel with the grid would make the shortages disappear when somebody scrolled
// forward to plan next week — the moment they most need to see them.
const blockers = ref({ blockers: [], unmeasured: 0 });
const blockersLoading = ref(false);

async function loadBlockers() {
	if (!activeCompany.value) return;
	blockersLoading.value = true;
	try {
		const rows = await call("stabler.api.manufacturing.list_work_orders", {
			company: activeCompany.value,
			// Waiting orders only — the panel's own question. Asking the server
			// narrows the payload; `launchBlockers` still decides what counts, so
			// a status this filter does not know about cannot slip through as a
			// blocker.
			status: "Not Started",
			limit: 100,
		});
		blockers.value = launchBlockers(rows, await loadStockLevels(rows));
	} catch {
		// The grid is this screen's job; the panel is an aid beside it. A stock
		// call that will not answer must not take the plan down with it — but it
		// must not print "nothing is blocking" either.
		blockers.value = null;
	} finally {
		blockersLoading.value = false;
	}
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		grid.value = await call("stabler.api.manufacturing.work_order_plan", {
			company: activeCompany.value,
			from_date: startDate.value,
			to_date: endDate.value,
		});
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		loading.value = false;
	}
}

const openOrder = (name) => router.push(`/manufacturing/work-orders/${encodeURIComponent(name)}`);

watch([activeCompany, startDate, mode], load);
// The panel does not move with the window, so it is reloaded on the company
// only — and once at mount.
watch(activeCompany, loadBlockers);
onMounted(() => {
	load();
	loadBlockers();
});
</script>

<template>
	<EmptyState
		v-if="!session.isMfgManager"
		icon="ti ti-lock"
		:title="t('Planning is a manager view')"
		:description="t('Your work orders are on the shift log.')"
	/>

	<template v-else>
		<div class="card mb-3">
			<div class="card-body d-flex flex-wrap gap-2 align-items-center">
				<button type="button" class="btn btn-outline-secondary btn-sm" @click="shiftWindow(-1)">
					<i class="ti ti-chevron-left"></i>
				</button>
				<button type="button" class="btn btn-outline-secondary btn-sm" @click="thisWeek">
					{{ t("This week") }}
				</button>
				<button type="button" class="btn btn-outline-secondary btn-sm" @click="shiftWindow(1)">
					<i class="ti ti-chevron-right"></i>
				</button>
				<div style="width: 12rem">
					<DateInput v-model="startDate" :placeholder="mode === 'day' ? t('Day') : t('Week starting')" />
				</div>
				<div class="btn-group" role="group">
					<button
						type="button"
						class="btn btn-sm btn-outline-secondary"
						:class="mode === 'day' ? 'active' : ''"
						@click="mode = 'day'"
					>{{ t("Day") }}</button>
					<button
						type="button"
						class="btn btn-sm btn-outline-secondary"
						:class="mode === 'week' ? 'active' : ''"
						@click="mode = 'week'"
					>{{ t("Week") }}</button>
				</div>
				<div class="ms-auto text-secondary small">
					<span v-if="grid.counts">
						{{
							t("{0} orders on {1} lines")
								.replace("{0}", grid.counts.orders)
								.replace("{1}", grid.counts.lines)
						}}
					</span>
				</div>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>
		<div v-if="notice" class="alert alert-success py-2">{{ notice }}</div>

		<div v-if="selected" class="alert alert-info py-2 d-flex align-items-center gap-2">
			<i class="ti ti-arrows-move"></i>
			<span>
				{{ t("Pick a day on the same line to move {0}.").replace("{0}", selected.name) }}
				<span class="text-secondary">{{
					t("A line cannot be changed after the order is submitted.")
				}}</span>
			</span>
			<button
				type="button"
				class="btn btn-sm btn-outline-secondary ms-auto"
				@click="selected = null"
			>
				{{ t("Cancel") }}
			</button>
		</div>

		<!-- The hours. A form and not a drag, because a drag moves a block that
		     already has a width and nothing here has one yet: 0 orders on this
		     site carry a planned end, and the planned start is ERPNext's default
		     on 91% of them. This is where that stops being true. -->
		<div v-if="selected" class="card mb-3">
			<div class="card-body d-flex flex-wrap align-items-end gap-2">
				<div>
					<label class="form-label small mb-1">{{ t("Day") }}</label>
					<div style="width: 10rem"><DateInput v-model="sched.day" /></div>
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("Starts") }}</label>
					<input v-model="sched.start" type="time" class="form-control" style="width: 8rem" />
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("Ends") }}</label>
					<input v-model="sched.end" type="time" class="form-control" style="width: 8rem" />
				</div>
				<!-- Asked, never guessed. An end earlier than the start is the same
				     input a planner produces by typing 06:00 and meaning tomorrow,
				     and rolling it forward on their behalf would silently schedule a
				     night nobody agreed to. -->
				<label class="form-check mb-2">
					<input v-model="sched.nextDay" type="checkbox" class="form-check-input" />
					<span class="form-check-label small">{{ t("ends the next day") }}</span>
				</label>
				<button
					type="button"
					class="btn btn-primary ms-auto"
					:disabled="schedSaving || !sched.day || !sched.start"
					@click="saveSchedule"
				>
					<span v-if="schedSaving" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Save hours") }}
				</button>
			</div>
			<div class="card-footer small text-secondary">
				{{ t("Leave the end blank if it is not known yet — the block gets a start and no width.") }}
			</div>
		</div>

		<div class="row g-3">
			<div class="col-12 col-xl-8">
				<!-- «Планирование: линия × время». One row per line, the clock across
				     the top, one block per order.
				     The rule that lets this exist without inventing anything: a block
				     is drawn WIDE only when an end was typed. An order with a start
				     and no end — which is every order on this site until somebody
				     uses the hours form — is a mark at its hour. No default duration,
				     no shift length, no average. The grid starts nearly empty and
				     fills as it is used, because it is the tool that makes the data
				     it draws.
				     Not drawn, each because nothing records the input: a load
				     percentage per line, a rate in units per hour, and shift bands
				     (this factory runs one shift). -->
				<div v-if="mode === 'day'" class="card">
					<div class="card-body">
						<div v-if="loading" class="text-secondary small">{{ t("Loading") }}</div>
						<div v-else>
							<div class="d-flex">
								<div class="text-secondary small" style="width: 11rem; flex: 0 0 11rem">
									{{ t("Line") }}
								</div>
								<div class="position-relative flex-grow-1" style="height: 1.25rem">
									<span
										v-for="h in hourTicks"
										:key="h"
										class="position-absolute small text-secondary font-monospace"
										:style="{ left: tickLeft(h) + '%', transform: 'translateX(-50%)' }"
									>{{ String(h).padStart(2, "0") }}</span>
								</div>
							</div>

							<div
								v-for="row in timeline.rows"
								:key="row.line"
								class="d-flex align-items-center border-top py-2"
							>
								<div class="text-truncate small" style="width: 11rem; flex: 0 0 11rem">{{ row.line }}</div>
								<div class="position-relative flex-grow-1 plan-track">
									<span
										v-for="h in hourTicks"
										:key="h"
										class="position-absolute plan-tick"
										:style="{ left: tickLeft(h) + '%' }"
									></span>

									<template v-for="b in row.blocks" :key="b.order.name">
										<!-- Typed hours: a bar of the width somebody planned. -->
										<div
											v-if="b.width !== null"
											class="position-absolute plan-block"
											:class="statusBadge(b.order.status)"
											:style="{ left: b.left + '%', width: b.width + '%' }"
											:title="`${b.order.name} · ${scheduleLabel(b.order)}`"
											@click="pick(b.order, row.line)"
										>
											<span class="text-truncate d-block">{{ b.order.item_name || b.order.production_item }}</span>
										</div>
										<!-- No end typed. A mark, never a bar: the difference between
										     "runs until 14:30" and "nobody has said" has to stay
										     visible, and it is the difference this screen is for. -->
										<div
											v-else
											class="position-absolute plan-mark"
											:style="{ left: b.left + '%' }"
											:title="`${b.order.name} · ${t('no end planned')}`"
											@click="pick(b.order, row.line)"
										></div>
									</template>
								</div>
							</div>

							<div v-if="!timeline.rows.length" class="text-secondary small py-3">
								{{ t("No lines to plan on.") }}
							</div>

							<!-- Named, not swallowed: an order with no hour, or on a line
							     this grid is not showing, is still work somebody scheduled. -->
							<div v-if="timeline.offGrid.length" class="border-top pt-2 mt-2 small text-secondary">
								{{ t("{0} order(s) have no planned hour yet", [timeline.offGrid.length]) }}
								<a
									v-for="o in timeline.offGrid"
									:key="o.name"
									href="#"
									class="ms-2 font-monospace"
									@click.prevent="pick(o, o.wip_warehouse)"
								>{{ o.name }}</a>
							</div>
						</div>
					</div>
				</div>

				<div v-else class="card">
					<div class="table-responsive">
						<table class="table table-vcenter card-table">
							<thead>
								<tr>
									<th style="min-width: 11rem">{{ t("Line") }}</th>
									<th v-for="day in grid.days" :key="day" :class="{ 'bg-primary-lt': isToday(day) }">
										{{ dayLabel(day) }}
									</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="line in grid.lines" :key="line">
									<td class="text-truncate">{{ line }}</td>
									<td
										v-for="day in grid.days"
										:key="day"
										class="align-top"
										:class="{ 'bg-primary-lt': isTarget(line, day) }"
										style="min-width: 9rem"
										@click="moveTo(line, day)"
									>
										<div
											v-for="order in cell(line, day).orders"
											:key="order.name"
											class="badge d-block text-start mb-1"
											:class="[
												statusBadge(order.status),
												selected?.name === order.name ? 'border border-2 border-dark' : '',
												moving === order.name ? 'opacity-50' : '',
											]"
											style="cursor: pointer; white-space: normal"
											@click.stop="pick(order, line)"
											@dblclick.stop="openOrder(order.name)"
										>
											{{ order.item_name || order.production_item }}
											<span class="d-block fw-normal">
												{{ order.qty }} &middot; {{ statusLabel(order.status) }}
											</span>
											<!-- The payoff for typing the hours. Blank on an order nobody has
											     scheduled, which is every order on this site until somebody uses
											     the form above. -->
											<span v-if="scheduleLabel(order)" class="d-block fw-normal font-monospace">
												{{ scheduleLabel(order) }}
											</span>
										</div>
										<div v-if="cell(line, day).orders.length" class="small text-secondary">
											{{ t("{0} orders").replace("{0}", cell(line, day).orders.length) }}
											&middot; {{ cell(line, day).qty }}
										</div>
										<div v-else-if="isTarget(line, day)" class="small text-primary">
											{{ t("Move here") }}
										</div>
									</td>
								</tr>
							</tbody>
						</table>
					</div>

					<div v-if="loading" class="card-footer text-secondary small">{{ t("Loading") }}</div>
					<div v-else-if="isEmpty" class="card-body">
						<EmptyState
							icon="ti ti-calendar-off"
							:title="t('Nothing is planned for this week')"
							:description="
								t(
									'Orders here are usually opened for the day they run. Move one forward to start planning.'
								)
							"
						/>
					</div>
			</div>
			</div>

			<!-- Design 1c's «ЧТО МЕШАЕТ ЗАПУСКУ». The half of that screen that is
			     backed by data — the line × time grid it sits beside is not, and
			     `launchBlockers.js` carries the measurement that says why.
			     Beside the plan rather than on the board, because it answers a
			     planner's question: not "can this order run" (the board's card chip
			     says that, per order) but "what do I have to chase before any of
			     them can". -->
			<div class="col-12 col-xl-4">
				<div class="card">
					<div class="card-header d-flex align-items-baseline gap-2">
						<h3 class="card-title">{{ t("What blocks the launch") }}</h3>
						<span
							v-if="blockers && blockers.blockers.length"
							class="badge bg-orange-lt ms-auto"
						>{{ blockers.blockers.length }}</span>
					</div>

					<div v-if="blockersLoading" class="card-body text-secondary small">{{ t("Loading") }}</div>

					<!-- Never "nothing is blocking" when nothing was read. The panel
					     failing has to look different from the factory being ready. -->
					<div v-else-if="!blockers" class="card-body text-secondary small">
						{{ t("Stock could not be read, so nothing here was checked.") }}
					</div>

					<div v-else-if="!blockers.blockers.length" class="card-body text-secondary small">
						{{ t("Every waiting order has its materials.") }}
					</div>

					<ul v-else class="list-group list-group-flush">
						<li v-for="b in blockers.blockers" :key="b.warehouse + b.item_code" class="list-group-item">
							<div class="d-flex align-items-baseline gap-2">
								<span class="fw-semibold">{{ b.item_name }}</span>
								<span class="ms-auto font-monospace text-danger">−{{ b.shortfall }}</span>
							</div>
							<div class="small text-secondary">
								{{ t("need {0} · in {1} there is {2}", [b.needed, b.warehouse, b.available]) }}
							</div>
							<div class="small mt-1">
								<span class="text-secondary me-1">{{ t("blocks") }}</span>
								<a
									v-for="name in b.blocks"
									:key="name"
									href="#"
									class="me-2 font-monospace"
									@click.prevent="openOrder(name)"
								>{{ name }}</a>
							</div>
						</li>
					</ul>

					<!-- Counted, never folded in. A shelf `loadStockLevels` could not
					     read is not a shelf that is full, and leaving it out in
					     silence is how a blocker panel says "all clear" about
					     materials nobody looked at. -->
					<div
						v-if="blockers && blockers.unmeasured"
						class="card-footer small text-secondary"
					>
						{{ t("{0} material(s) could not be measured", [blockers.unmeasured]) }}
					</div>
				</div>
			</div>
		</div>

		<!-- Not a feature: the honest catch. An order whose line is blank belongs to
		     no column and would otherwise vanish from a grid that claims to show the
		     week. Measured 0 such orders on anjan, which is exactly why it must be
		     visible if one ever appears. -->
		<div v-if="grid.unscheduled?.length" class="card mt-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Not on any line") }}</h3>
			</div>
			<ul class="list-group list-group-flush">
				<li v-for="order in grid.unscheduled" :key="order.name" class="list-group-item">
					<a href="#" @click.prevent="openOrder(order.name)">{{ order.name }}</a>
					<span class="text-secondary ms-2">{{ order.item_name || order.production_item }}</span>
				</li>
			</ul>
		</div>
	</template>
</template>

<style scoped>
/* The track is the day. Height is fixed so an idle line keeps its row and the
   grid does not change shape as work is planned onto it. */
.plan-track {
	height: 2.75rem;
}

.plan-tick {
	top: 0;
	bottom: 0;
	width: 1px;
	background: var(--tblr-border-color);
	opacity: 0.6;
}

/* Bars own the upper band, marks the lower one — they never share vertical
   space. Measured on prod 2026-08-29 with real hours typed in: all four of the
   day's orders sat on one line and a mark landed at 53.4%, inside a bar
   spanning 43.8%–71.9%. On a single band the mark is drawn under the bar:
   invisible and unclickable, on exactly the order that still needs hours. */
.plan-block {
	top: 0.25rem;
	bottom: 1rem;
	border-radius: 0.25rem;
	padding: 0 0.4rem;
	font-size: 0.75rem;
	line-height: 1.75rem;
	overflow: hidden;
	cursor: pointer;
}

/* An order with a start and no end. Deliberately not a narrow bar: a bar of any
   width is read as a duration, and nobody has said one. */
.plan-mark {
	top: 1.5rem;
	bottom: 0.25rem;
	width: 3px;
	border-radius: 1px;
	background: var(--tblr-secondary);
	cursor: pointer;
}

/* Two marks 0.7% apart on a wide track are 3px bars almost touching. This grows
   the hit area without growing the drawn width, which has to stay a mark. */
.plan-mark::after {
	content: "";
	position: absolute;
	inset: -0.25rem -0.35rem;
}
</style>
