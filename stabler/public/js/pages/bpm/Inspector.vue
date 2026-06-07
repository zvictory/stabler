<script setup>
/**
 * Inspector — right-side properties panel.
 * Shows when exactly one node OR one edge is selected.
 * Emits update:node / update:edge with a diff object (not a full clone).
 */
import { computed, ref, watch } from "vue";
import { t } from "../../composables/i18n.js";
import { SHAPE_CATALOG, CATEGORY_META, CATEGORY_ORDER, shapeDef } from "./shapes.js";

const props = defineProps({
	node:  { type: Object, default: null }, // selected vue-flow node | null
	edge:  { type: Object, default: null }, // selected vue-flow edge | null
	lanes: { type: Array,  default: () => [] },
});

const emit = defineEmits(["update:node", "update:edge"]);

// ── Local editable copies (synced from props) ────────────────────────────────
const nodeLabel = ref("");
const nodeShape = ref("task");
const nodeColor = ref("#4299e1");
const nodeBadge = ref(null);
const nodeLane  = ref("");

const edgeLabel  = ref("");
const edgeDashed = ref(false);
const edgeAnimated = ref(false);

watch(() => props.node, (n) => {
	if (!n) return;
	nodeLabel.value   = n.data.label  || "";
	nodeShape.value   = n.data.shape  || "task";
	nodeColor.value   = n.data.color  || "#4299e1";
	nodeBadge.value   = n.data.badge  || null;
	nodeLane.value    = n.data.laneId || "";
}, { immediate: true, deep: true });

watch(() => props.edge, (e) => {
	if (!e) return;
	edgeLabel.value    = e.label || "";
	edgeDashed.value   = e.data?.dashed   || false;
	edgeAnimated.value = e.animated || false;
}, { immediate: true, deep: true });

// ── Shape selector: grouped by category ──────────────────────────────────────
const groupedShapes = computed(() => {
	return CATEGORY_ORDER.map((cat) => ({
		cat,
		meta: CATEGORY_META[cat],
		shapes: SHAPE_CATALOG.filter((s) => s.category === cat),
	}));
});

// ── Emit helpers ─────────────────────────────────────────────────────────────
function applyNodeLabel() {
	if (!props.node) return;
	emit("update:node", { id: props.node.id, data: { ...props.node.data, label: nodeLabel.value } });
}

function applyNodeShape(shapeKey) {
	if (!props.node) return;
	const def = shapeDef(shapeKey);
	emit("update:node", {
		id: props.node.id,
		type: def.category,                // renderer component switches
		data: {
			...props.node.data,
			shape: shapeKey,
			color: nodeColor.value,
			label: nodeLabel.value,
		},
	});
}

function applyNodeColor() {
	if (!props.node) return;
	emit("update:node", { id: props.node.id, data: { ...props.node.data, color: nodeColor.value } });
}

function applyNodeBadge(badge) {
	if (!props.node) return;
	nodeBadge.value = nodeBadge.value === badge ? null : badge;
	emit("update:node", { id: props.node.id, data: { ...props.node.data, badge: nodeBadge.value } });
}

function applyNodeLane(laneId) {
	if (!props.node) return;
	emit("update:node", { id: props.node.id, data: { ...props.node.data, laneId } });
}

function applyEdgeLabel() {
	if (!props.edge) return;
	emit("update:edge", { id: props.edge.id, label: edgeLabel.value });
}

function applyEdgeDashed() {
	if (!props.edge) return;
	const dashed = !edgeDashed.value;
	edgeDashed.value = dashed;
	emit("update:edge", {
		id: props.edge.id,
		style: { strokeDasharray: dashed ? "6 4" : "" },
		data: { ...(props.edge.data || {}), dashed },
	});
}

function applyEdgeAnimated() {
	if (!props.edge) return;
	const animated = !edgeAnimated.value;
	edgeAnimated.value = animated;
	emit("update:edge", { id: props.edge.id, animated });
}
</script>

