<script setup>
/**
 * İhale Giriş Merkezi — tek seviyeli mimari.
 *
 * Bu çekmece bir Tender Master YARATMAZ; bir CRM Deal yaratır (deal_type=Tender).
 * İhale doğrudan kanban Intake aşamasında belirir — parent/lot dansı yok.
 *
 * 5 bölüm (bu yorum "4 bölüm" diyordu ve E'yi hiç anmıyordu — E sonradan
 * eklendi, özet güncellenmedi; prompt 01 tutarsızlığı ölçüp kapatılmasını
 * istedi ve tasarım E'yi çekmecede bıraktı, ADR-206):
 *   A) Müşteri — Typeahead ile mevcut Customer seç (yoksa Sales'e yönlendir)
 *   B) İhale bilgisi — başlık, no, tarihler, tahmini tutar + currency
 *   C) İhale dosyaları — tek dropzone (snap, PDF, birden fazla)
 *   D) Talep itemları — LineItemsEditor + itemSearcher (yoksa Inventory'ye yönlendir)
 *   E) Teklif verilsin mi — Go/No-go, alım usulü, ceza %/gün, teminat, sertifika
 *
 * Kayıt: crm.save_deal (deal_type=Tender) + tender.save_deal_intake (items + files JSON overlay).
 * Altyapı hazır: custom_tender_intake zaten CRM Deal'da var.
 *
 * Görsel dil: ADR-301'den beri modülün `ds-*` katmanı (stabler-modernist.css).
 * Bu dosyanın kendine ait üçüncü lehçesi 2026-09-03'te emekli edildi. Katman
 * `.stbl-ds` altında kapsamlı — yani bu çekmece yalnız TenderPage'in içinden
 * monte edildiğinde giyinir; dışarıda sınıf adları hiçbir şeye karşılık gelmez.
 */
import { reactive, ref, watch, computed } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { t } from "../composables/i18n.js";
import { useToast } from "../composables/useToast.js";
import { itemSearcher } from "../composables/items.js";
import { customerSearcher } from "../composables/customers.js";
import MoneyInput from "./MoneyInput.vue";
import DateInput from "./DateInput.vue";
import Typeahead from "./Typeahead.vue";
import FileSlot from "./files/FileSlot.vue";

const props = defineProps({
	open: { type: Boolean, default: false },
	/** Mevcut deal düzenleme (null = yeni ihale). */
	deal: { type: Object, default: null },
	initialLot: { type: Object, default: null },
});

const emit = defineEmits(["update:open", "saved", "close"]);

const router = useRouter();
const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const saving = ref(false);
const currencies = ref(["USD", "UZS", "RUB", "EUR"]);

const form = reactive({
	name: "",
	organization: "",
	tender_no: "",
	title: "",
	source: "UZEX",
	publication_date: "",
	submission_deadline: "",
	currency: "USD",
	estimated_total: 0,
	items: [],
	files: [],
	// ── E: pre-win evaluation (ADR-206) ──────────────────────────────────────
	// These six were only editable in TenderIntake.vue, which is embedded in the
	// PO control board — a post-win screen. So the Go/No-Go call had to be made
	// on a screen you only reach after the tender is already won.
	go_no_go: "",
	guarantee_amount: 0,
	guarantee_return: "",
	penalty_pct_per_day: null,
	cert_required: 0,
	purchase_method: "",
});

// ── Müşteri arama (Typeahead) ──────────────────────────────────────────────
// customerSearcher her zaman düz dizi döndürür. Buradaki eski elle yazılmış arama
// müşteri LİSTE sayfasının ucunu çağırıyordu; o uç bir {rows: …} zarfı döndürüyor,
// Typeahead diziyi olmayan her şeyi sessizce [] yapıyor — dropdown hep boş kalıyordu.
const searchCustomers = customerSearcher(() => activeCompany.value);

function pickCustomer(c) {
	if (!c) return;
	form.organization = c.customer_name || c.name || "";
}

