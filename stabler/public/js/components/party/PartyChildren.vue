<script setup>
/**
 * Party Center — alt kayıtlar (QuickBooks tarzı Customer:Job hiyerarşisi).
 *
 * Bakiyeler satırın KENDİ hesap para biriminde; üst kaydın kümülatif bakiyesi
 * KPI şeridinde gösterilir (sunucu tarafı rollup), burada tekrar toplanmaz.
 */
import PartyAvatar from "../PartyAvatar.vue";
import { formatMoney } from "../../composables/money.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { t } from "../../composables/i18n.js";

const props = defineProps({
	children: { type: Array, default: () => [] },
	nameField: { type: String, default: "customer_name" },
	statusDoctype: { type: String, default: "Customer" },
	currency: { type: String, default: "" },
	language: { type: String, default: "" },
});

const emit = defineEmits(["open"]);

function balanceOf(ch) {
	return Number(ch.balance_acc ?? ch.balance_base ?? 0);
}
function currencyOf(ch) {
	return balanceOf(ch) ? ch.account_currency || props.currency : props.currency;
}
</script>

<template>
	<table class="ds-table pc-table">
		<thead>
			<tr>
				<th>{{ t("Name") }}</th>
				<th>{{ t("Job Status") }}</th>
				<th class="ds-td-num">{{ t("Balance") }}</th>
			</tr>
		</thead>
		<tbody>
			<tr v-for="ch in props.children" :key="ch.name" class="pc-row" @click="emit('open', ch.name)">
				<td>
					<div class="pc-name">
						<PartyAvatar :name="ch[props.nameField] || ch.name" size="sm" class="flex-shrink-0" />
						<div class="pc-name-text">
							<div class="pc-title">{{ ch[props.nameField] || ch.name }}</div>
							<div class="pc-sub">{{ ch.name }}</div>
						</div>
					</div>
				</td>
				<td>
					<span v-if="ch.job_status" class="badge" :class="getStatusBadgeClass(props.statusDoctype, ch.job_status)">
						{{ t(ch.job_status) }}
					</span>
					<span v-else class="pc-dash">—</span>
				</td>
				<td class="ds-td-num font-monospace">
					<span
						:class="{
							'pc-pos': balanceOf(ch) > 0,
							'pc-neg': balanceOf(ch) < 0,
							'pc-zero': !balanceOf(ch),
						}"
					>
						{{ formatMoney(balanceOf(ch), currencyOf(ch), props.language) }}
					</span>
				</td>
			</tr>
			<tr v-if="!props.children.length">
				<td colspan="3" class="pc-empty">{{ t("No child records.") }}</td>
			</tr>
		</tbody>
	</table>
</template>

<style scoped>
.pc-row {
	cursor: pointer;
}
.pc-name {
	display: flex;
	align-items: center;
	gap: 8px;
	min-width: 0;
}
.pc-name-text {
	min-width: 0;
}
.pc-title {
	font-weight: 600;
	color: #1d273b;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.pc-sub {
	font-family: var(--ds-mono, monospace);
	font-size: 11.5px;
	color: var(--tblr-gray-600, #667382);
}
.pc-dash,
.pc-zero {
	color: var(--tblr-gray-600, #667382);
}
.pc-pos {
	color: #1c7a3a;
}
.pc-neg {
	color: #b32424;
}
.pc-empty {
	padding: 28px 16px;
	text-align: center;
	color: var(--tblr-gray-600, #667382);
	font-size: 13px;
}
</style>
