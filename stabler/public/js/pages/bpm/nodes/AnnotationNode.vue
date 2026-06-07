<script setup>
/**
 * AnnotationNode — BPMN artifacts.
 * shape: "bracket" (text annotation) | "group" (dashed rectangle)
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

const def = computed(() => shapeDef(props.data.shape || "annotation"));
const color = computed(() => props.data.color || def.value.defaultColor || "#495057");
const isGroup = computed(() => def.value.shape === "group");

const W = computed(() => def.value.defaultW || 140);
const H = computed(() => def.value.defaultH || 50);

function onLabelInput(e) {
	emit("update:data", { ...props.data, label: e.target.value });
}
</script>

<template>
	<!-- Annotation bracket -->
	<div
		v-if="!isGroup"
		class="bpm-annotation"
		:class="{ 'bpm-node--selected': selected }"
		:style="{ width: `${W}px`, minHeight: `${H}px`, borderLeft: `3px solid ${color}` }"
	>
		<textarea
			class="bpm-annotation-text"
			:value="data.label || def.label"
			@input="onLabelInput"
			@click.stop
			rows="2"
		></textarea>

		<Handle :id="`${id}-t`" type="source" :position="Position.Top" />
		<Handle :id="`${id}-r`" type="source" :position="Position.Right" />
		<Handle :id="`${id}-b`" type="source" :position="Position.Bottom" />
		<Handle :id="`${id}-l`" type="target" :position="Position.Left" />
		<NodeBadge :badge="data.badge" />
	</div>

	<!-- Group: dashed container -->
	<div
		v-else
		class="bpm-group"
		:class="{ 'bpm-node--selected': selected }"
		:style="{
			width: `${W}px`,
			height: `${H}px`,
			border: `2px dashed ${color}`,
			borderRadius: '8px',
		}"
	>
		<input
			class="bpm-group-label"
			:value="data.label || def.label"
			:style="{ color }"
			@input="onLabelInput"
			@click.stop
		/>
		<Handle :id="`${id}-t`" type="source" :position="Position.Top" />
		<Handle :id="`${id}-r`" type="source" :position="Position.Right" />
		<Handle :id="`${id}-b`" type="source" :position="Position.Bottom" />
		<Handle :id="`${id}-l`" type="target" :position="Position.Left" />
		<NodeBadge :badge="data.badge" />
	</div>
</template>

<style>
.bpm-annotation {
	position: relative;
	background: rgba(255, 255, 255, 0.9);
	padding: 6px 8px;
	border-radius: 0 4px 4px 0;
	box-shadow: 0 1px 4px rgba(0,0,0,.08);
}
.bpm-annotation.bpm-node--selected {
	box-shadow: 0 0 0 2px #4299e1;
}
.bpm-annotation-text {
	width: 100%;
	background: transparent;
	border: none;
	outline: none;
	font-size: 11px;
	color: #343a40;
	resize: none;
	cursor: text;
	font-family: inherit;
}
.bpm-group {
	position: relative;
	background: transparent;
}
.bpm-group.bpm-node--selected {
	box-shadow: 0 0 0 2px #4299e1;
	border-radius: 8px;
}
.bpm-group-label {
	position: absolute;
	top: 6px;
	left: 10px;
	background: transparent;
	border: none;
	outline: none;
	font-size: 12px;
	font-weight: 600;
	cursor: text;
}
</style>
