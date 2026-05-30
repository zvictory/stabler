<script setup>
/**
 * DateInput — dd.mm.yyyy masked date entry component.
 *
 * Global rule (project CLAUDE.md): every date input in the SPA uses this
 * component, never bare <input type="date">, so the display is always
 * dd.mm.yyyy regardless of the browser/OS locale.
 *
 * Contract (drop-in for all native <input type="date"> call sites):
 *   - v-model is an ISO "yyyy-mm-dd" string (or "" when blank) — identical
 *     to what the native date input emits, so callers need zero changes.
 *   - Displays "dd.mm.yyyy" in the text field.
 *   - On blur: reformats partial input; emits "" if incomplete.
 *   - Calendar button: calls showPicker() on a visually-hidden native date
 *     input so the OS calendar opens. The native input never renders its
 *     own text to the user — only the masked text field is visible.
 *   - min / max: forwarded to the hidden native input as ISO yyyy-mm-dd so
 *     the calendar constrains the selectable range.
 */
import { ref, watch, onMounted, computed } from "vue";
import { parseDateInput, formatDate } from "../composables/date.js";

const props = defineProps({
	modelValue: { type: String, default: "" },
	size: { type: String, default: "" }, // "" | "sm" | "lg"
	disabled: { type: Boolean, default: false },
	required: { type: Boolean, default: false },
	id: { type: String, default: "" },
	placeholder: { type: String, default: "дд.мм.гггг" },
	min: { type: String, default: "" }, // ISO yyyy-mm-dd
	max: { type: String, default: "" }, // ISO yyyy-mm-dd
});

const emit = defineEmits(["update:modelValue", "blur", "focus"]);

const display = ref("");
const nativePicker = ref(null);

function toDisplay(iso) {
	if (!iso) return "";
	const formatted = formatDate(iso);
	return formatted === "—" ? "" : formatted;
}

function syncFromModel() {
	display.value = toDisplay(props.modelValue);
}

onMounted(syncFromModel);
watch(() => props.modelValue, syncFromModel);

function onInput(event) {
	let raw = event.target.value;

	// Auto-insert dots as the user types digits (dd, dd., dd.mm, dd.mm.)
	// Strip any non-digit/dot first to prevent duplicate dots on paste.
	const digits = raw.replace(/\D/g, "");
	let masked = "";
	for (let i = 0; i < Math.min(digits.length, 8); i++) {
		masked += digits[i];
		if (i === 1 || i === 3) masked += ".";
	}

	display.value = masked;

	const iso = parseDateInput(masked);
	emit("update:modelValue", iso);
}

function onBlur(event) {
	// Reformat on blur — clean up partial input
	const iso = parseDateInput(display.value);
	display.value = iso ? toDisplay(iso) : "";
	if (!iso) emit("update:modelValue", "");
	emit("blur", event);
}

function onFocus(event) {
	emit("focus", event);
}

function openCalendar() {
	nativePicker.value?.showPicker?.();
}

function onNativeChange(event) {
	const iso = event.target.value; // always yyyy-mm-dd from native input
	display.value = toDisplay(iso);
	emit("update:modelValue", iso);
}

const textClass = computed(() => {
	const base = ["form-control"];
	if (props.size === "sm") base.push("form-control-sm");
	if (props.size === "lg") base.push("form-control-lg");
	return base.join(" ");
});

const btnClass = computed(() => {
	const base = ["btn", "btn-outline-secondary"];
	if (props.size === "sm") base.push("btn-sm");
	if (props.size === "lg") base.push("btn-lg");
	return base.join(" ");
});
</script>

<template>
	<div class="input-group" :class="{ 'input-group-sm': size === 'sm', 'input-group-lg': size === 'lg' }">
		<input
			:id="id || undefined"
			type="text"
			inputmode="numeric"
			autocomplete="off"
			:class="textClass"
			:value="display"
			:placeholder="placeholder"
			:disabled="disabled"
			:required="required"
			maxlength="10"
			@input="onInput"
			@blur="onBlur"
			@focus="onFocus"
		/>
		<button
			type="button"
			:class="btnClass"
			:disabled="disabled"
			tabindex="-1"
			@click.prevent="openCalendar"
			title="Выбрать дату"
		>
			<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
				<line x1="16" y1="2" x2="16" y2="6"></line>
				<line x1="8" y1="2" x2="8" y2="6"></line>
				<line x1="3" y1="10" x2="21" y2="10"></line>
			</svg>
		</button>
		<!-- Visually hidden native date input — only used for showPicker() calendar -->
		<input
			ref="nativePicker"
			type="date"
			:value="modelValue"
			:min="min || undefined"
			:max="max || undefined"
			:disabled="disabled"
			tabindex="-1"
			aria-hidden="true"
			style="position:absolute;width:1px;height:1px;opacity:0;pointer-events:none;"
			@change="onNativeChange"
		/>
	</div>
</template>