<template>
	<div class="bpm-inspector card" style="width: 200px; flex-shrink: 0">
		<!-- Node inspector -->
		<template v-if="node">
			<div class="card-header py-2 small fw-semibold d-flex align-items-center gap-1">
				<i class="ti ti-adjustments-horizontal text-muted"></i>
				{{ t("Properties") }}
			</div>
			<div class="card-body p-2 d-flex flex-column gap-3">

				<!-- Label -->
				<div>
					<label class="form-label form-label-sm mb-1 text-muted">{{ t("Label") }}</label>
					<input
						v-model="nodeLabel"
						type="text"
						class="form-control form-control-sm"
						@change="applyNodeLabel"
						@blur="applyNodeLabel"
					/>
				</div>

				<!-- Shape -->
				<div>
					<label class="form-label form-label-sm mb-1 text-muted">{{ t("Shape") }}</label>
					<select
						v-model="nodeShape"
						class="form-select form-select-sm"
						@change="applyNodeShape(nodeShape)"
					>
						<optgroup
							v-for="group in groupedShapes"
							:key="group.cat"
							:label="t(group.meta.label)"
						>
							<option v-for="s in group.shapes" :key="s.key" :value="s.key">
								{{ t(s.label) }}
							</option>
						</optgroup>
					</select>
				</div>

				<!-- Color -->
				<div class="d-flex align-items-center gap-2">
					<label class="form-label form-label-sm mb-0 text-muted flex-grow-1">{{ t("Color") }}</label>
					<input
						v-model="nodeColor"
						type="color"
						class="form-control form-control-color p-0 border-0"
						style="width: 30px; height: 28px; cursor: pointer; border-radius: 4px"
						@change="applyNodeColor"
					/>
				</div>

				<!-- Badge -->
				<div>
					<label class="form-label form-label-sm mb-1 text-muted">{{ t("Badge") }}</label>
					<div class="d-flex gap-1">
						<button
							v-for="b in ['success', 'danger', 'warning']"
							:key="b"
							type="button"
							class="btn btn-sm flex-grow-1"
							:class="nodeBadge === b
								? (b === 'success' ? 'btn-success' : b === 'danger' ? 'btn-danger' : 'btn-warning')
								: 'btn-outline-secondary'"
							@click="applyNodeBadge(b)"
						>
							{{ b === 'success' ? '✓' : b === 'danger' ? '✕' : '!' }}
						</button>
					</div>
				</div>

				<!-- Lane assignment -->
				<div v-if="lanes.length">
					<label class="form-label form-label-sm mb-1 text-muted">{{ t("Lane") }}</label>
					<select
						v-model="nodeLane"
						class="form-select form-select-sm"
						@change="applyNodeLane(nodeLane)"
					>
						<option value="">{{ t("(none)") }}</option>
						<option v-for="lane in lanes" :key="lane.id" :value="lane.id">
							{{ lane.label }}
						</option>
					</select>
				</div>
			</div>
		</template>

		<!-- Edge inspector -->
		<template v-else-if="edge">
			<div class="card-header py-2 small fw-semibold d-flex align-items-center gap-1">
				<i class="ti ti-arrow-right text-muted"></i>
				{{ t("Connector") }}
			</div>
			<div class="card-body p-2 d-flex flex-column gap-3">

				<!-- Edge label -->
				<div>
					<label class="form-label form-label-sm mb-1 text-muted">{{ t("Label") }}</label>
					<input
						v-model="edgeLabel"
						type="text"
						class="form-control form-control-sm"
						:placeholder="t('e.g. OK, Approved')"
						@change="applyEdgeLabel"
						@blur="applyEdgeLabel"
					/>
				</div>

				<!-- Dashed -->
				<div class="form-check form-switch mb-0">
					<input
						id="edge-dashed"
						class="form-check-input"
						type="checkbox"
						:checked="edgeDashed"
						@change="applyEdgeDashed"
					/>
					<label class="form-check-label small" for="edge-dashed">{{ t("Dashed") }}</label>
				</div>

				<!-- Animated -->
				<div class="form-check form-switch mb-0">
					<input
						id="edge-animated"
						class="form-check-input"
						type="checkbox"
						:checked="edgeAnimated"
						@change="applyEdgeAnimated"
					/>
					<label class="form-check-label small" for="edge-animated">{{ t("Animated") }}</label>
				</div>
			</div>
		</template>

		<!-- Nothing selected -->
		<template v-else>
			<div class="card-body p-3 text-center text-muted small">
				<i class="ti ti-cursor-text d-block mb-2" style="font-size: 22px; opacity: 0.4"></i>
				{{ t("Select a shape or connector to edit its properties.") }}
			</div>
		</template>
	</div>
</template>
