<script setup>
/* Tedarikçi teklifi girişi — Stabler'ın içinde, Desk'e gitmeden.
 *
 * Bu ekrana kadar bir Supplier Quotation başka bir yerde oluşturulup lota elle
 * etiketlenmek zorundaydı, ve "başka bir yer" pratikte Frappe Desk'ti — projenin
 * sert kuralı oraya link vermeyi yasaklıyor, yani ortada kapatılamayan bir boşluk
 * vardı. Boşluk kozmetik değildi: etiketlenmemiş teklif 5-teklif / 2-ülke
 * politikasının saymasına girmiyor, dolayısıyla "fiyatlamaya hazır" rozeti boş bir
 * teklif setiyle yeşil yanabiliyordu.
 *
 * KAYDET VE GÖNDER AYRI İKİ EYLEM. Politika sayımı taslakla kesinleşmiş teklifi
 * ayırt ediyor; kaydederken gönderen bir düğme "5 teklif toplandı" cümlesini
 * yanlışlanamaz hale getirirdi — yarım yazılmış her taslak kesin teklif sayılırdı.
 * Bu yüzden gönderme, kayıttan sonra ayrı bir düğme ve ayrı bir uç nokta.
 *
 * Sunucu neyi kabul ediyorsa burada da o geçerli (api/sourcing.py): oran negatif
 * olamaz — sıfır olabilir, çünkü dahil edilmiş kalem/numune gerçek bir tekliftir;
 * miktar sıfırdan büyük olmalı; para birimi zorunlu, çünkü karşılaştırma şirket
 * para birimine `base_grand_total` üzerinden çevirerek yapılıyor.
 */
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { t } from "../composables/i18n.js";
import { formatMoney } from "../composables/money.js";
import { formatDate, todayIso } from "../composables/date.js";
import { useToast } from "../composables/useToast.js";
import MoneyInput from "./MoneyInput.vue";
import DateInput from "./DateInput.vue";
import Select from "./Select.vue";
import Typeahead from "./Typeahead.vue";

const props = defineProps({
	deal: { type: String, required: true },
	dealLabel: { type: String, default: "" },
	quotationName: { type: String, default: "" },
	rfq: { type: String, default: "" },
});
const emit = defineEmits(["close", "saved"]);

const session = useSession();
const { activeCompany, user, currency } = storeToRefs(session);
const toast = useToast();

// Set when the currency list request failed and the field fell back to the
// company's own currency. Degrading is fine; degrading silently is not — the
// only place a foreign currency enters the product would go quietly dead.
const currencyListFailed = ref(false);
const saving = ref(false);
const submitting = ref(false);
const currencies = ref([]);

const form = ref(newForm());
function newForm() {
	return {
		name: "",
		supplier: "",
		supplierLabel: "",
		currency: currency.value || "",
		valid_till: "",
		transaction_date: "",
		items: [blankLine()],
	};
}
function blankLine() {
	return { item_code: "", itemLabel: "", qty: null, rate: null };
}

onMounted(async () => {
	if (props.quotationName) {
		try {
			const res = await call("stabler.api.sourcing.get_supplier_quotation", {
				name: props.quotationName,
				company: activeCompany.value,
			});
			if (res) {
				form.value.name = res.name;
				form.value.supplier = res.supplier;
				form.value.supplierLabel = res.supplier_name || res.supplier;
				form.value.currency = res.currency || currency.value;
				form.value.valid_till = res.valid_till || "";
				form.value.transaction_date = res.transaction_date || "";
				if (res.items && res.items.length) {
					form.value.items = res.items.map((i) => ({
						item_code: i.item_code,
						itemLabel: i.item_name || i.item_code,
						qty: i.qty,
						rate: i.rate,
					}));
				}
			}
		} catch (err) {
			toast.error(err?.message || t("Could not load quotation details."));
		}
	} else if (props.deal) {
		try {
			const res = await call("stabler.api.sourcing.get_quotation_defaults", {
				deal: props.deal,
				rfq: props.rfq || null,
				company: activeCompany.value,
			});
			if (res?.items && res.items.length) {
				form.value.items = res.items.map((i) => ({
					item_code: i.item_code,
					itemLabel: i.item_name || i.item_code,
					qty: i.qty,
					rate: null,
				}));
			}
		} catch {
			// Non-blocking fallback to blankLine
		}
	}
});