// ── Item arama (itemSearcher) ───────────────────────────────────────────────
// Depo GEÇİLMEZ: depo verilince backend `tabBin.actual_qty > 0` filtresi uygular.
// İhale girişi satış öncesi bir ekran — talep edilen item'ın stokta olması
// beklenmez. QuotationForm / PurchaseOrderForm / StockEntries ile aynı desen.
const searchItems = itemSearcher("all");

function blankItemLine() {
	return {
		item_code: "",
		item_name: "",
		qty: 1,
		uom: "",
		rate: 0,
		amount: 0,
	};
}

function addItem() {
	form.items.push(blankItemLine());
}

function removeItem(i) {
	form.items.splice(i, 1);
}

function handlePickItem({ line, item }) {
	if (!item) return;
	line.item_code = item.item_code || item.name || "";
	line.item_name = item.item_name || item.name || "";
	line.uom = item.stock_uom || item.uom || line.uom || "";
	if (!line.rate && item.standard_rate) line.rate = item.standard_rate;
	recomputeLine(line);
}

function recomputeLine(line) {
	line.amount = (Number(line.qty) || 0) * (Number(line.rate) || 0);
}

const itemTotal = computed(() => form.items.reduce((s, l) => s + (Number(l.amount) || 0), 0));

// ── Dosya yükleme ───────────────────────────────────────────────────────────
function onFileUploaded(fileInfo) {
	form.files.push(fileInfo);
}

function removeFile(i) {
	form.files.splice(i, 1);
}

// ── Form reset ───────────────────────────────────────────────────────────────
function reset() {
	form.name = "";
	form.organization = "";
	form.tender_no = "";
	form.title = "";
	form.source = "UZEX";
	form.publication_date = "";
	form.submission_deadline = "";
	form.currency = "USD";
	form.estimated_total = 0;
	form.items = [];
	form.files = [];
	form.go_no_go = "";
	form.guarantee_amount = 0;
	form.guarantee_return = "";
	form.penalty_pct_per_day = null;
	form.cert_required = 0;
	form.purchase_method = "";
}

watch(
	() => props.deal,
	(val) => {
		if (val) {
			form.name = val.name || "";
			form.organization = val.organization || "";
			form.tender_no = val.tender_no || "";
			form.title = val.title || "";
			form.source = val.source || "UZEX";
			form.publication_date = val.publication_date || "";
			form.submission_deadline = val.submission_deadline || "";
			form.currency = val.currency || "USD";
			form.estimated_total = val.deal_value || val.estimated_total || 0;
			form.items = [];
			form.files = [];
			// Intake itemları artık kalıcı; düzenleme kaydı onları silmemeli. Editlenen
			// kaydın intake'i varsa satırlar + ihale künyesi geri yüklenir — yoksa (yeni/
			// henüz intake'siz kayıt) bugünkü gibi boş kalır. Deal çözülemiyorsa sessiz
			// geç: form yine dolar.
			call("stabler.api.tender.deal_intake", {
				deal: val.name,
				company: activeCompany.value,
			})
				.then((res) => {
					if (form.name !== val.name) return; // kullanıcı başka kayda geçti
					const intake = res?.intake || {};
					// Unconditional: the intake JSON is `title`'s only home — `crm.save_deal`
					// does not accept it — so the stored value is the only truth there is.
					// A guard that skipped an empty one left the caller's seed sitting in a
					// required field, and since 8abffa2 made `title` persistent that seed
					// was saved over the real title with no error at any layer.
					form.title = intake.title || "";
					if (intake.tender_no) form.tender_no = intake.tender_no;
					if (intake.source) form.source = intake.source;
					if (intake.publication_date) form.publication_date = intake.publication_date;
					// bid_deadline is the single key (ADR-203); submission_deadline is
					// what this drawer wrote before the rename and still reads back.
					if (intake.bid_deadline || intake.submission_deadline || val.deadline) {
						form.submission_deadline =
							intake.bid_deadline || intake.submission_deadline || val.deadline;
					}
					if (intake.currency) form.currency = intake.currency;
					if (Number(intake.estimated_total) > 0)
						form.estimated_total = Number(intake.estimated_total);
					// Unconditional, unlike the fields above: nothing else writes these
					// six, so the stored value is the only truth there is — and a guard
					// that skipped an empty one would make "cleared" unsavable.
					form.go_no_go = intake.go_no_go || "";
					form.guarantee_amount = Number(intake.guarantee_amount) || 0;
					form.guarantee_return = intake.guarantee_return || "";
					form.penalty_pct_per_day = Number(intake.penalty_pct_per_day) || null;
					form.cert_required = intake.cert_required ? 1 : 0;
					form.purchase_method = intake.purchase_method || "";
					if (Array.isArray(intake.tender_files) && intake.tender_files.length) {
						form.files = intake.tender_files.map((f) => ({
							file_name: f.file_name || "",
							file_url: f.file_url || "",
							file_size: f.file_size || 0,
						}));
					}
					const lines = (intake.items || []).map((l) => ({
						item_code: l.item_code || "",
						item_name: l.item_name || "",
						qty: Number(l.qty) || 1,
						uom: l.uom || "",
						rate: Number(l.rate) || 0,
						amount: Number(l.amount) || 0,
					}));
					if (lines.length) form.items = lines;
				})
				.catch(() => {});
		} else {
			reset();
		}
	},
	{ immediate: true }
);

