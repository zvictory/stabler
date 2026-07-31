<script setup>
// Sales order line editor — this screen only.
//
// The shared LineItemsEditor is used by five screens and its column structure
// is a plain qty/uom/rate grid. The sales order design needs a different row
// entirely: a stock-availability bar under the item, a stepper for quantity and
// a segmented control for the unit. Those are not slots into the shared editor,
// they replace its columns. So this screen gets its own editor and the shared
// one is left exactly as the other four screens expect it.
import { computed } from "vue";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import Typeahead from "../../components/Typeahead.vue";

const props = defineProps({
	items: { type: Array, required: true },
	editable: { type: Boolean, default: true },
	currency: { type: String, default: "" },
	language: { type: String, default: "en" },
	searchItems: { type: Function, required: true },
	blankLine: { type: Function, required: true },
	showDiscounts: { type: Boolean, default: false },
});
const emit = defineEmits(["pick-item", "remove"]);

const fm = (v) => formatMoney(v, props.currency, props.language);

const lineAmount = (l) => {
	const gross = (Number(l.qty) || 0) * (Number(l.rate) || 0);
	const pct = (Number(l.discount_percentage) || 0) / 100;
	return Math.max(0, gross - gross * pct - (Number(l.discount_amount) || 0));
};

/* Satır başına stok birimindeki talep. Girilen adet satış biriminde (koli),
 * stok ise stok biriminde (dona) tutuluyor — karşılaştırmak için ikisini aynı
 * birime çevirmek şart, yoksa "24 koli var" diye yanlış bir güven veririz. */
const stockQty = (l) => (Number(l.qty) || 0) * (Number(l.conversion_factor) || 1);

const freeQty = (l) => Number(l.availability?.free ?? 0);

/* Çubuk, TALEBIN uygun stoğa oranı — stoğun doluluğu değil. Soru "bu satır
 * karşılanır mı", "depo ne kadar dolu" değil. */
function fillPct(l) {
	const free = freeQty(l);
	if (!free) return 0;
	return Math.min(100, Math.round((stockQty(l) / free) * 100));
}

const isShort = (l) => Boolean(l.availability) && stockQty(l) > freeQty(l);

function step(line, delta) {
	if (!props.editable) return;
	const next = (Number(line.qty) || 0) + delta;
	line.qty = next < 0 ? 0 : Number(next.toFixed(6));
}

/* Birim seçenekleri ürünün kendi tanımından gelir. Tek seçenek varsa segment
 * çizilmez — tek düğmeli bir seçici seçim varmış gibi görünür. */
function uomOptions(line) {
	const list = Array.isArray(line.uoms) ? line.uoms : [];
	const names = [...new Set([line.stock_uom, ...list.map((u) => u.uom)].filter(Boolean))];
	return names.length > 1 ? names : [];
}

function pickUom(line, uom) {
	if (!props.editable || line.uom === uom) return;
	const hit = (line.uoms || []).find((u) => u.uom === uom);
	line.uom = uom;
	line.conversion_factor = Number(hit?.conversion_factor) || (uom === line.stock_uom ? 1 : line.conversion_factor) || 1;
}

const totalQtyLabel = computed(() => {
	const byUom = new Map();
	for (const l of props.items) {
		if (!l.item_code) continue;
		const u = l.stock_uom || l.uom || "";
		byUom.set(u, (byUom.get(u) || 0) + stockQty(l));
	}
	return [...byUom].map(([u, q]) => `${Number(q.toFixed(2))} ${u}`).join(" · ");
});

const filledCount = computed(() => props.items.filter((l) => l.item_code).length);
</script>

