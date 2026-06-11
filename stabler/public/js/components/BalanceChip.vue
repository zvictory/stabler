<script setup>
import { computed } from "vue";
import { t } from "../composables/i18n.js";
import { balanceState, formatMoney } from "../composables/money.js";

const props = defineProps({
	value: { type: [Number, String], default: 0 },
	currency: { type: String, default: "UZS" },
	partyType: { type: String, default: "Customer" },
	language: { type: String, default: "en" },
	size: { type: String, default: "md" },
});

const state = computed(() => balanceState(props.value, props.partyType));
const label = computed(() => {
	if (state.value.state === "settled") return t("Settled");
	if (state.value.state === "prepaid") return t("Prepaid");
	if (state.value.state === "we_owe") return t("We owe");
	return t("Owes us");
});
const toneClass = computed(() => {
	if (state.value.state === "settled") return "bg-secondary-lt text-secondary";
	if (state.value.state === "prepaid") return "bg-green-lt text-green";
	if (state.value.state === "we_owe") return "bg-orange-lt text-orange";
	return "bg-red-lt text-red";
});
const chipClass = computed(() => ["badge", "stbl-balance-chip", toneClass.value, props.size === "lg" ? "stbl-balance-chip-lg" : ""]);
</script>

<template>
	<span :class="chipClass">
		<span>{{ label }}</span>
		<span v-if="state.state !== 'settled'" class="font-monospace stbl-amount">
			{{ formatMoney(state.abs, currency, language) }}
		</span>
	</span>
</template>
