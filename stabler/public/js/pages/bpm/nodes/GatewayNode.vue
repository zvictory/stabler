<script setup>
/**
 * GatewayNode — BPMN diamond gateways.
 * glyph: "X" (exclusive) | "+" (parallel) | "O" (inclusive) |
 *         "E" (event-based) | "*" (complex)
 * Keeps -yes / -no source handles for auto-labeled Yes/No edges.
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

const def = computed(() => shapeDef(props.data.shape || "gateway-exclusive"));
const color = computed(() => props.data.color || def.value.defaultColor || "#f59f00");

// SVG in 60×60 viewBox — diamond polygon points
const W = 60;
const H = 60;
const HW = W / 2; // 30
const HH = H / 2; // 30
const PAD = 3;    // inset from edge

// Inner glyph: SVG text for X/+/O/E/*, or path for special
const glyph = computed(() => def.value.glyph || "X");

// For inclusive (O): render an inner circle instead of text
const isInclusive = computed(() => glyph.value === "O");
// For event-based (E): render inner pentagon
const isEventBased = computed(() => glyph.value === "E");

// Pentagon points for event-based gateway (inscribed in r=10)
function pentagonPoints(cx, cy, r) {
	return Array.from({ length: 5 }, (_, i) => {
		const angle = (Math.PI * 2 * i) / 5 - Math.PI / 2;
		return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
	}).join(" ");
}

function onLabelInput(e) {
	emit("update:data", { ...props.data, label: e.target.value });
}
</script>

<template>
	<div class="bpm-gateway-wrap" :class="{ 'bpm-node--selected': selected }">
		<svg :width="W" :height="H" :viewBox="`0 0 ${W} ${H}`" class="bpm-gateway-svg">
			<!-- Diamond -->
			<polygon
				:points="`${HW},${PAD} ${W - PAD},${HH} ${HW},${H - PAD} ${PAD},${HH}`"
				:fill="color + '22'"
				:stroke="color"
				stroke-width="2"
			/>

			<!-- Exclusive: × -->
			<template v-if="glyph === 'X'">
				<line x1="22" y1="22" x2="38" y2="38" :stroke="color" stroke-width="3" stroke-linecap="round"/>
				<line x1="38" y1="22" x2="22" y2="38" :stroke="color" stroke-width="3" stroke-linecap="round"/>
			</template>

			<!-- Parallel: + -->
			<template v-else-if="glyph === '+'">
				<line :x1="HW" y1="18" :x2="HW" y2="42" :stroke="color" stroke-width="3" stroke-linecap="round"/>
				<line x1="18" :y1="HH" x2="42" :y2="HH" :stroke="color" stroke-width="3" stroke-linecap="round"/>
			</template>

			<!-- Inclusive: inner circle -->
			<circle
				v-else-if="isInclusive"
				:cx="HW" :cy="HH" r="9"
				fill="none"
				:stroke="color"
				stroke-width="2.5"
			/>

			<!-- Event-based: inner pentagon -->
			<polygon
				v-else-if="isEventBased"
				:points="pentagonPoints(HW, HH, 10)"
				fill="none"
				:stroke="color"
				stroke-width="1.5"
			/>

			<!-- Complex: * -->
			<template v-else-if="glyph === '*'">
				<line :x1="HW" y1="17" :x2="HW" y2="43" :stroke="color" stroke-width="2.5" stroke-linecap="round"/>
				<line x1="17" :y1="HH" x2="43" :y2="HH" :stroke="color" stroke-width="2.5" stroke-linecap="round"/>
				<line x1="21" y1="21" x2="39" y2="39" :stroke="color" stroke-width="2.5" stroke-linecap="round"/>
				<line x1="39" y1="21" x2="21" y2="39" :stroke="color" stroke-width="2.5" stroke-linecap="round"/>
			</template>
		</svg>

		<!-- 4 directional handles -->
		<Handle :id="`${id}-t`"   type="source" :position="Position.Top" />
		<Handle :id="`${id}-r`"   type="source" :position="Position.Right" />
		<Handle :id="`${id}-b`"   type="source" :position="Position.Bottom" />
		<Handle :id="`${id}-l`"   type="target" :position="Position.Left" />
		<!-- Yes / No labelled handles (kept for auto-labelling on connect) -->
		<Handle :id="`${id}-yes`" type="source" :position="Position.Top"   style="opacity:0" />
		<Handle :id="`${id}-no`"  type="source" :position="Position.Right" style="opacity:0" />

		<NodeBadge :badge="data.badge" />

		<!-- Label below diamond -->
		<input
			class="bpm-gateway-label"
			:value="data.label || def.label"
			@input="onLabelInput"
			@click.stop
		/>
	</div>
</template>

<style>
.bpm-gateway-wrap {
	position: relative;
	display: flex;
	flex-direction: column;
	align-items: center;
	user-select: none;
}
.bpm-gateway-wrap.bpm-node--selected .bpm-gateway-svg {
	filter: drop-shadow(0 0 0 3px #4299e1);
}
.bpm-gateway-label {
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
