<script setup>
/**
 * EventNode — BPMN circle events.
 * ring: "start" (thin)  | "intermediate" / "throw" (double ring)  | "end" (thick)
 * trigger: drives the inner SVG glyph.
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

const def = computed(() => shapeDef(props.data.shape || "event-start-none"));
const ring = computed(() => def.value.ring || "start");
const trigger = computed(() => def.value.trigger || "none");
const color = computed(() => props.data.color || def.value.defaultColor || "#2fb344");

// Stroke widths per ring type
const outerStroke = computed(() => ring.value === "end" ? 4 : 2);
const hasInnerRing = computed(() => ring.value === "intermediate" || ring.value === "throw");

// SVG radii (viewBox = 44×44, centre at 22,22)
const R_OUTER = 19;
const R_INNER = 14; // second ring for intermediate/throw

// Trigger → icon class (Tabler)
const iconClass = computed(() => def.value.icon || "ti-circle");

// For throw events, glyph is filled (darker). For catch, outlined.
const glyphFilled = computed(() => ring.value === "end" || ring.value === "throw");

function onLabelInput(e) {
	emit("update:data", { ...props.data, label: e.target.value });
}
</script>

<template>
	<div class="bpm-event-wrap" :class="{ 'bpm-node--selected': selected }">
		<!-- SVG rings -->
		<svg
			:width="def.defaultW"
			:height="def.defaultH"
			:viewBox="`0 0 ${def.defaultW} ${def.defaultH}`"
			class="bpm-event-svg"
		>
			<!-- outer ring (always present) -->
			<circle
				:cx="def.defaultW / 2"
				:cy="def.defaultH / 2"
				:r="R_OUTER"
				:fill="color"
				:stroke="color"
				:stroke-width="outerStroke"
				stroke-opacity="0.6"
				fill-opacity="0.15"
			/>
			<!-- inner ring for intermediate/throw -->
			<circle
				v-if="hasInnerRing"
				:cx="def.defaultW / 2"
				:cy="def.defaultH / 2"
				:r="R_INNER"
				fill="none"
				:stroke="color"
				stroke-width="1.5"
			/>
			<!-- terminate: filled inner circle -->
			<circle
				v-if="trigger === 'terminate'"
				:cx="def.defaultW / 2"
				:cy="def.defaultH / 2"
				r="8"
				:fill="color"
			/>
		</svg>

		<!-- Trigger icon, centred -->
		<i
			v-if="trigger !== 'none' && trigger !== 'terminate'"
			class="ti bpm-event-glyph"
			:class="iconClass"
			:style="{ color, opacity: glyphFilled ? 0.9 : 0.75, fontSize: '13px' }"
		></i>

		<!-- 4 handles (T/R/B/L) so connections work in both orientations -->
		<Handle :id="`${id}-t`" type="source" :position="Position.Top" />
		<Handle :id="`${id}-r`" type="source" :position="Position.Right" />
		<Handle :id="`${id}-b`" type="source" :position="Position.Bottom" />
		<Handle :id="`${id}-l`" type="target" :position="Position.Left" />

		<NodeBadge :badge="data.badge" />

		<!-- Label below the circle -->
		<input
			class="bpm-event-label"
			:value="data.label || def.label"
			@input="onLabelInput"
			@click.stop
		/>
	</div>
</template>

<style>
.bpm-event-wrap {
	position: relative;
	display: flex;
	flex-direction: column;
	align-items: center;
	user-select: none;
}
.bpm-event-wrap.bpm-node--selected .bpm-event-svg {
	filter: drop-shadow(0 0 0 3px #4299e1);
}
.bpm-event-svg {
	display: block;
	border-radius: 50%;
	transition: filter 0.15s;
}
.bpm-event-glyph {
	position: absolute;
	top: 0;
	left: 0;
	width: 44px;
	height: 44px;
	display: flex;
	align-items: center;
	justify-content: center;
	pointer-events: none;
}
.bpm-event-label {
	margin-top: 4px;
	width: max-content;
	max-width: 100px;
	background: transparent;
	border: none;
	outline: none;
	font-size: 11px;
	text-align: center;
	color: #495057;
	cursor: text;
}
</style>
