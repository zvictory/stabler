<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useWorkOrderStatus } from "../../composables/workOrderStatus.js";
import { todayIso } from "../../composables/date.js";
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

const endDate = computed(() => addDays(startDate.value, WINDOW_DAYS - 1));
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
	startDate.value = addDays(startDate.value, n * WINDOW_DAYS);
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

watch([activeCompany, startDate], load);
onMounted(load);
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
					<DateInput v-model="startDate" :placeholder="t('Week starting')" />
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

		<div class="card">
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
