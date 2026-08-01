<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

const props = defineProps({
	modelValue: { type: [String, Number, null], default: "" },
	search: { type: Function, required: true },
	display: { type: String, default: "" },
	placeholder: { type: String, default: "Search…" },
	size: { type: String, default: "md" },
	disabled: { type: Boolean, default: false },
	minChars: { type: Number, default: 1 },
	debounce: { type: Number, default: 200 },
	noResultsText: { type: String, default: "No matches found" },
	menuMinWidth: { type: String, default: "100%" },
	// Namespace for a caller that needs to restyle the popover (e.g. lay the rows out
	// as a table). The menu is teleported to <body>, so the parent's scoped CSS can't
	// reach the row element the component itself renders — this class can.
	menuClass: { type: String, default: "" },
	// When true, clicking/focusing the field immediately loads a browse list
	// without requiring any typing first. Safe to leave false (default) on
	// fields where the dataset is small enough — e.g. Customers.
	openOnFocus: { type: Boolean, default: false },
});

const emit = defineEmits(["update:modelValue", "pick", "clear"]);

const rootEl = ref(null);
const inputWrapEl = ref(null);
const menuEl = ref(null);
const query = ref("");
const options = ref([]);
const showOptions = ref(false);
const loading = ref(false);
const activeIdx = ref(-1);
const menuStyle = ref({});

function computeMenuStyle() {
	const anchor = inputWrapEl.value;
	if (!anchor) return;
	const r = anchor.getBoundingClientRect();
	const minW = props.menuMinWidth === "100%" ? `${r.width}px` : props.menuMinWidth;
	const spaceBelow = window.innerHeight - r.bottom;
	const spaceAbove = r.top;
	const flipUp = spaceBelow < 160 && spaceAbove > spaceBelow;
	const available = flipUp ? spaceAbove : spaceBelow;
	const maxH = `${Math.min(260, Math.max(120, available - 8))}px`;
	if (flipUp) {
		menuStyle.value = {
			position: "fixed",
			bottom: `${window.innerHeight - r.top}px`,
			left: `${r.left}px`,
			minWidth: minW,
			width: `${r.width}px`,
			maxHeight: maxH,
			overflowY: "auto",
			zIndex: 2000,
		};
	} else {
		menuStyle.value = {
			position: "fixed",
			top: `${r.bottom}px`,
			left: `${r.left}px`,
			minWidth: minW,
			width: `${r.width}px`,
			maxHeight: maxH,
			overflowY: "auto",
			zIndex: 2000,
		};
	}
}

function onScrollOrResize() {
	if (showOptions.value) computeMenuStyle();
}

watch(showOptions, async (v) => {
	if (v) {
		await nextTick();
		computeMenuStyle();
		window.addEventListener("scroll", onScrollOrResize, true);
		window.addEventListener("resize", onScrollOrResize);
	} else {
		window.removeEventListener("scroll", onScrollOrResize, true);
		window.removeEventListener("resize", onScrollOrResize);
	}
});

onBeforeUnmount(() => {
	window.removeEventListener("scroll", onScrollOrResize, true);
	window.removeEventListener("resize", onScrollOrResize);
});

const inputClass = computed(() =>
	props.size === "sm" ? "form-control form-control-sm" : "form-control"
);
const btnClass = computed(() =>
	props.size === "sm" ? "btn btn-outline-secondary btn-sm" : "btn btn-outline-secondary"
);
const groupClass = computed(() =>
	props.size === "sm" ? "input-group input-group-sm" : "input-group"
);
const hasSelection = computed(() => !!props.modelValue);

let timer = null;

// Shared fetch — called from both onSearch and onFocus.
async function fetchOptions(q) {
	loading.value = true;
	activeIdx.value = -1;
	try {
		const res = await props.search(q);
		options.value = Array.isArray(res) ? res : [];
	} catch {
		options.value = [];
	} finally {
		loading.value = false;
		// Highlight the first real (non-group) row so Tab/Enter commits it.
		activeIdx.value = options.value.findIndex((o) => !o.__group);
	}
}

// After a pick the editable input unmounts (replaced by the selected display),
// which would drop focus to <body>. Move focus to the next field (the amount)
// instead, so keyboard entry flows account → amount → memo → next row.
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
function focusNextAfter(el) {
	if (!el) return;
	const all = Array.from(document.querySelectorAll(FOCUSABLE)).filter(
		(n) => n.offsetWidth || n.offsetHeight || n.getClientRects().length,
	);
	const next = all.find(
		(n) => !el.contains(n) && el.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING,
	);
	next?.focus();
}

function onSearch() {
	clearTimeout(timer);
	const q = query.value.trim();

	if (q.length < props.minChars) {
		if (props.openOnFocus) {
			// Keep the menu open and (re)load the unfiltered browse list.
			showOptions.value = true;
			loading.value = true;
			timer = setTimeout(() => fetchOptions(""), props.debounce);
		} else {
			options.value = [];
			showOptions.value = false;
			loading.value = false;
		}
		return;
	}

	showOptions.value = true;
	loading.value = true;
	timer = setTimeout(() => fetchOptions(q), props.debounce);
}

function onFocus() {
	if (options.value.length || loading.value) {
		showOptions.value = true;
		return;
	}
	// Open-on-focus: show the menu immediately and load a browse list if we
	// don't already have options cached.
	if (props.openOnFocus && !hasSelection.value) {
		showOptions.value = true;
		fetchOptions("");
	}
}