// Çekmece kapanınca bileşen sökülmüyor, sadece gizleniyor. Tahta "Yeni İhale"de
// `editingTender`'ı null yapıyor — ama zaten null'sa yukarıdaki izleyici (referans
// değişmediği için) hiç tetiklenmiyor. Sonuç: iptal edilen bir giriş bir sonraki
// açılışta olduğu gibi geri geliyordu; kullanıcı yeni ihale açtığını sanırken
// önceki müşteri ve item satırları formda duruyordu. Açılışta deal yoksa sıfırla.
watch(
	() => props.open,
	(open) => {
		if (open && !props.deal) reset();
	}
);

function close() {
	emit("update:open", false);
	emit("close");
}

// ── Yeni müşteri / yeni item yönlendirme ──────────────────────────────────────
function goToNewCustomer() {
	router.push({ name: "sales-customers" });
}

function goToNewItem() {
	router.push({ name: "inventory-items" });
}

// ── Kaydet ─────────────────────────────────────────────────────────────────────
async function save() {
	if (!form.organization) {
		toast.error(t("Customer is required"));
		return;
	}
	if (!form.title) {
		toast.error(t("Title is required"));
		return;
	}
	saving.value = true;
	try {
		// 1. CRM Deal yarat (deal_type=Tender)
		const dealRes = await call("stabler.api.crm.save_deal", {
			data: {
				name: form.name || undefined,
				organization: form.organization,
				deal_type: "Tender",
				tender_no: form.tender_no,
				currency: form.currency,
				deal_value: form.estimated_total || itemTotal.value || 0,
				source: form.source,
			},
			company: activeCompany.value,
		});

		const dealName = dealRes?.name || dealRes?.docname;
		if (!dealName) throw new Error("No deal name returned");

		// 2. custom_tender_intake JSON overlay — items + files + meta
		const intakePayload = {
			title: form.title,
			tender_no: form.tender_no,
			source: form.source,
			publication_date: form.publication_date,
			bid_deadline: form.submission_deadline,
			currency: form.currency,
			estimated_total: form.estimated_total || itemTotal.value || 0,
			items: (form.items || [])
				.filter((l) => l.item_code)
				.map((l) => ({
					item_code: l.item_code,
					item_name: l.item_name,
					qty: Number(l.qty) || 0,
					uom: l.uom,
					rate: Number(l.rate) || 0,
					amount: Number(l.amount) || 0,
				})),
			tender_files: (form.files || []).map((f) => ({
				file_name: f.file_name,
				file_url: f.file_url,
				file_size: f.file_size || 0,
			})),
			// Section E. `go_no_go_at` / `go_no_go_by` are deliberately absent:
			// the server stamps who decided and when (_clean_intake), and a
			// browser-supplied stamp is a claim about the past nobody can check.
			go_no_go: form.go_no_go,
			guarantee_amount: form.guarantee_amount || 0,
			guarantee_return: form.guarantee_return,
			penalty_pct_per_day: form.penalty_pct_per_day || 0,
			cert_required: form.cert_required ? 1 : 0,
			purchase_method: form.purchase_method,
		};

		await call("stabler.api.tender.save_deal_intake", {
			deal: dealName,
			intake: intakePayload,
			company: activeCompany.value,
		});

		toast.success(form.name ? t("Tender updated") : t("Tender created"));
		emit("saved", dealRes);
		close();
	} catch (err) {
		toast.error(err?.message || t("Could not save tender"));
	} finally {
		saving.value = false;
	}
}
</script>

