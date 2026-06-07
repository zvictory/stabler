<script setup>
/**
 * DataNode — BPMN data shapes.
 * shape: "page" | "page-in" | "page-out" | "cylinder" | "document" | "collection"
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

const def = computed(() => shapeDef(props.data.shape || "data-object"));
const color = computed(() => props.data.color || def.value.defaultColor || "#868e96");
const shape = computed(() => def.value.shape || "page");

const W = computed(() => def.value.defaultW || 50);
const H = computed(() => def.value.defaultH || 68);

// Data-store cylinder dimensions
const CX = computed(() => W.value / 2);
const RY = 8; // ellipse y-radius for cylinder cap

function onLabelInput(e) {
	emit("update:data", { ...props.data, label: e.target.value });
}
</script>

<template>
	<div
		class="bpm-data-wrap"
		:class="{ 'bpm-node--selected': selected }"
		:style="{ position: 'relative', width: `${W}px` }"
	>
		<!-- Page / page-in / page-out / document / collection -->
		<svg
			v-if="shape !== 'cylinder'"
			:width="W" :height="H"
			:viewBox="`0 0 ${W} ${H}`"
			class="bpm-data-svg"
		>
			<!-- Page with folded corner -->
			<template v-if="shape === 'page' || shape === 'page-in' || shape === 'page-out' || shape === 'collection'">
				<!-- Body (without folded corner area) -->
				<polygon
					:points="`2,2 ${W - 12},2 ${W - 2},12 ${W - 2},${H - 2} 2,${H - 2}`"
					:fill="color + '18'"
					:stroke="color"
					stroke-width="1.8"
				/>
				<!-- Fold -->
				<polyline
					:points="`${W - 12},2 ${W - 12},12 ${W - 2},12`"
					fill="none"
					:stroke="color"
					stroke-width="1.5"
				/>
				<!-- Data-input arrowhead (left, pointing inward) -->
				<polygon
					v-if="shape === 'page-in'"
					:points="`2,${H / 2 - 6} 10,${H / 2} 2,${H / 2 + 6}`"
					:fill="color"
				/>
				<!-- Data-output arrowhead (right) -->
				<polygon
					v-if="shape === 'page-out'"
					:points="`${W - 2},${H / 2 - 6} ${W - 10},${H / 2} ${W - 2},${H / 2 + 6}`"
					:fill="color"
				/>
				<!-- Collection: two vertical lines at bottom -->
				<line v-if="shape === 'collection'" :x1="W / 2 - 5" :y1="H - 10" :x2="W / 2 - 5" :y2="H - 3" :stroke="color" stroke-width="1.5"/>
				<line v-if="shape === 'collection'" :x1="W / 2 + 5" :y1="H - 10" :x2="W / 2 + 5" :y2="H - 3" :stroke="color" stroke-width="1.5"/>
			</template>

			<!-- Document: rounded rect with wavy bottom -->
			<template v-if="shape === 'document'">
				<path
					:d="`M4,4 L${W - 4},4 L${W - 4},${H - 14} Q${W * 0.75},${H - 4} ${W / 2},${H - 14} Q${W * 0.25},${H - 24} 4,${H - 14} Z`"
					:fill="color + '18'"
					:stroke="color"
					stroke-width="1.8"
				/>
			</template>

			<!-- Type icon centered upper area -->
			<foreignObject x="10" y="16" width="30" height="24">
				<i xmlns="http://www.w3.org/1999/xhtml" class="ti" :class="def.icon" :style="`color:${color};font-size:14px;display:block;text-align:center`"></i>
			</foreignObject>
		</svg>

		<!-- Cylinder (data store) -->
		<svg
			v-else
			:width="W" :height="H"
			:viewBox="`0 0 ${W} ${H}`"
			class="bpm-data-svg"
		>
			<!-- Body rect -->
			<rect :x="2" :y="RY" :width="W - 4" :height="H - RY * 2 - 2" :fill="color + '18'" :stroke="color" stroke-width="1.8"/>
			<!-- Top ellipse -->
			<ellipse :cx="CX" :cy="RY" :rx="(W - 4) / 2" :ry="RY - 1" :fill="color + '30'" :stroke="color" stroke-width="1.8"/>
			<!-- Bottom ellipse (visible arc) -->
			<path
				:d="`M2,${H - RY - 2} Q${CX},${H - 2} ${W - 2},${H - RY - 2}`"
				fill="none"
				:stroke="color"
				stroke-width="1.8"
			/>
			<!-- Icon -->
			<foreignObject :x="CX - 10" y="20" width="20" height="20">
				<i xmlns="http://www.w3.org/1999/xhtml" class="ti ti-database" :style="`color:${color};font-size:12px;display:block;text-align:center`"></i>
			</foreignObject>
		</svg>

		<!-- 4 handles -->
		<Handle :id="`${id}-t`" type="source" :position="Position.Top" />
		<Handle :id="`${id}-r`" type="source" :position="Position.Right" />
		<Handle :id="`${id}-b`" type="source" :position="Position.Bottom" />
		<Handle :id="`${id}-l`" type="target" :position="Position.Left" />

		<NodeBadge :badge="data.badge" />

		<!-- Label below shape -->
		<input
			class="bpm-data-label"
			:value="data.label || def.label"
			@input="onLabelInput"
			@click.stop
		/>
	</div>
</template>

<style>
.bpm-data-wrap {
	display: flex;
	flex-direction: column;
	align-items: center;
	user-select: none;
}
.bpm-data-wrap.bpm-node--selected .bpm-data-svg {
	filter: drop-shadow(0 0 0 2px #4299e1);
}
.bpm-data-label {
	margin-top: 3px;
	width: max-content;
	max-width: 90px;
	background: transparent;
	border: none;
	outline: none;
	font-size: 11px;
	text-align: center;
	color: #495057;
	cursor: text;
}
</style>
