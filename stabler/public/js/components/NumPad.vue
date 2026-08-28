<script setup>
/**
 * NumPad — on-screen digit entry for the shop-floor terminal.
 *
 * The operator board runs wall-mounted and is operated with gloves. Native
 * number spinners put two 12-pixel arrows on that wall, and on a locked-down
 * Android kiosk whether any soft keyboard appears at all is a coin toss. This
 * puts the digits on the screen that is already being touched.
 *
 * Contract:
 *   - v-model is a STRING, not a number. "1." is a legitimate half-typed
 *     quantity and no number can hold it; the caller converts once, on submit.
 *   - Every keystroke goes through `applyNumpadKey`, so the rules that keep the
 *     buffer parseable (one decimal point, no bare ".", no leading zero) hold
 *     wherever this component is used.
 */
import { applyNumpadKey, sanitizeNumeric } from "../composables/numpad.js";
import { t } from "../composables/i18n.js";

const props = defineProps({
	modelValue: { type: String, default: "" },
	// The whole quantity this pad can be filled with in one tap — the caller's
	// knowledge, not the pad's. Empty means there is nothing to fill and no key
	// is drawn: a key that does nothing teaches operators to distrust the pad.
	fill: { type: String, default: "" },
});
const emit = defineEmits(["update:modelValue"]);

// Calculator order — 7 8 9 on top. Operators reach for the layout on the
// counting scale beside them, not a phone dialpad.
const KEYS = ["7", "8", "9", "4", "5", "6", "1", "2", "3", ".", "0", "back"];

const press = (key) => emit("update:modelValue", applyNumpadKey(props.modelValue, key));

// Replaces the buffer rather than extending it. Routed through applyNumpadKey a
// half-typed "500" plus a 1 360 balance would post 5001360.
function fillAll() {
	emit("update:modelValue", sanitizeNumeric(props.fill));
}
</script>

<template>
	<div class="numpad">
		<button
			v-for="key in KEYS"
			:key="key"
			type="button"
			class="btn btn-outline-secondary fs-2 fw-bold font-monospace"
			:aria-label="key === 'back' ? t('Backspace') : key"
			@click="press(key)"
		>
			<i v-if="key === 'back'" class="ti ti-backspace"></i>
			<template v-else>{{ key }}</template>
		</button>
		<button
			v-if="fill"
			type="button"
			class="btn btn-outline-primary fw-semibold numpad-fill"
			@click="fillAll"
		>
			{{ t("All") }}
			<span class="d-block small fw-normal font-monospace">{{ fill }}</span>
		</button>
		<button
			type="button"
			class="btn btn-outline-secondary fw-semibold numpad-clear"
			@click="press('clear')"
		>
			{{ t("Clear") }}
		</button>
	</div>
</template>

<style scoped>
.numpad {
	display: grid;
	grid-template-columns: repeat(3, 1fr);
	gap: 0.5rem;
}
/* 64px is the smallest target that is reliably hit with a gloved finger. */
.numpad .btn {
	height: 64px;
}
.numpad-fill,
.numpad-clear {
	grid-column: 1 / -1;
	height: 48px;
}
</style>