<template>
	<template v-if="open">
		<button
			class="ds-drawer-backdrop"
			:aria-label="t('Close panel')"
			tabindex="-1"
			@click="close"
		></button>
		<aside
			class="ds-drawer"
			data-size="lg"
			role="dialog"
			aria-modal="true"
			aria-labelledby="tender-intake-title"
		>
			<!-- Header -->
			<header class="ds-drawer-head">
				<div class="intake-head">
					<div class="ds-drawer-kicker">
						{{ form.name ? t("Edit") : t("New") }} · CRM Deal · deal_type: Tender
					</div>
					<div id="tender-intake-title" class="ds-drawer-title">
						{{ t("Tender Intake Center") }}
					</div>
				</div>
				<button type="button" class="ds-drawer-close" :aria-label="t('Close')" @click="close">
					✕
				</button>
			</header>

			<!-- Body -->
			<div class="ds-drawer-body">
				<form @submit.prevent="save">
					<!-- ═══ A: Customer ═══ -->
					<section class="ds-form-section">
						<div class="ds-form-section-head">
							<span class="ds-label">A · {{ t("Who is the Tender From?") }}</span>
						</div>
						<div class="ds-form-body">
							<div class="d-flex gap-2 align-items-end">
								<div class="ds-field flex-grow-1">
									<label class="ds-label">
										{{ t("Customer / Buyer") }} <span class="ds-field-req">*</span>
									</label>
									<Typeahead
										v-model="form.organization"
										:search="searchCustomers"
										:display="form.organization"
										:placeholder="t('Search customer…')"
										@pick="pickCustomer"
									/>
								</div>
								<button
									type="button"
									class="btn btn-outline-secondary btn-sm whitespace-nowrap"
									@click="goToNewCustomer"
								>
									+ {{ t("New") }}
									<span class="text-muted ms-1">↗ Sales</span>
								</button>
							</div>
						</div>
					</section>

					<!-- ═══ B: Tender Information ═══ -->
					<section class="ds-form-section">
						<div class="ds-form-section-head">
							<span class="ds-label">B · {{ t("Tender Information") }}</span>
						</div>
						<div class="ds-form-body">
							<div class="ds-field mb-2">
								<label class="ds-label">
									{{ t("Tender Title") }} <span class="ds-field-req">*</span>
								</label>
								<input
									v-model="form.title"
									type="text"
									class="form-control"
									placeholder="UZEX Supply Tender 2026 — Construction Materials"
									required
								/>
							</div>
							<div class="ds-form-grid" data-cols="2">
								<div class="ds-field">
									<label class="ds-label">{{ t("Tender No") }}</label>
									<input
										v-model="form.tender_no"
										type="text"
										class="form-control mono"
										placeholder="UZEX-2026-CM-042"
									/>
								</div>
								<div class="ds-field">
									<label class="ds-label">{{ t("Source") }}</label>
									<select v-model="form.source" class="form-select">
										<option value="UZEX">UZEX</option>
										<option value="Direct">Direct</option>
										<option value="Portal">Portal</option>
										<option value="Other">Other</option>
									</select>
								</div>
								<div class="ds-field">
									<label class="ds-label">{{ t("Publication Date") }}</label>
									<DateInput v-model="form.publication_date" />
								</div>
								<div class="ds-field">
									<label class="ds-label">{{ t("Submission Deadline") }}</label>
									<DateInput v-model="form.submission_deadline" />
								</div>
								<div class="ds-field">
									<label class="ds-label">{{ t("Estimated Total") }}</label>
									<MoneyInput
										v-model="form.estimated_total"
										:currency="form.currency"
										:language="user.language"
									/>
								</div>
								<div class="ds-field">
									<label class="ds-label">{{ t("Currency") }}</label>
									<select v-model="form.currency" class="form-select">
										<option v-for="c in currencies" :key="c" :value="c">{{ c }}</option>
									</select>
								</div>
							</div>
						</div>
					</section>

					<!-- ═══ C: Tender Files ═══ -->
					<section class="ds-form-section">
						<div class="ds-form-section-head">
							<span class="ds-label">C · {{ t("Tender Files") }}</span>
						</div>
						<div class="ds-form-body">
							<div class="ds-file-list" data-mode="edit">
								<div v-for="(f, i) in form.files" :key="i" class="ds-file-row">
									<span aria-hidden="true">📄</span>
									<span class="ds-file-name font-monospace">{{ f.file_name }}</span>
									<span class="ds-file-meta">{{ f.file_size || "" }}</span>
									<button
										type="button"
										class="ds-cut-del"
										:aria-label="t('Remove file')"
										@click="removeFile(i)"
									>
										✕
									</button>
								</div>
							</div>
							<FileSlot :attached-to="'CRM Deal'" @uploaded="onFileUploaded" />
						</div>
					</section>

					<!-- ═══ D: Requested Items ═══ -->
					<section class="ds-form-section">
						<div class="ds-form-section-head">
							<span class="ds-label">D · {{ t("Requested Items") }}</span>
							<div class="d-flex align-items-center gap-1">
								<span class="ds-label">{{ t("Currency") }}:</span>
								<select
									v-model="form.currency"
									class="form-select form-select-sm"
									style="width: 80px"
								>
									<option v-for="c in currencies" :key="c" :value="c">{{ c }}</option>
								</select>
							</div>
						</div>
						<div class="ds-form-body">
							<table v-if="form.items.length" class="table table-no-stripe table-sm align-middle">
								<thead>
									<tr>
										<th>{{ t("Item") }}</th>
										<th class="text-end" style="width: 80px">{{ t("Qty") }}</th>
										<th style="width: 70px">{{ t("UOM") }}</th>
										<th class="text-end" style="width: 100px">{{ t("Price") }}</th>
										<th class="text-end" style="width: 110px">{{ t("Amount") }}</th>
										<th style="width: 30px"></th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(line, i) in form.items" :key="i">
										<td>
											<Typeahead
												v-model="line.item_code"
												:search="searchItems"
												:display="line.item_name || line.item_code"
												:placeholder="t('Search item…')"
												@pick="(item) => handlePickItem({ line, item })"
												@clear="line.item_name = ''"
											/>
										</td>
										<td class="text-end">
											<input
												v-model.number="line.qty"
												type="number"
												class="form-control form-control-sm text-end"
												@input="recomputeLine(line)"
											/>
										</td>
										<td>
											<input v-model="line.uom" type="text" class="form-control form-control-sm" />
										</td>
										<td class="text-end">
											<MoneyInput
												v-model="line.rate"
												:currency="form.currency"
												:language="user.language"
												size="sm"
												@update:model-value="recomputeLine(line)"
											/>
										</td>
										<td class="text-end font-monospace fw-bold">
											{{ line.amount.toLocaleString() }}
										</td>

										<td>
											<button
												type="button"
												class="btn btn-ghost-danger btn-sm py-0"
												@click="removeItem(i)"
											>
												✕
											</button>
										</td>
									</tr>
								</tbody>
							</table>
							<div class="d-flex justify-content-between align-items-center mt-2">
								<div class="d-flex gap-2">
									<button type="button" class="btn btn-ghost-primary btn-sm" @click="addItem">
										+ {{ t("Add Item") }}
									</button>
									<button
										type="button"
										class="btn btn-outline-secondary btn-sm"
										@click="goToNewItem"
									>
										{{ t("New Item") }} <span class="text-muted ms-1">↗ Inventory</span>
									</button>
								</div>
								<div class="text-end">
									<span class="text-muted small">{{ form.items.length }} item · </span>
									<span class="font-monospace fw-bold">{{ itemTotal.toLocaleString() }}</span>
									<span class="text-muted small ms-1">{{ form.currency }}</span>
								</div>
							</div>
						</div>
					</section>

					<!-- ═══ E: Should We Bid? ═══ -->
					<section class="ds-form-section">
						<div class="ds-form-section-head">
							<span class="ds-label">E · {{ t("Should We Bid?") }}</span>
						</div>
						<div class="ds-form-body">
							<div class="ds-form-grid" data-cols="2">
								<div class="ds-field">
									<label class="ds-label">{{ t("Decision") }}</label>
									<select v-model="form.go_no_go" class="form-select">
										<option value="">—</option>
										<option value="go">{{ t("Go") }}</option>
										<option value="no_go">{{ t("No-go") }}</option>
									</select>
								</div>
								<div class="ds-field">
									<label class="ds-label">{{ t("Purchase method") }}</label>
									<select v-model="form.purchase_method" class="form-select">
										<option value="">—</option>
										<option value="auction">{{ t("Auction") }}</option>
										<option value="shop">{{ t("Shop") }}</option>
										<option value="selection">{{ t("Selection") }}</option>
										<option value="tender">{{ t("Tender") }}</option>
									</select>
								</div>
								<div class="ds-field">
									<label class="ds-label">{{ t("Penalty %/day") }}</label>
									<input
										v-model.number="form.penalty_pct_per_day"
										type="number"
										step="0.01"
										class="form-control"
									/>
								</div>
								<div class="ds-field">
									<label class="ds-label">{{ t("Guarantee") }}</label>
									<MoneyInput
										v-model="form.guarantee_amount"
										:currency="form.currency"
										:language="user.language"
									/>
								</div>
								<div class="ds-field">
									<label class="ds-label">{{ t("Guarantee return") }}</label>
									<DateInput v-model="form.guarantee_return" />
								</div>
								<!-- The checkbox carries its own label, so it is a grid cell and not a
								     `ds-field`: a second label above it would name the same control twice. -->
								<div class="d-flex align-items-end">
									<label class="form-check mb-2">
										<input
											v-model="form.cert_required"
											type="checkbox"
											class="form-check-input"
											:true-value="1"
											:false-value="0"
										/>
										<span class="form-check-label">{{ t("Certificate required") }}</span>
									</label>
								</div>
							</div>
						</div>
					</section>
				</form>
			</div>

			<!-- Footer -->
			<div class="ds-drawer-foot">
				<button type="submit" class="btn btn-primary" :disabled="saving" @click="save">
					<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Save Tender") }}
				</button>
				<button type="button" class="btn btn-ghost-secondary" :disabled="saving" @click="close">
					{{ t("Cancel") }}
				</button>
			</div>
		</aside>
	</template>
