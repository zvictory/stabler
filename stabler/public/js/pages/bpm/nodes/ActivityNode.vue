<script setup>
/**
 * ActivityNode — BPMN rounded-rect tasks, sub-processes, call activities.
 * marker: null | "plus" (sub-process ＋) | "thick" (call-activity thick border)
 */
import { computed } from "vue";
import { Handle, Position } from "@vue-flow/core";
import { shapeDef } from "../shapes.js";
import NodeBadge from "./NodeBadge.vue";

const props = defineProps({
	id:       { type: String, required: true },
	data:     { type: Object, required: true },
	selected: { type: Boolean, default: false },
});

const emit = defineEmits(["update:data"]);

const def = computed(() => shapeDef(props.data.shape || "task"));
const color = computed(() => props.data.color || def.value.defaultColor || "#4299e1");
const isCallActivity = computed(() => def.value.marker === "thick");
const hasPlus = computed(() => def.value.marker === "plus");

// Darker border from color (just use same color at higher opacity)
const borderColor = computed(() => color.value);
const borderWidth = computed(() => isCallActivity.value ? "3px" : "2px");

function onLabelInput(e) {
	emit("update:data", { ...props.data, label: e.target.value });
}
</script>

<template>
	<div
		class="bpm-activity"
		:class="{ 'bpm-node--selected': selected }"
		:style="{
			width: `${def.defaultW}px`,
			height: `${def.defaultH}px`,
			backgroundColor: color + '22',
			border: `${borderWidth} solid ${borderColor}`,
			borderRadius: '8px',
			position: 'relative',
		}"
	>
		<!-- Type icon — top-left -->
		<i
			v-if="def.icon && def.icon !== 'ti-square'"
			class="ti bpm-activity-icon"
			:class="def.icon"
			:style="{ color }"
		></i>

		<!-- Inline label (center) -->
		<input
			class="bpm-node__label bpm-activity-label"
			:value="data.label || def.label"
			@input="onLabelInput"
			@click.stop
		/>

		<!-- Sub-process ＋ marker (bottom-center) -->
		<div v-if="hasPlus" class="bpm-subprocess-marker" :style="{ color, borderColor: borderColor }">＋</div>

		<!-- 4 handles -->
		<Handle :id="`${id}-t`" type="source" :position="Position.Top" />
		<Handle :id="`${id}-r`" type="source" :position="Position.Right" />
		<Handle :id="`${id}-b`" type="source" :position="Position.Bottom" />
		<Handle :id="`${id}-l`" type="target" :position="Position.Left" />

		<!-- Yes/No handles (for backward compat with gateway-style wiring if needed) -->

		<NodeBadge :badge="data.badge" />
	</div>
</template>

<style>
.bpm-activity {
	display: flex;
	align-items: center;
	justify-content: center;
	box-shadow: 0 2px 6px rgba(0,0,0,.10);
	cursor: default;
	transition: box-shadow 0.15s;
}
.bpm-activity.bpm-node--selected {
	box-shadow: 0 0 0 3px #4299e1, 0 2px 6px rgba(0,0,0,.10);
}
.bpm-activity-icon {
	position: absolute;
	top: 5px;
	left: 6px;
	font-size: 12px;
	opacity: 0.7;
	pointer-events: none;
}
.bpm-activity-label {
	width: calc(100% - 16px);
	text-align: center;
	color: #1e293b;
	font-size: 12px;
	font-weight: 500;
}
.bpm-subprocess-marker {
	position: absolute;
	bottom: 3px;
	left: 50%;
	transform: translateX(-50%);
	width: 16px;
	height: 16px;
	border: 1.5px solid;
	border-radius: 2px;
	display: flex;
	align-items: center;
	justify-content: center;
	font-size: 11px;
	line-height: 1;
	background: #fff;
	pointer-events: none;
}
</style>
