/* Süreç adımlarının ortak sözlüğü.
 *
 * İki ekran aynı adımları çiziyor — `/tender/flow` tam tabloyu, `/dashboard`
 * özet şeridi. Aynı adıma iki ekranda iki farklı isim vermek, `tender_flow`
 * ekranının kendi başlığındaki uyarının aynısı: iki sayının farklı görünmesi
 * ikisine de güveni bitirir. İsimler bu yüzden tek yerde.
 */
import { t } from "../../composables/i18n.js";

const STEP_LABELS = {
	seen: "Intake — file opened",
	go: "GO / NO-GO decision",
	sourcing: "Quotation gathering",
	priced: "Bid pricing",
	submitted: "Bid submitted",
};

/* Tasarımın üç durumu artı iki dürüstlük durumu. `empty` ile `unknown` ayrı
 * kelimeler: boş adımda bekleyen iş yok, damgasız adımda bekleyen iş var ama
 * süresini bilmiyoruz. */
const STATE_LABELS = {
	in: "Within",
	edge: "At the edge",
	out: "Over SLA",
	unknown: "Not measurable",
	empty: "Empty",
};

export const stepLabel = (key) => t(STEP_LABELS[key] || key);
export const stateLabel = (state) => t(STATE_LABELS[state] || state);

/* `ds-wait` yalnız kenar ve aşım için renkleniyor; "içinde" olan bir bekleme
 * süresini vurgulamak, gözü sorunu olmayan satıra çeker. */
export const waitState = (row) => (row.state === "out" || row.state === "edge" ? row.state : null);