let blurTimer = null;
function onBlur() {
	blurTimer = setTimeout(() => {
		showOptions.value = false;
	}, 150);
}

function pick(item) {
	if (item.__group) return;
	clearTimeout(blurTimer);
	showOptions.value = false;
	options.value = [];
	query.value = "";
	emit("pick", item);
	// DOM swaps to the selected display next tick; then advance to the next field.
	nextTick(() => focusNextAfter(rootEl.value));
}

function clear() {
	query.value = "";
	options.value = [];
	showOptions.value = false;
	activeIdx.value = -1;
	emit("clear");
	emit("update:modelValue", "");
}

// Keep the keyboard-highlighted row visible inside the scrolling menu. The
// menu is Teleported to <body>, so we reach it via menuEl and scroll only when
// the active row falls outside the 260px window (block:"nearest" is a no-op for
// already-visible rows).
async function scrollActiveIntoView() {
	await nextTick();
	if (!menuEl.value || activeIdx.value < 0) return;
	const rows = menuEl.value.querySelectorAll(".stbl-menu-item");
	rows[activeIdx.value]?.scrollIntoView({ block: "nearest" });
}

function onKeydown(e) {
	if (e.key === "Escape") {
		showOptions.value = false;
		return;
	}
	// ArrowDown summons a closed menu so the keyboard alone can browse — mirrors
	// onFocus: reuse cached options if present, else load a browse list.
	if (e.key === "ArrowDown" && !showOptions.value) {
		e.preventDefault();
		if (options.value.length) {
			showOptions.value = true;
		} else if (props.openOnFocus && !hasSelection.value) {
			showOptions.value = true;
			fetchOptions("");
		}
		return;
	}
	if (!showOptions.value || !options.value.length) return;
	if (e.key === "ArrowDown") {
		e.preventDefault();
		activeIdx.value = activeIdx.value < options.value.length - 1 ? activeIdx.value + 1 : 0;
		scrollActiveIntoView();
	} else if (e.key === "ArrowUp") {
		e.preventDefault();
		activeIdx.value =
			activeIdx.value <= 0 ? options.value.length - 1 : activeIdx.value - 1;
		scrollActiveIntoView();
	} else if (e.key === "Enter") {
		if (activeIdx.value >= 0 && !options.value[activeIdx.value]?.__group) {
			e.preventDefault();
			pick(options.value[activeIdx.value]);
		}
	} else if (e.key === "Tab" && !e.shiftKey && activeIdx.value >= 0 && !options.value[activeIdx.value]?.__group) {
		// Commit the highlighted option, then advance to the next field (amount).
		e.preventDefault();
		pick(options.value[activeIdx.value]);
	} else if (e.key === "Tab") {
		showOptions.value = false;
	}
}
</script>

<template>
	<div ref="rootEl" class="typeahead">
		<div ref="inputWrapEl">
			<div v-if="!hasSelection" :class="groupClass">
				<input
					v-model="query"
					type="text"
					:class="inputClass"
					:placeholder="placeholder"
					:disabled="disabled"
					autocomplete="off"
					@input="onSearch"
					@focus="onFocus"
					@blur="onBlur"
					@keydown="onKeydown"
				/>
				<span v-if="loading" class="input-group-text">
					<span class="spinner-border spinner-border-sm text-secondary" role="status"></span>
				</span>
			</div>
			<div v-else :class="groupClass">
				<input :value="display" type="text" :class="inputClass" readonly :disabled="disabled" tabindex="-1" />
				<button type="button" :class="btnClass" :disabled="disabled" tabindex="-1" @click="clear" aria-label="Clear selection">
					<i class="ti ti-x"></i>
				</button>
			</div>
		</div>

		<Teleport to="body">
			<div
				v-if="showOptions && !hasSelection"
				ref="menuEl"
				class="stbl-menu stbl-menu--nocheck typeahead-menu"
				:class="menuClass"
				:style="menuStyle"
				role="listbox"
			>
				<div v-if="loading && !options.length" class="stbl-menu-empty">
					<span class="spinner-border spinner-border-sm me-2"></span>
					<span class="small">Searching…</span>
				</div>
				<div v-else-if="!options.length" class="stbl-menu-empty small">
					<i class="ti ti-search-off me-1"></i>{{ noResultsText }}
				</div>
				<!-- Column headings for a caller that renders its options as table rows.
				     Only when there is something to head. -->
				<slot v-if="options.length" name="menu-header" />
				<template v-for="(item, i) in options" :key="item.name || item.__group || i">
					<div
						v-if="item.__group"
						class="px-3 py-1 text-secondary"
						style="font-size: 0.7em; text-transform: uppercase; letter-spacing: .06em; font-weight: 600; pointer-events: none"
					>
						<slot name="option" :item="item" :query="query">{{ item.__group }}</slot>
					</div>
					<button
						v-else
						type="button"
						class="stbl-menu-item"
						:class="{ 'is-active': activeIdx === i }"
						role="option"
						:aria-selected="activeIdx === i"
						tabindex="-1"
						@mousedown.prevent="pick(item)"
						@mouseenter="activeIdx = i"
					>
						<slot name="option" :item="item" :query="query">{{ item.name }}</slot>
					</button>
				</template>
			</div>
		</Teleport>
	</div>
</template>

<style>
/* The popover look now comes from the shared `.stbl-menu` rules in stabler.css.
 * Only the combobox-specific avatar sizing stays here. */
.typeahead-menu .stbl-menu-item .avatar.avatar-xs {
	width: 1.25rem;
	height: 1.25rem;
	font-size: 0.6rem;
}
</style>
