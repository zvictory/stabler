<script setup>
/**
 * Chip-based multi-select. Same async-search / Teleport-menu / keyboard-nav
 * pattern as Typeahead.vue, extended to hold an array of picks instead of one.
 *
 * modelValue is a plain array of ids (matches the backend's _in_clause
 * contract) — chip labels are resolved locally via `display()` and cached
 * so they survive even though the id array itself carries no label.
 */
import { ref, computed, watch, nextTick, onBeforeUnmount } from "vue";
import { call } from "../api/client.js";

const props = defineProps({
	modelValue: { type: Array, default: () => [] },
	searchApi: { type: String, required: true },
	extraParams: { type: Object, default: () => ({}) },
	idKey: { type: String, default: "name" },
	display: { type: Function, required: true }, // (row) => label string
	placeholder: { type: String, default: "" },
	minChars: { type: Number, default: 1 },
	debounce: { type: Number, default: 200 },
	noResultsText: { type: String, default: "No matches found" },
	size: { type: String, default: "md" },
});

const emit = defineEmits(["update:modelValue"]);

const rootEl = ref(null);
const inputWrapEl = ref(null);
const menuEl = ref(null);

const picks = ref([]); // [{id, label}] — local shadow of modelValue with labels
const query = ref("");
const options = ref([]);
const showOptions = ref(false);
const loading = ref(false);
const activeIdx = ref(-1);
const menuStyle = ref({});

// Reconcile inward only when the id *set* actually changed, so a fresh pick's
// label isn't clobbered by a bare-id fallback on the next tick.
watch(
	() => props.modelValue,
	(next) => {
		const nextIds = (next || []).map(String);
		const curIds = picks.value.map((p) => String(p.id));
		if (nextIds.length === curIds.length && nextIds.every((id, i) => id === curIds[i])) return;
		picks.value = (next || []).map((id) => {
			const existing = picks.value.find((p) => String(p.id) === String(id));
			return existing || { id, label: String(id) };
		});
	},
	{ immediate: true }
);

function emitValue() {
	emit(
		"update:modelValue",
		picks.value.map((p) => p.id)
	);
}

const pickedIds = computed(() => new Set(picks.value.map((p) => String(p.id))));

const inputClass = computed(() => (props.size === "sm" ? "form-control form-control-sm" : "form-control"));

function computeMenuStyle() {
	const el = inputWrapEl.value;
	if (!el) return;
	const rect = el.getBoundingClientRect();
	const spaceBelow = window.innerHeight - rect.bottom;
	const spaceAbove = rect.top;
	const flipUp = spaceBelow < 160 && spaceAbove > spaceBelow;
	const available = flipUp ? spaceAbove : spaceBelow;
	const maxH = Math.min(260, Math.max(120, available - 8));
	menuStyle.value = {
		position: "fixed",
		left: `${rect.left}px`,
		width: `${rect.width}px`,
		maxHeight: `${maxH}px`,
		zIndex: 2000,
		...(flipUp ? { bottom: `${window.innerHeight - rect.top}px` } : { top: `${rect.bottom}px` }),
	};
}

function onScrollOrResize() {
	if (showOptions.value) computeMenuStyle();
}

watch(showOptions, (open) => {
	if (open) {
		nextTick(() => {
			computeMenuStyle();
			window.addEventListener("scroll", onScrollOrResize, true);
			window.addEventListener("resize", onScrollOrResize);
		});
	} else {
		window.removeEventListener("scroll", onScrollOrResize, true);
		window.removeEventListener("resize", onScrollOrResize);
	}
});

onBeforeUnmount(() => {
	window.removeEventListener("scroll", onScrollOrResize, true);
	window.removeEventListener("resize", onScrollOrResize);
	if (timer) clearTimeout(timer);
	if (blurTimer) clearTimeout(blurTimer);
});

async function fetchOptions(q) {
	loading.value = true;
	try {
		const rows = await call(props.searchApi, { ...props.extraParams, search: q, limit: 20 });
		options.value = Array.isArray(rows) ? rows.filter((r) => !pickedIds.value.has(String(r[props.idKey]))) : [];
	} catch {
		options.value = [];
	} finally {
		loading.value = false;
		activeIdx.value = options.value.length ? 0 : -1;
	}
}