const minValidTill = computed(() => {
	if (form.value.transaction_date) {
		return form.value.transaction_date;
	}
	return todayIso();
});

(async () => {
	try {
		const raw = await call("stabler.api.sales.list_currencies");
		currencies.value = (raw || []).map((c) => (typeof c === "object" && c ? (c.name || c.value) : c));
	} catch {
		// Para birimi listesi düşerse alan boş kalmasın: hiç değilse şirketinki.
		currencies.value = currency.value ? [currency.value] : [];
		currencyListFailed.value = true;
	}
	if (!form.value.currency && currencies.value.length) {
		form.value.currency = currency.value || currencies.value[0] || "";
	}
})();

async function searchSuppliers(q) {
	const rows = await call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 20,
	});
	return (rows || []).map((r) => ({ name: r.name, label: r.supplier_name || r.name }));
}
async function searchItems(q) {
	const rows = await call("stabler.api.inventory.list_items", { search: q, limit: 20 });
	return (rows || []).map((r) => ({ name: r.name, label: r.item_name || r.name }));
}

function addLine() {
	form.value.items.push(blankLine());
}
function removeLine(index) {
	form.value.items.splice(index, 1);
	if (!form.value.items.length) form.value.items.push(blankLine());
}

const lineTotal = (row) => Number(row.qty || 0) * Number(row.rate || 0);
const total = computed(() => form.value.items.reduce((sum, row) => sum + lineTotal(row), 0));

// Money goes through the house formatter, never `toLocaleString()` — that reads
// the BROWSER's locale, not the user's language, and knows nothing about how
// many fraction digits a currency carries. `form.currency` can genuinely be
// empty (the currency list request can fail and leave the field unfilled), and
// `formatMoney(v, "")` makes Intl throw and degrades to an unformatted
// `toFixed(2)`. An amount whose unit nobody knows is not measurable, and says so.
function fmtAmount(v) {
	if (!form.value.currency) return "—";
	return formatMoney(v, form.value.currency, user.value.language);
}

/* Sunucunun reddedeceği şeyi göndermeden söylüyoruz. Bu bir GÜVENLİK kontrolü
 * DEĞİL — api/sourcing.py aynı kuralları kendi uyguluyor ve asıl kapı orası.
 * Buradaki tek amaç, kullanıcının hatayı formu terk etmeden görmesi. */
const problems = computed(() => {
	const list = [];
	if (!form.value.supplier) list.push(t("Pick the supplier who quoted."));
	if (!form.value.currency) list.push(t("Pick the currency the supplier quoted in."));
	if (form.value.valid_till && form.value.valid_till < minValidTill.value) {
		list.push(t("Valid till date cannot be before transaction date."));
	}
	const filled = form.value.items.filter((r) => r.item_code);
	if (!filled.length) list.push(t("A quotation needs at least one line."));
	if (filled.some((r) => Number(r.qty || 0) <= 0)) list.push(t("Quantity must be greater than zero."));
	if (filled.some((r) => Number(r.rate) < 0)) list.push(t("Rate cannot be negative."));
	return list;
});

