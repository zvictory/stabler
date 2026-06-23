<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { t } from "../composables/i18n.js";

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
	// Inline substring search. Shown only when `searchable` AND the list is longer
	// than `searchThreshold`, so 2–3 item toggles stay clean while real pickers
	// (accounts, parties, currencies) get a search box. Set searchThreshold=0 to
	// force-show. `searchKeys` targets specific object fields for options rendered
	// via #option without a `label` (e.g. raw account rows).
	searchable: { type: Boolean, default: true },
	searchThreshold: { type: Number, default: 6 },
	searchKeys: { type: Array, default: () => [] },
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
const query = ref("");
const searchInputEl = ref(null);
// Per-instance id so aria-activedescendant references this widget's rows only.
const uid = Math.random().toString(36).slice(2, 8);

const isPrimitive = (o) => o === null || typeof o !== "object";
const optionValue = (o) => (isPrimitive(o) ? o : o[props.valueKey]);
const optionLabel = (o) => (isPrimitive(o) ? String(o ?? "") : o[props.labelKey]);
const optionDisabled = (o) => (isPrimitive(o) ? false : !!o.disabled);

const selectedOption = computed(
	() => props.options.find((o) => optionValue(o) === props.modelValue) ?? null
);
const hasValue = computed(() => props.modelValue !== "" && props.modelValue != null);

const triggerClass = computed(() => ["form-select", "stbl-select-trigger", { "form-select-sm": props.size === "sm" }]);

// ── Inline search ──────────────────────────────────────────────────────────
const showSearch = computed(() => props.searchable && props.options.length > props.searchThreshold);

// Case- and diacritic-insensitive (NFKD strips combining marks → uz/ru friendly).
function norm(s) {
	return String(s ?? "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");
}
// Search text for an option: explicit searchKeys win; else the label; else the
// option's own string/number values joined (covers #option-only rows w/o label).
function optionSearchText(o) {
	if (isPrimitive(o)) return String(o ?? "");
	if (props.searchKeys.length) return props.searchKeys.map((k) => o[k]).filter(Boolean).join(" ");
	const lbl = o[props.labelKey];
	if (lbl) return String(lbl);
	return Object.values(o).filter((v) => typeof v === "string" || typeof v === "number").join(" ");
}
const filtered = computed(() => {
	const q = norm(query.value).trim();
	if (!q) return props.options;
	return props.options.filter((o) => norm(optionSearchText(o)).includes(q));
});
// Cap the rendered rows when there's no query (lists can be ~1000 rows); the full
// matched set renders once the user types. Keyboard/pick operate over what renders.
const RENDER_CAP = 200;
const visibleOptions = computed(() => {
	const q = norm(query.value).trim();
	return q ? filtered.value : filtered.value.slice(0, RENDER_CAP);
});
const truncatedCount = computed(() => filtered.value.length - visibleOptions.value.length);
const rowId = (i) => `stbl-opt-${uid}-${i}`;

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
		if (showSearch.value) searchInputEl.value?.focus({ preventScroll: true });
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

// As the query changes the list shrinks/grows: move the cursor to the first
// enabled match and recompute the menu height for the new row count.
watch(query, () => {
	activeIdx.value = visibleOptions.value.findIndex((o) => !optionDisabled(o));
	nextTick(computeMenuStyle);
});

async function scrollActiveIntoView() {
	await nextTick();
	if (!menuEl.value || activeIdx.value < 0) return;
	const rows = menuEl.value.querySelectorAll(".stbl-menu-item");
	const el = rows[activeIdx.value];
	if (!el) return;
	// Scroll WITHIN the menu only — never call el.scrollIntoView(), which can scroll
	// the whole page/document to bring this fixed-positioned menu row into view
	// (that is the "page jumps down when I open the dropdown" bug).
	const menu = menuEl.value;
	const top = el.offsetTop;
	const bottom = top + el.offsetHeight;
	if (top < menu.scrollTop) {
		menu.scrollTop = top;
	} else if (bottom > menu.scrollTop + menu.clientHeight) {
		menu.scrollTop = bottom - menu.clientHeight;
	}
}

function openMenu() {
	if (props.disabled) return;
	query.value = ""; // reset the filter every time the menu opens
	open.value = true;
	// Start the cursor on the selected row (or the first one).
	const sel = visibleOptions.value.findIndex((o) => optionValue(o) === props.modelValue);
	activeIdx.value = sel >= 0 ? sel : 0;
}

function toggle() {
	if (open.value) open.value = false;
	else openMenu();
}

function pick(o) {
	if (optionDisabled(o)) return;
	const v = optionValue(o);
	// Return focus to the trigger BEFORE tearing down the Teleport. When the
	// search box is visible, focus lives inside the Teleport'd menu. Removing
	// that DOM node while it holds focus makes the browser hunt for a new focus
	// target at body-end — which lands on the page footer.
	triggerEl.value?.focus({ preventScroll: true });
	open.value = false;
	if (v !== props.modelValue) {
		emit("update:modelValue", v);
		emit("change", v);
	}
}