let timer = null;
function onSearch() {
	if (timer) clearTimeout(timer);
	const q = query.value.trim();
	if (q.length < props.minChars) {
		showOptions.value = false;
		return;
	}
	timer = setTimeout(() => {
		showOptions.value = true;
		fetchOptions(q);
	}, props.debounce);
}

function onFocus() {
	if (query.value.trim().length >= props.minChars) {
		showOptions.value = true;
		if (!options.value.length) fetchOptions(query.value.trim());
	}
}

let blurTimer = null;
function onBlur() {
	blurTimer = setTimeout(() => {
		showOptions.value = false;
	}, 150);
}

function pick(item) {
	if (blurTimer) clearTimeout(blurTimer);
	const id = item[props.idKey];
	if (pickedIds.value.has(String(id))) return;
	picks.value = [...picks.value, { id, label: props.display(item) }];
	emitValue();
	query.value = "";
	options.value = [];
	showOptions.value = false;
}

function removeChip(id) {
	picks.value = picks.value.filter((p) => String(p.id) !== String(id));
	emitValue();
}

function scrollActiveIntoView() {
	nextTick(() => {
		const el = menuEl.value;
		if (!el) return;
		const row = el.querySelectorAll(".stbl-menu-item")[activeIdx.value];
		if (row) row.scrollIntoView({ block: "nearest" });
	});
}

function onKeydown(e) {
	if (e.key === "Escape") {
		showOptions.value = false;
		return;
	}
	if (e.key === "Backspace" && !query.value && picks.value.length) {
		removeChip(picks.value[picks.value.length - 1].id);
		return;
	}
	if (!showOptions.value) return;
	if (e.key === "ArrowDown") {
		e.preventDefault();
		if (options.value.length) {
			activeIdx.value = (activeIdx.value + 1) % options.value.length;
			scrollActiveIntoView();
		}
	} else if (e.key === "ArrowUp") {
		e.preventDefault();
		if (options.value.length) {
			activeIdx.value = (activeIdx.value - 1 + options.value.length) % options.value.length;
			scrollActiveIntoView();
		}
	} else if (e.key === "Enter") {
		e.preventDefault();
		if (activeIdx.value >= 0 && options.value[activeIdx.value]) pick(options.value[activeIdx.value]);
	}
}
</script>

<template>
	<div ref="rootEl" class="multiselect">
		<div ref="inputWrapEl" class="d-flex flex-wrap align-items-center gap-1 border rounded px-2 py-1">
			<span v-for="p in picks" :key="p.id" class="badge bg-blue-lt d-inline-flex align-items-center gap-1">
				{{ p.label }}
				<button
					type="button"
					class="btn-close btn-close-sm"
					style="font-size: 0.55rem"
					:aria-label="'Remove ' + p.label"
					tabindex="-1"
					@mousedown.prevent="removeChip(p.id)"
				></button>
			</span>
			<input
				v-model="query"
				type="text"
				:class="inputClass"
				style="border: 0; flex: 1 1 6rem; min-width: 6rem; padding: 0.1rem 0.25rem"
				:placeholder="picks.length ? '' : placeholder"
				@input="onSearch"
				@focus="onFocus"
				@blur="onBlur"
				@keydown="onKeydown"
			/>
		</div>

		<Teleport to="body">
			<div v-if="showOptions" ref="menuEl" class="stbl-menu stbl-menu--nocheck" :style="menuStyle" role="listbox">
				<div v-if="loading" class="stbl-menu-empty">
					<span class="spinner-border spinner-border-sm me-1"></span>Searching…
				</div>
				<div v-else-if="!options.length" class="stbl-menu-empty">{{ noResultsText }}</div>
				<button
					v-for="(item, i) in options"
					:key="item[idKey]"
					type="button"
					class="stbl-menu-item"
					:class="{ 'is-active': activeIdx === i }"
					role="option"
					@mousedown.prevent="pick(item)"
					@mouseenter="activeIdx = i"
				>
					{{ display(item) }}
				</button>
			</div>
		</Teleport>
	</div>
</template>
