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

import { LOCALE_MAP, groupMoneyWhileTyping, moneyFractionDigits, moneySeparators, parseMoneyInput } from "../composables/money.js";

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
	// data-field passed through to the inner <input> so querySelectorAll('[data-field=...]')
	// can reliably target it for keyboard navigation (the root is a <div>, not focusable).
	dataField: { type: String, default: "" },
	// When true, keeps grouped display while focused and reformats on every keystroke.
	// Cursor jumps to end on each input — acceptable for right-aligned money fields.
	groupWhileTyping: { type: Boolean, default: false },
	// Optional override for unit prices (e.g. 4 for $4.4150 or $6.1250)
	maxFractionDigits: { type: Number, default: null },
	// When true, omits the input-group-text currency badge addon (ideal for dense
	// table cells where the currency is stated in the column header).
	hideCurrency: { type: Boolean, default: false },
});

const emit = defineEmits(["update:modelValue", "blur", "focus"]);

// The root is a <div class="input-group"> on every branch that shows a currency,
// so Vue's automatic fallthrough put a caller's `aria-invalid` on the GROUP, where
// `.stbl-ds .form-control[aria-invalid="true"]` cannot match it. Turning it off and
// binding $attrs onto the control is what makes an invalid money field look invalid.
//
// Both branches bind it, and that is the point: the same `class="is-invalid"` used
// to land on the input when no currency was set and on the wrapper when one was.
defineOptions({ inheritAttrs: false });

const focused = ref(false);
const display = ref("");

// Separators come from the same LOCALE_MAP that formatMoney() uses. They used
// to be hardcoded as `en ? "," : NBSP` here, which left tr out entirely: a
// Turkish user read "20 820,00" inside the input and "20.820,00" in the table
// beside it, on the same screen.
const separators = computed(() => moneySeparators(props.language));
const decimalSep = computed(() => separators.value.decimal);
const localeCode = computed(() => LOCALE_MAP[props.language] || "en-US");
// `isUZS` picks the native "сўм" suffix and nothing else. It used to decide
// precision too — a second copy of a policy that already lives in money.js —
// and the two copies were free to disagree. They did: money.js and this file
// both said 0, the LEDGER says 2, and a Mikas user's 1 500 000,50 opening
// balance was rounded to 1 500 001 on blur and posted that way.
const isUZS = computed(() => (props.currency || "").toUpperCase() === "UZS");
const currencyDigits = computed(() => moneyFractionDigits(props.currency));
const minFractionDigits = computed(() => currencyDigits.value);
const maxFractionDigits = computed(() => {
	// A currency with no sub-unit (JPY, KRW) cannot show one, and the unit-price
	// override must not invent it. This guard comes first for that reason.
	if (currencyDigits.value === 0) return 0;
	if (props.maxFractionDigits !== null && props.maxFractionDigits !== undefined) {
		return props.maxFractionDigits;
	}
	return currencyDigits.value;
});

const parse = (text) => parseMoneyInput(text, props.language);

function format(n) {
	if (n === null || n === undefined || n === "") return "";
	const num = Number(n);
	if (!Number.isFinite(num)) return "";
	return new Intl.NumberFormat(localeCode.value, {
		minimumFractionDigits: minFractionDigits.value,
		maximumFractionDigits: maxFractionDigits.value,
		useGrouping: true,
	}).format(num);
}

// Live grouping while typing. The implementation lives in money.js next to
// `parseMoneyInput`, which has to read this output back on the very next
// keystroke — the two are one contract and keeping them apart is what let them
// disagree.
const liveGroup = (text) => groupMoneyWhileTyping(text, props.language, maxFractionDigits.value);

function rawText(n) {
	if (n === null || n === undefined || n === "") return "";
	const num = Number(n);
	if (!Number.isFinite(num)) return "";
	// Edit mode: show raw value using the locale's decimal separator, no grouping.
	const s = num.toString();
	return decimalSep.value === "," ? s.replace(".", ",") : s;
}

function syncFromModel() {
	if (focused.value && props.groupWhileTyping) return;
	const showRaw = focused.value && !props.groupWhileTyping;
	display.value = showRaw ? rawText(props.modelValue) : format(props.modelValue);
}

onMounted(syncFromModel);
watch(() => [props.modelValue, props.language], syncFromModel);

function onInput(event) {
	const text = event.target.value;
	const parsed = parse(text);
	if (parsed === null) {
		display.value = text;
		emit("update:modelValue", null);
		return;
	}
	let next = parsed;
	if (props.min !== null && next < props.min) next = props.min;
	if (props.max !== null && next > props.max) next = props.max;
	emit("update:modelValue", next);
	display.value = props.groupWhileTyping ? liveGroup(text) : text;
}

function onFocus(event) {
	focused.value = true;
	display.value = props.groupWhileTyping
		? liveGroup(rawText(props.modelValue))
		: rawText(props.modelValue);
	requestAnimationFrame(() => {
		try {
			event.target.select();
		} catch {
			/* ignore */
		}
	});
	emit("focus", event);
}

function onBlur(event) {
	focused.value = false;
	// A zero-fraction currency (JPY, KRW) formats 1500000.5 as "1 500 001", but
	// the model kept 1500000.5 and that is what reached the ledger — the field
	// showed one number and posted another. Snap the value to what is on
	// screen. Only for 0 digits: rate fields pass no `currency`, keep the
	// 2-digit default, and must not lose a 4-decimal rate to this.
	//
	// UZS used to land here and this is where it lost the user's kopecks. It no
	// longer reports 0 digits, so the branch is simply not taken for it — the
	// fix is in the precision, not in an exception carved out of this guard.
	if (maxFractionDigits.value === 0 && Number.isFinite(Number(props.modelValue)) && props.modelValue !== null && props.modelValue !== "") {
		const snapped = Math.round(Number(props.modelValue));
		if (snapped !== Number(props.modelValue)) emit("update:modelValue", snapped);
	}
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
	<input
		v-if="hideCurrency || (!currency && !isUZS)"
		v-bind="$attrs"
		:id="id || undefined"
		:data-field="dataField || undefined"
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
	<div v-else class="input-group" :class="{ 'input-group-sm': size === 'sm', 'input-group-lg': size === 'lg' }">
		<span v-if="currency && !isUZS" class="input-group-text text-uppercase small">{{ currency }}</span>
		<input
			v-bind="$attrs"
			:id="id || undefined"
			:data-field="dataField || undefined"
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