</template>

<style scoped>
/* Layout only. Colour, border tone and typography come from the layer (.ds-*),
 * exactly as in the board this drawer opens from (TenderCrm.vue's own block). */

/* The head's text column. It shares the row with the close button, so a long
 * title has to wrap rather than push the button off the edge. */
.intake-head {
	flex: 1;
	min-width: 0;
}

/* Adjacent stack — settled 2026-09-01 with the alternative drawn beside it.
 * The layer frames `.ds-form-section` as a free-standing card (border + 14px
 * gap) because its first caller is a page-width form; five cards inside a
 * 760px drawer spend some 60px of the scroll on separation alone, and the eye
 * counts frames before it reads fields. So inside THIS body the sections sit
 * flush and are divided by their own heads — which is also what the drawer
 * looked like before the migration, so the class names change and the user
 * sees the same form. Scoped to the drawer body: no other caller of the
 * layer's form grammar is touched. */
.ds-drawer-body .ds-form-section {
	border: 0;
	margin-bottom: 0;
}
.ds-drawer-body .ds-form-section + .ds-form-section .ds-form-section-head {
	border-top: 1px solid var(--ds-ln);
}

/* A section head carries its heading and, in section D, a currency picker.
 * Measured worst-case interface-language growth is 3.75x, so the pair wraps
 * instead of crushing the picker. */
.ds-drawer-body .ds-form-section-head {
	flex-wrap: wrap;
}

.whitespace-nowrap {
	white-space: nowrap;
}
</style>
