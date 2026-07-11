<script setup>
/**
 * Pagination — standard list footer: page-size select (25/50/100), prev/next
 * and a "showing X–Y of N" count. Drives the limit_start / limit_page_length
 * params the imports list endpoints expect. v-model:limitStart is 0-based.
 */
import { computed } from "vue";
import { t } from "../composables/i18n.js";

const props = defineProps({
	total: { type: Number, default: 0 },
	limitStart: { type: Number, default: 0 },
	pageLength: { type: Number, default: 25 },
	pageCount: { type: Number, default: 0 }, // rows actually on the current page
});

const emit = defineEmits(["update:limitStart", "update:pageLength"]);

const SIZES = [25, 50, 100];

const from = computed(() => (props.total === 0 ? 0 : props.limitStart + 1));
const to = computed(() => Math.min(props.limitStart + props.pageCount, props.total));
const hasPrev = computed(() => props.limitStart > 0);
const hasNext = computed(() => props.limitStart + props.pageLength < props.total);

function prev() {
	if (!hasPrev.value) return;
	emit("update:limitStart", Math.max(0, props.limitStart - props.pageLength));
}
function next() {
	if (!hasNext.value) return;
	emit("update:limitStart", props.limitStart + props.pageLength);
}
function onSize(e) {
	// Parent watches pageLength and resets the offset to 0 (avoids a double load).
	emit("update:pageLength", Number(e.target.value));
}
</script>

<template>
	<div class="d-flex align-items-center gap-3 flex-wrap py-2 px-3 border-top bg-light">
		<div class="d-flex align-items-center gap-2">
			<span class="text-secondary small">{{ t("Rows per page") }}</span>
			<select class="form-select form-select-sm" style="width: auto" :value="pageLength" @change="onSize">
				<option v-for="s in SIZES" :key="s" :value="s">{{ s }}</option>
			</select>
		</div>
		<div class="ms-auto d-flex align-items-center gap-3">
			<span class="text-secondary small font-monospace">
				{{ from }}–{{ to }} {{ t("of") }} {{ total }}
			</span>
			<div class="btn-group">
				<button
					type="button"
					class="btn btn-sm btn-outline-secondary"
					:disabled="!hasPrev"
					@click="prev"
				>
					<i class="ti ti-chevron-left"></i>
				</button>
				<button
					type="button"
					class="btn btn-sm btn-outline-secondary"
					:disabled="!hasNext"
					@click="next"
				>
					<i class="ti ti-chevron-right"></i>
				</button>
			</div>
		</div>
	</div>
</template>
