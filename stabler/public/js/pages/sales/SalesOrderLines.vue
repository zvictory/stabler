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
	showDiscounts: { type: Boolean, default: false },
});
const emit = defineEmits(["pick-item", "remove"]);

const fm = (v) => formatMoney(v, props.currency, props.language);

/* İskonto kuralı ERPNext'inki: yüzde ÖNCELIKLI ve `discount_amount` BIRIM
 * BAŞINA bir indirim (rate - discount_amount), satırın tamamından düşülen bir
 * tutar değil. Burada satır gross'undan bir kez düşülüyordu; sonuç, formun
 * kendi toplamıyla (SalesOrderForm.lineAmount) ve kaydedilen belgeyle
 * uyuşmayan bir satır tutarıydı — tabloda bir sayı, özet rayında başka bir
 * sayı. Formül üç yerde birebir aynı olmalı: burada, SalesOrderForm'da ve
 * paylaşılan LineItemsEditor'da. */
const lineAmount = (l) => {
	const qty = Number(l.qty) || 0;
	const rate = Number(l.rate) || 0;
	const discPct = Number(l.discount_percentage) || 0;
	const discAmt = Number(l.discount_amount) || 0;
	if (discPct > 0) return qty * Math.max(rate * (1 - discPct / 100), 0);
	if (discAmt > 0) return qty * Math.max(rate - discAmt, 0);
	return qty * rate;
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

/* ── Ölçüden miktar üreten kalemler ────────────────────────────────────────
 * Karar SATIR düzeyinde veriliyor, kiracı düzeyinde değil: Item'ın kendi
 * custom_dimension_mode'u belirliyor. Aynı siparişte panel (m²), membran
 * (rulo) ve dondurma (koli) yan yana yaşayabilsin diye böyle.
 *
 * Motor zaten üretimde: _dimensions.py hesaplıyor, dimensions_hook.py KAYITTA
 * yeniden hesaplayıp qty'yi eziyor. Yani bu girişler burada yoksa kullanıcı
 * miktarı elle yazar ve sunucu yazdığını sessizce atar — bu düzenleyici tam
 * olarak o hâldeydi. Buradaki iş yalnızca girişleri çizmek; hesap kuralına
 * dokunulmuyor. */
const DIM_MODES = ["Linear", "Area", "Volume"];
const isDim = (l) => DIM_MODES.includes(l?.dimension_mode);
const dimNeedsWidth = (l) => l?.dimension_mode === "Area" || l?.dimension_mode === "Volume";
const dimNeedsHeight = (l) => l?.dimension_mode === "Volume";

/* Sütun yalnız siparişte ölçülü kalem VARSA açılıyor. Dondurma siparişinde
 * tablo bugünkü hâlinde kalsın — boş bir "Ölçü" sütunu her satırda tire
 * göstermekten başka bir iş yapmaz. */
const hasDims = computed(() => props.items.some(isDim));

const round6 = (n) => Math.round((Number(n) || 0) * 1e6) / 1e6;

/* Sunucudaki dimensional_qty ile BIREBIR aynı olmak zorunda — boş adet 1
 * parça, açık 0 hiç. Ayrışırsa kullanıcı bir sayı görür, başka bir sayı
 * kaydeder. */
function recalcDim(line) {
	if (!isDim(line)) return;
	const L = Number(line.custom_length) || 0;
	const W = Number(line.custom_width) || 0;
	const H = Number(line.custom_height) || 0;
	const P =
		line.custom_pieces === null || line.custom_pieces === undefined || line.custom_pieces === ""
			? 1
			: Number(line.custom_pieces) || 0;
	if (line.dimension_mode === "Linear") line.qty = round6(L * P);
	else if (line.dimension_mode === "Area") line.qty = round6(L * W * P);
	else line.qty = round6(L * W * H * P);
}

/* "2,5 × 0,3 × 10" — miktarın nereden geldiğini gösteriyor. */
function dimSummary(line) {
	if (!isDim(line)) return "";
	const parts = [line.custom_length];
	if (dimNeedsWidth(line)) parts.push(line.custom_width);
	if (dimNeedsHeight(line)) parts.push(line.custom_height);
	const dims = parts.filter((v) => v !== null && v !== undefined && v !== "").join(" × ");
	return dims ? `${dims} × ${line.custom_pieces || 1}` : "";
}

/* Arama çubuğundan seçim.
 *
 * Bu, formda en sık yapılan iş — ve bir süredir HİÇ çalışmıyordu: emit
 * `{ item, line: null }` gönderiyordu, üst bileşenin handlePickItem'ı ise
 * `field === "item"` bekliyor. İkisi eşleşmeyince olay sessizce düşüyordu,
 * yani yeniden tasarlanan formda ürün eklenemiyordu.
 *
 * Satırı burada AÇMIYORUZ: `items` bir prop ve listenin sahibi üst bileşen.
 * Arama yalnız "şu ürün seçildi" diyor; boş satırı bulmak ya da yenisini
 * açmak listeyi tutan tarafın işi. */
function onSearchPick(item) {
	if (!item) return;
	emit("pick-item", { item, field: "search" });
}

function step(line, delta) {
	if (!props.editable) return;
	const next = (Number(line.qty) || 0) + delta;
	line.qty = next < 0 ? 0 : Number(next.toFixed(6));
}

/* Birim seçenekleri ürünün kendi tanımından gelir. Tek seçenek varsa segment
 * çizilmez — tek düğmeli bir seçici seçim varmış gibi görünür. */
function uomOptions(line) {
	// Ölçülü kalemde birim ölçünün kendisi (m / m² / m³) — seçilemez, çünkü
	// fiyat da miktar da stok biriminde tutuluyor.
	if (isDim(line)) return [];
	const list = Array.isArray(line.uoms) ? line.uoms : [];
	const names = [...new Set([line.stock_uom, ...list.map((u) => u.uom)].filter(Boolean))];
	return names.length > 1 ? names : [];
}

function pickUom(line, uom) {
	if (!props.editable || line.uom === uom) return;
	const hit = (line.uoms || []).find((u) => u.uom === uom);
	line.uom = uom;
	line.conversion_factor = Number(hit?.conversion_factor) || (uom === line.stock_uom ? 1 : line.conversion_factor) || 1;
	// Fiyat birime bağlı: koli fiyatı ile dona fiyatı aynı sayı değil. Bu emit
	// olmadan birim değişiyor ama fiyat eski birimde kalıyordu — tutar sessizce
	// yanlış çıkıyordu. Paylaşılan düzenleyici bunu hep yapıyordu.
	emit("pick-item", { line, field: "uom" });
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
				@pick="onSearchPick"
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
					<th v-if="hasDims" class="so-c-dims">{{ t("Measurements") }}</th>
					<th class="so-c-qty">{{ t("Qty") }}</th>
					<th class="so-c-uom">{{ t("Unit") }}</th>
					<th class="ds-td-num so-c-rate">{{ t("Unit price") }}</th>
					<th v-if="showDiscounts" class="ds-td-num so-c-disc">%</th>
					<th v-if="showDiscounts" class="ds-td-num so-c-disc">{{ t("Disc") }}</th>
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

					<!-- Ölçü girişi · sütun yalnız ölçülü kalem varsa açılıyor -->
					<td v-if="hasDims">
						<template v-if="isDim(line)">
							<div class="ds-dims">
								<label class="ds-dim">
									<span class="ds-dim-label">{{ t("Length") }}</span>
									<input
										v-model.number="line.custom_length"
										class="ds-dim-input"
										type="number"
										step="any"
										inputmode="decimal"
										:disabled="!editable"
										@input="recalcDim(line)"
									/>
								</label>
								<label v-if="dimNeedsWidth(line)" class="ds-dim">
									<span class="ds-dim-label">{{ t("Width") }}</span>
									<input
										v-model.number="line.custom_width"
										class="ds-dim-input"
										type="number"
										step="any"
										inputmode="decimal"
										:disabled="!editable"
										@input="recalcDim(line)"
									/>
								</label>
								<label v-if="dimNeedsHeight(line)" class="ds-dim">
									<span class="ds-dim-label">{{ t("Height") }}</span>
									<input
										v-model.number="line.custom_height"
										class="ds-dim-input"
										type="number"
										step="any"
										inputmode="decimal"
										:disabled="!editable"
										@input="recalcDim(line)"
									/>
								</label>
								<label class="ds-dim">
									<span class="ds-dim-label">{{ t("Pieces") }}</span>
									<input
										v-model.number="line.custom_pieces"
										class="ds-dim-input"
										data-w="sm"
										type="number"
										step="any"
										inputmode="decimal"
										:disabled="!editable"
										@input="recalcDim(line)"
									/>
								</label>
							</div>
							<div v-if="dimSummary(line)" class="ds-dim-note">{{ dimSummary(line) }}</div>
						</template>
						<span v-else class="ds-mono so-empty">—</span>
					</td>

					<!-- Adet: ölçülüyse TÜRETILMIŞ, değilse stepper -->
					<td>
						<!-- Hesaplanan miktar bilinçli olarak input DEĞIL: yazılabilir
						     olsaydı ölçüyle miktar çelişirdi ve sunucu kayıtta zaten
						     ölçüden yeniden hesapladığı için yazılan sessizce düşerdi. -->
						<div v-if="isDim(line)" class="ds-calc">
							<div class="ds-calc-val">{{ Number(line.qty || 0).toLocaleString() }}</div>
							<div class="ds-calc-note">{{ line.stock_uom }} · {{ t("computed") }}</div>
						</div>
						<span v-else-if="editable" class="ds-stepper">
							<button type="button" :aria-label="t('Decrease')" @click="step(line, -1)">−</button>
							<input v-model.number="line.qty" type="number" step="any" inputmode="decimal" data-field="qty" />
							<button type="button" :aria-label="t('Increase')" @click="step(line, 1)">+</button>
						</span>
						<span v-else class="ds-mono">{{ line.qty }}</span>
					</td>

					<!-- Birim: ölçülüyse sabit, değilse segment + dönüşüm notu -->
					<td>
						<template v-if="isDim(line)">
							<span class="ds-mono so-uom-flat">{{ line.stock_uom || line.uom || "—" }}</span>
							<div class="ds-uom-note">{{ t("measure unit · fixed") }}</div>
						</template>
						<template v-else-if="uomOptions(line).length">
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

					<!-- İskonto · yüzde ve tutar
					     Sütun gizliyken bile lineAmount iskontoyu düşüyor. Görünmezse
					     kullanıcı qty×rate ile uyuşmayan bir tutar görüp nedenini
					     bulamıyordu; bu yüzden düzenlenebilir yolda da çizilmesi şart. -->
					<td v-if="showDiscounts" class="ds-td-num">
						<input
							v-if="editable"
							v-model.number="line.discount_percentage"
							type="number"
							step="any"
							min="0"
							max="100"
							inputmode="decimal"
							data-field="disc-pct"
							class="ds-input so-rate"
							placeholder="0"
						/>
						<span v-else>{{ line.discount_percentage > 0 ? line.discount_percentage + "%" : "—" }}</span>
					</td>
					<td v-if="showDiscounts" class="ds-td-num">
						<input
							v-if="editable"
							v-model.number="line.discount_amount"
							type="number"
							step="any"
							min="0"
							inputmode="decimal"
							data-field="disc-amt"
							class="ds-input so-rate"
							placeholder="0"
						/>
						<span v-else>{{ line.discount_amount > 0 ? fm(line.discount_amount) : "—" }}</span>
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

/* Sütun genişlikleri bu ekrana özel: tablo sağdaki 344px'lik rayla yer
 * paylaşıyor, referans sayfadaki tam genişlik burada yok. Ürün sütunu
 * (isim + stok çubuğu) en çok yeri hak eden, o yüzden geri kalanı sıkı. */
.so-c-dims { width: 252px; }
.so-c-qty { width: 128px; }
.so-c-uom { width: 150px; }
.so-c-rate { width: 132px; }
.so-c-disc { width: 104px; }
.so-c-amt { width: 140px; }
.so-c-del { width: 62px; }

/* Ölçü alanları katmanda sabit 106px; bu dar sütunda üçü tek satıra sığmıyor
 * ve "2,76 × 1 × 6" tek bir ölçü ifadesi gibi okunmuyordu. Yalnız GENIŞLIK
 * esnetiliyor — kenar, tipografi ve hizalama katmandan geliyor. */
.so-lines :deep(.ds-dim) {
	flex: 1 1 0;
	min-width: 0;
}

.so-lines :deep(.ds-dim-input) {
	width: 100%;
	/* Tarayıcının artır/azalt okları alanın ~15px'ini yiyor ve "2,76" son
	 * hanesinden kırpılıyordu. Ölçüyü ok tuşlarıyla değiştirmek zaten anlamlı
	 * bir hareket değil — yazılan bir sayı, sayılan bir şey değil. */
	appearance: textfield;
	-moz-appearance: textfield;
}

.so-lines :deep(.ds-dim-input)::-webkit-outer-spin-button,
.so-lines :deep(.ds-dim-input)::-webkit-inner-spin-button {
	-webkit-appearance: none;
	margin: 0;
}

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
