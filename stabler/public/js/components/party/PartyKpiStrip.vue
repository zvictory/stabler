<script setup>
/**
 * Party Center — KPI şeridi (`ds-kpis` / `ds-kpi`).
 *
 * Tutarlar HER ZAMAN kendi işlem/hesap para biriminde gelir; bu bileşen hiçbir
 * çevrim yapmaz — biçimlenmiş metni PartyCenter üretir.
 *
 * item = { key, label, text?, chip?, note?, sev? }
 *   chip = { value, currency, partyType }  → BalanceChip ile render edilir
 *   sev  = "neutral" | "ok" | "soon" | "crit"
 */
import BalanceChip from "../BalanceChip.vue";

const props = defineProps({
	items: { type: Array, default: () => [] },
	cols: { type: Number, default: 4 },
	language: { type: String, default: "" },
});
</script>

<template>
	<div class="ds-kpis pc-kpis" :data-cols="String(props.cols)">
		<div v-for="k in props.items" :key="k.key" class="ds-kpi" :data-sev="k.sev || 'neutral'">
			<div class="pc-label">{{ k.label }}</div>
			<BalanceChip
				v-if="k.chip"
				:value="k.chip.value"
				:currency="k.chip.currency"
				:party-type="k.chip.partyType"
				:language="props.language"
				size="md"
				class="pc-chip"
			/>
			<div v-else class="ds-kpi-val pc-val">{{ k.text }}</div>
			<div v-if="k.note" class="ds-kpi-note pc-note">{{ k.note }}</div>
		</div>
	</div>
</template>

<style scoped>
.pc-kpis {
	border-left: 0;
	border-right: 0;
}
/* Global `.ds-kpi` dashboard kartı ölçüsünde (min-height 104). Party Center'da
   asıl iş ekstre; şerit üstten çaldığı her pikseli ekstre viewport'undan alıyor.
   Etiket ile değer yan yana getirilerek hücre iki satırdan bire iner —
   token'a dokunulmaz, override yalnızca bu bileşende geçerli. */
.ds-kpi {
	display: flex;
	flex-wrap: wrap;
	align-items: baseline;
	gap: 0 8px;
	min-height: auto;
	padding: 7px 12px 8px;
	border-top-width: 2px;
}
.pc-val {
	margin-top: 0;
	font-size: 16px;
}
.pc-chip {
	margin-top: 0;
}
.pc-note {
	flex: 1 1 100%;
	margin-top: 1px;
	font-size: 11.5px;
	color: var(--tblr-gray-600, #667382);
}

/* Mikro etiket — `.ds-label` çevrilmeyen teknik kimliklere ayrılmıştır;
   çevrili etiketler tipografiyi buradan alır, tonu AA'ya çekilir. */
.pc-label {
	font-family: var(--ds-mono);
	font-size: 10px;
	letter-spacing: 0.14em;
	text-transform: uppercase;
	color: var(--tblr-gray-600, #667382);
}
</style>
