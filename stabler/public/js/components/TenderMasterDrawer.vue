<script setup>
/**
 * İhale Giriş Merkezi — tek seviyeli mimari.
 *
 * Bu çekmece bir Tender Master YARATMAZ; bir CRM Deal yaratır (deal_type=Tender).
 * İhale doğrudan kanban Intake aşamasında belirir — parent/lot dansı yok.
 *
 * 4 bölüm:
 *   A) Müşteri — Typeahead ile mevcut Customer seç (yoksa Sales'e yönlendir)
 *   B) İhale bilgisi — başlık, no, tarihler, tahmini tutar + currency
 *   C) İhale dosyaları — tek dropzone (snap, PDF, birden fazla)
 *   D) Talep itemları — LineItemsEditor + itemSearcher (yoksa Inventory'ye yönlendir)
 *
 * Kayıt: crm.save_deal (deal_type=Tender) + tender.save_deal_intake (items + files JSON overlay).
 * Altyapı hazır: custom_tender_intake zaten CRM Deal'da var.
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

const itemTotal = computed(() =>
	form.items.reduce((s, l) => s + (Number(l.amount) || 0), 0)
);

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
}

watch(
	() => props.deal,
	(val) => {
		if (val) {
			form.name = val.name || "";
			form.organization = val.organization || "";
			form.tender_no = val.tender_no || "";
			form.title = val.title || val.organization || "";
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
					if (intake.title) form.title = intake.title;
					if (intake.tender_no) form.tender_no = intake.tender_no;
					if (intake.source) form.source = intake.source;
					if (intake.publication_date) form.publication_date = intake.publication_date;
					if (intake.submission_deadline || val.deadline) {
						form.submission_deadline = intake.submission_deadline || val.deadline;
					}
					if (intake.currency) form.currency = intake.currency;
					if (Number(intake.estimated_total) > 0) form.estimated_total = Number(intake.estimated_total);
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
			submission_deadline: form.submission_deadline,
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
			documents: [],
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
	<div v-if="open" class="modal-backdrop fade show" @click="close"></div>
	<div v-if="open" class="tgm-drawer fade show d-block" tabindex="-1" role="dialog">
		<div class="tgm-drawer-dialog">
			<div class="tgm-drawer-content">
				<!-- Header -->
				<div class="tgm-drawer-header">
					<div>
						<div class="tgm-kicker">
							{{ form.name ? t("Edit") : t("New") }} · CRM Deal · deal_type: Tender
						</div>
						<h3 class="tgm-drawer-title">
							{{ t("Tender Intake Center") }}
						</h3>
					</div>
					<button type="button" class="btn-close" @click="close"></button>
				</div>

				<!-- Body -->
				<div class="tgm-drawer-body">
					<form @submit.prevent="save">

						<!-- ═══ A: Customer ═══ -->
						<div class="tgm-section">
							<div class="tgm-sec-head">
								<span class="tgm-sec-num">A</span>
								{{ t("Who is the Tender From?") }}
							</div>
							<div class="tgm-sec-body">
								<div class="d-flex gap-2 align-items-end">
									<div class="flex-grow-1">
										<label class="form-label required">{{ t("Customer / Buyer") }}</label>
										<Typeahead
											v-model="form.organization"
											:search="searchCustomers"
											:display="form.organization"
											:placeholder="t('Search customer…')"
											@pick="pickCustomer"
										/>
									</div>
									<button type="button" class="btn btn-outline-secondary btn-sm whitespace-nowrap" @click="goToNewCustomer">
										+ {{ t("New") }}
										<span class="text-muted ms-1">↗ Sales</span>
									</button>
								</div>
							</div>
						</div>

						<!-- ═══ B: Tender Information ═══ -->
						<div class="tgm-section">
							<div class="tgm-sec-head">
								<span class="tgm-sec-num">B</span>
								{{ t("Tender Information") }}
							</div>
							<div class="tgm-sec-body">
								<div class="mb-2">
									<label class="form-label required">{{ t("Tender Title") }}</label>
									<input v-model="form.title" type="text" class="form-control"
										placeholder="UZEX Supply Tender 2026 — Construction Materials" required />
								</div>
								<div class="row g-2 mb-2">
									<div class="col-6">
										<label class="form-label">{{ t("Tender No") }}</label>
										<input v-model="form.tender_no" type="text" class="form-control mono"
											placeholder="UZEX-2026-CM-042" />
									</div>
									<div class="col-6">
										<label class="form-label">{{ t("Source") }}</label>
										<select v-model="form.source" class="form-select">
											<option value="UZEX">UZEX</option>
											<option value="Direct">Direct</option>
											<option value="Portal">Portal</option>
											<option value="Other">Other</option>
										</select>
									</div>
								</div>
								<div class="row g-2 mb-2">
									<div class="col-6">
										<label class="form-label">{{ t("Publication Date") }}</label>
										<DateInput v-model="form.publication_date" />
									</div>
									<div class="col-6">
										<label class="form-label">{{ t("Submission Deadline") }}</label>
										<DateInput v-model="form.submission_deadline" />
									</div>
								</div>
								<div class="row g-2 align-items-end">
									<div class="col-8">
										<label class="form-label">{{ t("Estimated Total") }}</label>
										<MoneyInput v-model="form.estimated_total"
											:currency="form.currency" :language="user.language" />
									</div>
									<div class="col-4">
										<label class="form-label">{{ t("Currency") }}</label>
										<select v-model="form.currency" class="form-select">
											<option v-for="c in currencies" :key="c" :value="c">{{ c }}</option>
										</select>
									</div>
								</div>
							</div>
						</div>

						<!-- ═══ C: Tender Files ═══ -->
						<div class="tgm-section">
							<div class="tgm-sec-head">
								<span class="tgm-sec-num">C</span>
								{{ t("Tender Files") }}
							</div>
							<div class="tgm-sec-body">
								<div class="tgm-file-list">
									<div v-for="(f, i) in form.files" :key="i" class="tgm-file-chip">
										<span>📄</span>
										<span class="tgm-file-name font-monospace">{{ f.file_name }}</span>
										<span class="text-muted small">{{ f.file_size || '' }}</span>
										<button type="button" class="btn-close btn-sm" @click="removeFile(i)"></button>
									</div>
								</div>
								<FileSlot
									:attached-to="'CRM Deal'"
									@uploaded="onFileUploaded"
								/>
							</div>
						</div>

						<!-- ═══ D: Requested Items ═══ -->
						<div class="tgm-section">
							<div class="tgm-sec-head">
								<span class="tgm-sec-num">D</span>
								{{ t("Requested Items") }}
								<div class="ms-auto d-flex align-items-center gap-1">
									<span class="text-muted small">{{ t("Currency") }}:</span>
									<select v-model="form.currency" class="form-select form-select-sm" style="width:80px">
										<option v-for="c in currencies" :key="c" :value="c">{{ c }}</option>
									</select>
								</div>
							</div>
							<div class="tgm-sec-body">
								<table v-if="form.items.length" class="table table-no-stripe table-sm align-middle">
									<thead>
										<tr>
											<th>{{ t("Item") }}</th>
											<th class="text-end" style="width:80px">{{ t("Qty") }}</th>
											<th style="width:70px">{{ t("UOM") }}</th>
											<th class="text-end" style="width:100px">{{ t("Price") }}</th>
											<th class="text-end" style="width:110px">{{ t("Amount") }}</th>
											<th style="width:30px"></th>
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
												<input v-model.number="line.qty" type="number" class="form-control form-control-sm text-end"
													@input="recomputeLine(line)" />
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
											<td class="text-end font-monospace fw-bold">{{ line.amount.toLocaleString() }}</td>

											<td>
												<button type="button" class="btn btn-ghost-danger btn-sm py-0" @click="removeItem(i)">✕</button>
											</td>
										</tr>
									</tbody>
								</table>
								<div class="d-flex justify-content-between align-items-center mt-2">
									<div class="d-flex gap-2">
										<button type="button" class="btn btn-ghost-primary btn-sm" @click="addItem">+ {{ t("Add Item") }}</button>
										<button type="button" class="btn btn-outline-secondary btn-sm" @click="goToNewItem">
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
						</div>

					</form>
				</div>

				<!-- Footer -->
				<div class="tgm-drawer-footer">
					<button type="button" class="btn btn-ghost-secondary" :disabled="saving" @click="close">
						{{ t("Cancel") }}
					</button>
					<button type="submit" class="btn btn-primary" :disabled="saving" @click="save">
						<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save Tender") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.modal-backdrop { opacity: 0.5; z-index: 1040; }
.tgm-drawer {
	position: fixed; top: 0; right: 0; bottom: 0; z-index: 1050;
	width: 720px; max-width: 100vw;
	background: var(--stbl-surface, #fff);
	box-shadow: -4px 0 24px rgba(0,0,0,0.15);
	display: flex; flex-direction: column;
}
.tgm-drawer-dialog { height: 100%; display: flex; flex-direction: column; }
.tgm-drawer-content { height: 100%; display: flex; flex-direction: column; }

.tgm-drawer-header {
	padding: 16px 24px; border-bottom: 1px solid var(--stbl-border, #dbe1ea);
	display: flex; align-items: center; justify-content: space-between;
}
.tgm-kicker {
	font-family: var(--stbl-mono, ui-monospace, monospace);
	font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.05em;
	color: var(--stbl-muted, #6c7a91); font-weight: 700;
}
.tgm-drawer-title { font-size: 18px; font-weight: 800; margin: 2px 0 0; }

.tgm-drawer-body { padding: 0; overflow-y: auto; flex: 1; }

.tgm-section { border-bottom: 1px solid var(--stbl-border, #dbe1ea); }
.tgm-sec-head {
	display: flex; align-items: center; gap: 8px;
	padding: 10px 24px; background: #f8f9fb;
	border-bottom: 1px solid var(--stbl-border, #dbe1ea);
	font-size: 13px; font-weight: 700;
}
.tgm-sec-num {
	width: 22px; height: 22px; border-radius: 6px;
	background: var(--tblr-primary, #206bc4); color: #fff;
	font-size: 11px; font-weight: 800;
	display: flex; align-items: center; justify-content: center;
}
.tgm-sec-body { padding: 16px 24px; }

.tgm-file-list { margin-bottom: 8px; }
.tgm-file-chip {
	display: flex; align-items: center; gap: 8px;
	padding: 6px 10px; background: #fff;
	border: 1px solid var(--stbl-border, #dbe1ea); border-radius: 7px;
	font-size: 12px; margin-bottom: 5px;
}
.tgm-file-name { flex: 1; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.tgm-drawer-footer {
	padding: 12px 24px; border-top: 1px solid var(--stbl-border, #dbe1ea);
	background: #fbfcfe; display: flex; justify-content: flex-end; gap: 8px;
}

.whitespace-nowrap { white-space: nowrap; }
</style>