async function save() {
	if (problems.value.length || saving.value) return;
	saving.value = true;
	try {
		const res = await call("stabler.api.sourcing.save_supplier_quotation", {
			deal: props.deal,
			supplier: form.value.supplier,
			currency: form.value.currency,
			valid_till: form.value.valid_till || null,
			name: form.value.name || null,
			rfq: props.rfq || null,
			company: activeCompany.value,
			items: JSON.stringify(
				form.value.items
					.filter((r) => r.item_code)
					.map((r) => ({ item_code: r.item_code, qty: r.qty, rate: r.rate }))
			),
		});
		form.value.name = res?.name || form.value.name;
		toast.success(t("Quotation saved as a draft."));
		emit("saved", res);
	} catch (err) {
		toast.error(err?.message || t("Could not save the quotation."));
	} finally {
		saving.value = false;
	}
}

/* Ayrı düğme, ayrı uç nokta, ayrı hak: Frappe'de submit yazma hakkının bir
 * uzantısı değil. Taslak yazabilen alıcı, karşılaştırmanın karar vereceği kaydı
 * dondurma yetkisine otomatik sahip değil. */
async function submitQuotation() {
	if (!form.value.name || submitting.value) return;
	submitting.value = true;
	try {
		const res = await call("stabler.api.sourcing.submit_supplier_quotation", {
			name: form.value.name,
			company: activeCompany.value,
		});
		toast.success(t("Quotation submitted."));
		emit("saved", res);
		emit("close");
	} catch (err) {
		toast.error(err?.message || t("Could not submit the quotation."));
	} finally {
		submitting.value = false;
	}
}
</script>

<template>
	<button class="ds-drawer-backdrop" :aria-label="t('Close panel')" tabindex="-1" @click="emit('close')"></button>
	<aside class="ds-drawer" data-size="lg" role="dialog" aria-modal="true" aria-labelledby="qed-title">
		<header class="ds-drawer-head">
			<div>
				<div class="ds-drawer-kicker">{{ deal }}{{ dealLabel ? ` · ${dealLabel}` : "" }}</div>
				<div id="qed-title" class="ds-drawer-title">
					{{ form.name ? t("Edit supplier quotation") : t("New supplier quotation") }}
				</div>
			</div>
			<button type="button" class="ds-drawer-close" :aria-label="t('Close')" @click="emit('close')">✕</button>
		</header>

		<div class="ds-drawer-body qed-body">
			<div class="qed-grid">
				<label class="qed-field">
					<span class="ds-label">{{ t("Supplier") }}</span>
					<Typeahead
						:model-value="form.supplier"
						:display="form.supplierLabel"
						:search="searchSuppliers"
						size="sm"
						:placeholder="t('Search a supplier… ⌘K')"
						@pick="(o) => { form.supplier = o.name; form.supplierLabel = o.label; }"
						@clear="() => { form.supplier = ''; form.supplierLabel = ''; }"
					>
						<template #option="{ item }">{{ item.label }}</template>
					</Typeahead>
				</label>

				<label class="qed-field qed-field--narrow">
					<span class="ds-label">{{ t("Currency") }}</span>
					<Select v-model="form.currency" :options="currencies" size="sm" />
					<span v-if="currencyListFailed" class="ds-hint text-danger" role="alert">
						{{ t("The currency list could not be loaded — only your company's currency is available.") }}
					</span>
				</label>

				<label class="qed-field qed-field--narrow">
					<span class="ds-label">{{ t("Valid till") }}</span>
					<DateInput v-model="form.valid_till" :min="minValidTill" size="sm" />
					<span v-if="form.transaction_date" class="ds-hint">
						{{ t("Quotation date") }}: {{ formatDate(form.transaction_date) }}
					</span>
				</label>
			</div>

			<div class="table-responsive">
			<table class="ds-table qed-lines">
				<thead>
					<tr>
						<th>{{ t("Item") }}</th>
						<th class="ds-td-num qed-col-qty">{{ t("Qty") }}</th>
						<th class="ds-td-num qed-col-rate">{{ t("Rate") }}</th>
						<th class="ds-td-num">{{ t("Line total") }}</th>
						<th class="qed-col-act"></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="(row, index) in form.items" :key="index">
						<td>
							<Typeahead
								:model-value="row.item_code"
								:display="row.itemLabel"
								:search="searchItems"
								size="sm"
								:placeholder="t('Search an item… ⌘K')"
								@pick="(o) => { row.item_code = o.name; row.itemLabel = o.label; }"
								@clear="() => { row.item_code = ''; row.itemLabel = ''; }"
							>
								<template #option="{ item }">{{ item.label }}</template>
							</Typeahead>
						</td>
						<td class="ds-td-num">
							<MoneyInput v-model="row.qty" :language="user.language" hide-currency size="sm" :min="0" />
						</td>
						<td class="ds-td-num">
							<MoneyInput
								v-model="row.rate"
								:currency="form.currency"
								:language="user.language"
								size="sm"
								:min="0"
								:max-fraction-digits="4"
							/>
						</td>
						<td class="ds-td-num ds-mono">{{ fmtAmount(lineTotal(row)) }}</td>
						<td class="qed-col-act">
							<button type="button" class="ds-btn qed-rm" :aria-label="t('Remove line')" @click="removeLine(index)">✕</button>
						</td>
					</tr>
				</tbody>
			</table>
			</div>

			<div class="qed-lines-foot">
				<button type="button" class="ds-btn" @click="addLine">＋ {{ t("Add line") }}</button>
				<span class="ds-mono qed-total">{{ t("Total") }}: {{ fmtAmount(total) }}</span>
			</div>

			<ul v-if="problems.length" class="qed-problems" role="alert">
				<li v-for="p in problems" :key="p">{{ p }}</li>
			</ul>
		</div>

		<footer class="ds-drawer-foot">
			<button
				type="button"
				class="ds-btn ds-btn--primary"
				:disabled="saving || problems.length > 0"
				:aria-busy="saving"
				@click="save"
			>
				{{ saving ? t("Saving…") : t("Save draft") }}
			</button>
			<button
				type="button"
				class="ds-btn"
				:disabled="!form.name || submitting"
				:title="!form.name ? t('Save the draft first') : ''"
				:aria-busy="submitting"
				@click="submitQuotation"
			>
				{{ submitting ? t("Submitting…") : t("Submit quotation") }}
			</button>
			<button type="button" class="ds-btn" @click="emit('close')">{{ t("Close") }}</button>
			<span class="ds-mono qed-src">supplier_quotation · {{ form.name || t("new") }}</span>
		</footer>
	</aside>
