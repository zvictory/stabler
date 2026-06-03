<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

// A click-to-open, fixed-list dropdown styled to the shadcn "new-york" look.
// It deliberately mirrors Typeahead.vue's architecture (options array + Teleport
// + computeMenuStyle + keyboard cursor) rather than a Radix-style compound, so
// the two share positioning code and the shared `.stbl-menu` visual layer.
//
// Drop-in for native <select>: v-model carries the same string/number value, so
// backend payloads are unchanged. Options may be objects (use valueKey/labelKey)
// or primitives (value === label).
const props = defineProps({
	modelValue: { type: [String, Number, null], default: "" },
	options: { type: Array, default: () => [] },
	valueKey: { type: String, default: "value" },
	labelKey: { type: String, default: "label" },
	// Prompt shown (muted) when nothing is selected AND no option matches the
	// current value. A selectable empty-value option (e.g. "All") should instead
	// live in `options` so it shows its own label once chosen.
	placeholder: { type: String, default: "Select…" },
	size: { type: String, default: "md" },
	disabled: { type: Boolean, default: false },
	clearable: { type: Boolean, default: false },
	menuMinWidth: { type: String, default: "100%" },
});

// inheritAttrs:false so class/style (font-monospace, max-width, etc.) from the
// call site land on the trigger button, not the outer wrapper.
defineOptions({ inheritAttrs: false });

const emit = defineEmits(["update:modelValue", "change"]);

const triggerEl = ref(null);
const menuEl = ref(null);
const open = ref(false);
const activeIdx = ref(-1);
const menuStyle = ref({});

const isPrimitive = (o) => o === null || typeof o !== "object";
const optionValue = (o) => (isPrimitive(o) ? o : o[props.valueKey]);
const optionLabel = (o) => (isPrimitive(o) ? String(o ?? "") : o[props.labelKey]);
const optionDisabled = (o) => (isPrimitive(o) ? false : !!o.disabled);

const selectedOption = computed(
	() => props.options.find((o) => optionValue(o) === props.modelValue) ?? null
);
const hasValue = computed(() => props.modelValue !== "" && props.modelValue != null);

const triggerClass = computed(() => ["form-select", "stbl-select-trigger", { "form-select-sm": props.size === "sm" }]);

// ── Positioning (copied from Typeahead.vue so the menus anchor identically) ──
function computeMenuStyle() {
	const anchor = triggerEl.value;
	if (!anchor) return;
	const r = anchor.getBoundingClientRect();
	const minW = props.menuMinWidth === "100%" ? `${r.width}px` : props.menuMinWidth;
	const spaceBelow = window.innerHeight - r.bottom;
	const spaceAbove = r.top;
	const flipUp = spaceBelow < 160 && spaceAbove > spaceBelow;
	const available = flipUp ? spaceAbove : spaceBelow;
	const maxH = `${Math.min(280, Math.max(120, available - 8))}px`;
	const base = {
		position: "fixed",
		left: `${r.left}px`,
		minWidth: minW,
		width: `${r.width}px`,
		maxHeight: maxH,
		overflowY: "auto",
		zIndex: 2000,
	};
	menuStyle.value = flipUp
		? { ...base, bottom: `${window.innerHeight - r.top + 4}px` }
		: { ...base, top: `${r.bottom + 4}px` };
}

function onScrollOrResize() {
	if (open.value) computeMenuStyle();
}

watch(open, async (v) => {
	if (v) {
		await nextTick();
		computeMenuStyle();
		window.addEventListener("scroll", onScrollOrResize, true);
		window.addEventListener("resize", onScrollOrResize);
		scrollActiveIntoView();
	} else {
		window.removeEventListener("scroll", onScrollOrResize, true);
		window.removeEventListener("resize", onScrollOrResize);
	}
});

onBeforeUnmount(() => {
	window.removeEventListener("scroll", onScrollOrResize, true);
	window.removeEventListener("resize", onScrollOrResize);
});

async function scrollActiveIntoView() {
	await nextTick();
	if (!menuEl.value || activeIdx.value < 0) return;
	const rows = menuEl.value.querySelectorAll(".stbl-menu-item");
	rows[activeIdx.value]?.scrollIntoView({ block: "nearest" });
}

function openMenu() {
	if (props.disabled) return;
	open.value = true;
	// Start the cursor on the selected row (or the first one).
	const sel = props.options.findIndex((o) => optionValue(o) === props.modelValue);
	activeIdx.value = sel >= 0 ? sel : 0;
}

function toggle() {
	if (open.value) open.value = false;
	else openMenu();
}

function pick(o) {
	if (optionDisabled(o)) return;
	const v = optionValue(o);
	open.value = false;
	if (v !== props.modelValue) {
		emit("update:modelValue", v);
		emit("change", v);
	}
}

function clear() {
	open.value = false;
	if (hasValue.value) {
		emit("update:modelValue", "");
		emit("change", "");
	}
}

