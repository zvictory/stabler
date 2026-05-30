<script setup>
/**
 * MoneyInput — locale-aware grouped currency input.
 * Per ~/.claude/rules/money-input.md:
 *   en        -> "20,820.00"   (comma group, dot decimal)
 *   ru/uz/uzc -> "20 820,00"   (space group, comma decimal)
 *
 * Behavior:
 *   - v-model is a raw Number (or null when blank).
 *   - On focus: shows raw, unformatted digits so the user can edit cleanly.
 *   - On blur / mount: re-formats with grouping + 2 fraction digits.
 *   - inputmode="decimal" so mobile shows the numeric keypad.
 */
import { computed, ref, watch, onMounted } from "vue";

const props = defineProps({
	modelValue: { type: [Number, String, null], default: null },
	currency: { type: String, default: "" },
	language: { type: String, default: "en" },
	placeholder: { type: String, default: "0.00" },
	disabled: { type: Boolean, default: false },
	min: { type: Number, default: null },
	max: { type: Number, default: null },
	id: { type: String, default: "" },
	size: { type: String, default: "" }, // "sm" | "lg" | ""
});

const emit = defineEmits(["update:modelValue", "blur", "focus"]);

const focused = ref(false);
const display = ref("");

const groupSep = computed(() => (props.language === "en" ? "," : " "));
const decimalSep = computed(() => (props.language === "en" ? "." : ","));
// UZS uses integer-only formatting and the native "сўм" suffix
// (tiyin/coins out of circulation since 1994).
const isUZS = computed(() => (props.currency || "").toUpperCase() === "UZS");
const fractionDigits = computed(() => (isUZS.value ? 0 : 2));

function parse(text) {
	if (text === null || text === undefined) return null;
	const raw = String(text).trim();
	if (raw === "") return null;
	// Strip grouping separators (space, NBSP, comma when not the decimal sep, apostrophe).
	let cleaned = raw.replace(/[\s  ']/g, "");
	if (decimalSep.value === ",") {
		// ru/uz/uzc: comma is decimal, drop stray dots used as thousand grouping
		cleaned = cleaned.replace(/\./g, "").replace(",", ".");
	} else {
		cleaned = cleaned.replace(/,/g, "");
	}
	const n = Number(cleaned);
	return Number.isFinite(n) ? n : null;
}

function format(n) {
	if (n === null || n === undefined || n === "") return "";
	const num = Number(n);
	if (!Number.isFinite(num)) return "";
	const localeCode = props.language === "en" ? "en-US" : "ru-RU";
	return new Intl.NumberFormat(localeCode, {
		minimumFractionDigits: fractionDigits.value,
		maximumFractionDigits: fractionDigits.value,
		useGrouping: true,
	}).format(num);
}

function rawText(n) {
	if (n === null || n === undefined || n === "") return "";
	const num = Number(n);
	if (!Number.isFinite(num)) return "";
	// Edit mode: show raw value using the locale's decimal separator, no grouping.
	const s = num.toString();
	return decimalSep.value === "," ? s.replace(".", ",") : s;
}

function syncFromModel() {
	display.value = focused.value ? rawText(props.modelValue) : format(props.modelValue);
}

onMounted(syncFromModel);
watch(() => [props.modelValue, props.language], syncFromModel);

function onInput(event) {
	const text = event.target.value;
	display.value = text;
	const parsed = parse(text);
	if (parsed === null) {
		emit("update:modelValue", null);
		return;
	}
	let next = parsed;
	if (props.min !== null && next < props.min) next = props.min;
	if (props.max !== null && next > props.max) next = props.max;
	emit("update:modelValue", next);
}

function onFocus(event) {
	focused.value = true;
	display.value = rawText(props.modelValue);
	emit("focus", event);
	// Select all so the user can overwrite quickly.
	requestAnimationFrame(() => {
		try {
			event.target.select();
		} catch {
			/* ignore */
		}
	});
}

function onBlur(event) {
	focused.value = false;
	display.value = format(props.modelValue);
	emit("blur", event);
}

const inputClass = computed(() => {
	const base = ["form-control", "text-end", "font-monospace"];
	if (props.size === "sm") base.push("form-control-sm");
	if (props.size === "lg") base.push("form-control-lg");
	return base.join(" ");
});
</script>

<template>
	<div class="input-group" :class="{ 'input-group-sm': size === 'sm', 'input-group-lg': size === 'lg' }">
		<span v-if="currency && !isUZS" class="input-group-text text-uppercase small">{{ currency }}</span>
		<input
			:id="id || undefined"
			type="text"
			inputmode="decimal"
			autocomplete="off"
			:class="inputClass"
			:value="display"
			:placeholder="placeholder"
			:disabled="disabled"
			@input="onInput"
			@focus="onFocus"
			@blur="onBlur"
		/>
		<span v-if="isUZS" class="input-group-text small">сўм</span>
	</div>
</template>