</template>

<style scoped>
/* Yalnız yerleşim. Renk, kenar, tipografi katmandan (.ds-*). */
.qed-body {
	padding: 14px var(--ds-pad, 16px);
}

.qed-grid {
	display: flex;
	gap: 12px;
	flex-wrap: wrap;
	margin-bottom: 14px;
}

.qed-field {
	display: flex;
	flex-direction: column;
	gap: 4px;
	flex: 1 1 240px;
	min-width: 0;
}

.qed-field--narrow {
	flex: 0 1 150px;
}

.qed-lines {
	width: 100%;
}

/* Miktar ve oran sütunları sabit: satır eklendikçe kalem sütunu daralmasın. */
.qed-col-qty {
	width: 110px;
}

.qed-col-rate {
	width: 150px;
}

.qed-col-act {
	width: 40px;
}

.qed-rm {
	padding: 2px 8px;
}

.qed-lines-foot {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	margin-top: 10px;
}

.qed-total {
	font-size: 12.5px;
}

/* Engeller listesi: kaydet düğmesi devre dışıysa SEBEBİ görünür olmalı, yoksa
 * kullanıcı tıklamayan bir düğmeye bakıp kalıyor. */
.qed-problems {
	margin: 12px 0 0;
	padding-left: 18px;
	font-size: 12.5px;
	color: var(--ds-crit-tx, #b42318);
}

.qed-src {
	margin-left: auto;
	font-size: 10.5px;
	color: var(--ds-tx3);
}
</style>
