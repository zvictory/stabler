<script setup>
import { ref, watch } from "vue";
import { t } from "../composables/i18n.js";

const props = defineProps({
	modelValue: { type: String, default: "" },
	placeholder: { type: String, default: "Search…" },
	count: { type: [Number, String], default: 0 },
	totalLabel: { type: String, default: "" },
	totalValue: { type: String, default: "" },
	primaryLabel: { type: String, default: "" },
	primaryIcon: { type: String, default: "" },
	searchWidth: { type: String, default: "240px" },
});

const emit = defineEmits(["update:modelValue", "search", "primary-click"]);

const searchVal = ref(props.modelValue);
let debounceTimer = null;

watch(() => props.modelValue, (newVal) => {
	searchVal.value = newVal;
});

function onInput() {
	emit("update:modelValue", searchVal.value);
	clearTimeout(debounceTimer);
	debounceTimer = setTimeout(() => {
		emit("search", searchVal.value);
	}, 300);
}
</script>

<template>
	<div class="d-flex align-items-center gap-2 flex-wrap py-2 px-3 border-bottom bg-light">
		<div class="position-relative" :style="{ minWidth: searchWidth }">
			<i class="ti ti-search position-absolute top-50 translate-middle-y text-secondary" style="left: 0.65rem"></i>
			<input
				v-model="searchVal"
				type="search"
				class="form-control form-control-sm ps-5 pe-5"
				:placeholder="placeholder"
				@input="onInput"
			/>
			<kbd class="position-absolute top-50 translate-middle-y text-secondary font-monospace" style="right: 0.5rem; font-size: 0.68rem">⌘K</kbd>
		</div>

		<!-- Slot for custom filter selects -->
		<slot name="filters"></slot>

		<div class="ms-auto d-flex align-items-center gap-3">
			<slot name="summary">
				<div class="d-flex gap-3 small text-secondary align-items-center flex-wrap">
					<div>{{ t("Count") }}: <strong class="font-monospace text-body">{{ count }}</strong></div>
					<div v-if="totalLabel && totalValue">
						{{ totalLabel }}: <strong class="font-monospace text-body">{{ totalValue }}</strong>
					</div>
				</div>
			</slot>
			<button
				v-if="primaryLabel"
				type="button"
				class="btn btn-sm btn-primary"
				@click="emit('primary-click')"
			>
				<i v-if="primaryIcon" class="ti me-1" :class="primaryIcon"></i>
				{{ primaryLabel }}
			</button>
		</div>
	</div>
</template>