<template>
	<div class="so-lines">
		<!-- Ürün arama kalemlerin ÜSTÜNDE ve tam genişlikte: bu formda en sık
		     yapılan iş satır eklemek, o yüzden en büyük hedef o olmalı. -->
		<div v-if="editable" class="so-search">
			<svg class="so-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
				stroke-width="1.7" aria-hidden="true">
				<circle cx="11" cy="11" r="7" /><path d="m20 20-3.6-3.6" />
			</svg>
			<Typeahead
				:model-value="''"
				:search="searchItems"
				:placeholder="t('Search a product — code, name or barcode · Enter to add')"
				:no-results-text="t('No products match that search')"
				open-on-focus
				@pick="(item) => emit('pick-item', { item, line: null })"
			>
				<template #option="{ item }">
					<div class="so-opt">
						<span class="ds-mono so-opt-code">{{ item.item_code || item.name }}</span>
						<span class="so-opt-name">{{ item.item_name || item.name }}</span>
						<span class="ds-mono so-opt-stock">{{ Number(item.actual_qty || 0).toLocaleString() }} {{ item.stock_uom }}</span>
					</div>
				</template>
			</Typeahead>
			<span class="ds-mono so-search-kbd" aria-hidden="true">⌘K</span>
		</div>

		<table class="ds-table so-table">
			<thead>
				<tr>
					<th>{{ t("Product · stock") }}</th>
					<th class="so-c-qty">{{ t("Qty") }}</th>
					<th class="so-c-uom">{{ t("Unit") }}</th>
					<th class="ds-td-num so-c-rate">{{ t("Unit price") }}</th>
					<th class="ds-td-num so-c-amt">{{ t("Amount") }}</th>
					<th v-if="editable" class="so-c-del"></th>
				</tr>
			</thead>
			<tbody>
				<tr v-for="(line, i) in items" :key="i">
					<!-- Ürün + stok uygunluğu -->
					<td>
						<template v-if="line.item_code">
							<div class="so-item">
								<span class="ds-mono so-code">{{ line.item_code }}</span>
								<strong class="so-name">{{ line.item_name || line.item_code }}</strong>
							</div>
							<div v-if="line.availabilityLoading" class="ds-mono so-avail-load">
								{{ t("checking stock…") }}
							</div>
							<template v-else-if="line.availability">
								<div class="ds-avail" :data-short="isShort(line) ? '1' : null">
									{{ Number(freeQty(line)).toLocaleString() }} {{ t("available") }}
									<span class="so-avail-demand">
										· {{ t("needs") }} {{ Number(stockQty(line).toFixed(2)) }} {{ line.stock_uom }}
									</span>
								</div>
								<div class="ds-avail-bar">
									<i :style="{ width: fillPct(line) + '%' }" :data-short="isShort(line) ? '1' : null"></i>
								</div>
							</template>
						</template>
						<span v-else class="ds-mono so-empty">{{ t("pick a product above") }}</span>
					</td>

					<!-- Adet: stepper -->
					<td>
						<span v-if="editable" class="ds-stepper">
							<button type="button" :aria-label="t('Decrease')" @click="step(line, -1)">−</button>
							<input v-model.number="line.qty" type="number" step="any" inputmode="decimal" />
							<button type="button" :aria-label="t('Increase')" @click="step(line, 1)">+</button>
						</span>
						<span v-else class="ds-mono">{{ line.qty }}</span>
					</td>

					<!-- Birim: segment + dönüşüm notu -->
					<td>
						<template v-if="uomOptions(line).length">
							<span class="ds-uom">
								<button
									v-for="u in uomOptions(line)"
									:key="u"
									type="button"
									:aria-pressed="String(line.uom === u)"
									:disabled="!editable"
									@click="pickUom(line, u)"
								>{{ u }}</button>
							</span>
							<div v-if="line.conversion_factor > 1" class="ds-uom-note">
								1 {{ line.uom }} = {{ line.conversion_factor }} {{ line.stock_uom }}
								· {{ Number(stockQty(line).toFixed(2)) }} {{ line.stock_uom }}
							</div>
						</template>
						<span v-else class="ds-mono so-uom-flat">{{ line.uom || line.stock_uom || "—" }}</span>
					</td>

					<!-- Birim fiyat -->
					<td class="ds-td-num">
						<input
							v-if="editable"
							v-model.number="line.rate"
							type="number"
							step="any"
							inputmode="decimal"
							class="ds-input so-rate"
							@input="line.rateTouched = true"
						/>
						<span v-else>{{ fm(line.rate) }}</span>
						<div v-if="line.uom" class="ds-uom-note so-rate-note">{{ line.uom }} {{ t("price") }}</div>
					</td>

					<!-- Tutar -->
					<td class="ds-td-num so-amount">{{ fm(lineAmount(line)) }}</td>

					<td v-if="editable" class="so-c-del">
						<button type="button" class="so-del" :aria-label="t('Remove line')" @click="emit('remove', i)">
							{{ t("REMOVE") }}
						</button>
					</td>
				</tr>
			</tbody>
		</table>

		<div class="ds-panel-foot">
			<span>{{ filledCount }} {{ filledCount === 1 ? t("item") : t("items") }}</span>
			<span class="ds-mono">{{ totalQtyLabel }}</span>
		</div>
	</div>
</template>

<style scoped>
/* Yerleşim yalnız. Renk, kenar, tipografi katmandan (.ds-*) geliyor. */
.so-search {
	display: flex;
	align-items: center;
	gap: 10px;
	border: 1px solid var(--ds-ln2);
	padding: 0 13px;
	margin: 0 var(--ds-pad) 14px;
}

.so-search :deep(.form-control) {
	border: 0;
	min-height: 46px;
	padding-left: 0;
}

.so-search :deep(.form-control:focus) {
	outline: none;
	box-shadow: none;
}

.so-search-icon {
	width: 18px;
	height: 18px;
	flex: none;
	color: var(--ds-tx3);
}

.so-search-kbd {
	flex: none;
	font-size: 11px;
	color: var(--ds-tx3);
}

.so-opt {
	display: flex;
	align-items: baseline;
	gap: 9px;
}

.so-opt-code {
	font-size: 11px;
	color: var(--ds-acc);
	flex: none;
}

.so-opt-name {
	flex: 1;
	font-weight: 600;
}

.so-opt-stock {
	font-size: 11px;
	color: var(--ds-tx3);
}

.so-table {
	table-layout: fixed;
}

.so-c-qty { width: 150px; }
.so-c-uom { width: 168px; }
.so-c-rate { width: 150px; }
.so-c-amt { width: 140px; }
.so-c-del { width: 62px; }

.so-item {
	display: flex;
	align-items: baseline;
	gap: 7px;
	flex-wrap: wrap;
}

.so-code {
	font-size: 11px;
	color: var(--ds-acc);
}

.so-name {
	font-family: var(--ds-font-head);
	font-weight: 800;
	font-size: 15px;
}

.so-avail-demand {
	color: var(--ds-tx3);
}

.so-avail-load,
.so-empty {
	font-size: 11.5px;
	color: var(--ds-tx3);
}

.so-uom-flat {
	font-size: 12px;
	color: var(--ds-tx2);
}

.so-rate {
	min-height: 34px;
	padding: 5px 8px;
	font-size: 13px;
	text-align: right;
	font-family: var(--ds-mono);
}

.so-rate-note {
	text-align: right;
}

.so-amount {
	font-weight: 600;
}

/* Sil, ikon değil KELIME: ikon tek başına ne yaptığını söylemiyor ve bu
 * geri alınamaz bir işlem. */
.so-del {
	border: 0;
	background: none;
	font-family: var(--ds-mono);
	font-size: 10px;
	letter-spacing: 0.1em;
	color: var(--ds-tx3);
	cursor: pointer;
	padding: 4px 2px;
}

.so-del:hover {
	color: var(--ds-crit-tx);
}
</style>