// Move the cursor over enabled options only, wrapping at the ends.
function moveCursor(step) {
	const n = props.options.length;
	if (!n) return;
	let i = activeIdx.value;
	for (let tries = 0; tries < n; tries++) {
		i = (i + step + n) % n;
		if (!optionDisabled(props.options[i])) {
			activeIdx.value = i;
			scrollActiveIntoView();
			return;
		}
	}
}

// Type-to-jump: typing a letter jumps to the next option whose label starts
// with the accumulated buffer — the one native-select behavior worth keeping.
let typeBuffer = "";
let typeTimer = null;
function onType(ch) {
	clearTimeout(typeTimer);
	typeBuffer += ch.toLowerCase();
	typeTimer = setTimeout(() => (typeBuffer = ""), 600);
	const start = activeIdx.value < 0 ? 0 : activeIdx.value;
	const n = props.options.length;
	for (let k = 0; k < n; k++) {
		const idx = (start + k) % n;
		const o = props.options[idx];
		if (!optionDisabled(o) && optionLabel(o).toLowerCase().startsWith(typeBuffer)) {
			activeIdx.value = idx;
			scrollActiveIntoView();
			return;
		}
	}
}

function onKeydown(e) {
	if (props.disabled) return;
	if (!open.value) {
		if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(e.key)) {
			e.preventDefault();
			openMenu();
		}
		return;
	}
	switch (e.key) {
		case "Escape":
			e.preventDefault();
			open.value = false;
			break;
		case "ArrowDown":
			e.preventDefault();
			moveCursor(1);
			break;
		case "ArrowUp":
			e.preventDefault();
			moveCursor(-1);
			break;
		case "Home":
			e.preventDefault();
			activeIdx.value = -1;
			moveCursor(1);
			break;
		case "End":
			e.preventDefault();
			activeIdx.value = 0;
			moveCursor(-1);
			break;
		case "Enter":
		case " ":
			e.preventDefault();
			if (activeIdx.value >= 0) pick(props.options[activeIdx.value]);
			break;
		default:
			if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) onType(e.key);
	}
}

// Items live in a Teleport, so clicking one blurs the trigger button. Mirror
// Typeahead: items use @mousedown.prevent to keep focus, and the trigger's blur
// closes the menu after a beat for genuine outside clicks.
let blurTimer = null;
function onBlur() {
	blurTimer = setTimeout(() => (open.value = false), 150);
}
function onItemMouseDown() {
	clearTimeout(blurTimer);
}
</script>

<template>
	<div class="stbl-select">
		<button
			ref="triggerEl"
			type="button"
			:class="triggerClass"
			:disabled="disabled"
			:aria-haspopup="'listbox'"
			:aria-expanded="open"
			v-bind="$attrs"
			@click="toggle"
			@keydown="onKeydown"
			@blur="onBlur"
		>
			<span class="stbl-select-value" :class="{ 'text-secondary': !selectedOption }">
				<slot v-if="selectedOption" name="selected" :option="selectedOption">{{ optionLabel(selectedOption) }}</slot>
				<template v-else>{{ placeholder }}</template>
			</span>
			<i
				v-if="clearable && hasValue"
				class="ti ti-x stbl-select-clear"
				role="button"
				:aria-label="'Clear'"
				@mousedown.prevent="onItemMouseDown"
				@click.stop="clear"
			></i>
			<i class="ti ti-chevron-down stbl-select-caret"></i>
		</button>

		<Teleport to="body">
			<div v-if="open" ref="menuEl" class="stbl-menu" :style="menuStyle" role="listbox">
				<div v-if="!options.length" class="stbl-menu-empty small">
					<slot name="empty">—</slot>
				</div>
				<button
					v-for="(o, i) in options"
					:key="optionValue(o) ?? i"
					type="button"
					class="stbl-menu-item"
					:class="{ 'is-active': activeIdx === i, 'is-disabled': optionDisabled(o) }"
					role="option"
					:aria-selected="optionValue(o) === modelValue"
					:disabled="optionDisabled(o)"
					@mousedown.prevent="onItemMouseDown"
					@click="pick(o)"
					@mouseenter="activeIdx = i"
				>
					<i v-if="optionValue(o) === modelValue" class="ti ti-check stbl-menu-check"></i>
					<slot name="option" :option="o" :selected="optionValue(o) === modelValue" :active="activeIdx === i">
						{{ optionLabel(o) }}
					</slot>
				</button>
			</div>
		</Teleport>
	</div>
</template>

<style scoped>
.stbl-select {
	position: relative;
}

/* Base the trigger on .form-select for height/border/focus parity with the
 * other inputs, but strip its built-in caret image — we render ti-chevron-down
 * so it matches the menu's icon family. */
.stbl-select-trigger {
	display: flex;
	align-items: center;
	gap: 0.5rem;
	text-align: left;
	background-image: none !important;
	padding-right: 0.6rem;
}

.stbl-select-value {
	flex: 1 1 auto;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.stbl-select-caret {
	flex: 0 0 auto;
	opacity: 0.5;
	font-size: 1rem;
}

.stbl-select-clear {
	flex: 0 0 auto;
	opacity: 0.6;
	cursor: pointer;
}
.stbl-select-clear:hover {
	opacity: 1;
}
</style>
