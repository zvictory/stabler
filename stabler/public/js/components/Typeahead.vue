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
	// When true, clicking/focusing the field immediately loads a browse list
	// without requiring any typing first. Safe to leave false (default) on
	// fields where the dataset is small enough — e.g. Customers.
	openOnFocus: { type: Boolean, default: false },
});

const emit = defineEmits(["update:modelValue", "pick", "clear"]);

const rootEl = ref(null);
const inputWrapEl = ref(null);
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
	menuStyle.value = {
		position: "fixed",
		top: `${r.bottom}px`,
		left: `${r.left}px`,
		minWidth: minW,
		width: `${r.width}px`,
		maxHeight: "260px",
		overflowY: "auto",
		zIndex: 2000,
	};
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
	}
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
	clearTimeout(blurTimer);
	showOptions.value = false;
	options.value = [];
	query.value = "";
	emit("pick", item);
}

function clear() {
	query.value = "";
	options.value = [];
	showOptions.value = false;
	activeIdx.value = -1;
	emit("clear");
	emit("update:modelValue", "");
}

function onKeydown(e) {
	if (e.key === "Escape") {
		showOptions.value = false;
		return;
	}
	if (!showOptions.value || !options.value.length) return;
	if (e.key === "ArrowDown") {
		e.preventDefault();
		activeIdx.value = activeIdx.value < options.value.length - 1 ? activeIdx.value + 1 : 0;
	} else if (e.key === "ArrowUp") {
		e.preventDefault();
		activeIdx.value =
			activeIdx.value <= 0 ? options.value.length - 1 : activeIdx.value - 1;
	} else if (e.key === "Enter") {
		if (activeIdx.value >= 0) {
			e.preventDefault();
			pick(options.value[activeIdx.value]);
		}
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
				<input :value="display" type="text" :class="inputClass" readonly :disabled="disabled" />
				<button type="button" :class="btnClass" :disabled="disabled" @click="clear" aria-label="Clear selection">
					<i class="ti ti-x"></i>
				</button>
			</div>
		</div>

		<Teleport to="body">
			<div
				v-if="showOptions && !hasSelection"
				class="list-group shadow-sm typeahead-menu"
				:style="menuStyle"
				role="listbox"
			>
				<div v-if="loading && !options.length" class="list-group-item text-center py-3">
					<span class="spinner-border spinner-border-sm me-2"></span>
					<span class="small text-secondary">Searching…</span>
				</div>
				<div v-else-if="!options.length" class="list-group-item text-center py-3 small text-secondary">
					<i class="ti ti-search-off me-1"></i>{{ noResultsText }}
				</div>
				<button
					v-for="(item, i) in options"
					:key="item.name || item.item_code || i"
					type="button"
					class="list-group-item list-group-item-action text-start"
					:class="{ active: activeIdx === i }"
					role="option"
					:aria-selected="activeIdx === i"
					@mousedown.prevent="pick(item)"
					@mouseenter="activeIdx = i"
				>
					<slot name="option" :item="item" :query="query">{{ item.name }}</slot>
				</button>
			</div>
		</Teleport>
	</div>
</template>

<style>
.typeahead-menu {
	background-color: #fff;
	border-radius: 0.25rem;
}
.typeahead-menu .list-group-item {
	background-color: #fff;
}
.typeahead-menu .list-group-item.active {
	background-color: var(--tblr-primary);
	color: white;
	border-color: var(--tblr-primary);
}
.typeahead-menu .list-group-item.active .text-secondary {
	color: rgba(255, 255, 255, 0.85) !important;
}
</style>
