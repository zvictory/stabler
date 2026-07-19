# KassaBot (mikas) — Tam Özellik Dokümanı

> **Kime ait?** Bu özellik **yalnızca `mikas` tenant'ına** aittir ve `tender` / `money`
> modülleriyle gate'lenir. Modül kapalı olan hiçbir tenant'ta görünmez.
> **Karıştırma uyarısı:** PI / PI Group özellikleri **yalnızca `msa`**'ya aittir; KassaBot
> ile hiçbir ilgisi yoktur. Bu iki özellik farklı tenant'lara, farklı modüllere aittir.

> **Kapsam:** Bu bir referans / spec dokümanıdır. WP-K1 → WP-K9 iş paketleri boyunca
> geliştirilen Telegram kasa botunun (KassaBot) tüm iş ve teknik özelliklerini tek yerde
> toplar. Atıflar `dosya:satır` formatındadır ve yazım anında (2026-07-19) doğrulanmıştır.

> ⚠️ **v2 yönü (2026-07-19):** Bu doküman **v1'i (gerçek-GL'e yazan bot)** anlatır. Yeni yön
> **shadow mode** — bot GL'e/ERPNext'e DOKUNMAZ, gün başı bakiye admin-sync'li, kassir akıllı
> Özbekçe serbest-metin yazar. Tasarım + WP-S1..S5: `docs/plans/2026-07-19-kassabot-shadow-mode.md`.
> KİLİTLİ: saf shadow (GL'e asla yazmaz), sync şimdilik admin.

---

## İçindekiler

1. [Genel bakış ve mimari ilke](#1-genel-bakış-ve-mimari-ilke)
2. [Kasa hesap ağacı (CoA)](#2-kasa-hesap-ağacı-coa)
3. [Bot operasyonları (iş özellikleri)](#3-bot-operasyonları-iş-özellikleri)
4. [Akıllı girdi ayrıştırma (WP-K6 / WP-K8)](#4-akıllı-girdi-ayrıştırma-wp-k6--wp-k8)
5. [Konvertatsiya detayı (WP-K9)](#5-konvertatsiya-detayı-wp-k9)
6. [Telegram Mini App (WP-K7)](#6-telegram-mini-app-wp-k7)
7. [Admin ekranı (SPA)](#7-admin-ekranı-spa)
8. [Doctype'lar](#8-doctypelar)
9. [Backend endpoint envanteri](#9-backend-endpoint-envanteri)
10. [Güvenlik / izin / gating](#10-güvenlik--izin--gating)
11. [Kod haritası](#11-kod-haritası)
12. [WP-K1 → WP-K9 tarihçesi](#12-wp-k1--wp-k9-tarihçesi)
13. [İlgili runbook'lar](#13-i̇lgili-runbooklar)

---

## 1. Genel bakış ve mimari ilke

**KassaBot**, mikas kasadarlarının (kassir) günlük nakit/plastik/döviz işlemlerini
**Telegram üzerinden** yazmasını sağlayan bir bottur. Yanında bir **Telegram Mini App**
(`/kassa`) ile bakiye ve ekstre görüntüleme sunar.

### İnce-glue mimarisi

KassaBot **yeni bir muhasebe motoru değildir.** Mevcut `stabler.api.money`
endpoint'lerinin üstünde duran **ince bir Telegram glue katmanıdır** — yalnızca
"kullanıcıya ne sorulacak, ne cevap verilecek" akışını yönetir; para hareketini
her zaman aynı money.py fonksiyonlarına yazdırır:

| Bot operasyonu | money.py karşılığı |
|----------------|--------------------|
| Kirim (giriş)  | `create_payment_entry` |
| Chiqim (gider) | `submit_expense_entry` |
| Konvertatsiya / Kassadan-kassaga | `submit_transfer_entry` |
| Mening jadvalim (ekstre/bakiye) | `account_transactions` / `chart_balances` |

Bu ilke `execute_action` içinde açıkça belgelenmiştir:
`bot.py:447` — *"Map a completed flow action onto the EXISTING money.py endpoints."*

### Impersonation (kullanıcı taklidi) modeli

Botun kritik güvenlik/tutarlılık ilkesi: **her işlem, kassirin kendi Stabler
kullanıcısı olarak** çalıştırılır. `handle_update` içinde:

```
original_user = frappe.session.user
try:
    frappe.set_user(kassir.user)      # bot.py:645
    ... akışı işle, money.py'ye yaz ...
finally:
    frappe.set_user(original_user)    # bot.py:675
```

Sonuç: company-scope filtreleri, maker-checker onayları ve backdating governance
**SPA'daki davranışın birebir aynısı** olarak uygulanır — bot ayrı bir ayrıcalık
katmanı açmaz. Onaya düşen bir işlem `pending_approval` olarak geri döner
(`_format_result_text`, `bot.py:508`).

### Frappe'siz state machine

Akış mantığı (`_flow.py`) Frappe'den **bağımsız, saf Python**'dır: `STEP_*` sabitleri
ve parse fonksiyonları unit-test edilebilir (`tests/test_kassa_flow.py`). Frappe'ye
dokunan tek katman `bot.py` (context + execute) ve `webhook.py`'dir. Bu ayrım, akış
mantığının bench olmadan test edilmesini sağlar.

---

## 2. Kasa hesap ağacı (CoA)

Kassirler yalnızca kendilerine atanmış **yaprak nakit hesapları** üzerinde işlem yapar.
mikas kasa ağacı dört kasa ve üç para/araç türünden oluşur:

| Kasa kodu | Açıklama | Türler (yaprak) |
|-----------|----------|-----------------|
| **AKASSA** | Ana kasa | UZS, PK (plastik karta), USD |
| **QKASSA** | (ikinci kasa) | UZS, PK, USD |
| **SKASSA** | (üçüncü kasa) | UZS, PK, USD |
| **TKASSA** | (dördüncü kasa) | UZS, PK, USD |

- **PK = plastik karta** (kart POS bakiyesi), UZS'den ayrı bir yaprak hesap.
- Bir kassire hangi yaprakların açık olduğu `Stabler Kassir` doctype'ının
  `accounts` child tablosunda tutulur (bkz. §8).
- Bot, `build_ctx` (`bot.py:318`) ile bu izinli hesap listesini yükler ve
  menüleri buna göre kurar — kassir izinsiz bir kasaya yazamaz.

---

## 3. Bot operasyonları (iş özellikleri)

Ana menü klavyesi `_flow.py:95` (`MENU_KEYBOARD`) ile tanımlıdır. Her operasyon,
`_flow.py`'deki bir dizi `STEP_*` durumuyla (satır 46-77) yürütülür; adımlar
`handle()` dispatcher'ında (`_flow.py:1234`) yönlendirilir.

### 🟢 Kirim — nakit/plastik giriş
- **Ne yapar:** Kasaya para girişi kaydeder.
- **Akış:** hesap seç → miktar → izoh (zorunlu açıklama) → onay.
- **money.py:** `create_payment_entry` (Receive yönünde).

### 🔴 Chiqim — gider
- **Ne yapar:** Kasadan gider öder ve bir **gider kategorisine** (hesaba) işler.
- **Akış:** ödeme kaynağı (payment_from) → **kategori filtre + sayfalı seçim** → miktar →
  izoh → **opsiyonel Tender / CRM Deal etiketi** → onay.
- **money.py:** `submit_expense_entry` (`bot.py:476-503`), `entry_kind="Expense"`,
  `deal=action.get("deal")`.
- **Çapraz-döviz gider:** ödeme hesabının para birimi şirket ana biriminden farklıysa,
  bot **Expenses.vue ile birebir aynı** kur mantığını uygular: `get_exchange_rate_for_currencies(base, leaf)` çağrılır ve **tersi** (`1/base_to_leaf`) `exchange_rate`
  olarak geçilir (`bot.py:477-490`). Bu, SPA ile hesap tutarlılığını garanti eder.

### 🔄 Konvertatsiya — kasa-içi döviz çevrimi
- **Ne yapar:** Aynı kasada bir dövizi diğerine çevirir (ör. UZS → PK, USD → UZS).
- **Akış:** yön seç (yön-çiftleri) → verilen miktar → **CBU kur asistanı** (tek-tık
  kabul) → alınan miktar → izoh → onay.
  (`_handle_konv_*`, `_flow.py:984-1128`)
- **money.py:** `submit_transfer_entry` (`bot.py:464-474`).
- Detaylar §5'te.

### 💱 Kassadan kassaga (K2K) — kasalar arası transfer
- **Ne yapar:** İki kasa arasında **aynı döviz** transferi.
- **Akış:** kaynak kasa → hedef kasa → miktar → izoh → onay.
  (`_handle_k2k_*`, `_flow.py:1128-1188`)
- **money.py:** `submit_transfer_entry`.

### 📝 Qolib ketgan amal — geç kalmış / backdated işlem
- **Ne yapar:** Geçmiş tarihli tek-seferlik bir işlem yazmak için tarih girişini açar.
- **Akış:** `STEP_BACKDATE` (`_flow.py:77`), `_handle_backdate` (`_flow.py:1188`);
  `parse_date_ddmmyyyy` (`_flow.py:319`) ile `dd.mm.yyyy` ayrıştırılır.
- **Tek-seferlik:** akış, `new_state`'te `posting_date`'i tekrar `None`'a resetler;
  bu yüzden `execute_action` posting_date'i **handle() ilerlemeden ÖNCEki** state'ten
  alır (`bot.py:450-461`). Backdated işlemlerde sonuç metnine bir uyarı eklenir.

### ℹ️ Mening jadvalim — ekstre / bakiye
- **Ne yapar:** Kassirin hesaplarının bakiyesini ve son hareketlerini gösterir.
- **Akış:** son `_STATEMENT_LOOKBACK=5` (`bot.py:35`) hareket + Mini App linki.
- **money.py:** `account_transactions` / `chart_balances`; zengin görünüm için Mini App
  (`kassa_summary`, §6).

### ❌ Bekor qilish — iptal
- **Ne yapar:** Devam eden akışı iptal edip ana menüye döner (state temizlenir).

---

## 4. Akıllı girdi ayrıştırma (WP-K6 / WP-K8)

Kassirin hızlı yazabilmesi için `_flow.py` çok biçimli miktar/komut ayrıştırması yapar:

- **Kelime-sayılar (uz/tr):** "besh ming", "ikki million" gibi → `_parse_word_number`
  (`_flow.py:243`).
- **Sonek kısaltmaları:** `100k`, `1.5m`, `ming`, `mln` → `_parse_suffix_shorthand`
  (`_flow.py:164`). Örn. `500k` = 500 000; `1.5m` = 1 500 000.
- **Birleşik ayrıştırıcı:** `parse_amount` (`_flow.py:302`) tüm biçimleri tek girişte
  dener.
- **Tek-satır hızlı transfer:** "somdan pkga 500 ming ..." gibi tek cümlelik komut →
  `parse_quick_transfer` (`_flow.py:545`), akışı adım adım sormadan doldurur.
- **Ham echo ("Yozganingiz: …"):** Kullanıcının yazdığı ham metin geri gösterilir
  (`_typed_echo`, `_flow.py:615`) — yanlış anlaşılmayı önler.
- **Zorunlu izoh:** Her para işleminde açıklama (izoh) zorunludur; boş geçilemez.
- **Memo kompozisyonu:** Transfer memo'su otomatik derlenir
  (`_compose_transfer_memo`, `bot.py:424`), gerekli bağlamı (yön, kur) içerir.
- **Tarih/biçim:** `dd.mm.yyyy` girişi `parse_date_ddmmyyyy` (`_flow.py:319`); gruplu
  gösterim `format_amount` (`_flow.py:334`).

---

## 5. Konvertatsiya detayı (WP-K9)

Konvertatsiya, kasa-içi döviz çevriminin **yön-çiftleri** modeliyle çalışır:

- **Yön-çiftleri:** İzinli yapraklardan olası (kaynak → hedef) çiftleri üretilir —
  `_konv_direction_pairs` (`_flow.py:956`). Kassir listeden yönü seçer
  (`_handle_konv_direction`, `_flow.py:984`).
- **Verilen miktar → CBU kur asistanı:** Kassir verdiği miktarı girer
  (`_handle_konv_given`, `_flow.py:1012`); ardından **CBU (Markaziy Bank) kuru**
  tek-tık öneri olarak sunulur (`_handle_konv_cbu_choice`, `_flow.py:1049`). Kassir
  kabul eder ya da elle girer.
- **Alınan miktar:** `_handle_konv_received` (`_flow.py:1066`).
- **İzoh + onay:** `_handle_konv_memo` (`_flow.py:1076`), `_handle_konv_confirm`
  (`_flow.py:1084`).
- **money.py:** `submit_transfer_entry` — `from_amount` ve (çapraz-döviz ise)
  `to_amount` ile (`bot.py:464-474`). Aynı-döviz durumunda tek miktar yeterlidir;
  çapraz-döviz durumunda iki taraf da yazılır.

---

## 6. Telegram Mini App (WP-K7)

Telegram içinde açılan hafif bir web görünümü — bakiye kartları + GL ekstresi.

- **Sayfa kabuğu:** `stabler/www/kassa.py` (`get_context`, satır 15) →
  `no_cache=1`, `no_sitemap=1`, **misafir (guest) statik kabuk**, sıfır session
  bağlamı. Veri tamamen XHR ile gelir.
- **Auth — initData HMAC:** Tek kimlik, Telegram'ın `initData` imzasıdır.
  `verify_init_data` (`miniapp.py:61`) Telegram'ın resmi doğrulamasını uygular:
  `secret_key = HMAC_SHA256("WebAppData", bot_token)`, sonra `data_check_string`
  üzerinden `computed_hash` hesaplanıp `hmac.compare_digest` ile karşılaştırılır
  (`miniapp.py:75-77`). `max_age_seconds=86400` ile süresi geçmiş initData reddedilir.
- **Endpoint:** `kassa_summary` (`miniapp.py:248`), whitelisted `allow_guest=True` +
  `rate_limit(limit=120, seconds=60)` (`miniapp.py:287`). Fail-closed: initData
  doğrulanamazsa **hiçbir veri dönmez** — `init_data` veya token asla loglanmaz.
- **Impersonation:** endpoint de initData'yı bir **enabled** `Stabler Kassir`'e
  (`telegram_user_id`) çözüp `frappe.set_user(kassir.user)` ile çalışır ve `finally`
  içinde geri alır (`miniapp.py:279-283`).
- **İçerik:** bakiye kartları (`_build_cards`, `miniapp.py:163`) + ekstre satırları
  (`_build_rows`, `miniapp.py:186`); tarih aralığı `_resolve_date_range`
  (`miniapp.py:135`).

---

## 7. Admin ekranı (SPA)

Stabler SPA içinde kassir yönetim ekranı — **Frappe Desk'e çıkış yok** (proje kuralı).

- **Rota:** `#/admin/kassa-bot`, `router.js:475`
  (`{ path: "kassa-bot", name: "admin-kassa-bot", component: AdminKassaBot }`),
  import `router.js:148`.
- **Nav:** `AdminHome.vue:22` — `ti-brand-telegram` ikonu, `t("Kassa Bot")`.
- **Bileşen:** `pages/admin/KassaBot.vue` (415 satır) — kassir listesi + drawer;
  alanlar: `telegram_user_id`, `user`, `company`, `enabled` (kill-switch toggle),
  izinli hesap (accounts) seçimi.
- **API sarmalayıcı:** `api/kassaAdmin.js` — `kassaAdminApi.{listKassirs, getKassir,
  createKassir, updateKassir, setKassirEnabled, deleteKassir}` (satır 4-10), hepsi
  `stabler.api.kassa_admin.*` çağırır.

---

## 8. Doctype'lar

### `Stabler Kassir` — ana doctype
- **Dosya:** `stabler/stabler/doctype/stabler_kassir/stabler_kassir.json`
- **autoname:** `field:telegram_user_id` — kayıt adı doğrudan Telegram kullanıcı id'sidir.
- **Alanlar:** `telegram_user_id` (Data, **reqd + unique**), `user` (Link → User,
  reqd), `company` (Link → Company, reqd), `enabled` (Check, **default `1`**),
  `section_accounts` (Section Break), `accounts` (Table → Stabler Kassir Account).
- **İzinler:** yalnız **System Manager** (create/read/write/delete). Doctype
  seviyesinde de kilitli — API guard'ıyla (§10) çift katman. `track_changes: 1`.
- **`unique:1`** sayesinde bir Telegram kullanıcısına en fazla bir kassir kaydı.
- **Kill-switch:** `enabled=0` → kassir botta çözülemez (`_resolve_kassir`
  `{telegram_user_id, enabled:1}` filtreler, `bot.py:605`) → işlem yapamaz.
  Kayıt silinmez, sadece toggle kapatılır.

### `Stabler Kassir Account` — child doctype
- **Dosya:** `.../stabler_kassir_account/stabler_kassir_account.json`
- `istable:1`, tek alan: `account` (Link → Account, reqd, in_list_view),
  `permissions:[]` (parent'tan miras). Bir kassire hangi yaprak kasa hesaplarının
  açık olduğunu listeler.

---

## 9. Backend endpoint envanteri

| Endpoint | Dosya:satır | Guard | Not |
|----------|-------------|-------|-----|
| `telegram_webhook` | `webhook.py:39` | `allow_guest=True`, `rate_limit(120/60s)`, fail-closed secret | Telegram update giriş noktası; her zaman `{"ok": True}` döner |
| `kassa_summary` | `miniapp.py:248` | `allow_guest=True`, `rate_limit(120/60s)`, initData HMAC | Mini App verisi; fail-closed |
| `list_kassirs` | `kassa_admin.py:23` | System Manager | Admin liste |
| `get_kassir` | `kassa_admin.py:48` | System Manager | Tekil kayıt |
| `create_kassir` | `kassa_admin.py:65` | System Manager | `telegram_user_id` dupe-guard |
| `update_kassir` | `kassa_admin.py:94` | System Manager | accounts clear-then-append; `telegram_user_id` değiştirilemez |
| `set_kassir_enabled` | `kassa_admin.py:122` | System Manager | inline kill-switch |
| `delete_kassir` | `kassa_admin.py:135` | System Manager | kayıt sil |

**Webhook fail-closed secret** (`webhook.py:46-54`): beklenen secret
`frappe.conf.kassa_telegram_secret`, gelen başlık `X-Telegram-Bot-Api-Secret-Token`;
`verify_secret(...)` (uzex'ten paylaşılan) başarısızsa `PermissionError` fırlatılır.
**Secret değerleri asla loglanmaz.** Doğrulama geçerse `bot.handle_update(update)`
çağrılır (`webhook.py:62`).

---

## 10. Güvenlik / izin / gating

| Katman | Mekanizma | Referans |
|--------|-----------|----------|
| **Modül gating** | `tender` / `money` modülü kapalıysa özellik görünmez; tenant adına dallanma YOK | proje kuralı (Tenant & feature ownership) |
| **Webhook auth** | Fail-closed secret token (başlık ↔ `frappe.conf`) | `webhook.py:46-54` |
| **Mini App auth** | initData HMAC-SHA256 (`WebAppData` anahtarı) + 24s tazelik | `miniapp.py:61-77` |
| **Impersonation** | Her işlem kassirin Stabler user'ı olarak (try/finally restore) | `bot.py:645-675`, `miniapp.py:279-283` |
| **Kill-switch** | `enabled=0` → kassir çözülemez | `bot.py:605`, `kassa_admin.py:122` |
| **Admin erişimi** | Sadece System Manager (API + doctype izni) | `kassa_admin.py:_require_admin @18`, doctype `permissions` |
| **Config sırları** | `kassa_telegram_token`, `kassa_telegram_secret` — `site_config.json`, `frappe.conf` üzerinden okunur, **asla loglanmaz** | (değerler bu dokümanda YAZILMAZ) |

> **Not:** SPA gating bir **UX erişim katmanıdır**, güvenlik sınırı değildir. Gerçek
> veri güvenliği Frappe `has_permission` + impersonation ile backend'de uygulanır.

---

## 11. Kod haritası

```
stabler/
├── integrations/kassa/
│   ├── __init__.py            # paket işaretleyici
│   ├── webhook.py             # telegram_webhook (fail-closed secret) — 72 satır
│   ├── bot.py                 # ctx + impersonation + execute_action — 680 satır
│   │                          #   handle_update @616, set_user @645/@675,
│   │                          #   execute_action @447, build_ctx @318
│   ├── _flow.py               # Frappe'siz state machine — 1252 satır
│   │                          #   STEP_* @46-77, parse_amount @302,
│   │                          #   parse_quick_transfer @545, handle() @1234
│   └── miniapp.py             # kassa_summary + verify_init_data — 338 satır
├── www/
│   ├── kassa.py               # /kassa guest kabuk (get_context @15) — 17 satır
│   └── kassa.html             # Mini App HTML
├── api/
│   └── kassa_admin.py         # kassir CRUD (System Manager) — 143 satır
├── stabler/doctype/
│   ├── stabler_kassir/            # ana doctype (autoname: telegram_user_id)
│   └── stabler_kassir_account/    # child (account Link)
└── public/js/
    ├── pages/admin/KassaBot.vue   # admin ekranı — 415 satır
    ├── api/kassaAdmin.js          # API sarmalayıcı
    ├── router.js:148,475          # rota + import
    └── pages/admin/AdminHome.vue:22  # nav girişi

tests/
├── test_kassa_flow.py         # _flow.py saf birim testleri
└── test_kassa_miniapp.py      # verify_init_data / kassa_summary testleri
```

---

## 12. WP-K1 → WP-K9 tarihçesi

| WP | Ne ekledi | Commit |
|----|-----------|--------|
| **K1** | Docs + CoA (kasa hesap ağacı) verisi — *standalone kod yok* | `f3f0e48` |
| **K2** | Bot iskeleti / webhook + temel akış | `6772cfc` |
| **K3** | Kirim / Chiqim / transfer akışları | `9c53215` |
| **K4** | Konvertatsiya + K2K genişletme | `4fb2cd8` |
| **K5** | *(standalone commit yok — K3/K4'e katlandı)* | — |
| **K6** | Akıllı girdi ayrıştırma (kelime-sayı, sonek, ham echo, bakiye echo) | `e5c4b27` |
| **K7** | Telegram Mini App (`/kassa`, initData HMAC, `kassa_summary`) | `b52c06d` |
| **K8** | Tek-satır hızlı transfer, memo presetleri, izoh zorunluluğu | `dd6e197` |
| **K9** | Konvertatsiya yön-çiftleri + CBU kur asistanı + qoldiq sarlavhalari | `0ec5b22` |
| — | Admin ekranı (KassaBot.vue + router + nav + i18n) | `b668992` |
| — | Companies'ten `tender`/`imports` modül toggle persist | `9d001b0` |
| — | Hesap defterinde kaynak-belge remarks overlay | `4d12434` / `df7f6c1` |

> **Boşluk notu:** WP-K5'in ayrı bir commit'i yoktur (K3/K4 içine katlanmıştır);
> WP-K1 yalnızca dokümantasyon + CoA verisidir, çalıştırılabilir kod içermez.

---

## 13. İlgili runbook'lar

- **Kurulum / verify:** `docs/plans/2026-07-17-kassa-bot-runbook.md` — bot token/secret
  ayarı, webhook kaydı, kassir oluşturma, smoke test.
- **PROD deploy:** `docs/plans/2026-07-17-kassa-tender-PROD-deploy-runbook.md` — mikas
  hedefli deploy adımları.
- **İş akışı görseli:** `docs/mikas-tender-kassa-workflow.html`.

> Deploy sırasında proje kuralı: `bench restart` **tüm 7 tenant'ı** kısaca etkiler;
> düşük trafikte planlayın. `migrate` her site için ayrıdır — doctype/patch değişince
> mikas dahil hedef site'ları ayrıca migrate edin.
