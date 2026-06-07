<script setup>
/**
 * NodePalette — categorised, draggable BPMN 2.0 shape bank.
 * Each tile can be dragged onto the canvas (primary) or clicked (fallback → adds at center).
 * Drag data: DataTransfer key "application/bpm-shape" = shapeKey string.
 */
import { ref } from "vue";
import { t } from "../../composables/i18n.js";
import { SHAPE_CATALOG, CATEGORY_META, CATEGORY_ORDER } from "./shapes.js";

const emit = defineEmits(["add"]);

// Collapsed state per category
const collapsed = ref(new Set());

function toggleCategory(cat) {
	if (collapsed.value.has(cat)) {
		collapsed.value.delete(cat);
	} else {
		collapsed.value.add(cat);
	}
	// Trigger reactivity on the Set (Vue 3 tracks Set mutations via reactive)
	collapsed.value = new Set(collapsed.value);
}

// Group shapes by category
const groups = CATEGORY_ORDER.map((cat) => ({
	cat,
	meta: CATEGORY_META[cat],
	shapes: SHAPE_CATALOG.filter((s) => s.category === cat),
}));

// ── Drag ──────────────────────────────────────────────────────────────────────
function onDragStart(event, shapeKey) {
	event.dataTransfer.effectAllowed = "copy";
	event.dataTransfer.setData("application/bpm-shape", shapeKey);
}

// ── Click-to-add fallback ─────────────────────────────────────────────────────
function addByClick(shapeKey) {
	emit("add", { shapeKey });
}
</script>

<template>
	<div class="bpm-palette card">
		<div class="card-header py-2 small fw-semibold d-flex align-items-center gap-1">
			<i class="ti ti-shapes text-muted"></i>
			{{ t("Shapes") }}
		</div>

		<div class="card-body p-0 bpm-palette-body">
			<div v-for="group in groups" :key="group.cat">
				<!-- Category header (collapsible) -->
				<button
					type="button"
					class="bpm-palette-cat d-flex align-items-center gap-1 w-100 border-0 bg-transparent px-2 py-1"
					@click="toggleCategory(group.cat)"
				>
					<i class="ti" :class="group.meta.icon" style="font-size: 12px; opacity: 0.6"></i>
					<span class="small fw-semibold text-secondary flex-grow-1 text-start" style="font-size: 11px">
						{{ t(group.meta.label) }}
					</span>
					<i
						class="ti"
						:class="collapsed.has(group.cat) ? 'ti-chevron-right' : 'ti-chevron-down'"
						style="font-size: 10px; opacity: 0.4"
					></i>
				</button>

				<!-- Shapes grid (hidden when collapsed) -->
				<div v-if="!collapsed.has(group.cat)" class="bpm-palette-shapes px-2 pb-2">
					<div
						v-for="s in group.shapes"
						:key="s.key"
						class="bpm-palette-tile"
						:title="t(s.label)"
						draggable="true"
						@dragstart="onDragStart($event, s.key)"
						@click="addByClick(s.key)"
					>
						<i
							class="ti bpm-palette-tile-icon"
							:class="s.icon"
							:style="{ color: s.defaultColor }"
						></i>
						<span class="bpm-palette-tile-label">{{ t(s.label) }}</span>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<style>
.bpm-palette-body {
	overflow-y: auto;
	max-height: calc(100vh - 260px);
}
.bpm-palette-cat {
	cursor: pointer;
	border-bottom: 1px solid #f1f3f5 !important;
	border-radius: 0;
}
.bpm-palette-cat:hover {
	background: #f8f9fa !important;
}
.bpm-palette-shapes {
	display: flex;
	flex-direction: column;
	gap: 1px;
}
.bpm-palette-tile {
	display: flex;
	align-items: center;
	gap: 6px;
	padding: 4px 6px;
	border-radius: 5px;
	cursor: grab;
	user-select: none;
	font-size: 12px;
}
.bpm-palette-tile:hover {
	background: #f1f3f5;
}
.bpm-palette-tile:active {
	cursor: grabbing;
}
.bpm-palette-tile-icon {
	font-size: 14px;
	flex-shrink: 0;
	width: 18px;
	text-align: center;
}
.bpm-palette-tile-label {
	color: #495057;
	font-size: 11px;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}
</style>