function clear() {
	triggerEl.value?.focus({ preventScroll: true });
	open.value = false;
	if (hasValue.value) {
		emit("update:modelValue", "");
		emit("change", "");
	}
}

// Move the cursor over enabled options only, wrapping at the ends. Operates over
// the rendered (filtered + capped) list so the cursor matches what's on screen.
function moveCursor(step) {
	const list = visibleOptions.value;
	const n = list.length;
	if (!n) return;
	let i = activeIdx.value;
	for (let tries = 0; tries < n; tries++) {
		i = (i + step + n) % n;
		if (!optionDisabled(list[i])) {
			activeIdx.value = i;
			scrollActiveIntoView();
			return;
		}
	}
}

// Type-to-jump: typing a letter jumps to the next option whose label starts
// with the accumulated buffer. Only used when the search box is hidden (short
// lists); when it's shown, keystrokes feed the search field instead.
let typeBuffer = "";
let typeTimer = null;
function onType(ch) {
	clearTimeout(typeTimer);
	typeBuffer += ch.toLowerCase();
	typeTimer = setTimeout(() => (typeBuffer = ""), 600);
	const start = activeIdx.value < 0 ? 0 : activeIdx.value;
	const list = visibleOptions.value;
	const n = list.length;
	for (let k = 0; k < n; k++) {
		const idx = (start + k) % n;
		const o = list[idx];
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
			triggerEl.value?.focus({ preventScroll: true });
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
			if (showSearch.value) break; // let Home move the text caret
			e.preventDefault();
			activeIdx.value = -1;
			moveCursor(1);
			break;
		case "End":
			if (showSearch.value) break; // let End move the text caret
			e.preventDefault();
			activeIdx.value = 0;
			moveCursor(-1);
			break;
		case "Enter":
			e.preventDefault();
			if (activeIdx.value >= 0) pick(visibleOptions.value[activeIdx.value]);
			break;
		case " ":
			if (showSearch.value) break; // let Space type into the search box
			e.preventDefault();
			if (activeIdx.value >= 0) pick(visibleOptions.value[activeIdx.value]);
			break;
		case "Tab":
			// pick() already returns focus to the trigger (see comment there).
			// preventDefault stops the Teleport-body Tab-order from jumping to
			// the footer; focus is on the trigger so the user's next Tab advances
			// from the trigger's natural document position.
			if (activeIdx.value >= 0) pick(visibleOptions.value[activeIdx.value]);
			e.preventDefault();
			break;
		default:
			// When the search box is shown, characters go to the input (don't
			// hijack them for type-to-jump).
			if (!showSearch.value && e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) onType(e.key);
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
// Focusing the search input blurs the trigger; cancel the trigger's close timer
// so moving focus into the box doesn't snap the menu shut.
function onSearchFocus() {
	clearTimeout(blurTimer);
}
</script>

<template>
	<div class="stbl-select">
		<button
			ref="triggerEl"
			type="button"
			role="combobox"
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
				<div v-if="showSearch" class="stbl-menu-search">
					<i class="ti ti-search stbl-menu-search-icon"></i>
					<input
						ref="searchInputEl"
						v-model="query"
						type="text"
						inputmode="search"
						autocomplete="off"
						class="stbl-menu-search-input"
						:placeholder="t('Search')"
						:aria-label="t('Search')"
						:aria-activedescendant="activeIdx >= 0 ? rowId(activeIdx) : undefined"
						@keydown="onKeydown"
						@focus="onSearchFocus"
						@blur="onBlur"
					/>
				</div>
				<div v-if="!visibleOptions.length" class="stbl-menu-empty small">
					<template v-if="query">{{ t("No matches found") }}</template>
					<slot v-else name="empty">—</slot>
				</div>
				<button
					v-for="(o, i) in visibleOptions"
					:id="rowId(i)"
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
				<div v-if="truncatedCount > 0" class="stbl-menu-foot small text-secondary">
					{{ t("Keep typing to narrow…") }} (+{{ truncatedCount }})
				</div>
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

/* Sticky search row at the top of the teleported menu. */
.stbl-menu-search {
	position: sticky;
	top: 0;
	z-index: 1;
	display: flex;
	align-items: center;
	gap: 0.4rem;
	padding: 0.4rem 0.55rem;
	background: var(--bs-body-bg, #fff);
	border-bottom: 1px solid var(--bs-border-color, #dee2e6);
}
.stbl-menu-search-icon {
	flex: 0 0 auto;
	opacity: 0.5;
	font-size: 0.95rem;
}
.stbl-menu-search-input {
	flex: 1 1 auto;
	border: 0;
	outline: none;
	background: transparent;
	font-size: 0.875rem;
	padding: 0;
}
.stbl-menu-foot {
	padding: 0.3rem 0.6rem;
	text-align: center;
}
</style>
