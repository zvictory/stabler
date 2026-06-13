<script setup>
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";

const props = defineProps({
	lanes: { type: Array, default: () => [] },
});

const emit = defineEmits(["update:lanes", "remove-lane-nodes"]);

const LANE_COLORS = [
	"#e8f4fd", "#fff3e0", "#f3e5f5", "#e8f5e9",
	"#fce4ec", "#e0f7fa", "#fff8e1", "#f1f8e9",
];

function updateLanes(lanes) {
	emit("update:lanes", lanes);
}

function addLane() {
	const order = props.lanes.length;
	const color = LANE_COLORS[order % LANE_COLORS.length];
	const newLane = {
		id: `lane-${crypto.randomUUID()}`,
		label: `${t("Lane")} ${order + 1}`,
		color,
		order,
	};
	updateLanes([...props.lanes, newLane]);
}

const { confirm } = useConfirm();

async function removeLane(lane) {
	const ok = await confirm({
		title: t("Remove Lane?"),
		body: `${t("Remove Lane")} "${lane.label}"?`,
		danger: true,
	});
	if (!ok) return;
	emit("remove-lane-nodes", lane.id);
	updateLanes(props.lanes.filter((l) => l.id !== lane.id).map((l, i) => ({ ...l, order: i })));
}

function onLabelChange(lane, value) {
	updateLanes(props.lanes.map((l) => (l.id === lane.id ? { ...l, label: value } : l)));
}

function onColorChange(lane, value) {
	updateLanes(props.lanes.map((l) => (l.id === lane.id ? { ...l, color: value } : l)));
}

function moveLane(idx, dir) {
	const newLanes = [...props.lanes];
	const swap = idx + dir;
	if (swap < 0 || swap >= newLanes.length) return;
	[newLanes[idx], newLanes[swap]] = [newLanes[swap], newLanes[idx]];
	updateLanes(newLanes.map((l, i) => ({ ...l, order: i })));
}
</script>

<template>
	<div class="bpm-lane-editor card">
		<div class="card-header py-2 d-flex align-items-center justify-content-between">
			<span class="small fw-semibold">{{ t("Lanes") }}</span>
			<button type="button" class="btn btn-ghost-primary btn-sm btn-icon" :title="t('Add Lane')" @click="addLane">
				<i class="ti ti-plus"></i>
			</button>
		</div>
		<div class="card-body p-2 d-flex flex-column gap-2" style="max-height: 280px; overflow-y: auto">
			<div
				v-for="(lane, idx) in lanes"
				:key="lane.id"
				class="d-flex align-items-center gap-1"
			>
				<input
					type="color"
					class="form-control form-control-color p-0 border-0"
					style="width: 24px; height: 24px; cursor: pointer; border-radius: 4px"
					:value="lane.color"
					:title="t('Color')"
					@input="onColorChange(lane, $event.target.value)"
				/>
				<input
					type="text"
					class="form-control form-control-sm flex-grow-1"
					:value="lane.label"
					@change="onLabelChange(lane, $event.target.value)"
				/>
				<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :disabled="idx === 0" @click="moveLane(idx, -1)">
					<i class="ti ti-arrow-up"></i>
				</button>
				<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :disabled="idx === lanes.length - 1" @click="moveLane(idx, 1)">
					<i class="ti ti-arrow-down"></i>
				</button>
				<button type="button" class="btn btn-ghost-danger btn-icon btn-sm" @click="removeLane(lane)">
					<i class="ti ti-trash"></i>
				</button>
			</div>
			<div v-if="!lanes.length" class="text-secondary small text-center py-2">
				{{ t("No lanes. Click + to add.") }}
			</div>
		</div>
	</div>
</template>
