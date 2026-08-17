# Runbook — `stabler` uygulamasını `msa.erpstable.com` canlı sitesine kurma

**Amaç:** Ortak bench üzerindeki canlı satış sitesi `msa.erpstable.com`'a `stabler` Frappe app'ini
in-place (restore YOK) kurmak. Migration planı §K1 kararı: msa zaten canlı, stabler o site'a kurulur.

**Operatör:** Zafar — tüm adımlar SSH üzerinden elle çalıştırılır.
**Hedef bench:** `/home/frappe/frappe-bench` · **SSH alias:** `ice-production` · **~22 kiracı**
**Bugün stabler'lı tek site:** `anjan.erpstable.com`. Bu runbook **msa.erpstable.com**'u ikinci site yapar.

> **Root vs frappe:** `ssh ice-production` root olarak açılır; Frappe root altında `bench` çalıştırmayı
> reddeder. Bu yüzden HER bench komutu `sudo -u frappe bench …` biçiminde. `deploy_full.sh` deseni budur.

> **Kod zaten sunucuda:** anjan stabler çalıştırdığı için `apps/stabler` prod'da MEVCUT. Bu runbook
> **kod deploy etmez** (rsync yok) — sadece msa site'ına `install-app` yapar. Kodun kendisi yeni sürüm
> gerektiriyorsa önce `deploy_full.sh` ile deploy et, sonra bu runbook'a dön.

---

## ⚠️ Kuruluma başlamadan bilinmesi gerekenler (özet risk kartı)

| Risk | Etki | Önlem (bu runbook'ta) |
|---|---|---|
| **desk_gate** app-global `before_request` hook | Kurulum + restart'tan sonra msa'daki **System Manager olmayan HER kullanıcı `/app` ve `/desk`'ten 403 alır** | §4.2 — Desk kullanıcı envanteri + geçici rol / SPA yönlendirme kararı |
| **scheduler_events** msa'da aktifleşir | `uzex_poll` + `one_c` saatlik dış API'ye vurmaya başlar; nightly GL/audit tarama loglar | §5.4 — belirli Scheduled Job Type'ları `stopped=1` yap |
| **Custom field çakışması** | Django'nun `custom_docs_*` vb. alanları ezilebilir | §1.5 — **çakışma YOK doğrulandı** (aşağıya bak), yine de DRY grep |
| **`bench restart`** tüm bench'i restart eder | **22 kiracının hepsinde kısa kesinti (blip)** | §3.5 — düşük trafik penceresi |
| **39 patch** install'da çalışır | v01–v38 model-sync ÖNCESİ, v39 sonrası | §3.3 — idempotent, ama migrate log'u izle |

**Custom-field çakışma bulgusu (§1.5'te tekrar test edilecek):** Django app'in `custom_fields_registry.py`
ile yarattığı **16 alan adının hiçbiri** stabler'ın patch'lerinde, `hooks.py custom_fields` fixture'ında
veya doctype JSON'larında geçmiyor. Tüm ağaçta grep = 0 isabet. Stabler'ın boyut patch'leri
(`v25_purchase_dimension_fields`) `custom_length/width/height/pieces` ekler — Django'nun
`custom_boxes/box_weight_kg/docs_rate/docs_amount` alanlarından farklı adlar. **Bu kurulum Django
alanlarını EZMEZ.** (Migration planı K3'teki `custom_docs_*` yeniden-kullanımı GELECEK migration işi,
bu install değil.)

---

## 1. Preflight (hepsi salt-okunur — hiçbir şeyi değiştirmez)

### 1.1 msa aynı bench'te mi ve stabler HENÜZ kurulu DEĞİL mi?

```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com list-apps"
```

**Beklenen:** `frappe`, `erpnext` (ve varsa payments/hrms) listelenir; **`stabler` GÖRÜNMEZ**.
Eğer `stabler` zaten listedeyse → **DUR**, kurulum yapılmış; runbook'un geri kalanı geçersiz.

Sitenin bench'te fiziksel var olduğunu da doğrula:

```bash
ssh ice-production "ls -d /home/frappe/frappe-bench/sites/msa.erpstable.com"
```

### 1.2 Sürüm uyumu — msa, anjan ile aynı frappe/erpnext'te mi?

```bash
# App kodu sürümleri (bench geneli — tüm siteler aynı kodu paylaşır)
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench version"

# Site bazında yüklü sürümü kıyasla (msa vs zaten-çalışan anjan)
ssh ice-production "cd /home/frappe/frappe-bench && \
  echo '--- msa ---'   && sudo -u frappe bench --site msa.erpstable.com   list-apps && \
  echo '--- anjan ---' && sudo -u frappe bench --site anjan.erpstable.com list-apps"
```

**Kayıt al (runbook'un altına yapıştır):** frappe sürümü __________, erpnext sürümü __________.
Ortak bench olduğu için kod sürümleri zaten aynıdır; asıl kontrol msa'nın **migrate'inin güncel**
olması (aşağıda). Migration planı K1(a): "msa v16 mı? değilse önce site upgrade" — bench zaten anjan'ı
çalıştırdığından kod v16; risk sadece msa'nın bekleyen kendi migrate'i.

### 1.3 stabler kodu apps/ altında mevcut mu?

```bash
ssh ice-production "ls -la /home/frappe/frappe-bench/apps/stabler && \
  cat /home/frappe/frappe-bench/apps/stabler/stabler/patches.txt | grep -c '^stabler.patches'"
```

**Beklenen:** dizin var; patch sayısı **39** (v01–v39; v39 `[post_model_sync]` altında).

### 1.4 Disk alanı (backup + migrate için yeterli mi?)

```bash
ssh ice-production "df -h /home/frappe/frappe-bench && \
  du -sh /home/frappe/frappe-bench/sites/msa.erpstable.com 2>/dev/null"
```

**Kural:** boş alan, site dizininin en az **2 katı** olmalı (DB dump + files tar backup için). %85'in
üstünde doluluk varsa önce yer aç.

### 1.5 DRY çakışma taraması — Django custom field'ları vs stabler patch'leri

Django app `msa.erpstable.com`'da şu **16 custom field**'i yarattı (`custom_fields_registry.py`).
Bunlar **PRE-EXISTING, kurulumdan SAĞ ÇIKMALI**:

| Doctype | Fieldname'ler |
|---|---|
| Purchase Order | `custom_pi_number`, `custom_msaerp_pi_id`, `custom_docs_total`, `custom_cash_difference`, `custom_advance_percentage` |
| Purchase Order Item | `custom_docs_rate`, `custom_docs_amount`, `custom_boxes`, `custom_box_weight_kg` |
| Purchase Invoice | `custom_ci_number`, `custom_msaerp_ci_id`, `custom_docs_total`, `custom_cash_difference`, `custom_allocated_advance_bank`, `custom_allocated_advance_cash` |
| Purchase Invoice Item | `custom_docs_rate`, `custom_docs_amount`, `custom_boxes`, `custom_box_weight_kg` |
| Payment Entry | `custom_payment_stream`, `custom_msaerp_advance_id`, `custom_pi_number` |
| Landed Cost Voucher | `custom_ci_number` |
| Customer | `custom_parent_customer` |

Kurulum öncesi kendin doğrula — stabler kodunda bu adların HİÇBİRİ geçmemeli:

```bash
ssh ice-production "cd /home/frappe/frappe-bench/apps/stabler && \
for f in custom_pi_number custom_msaerp_pi_id custom_docs_total custom_cash_difference \
         custom_advance_percentage custom_docs_rate custom_docs_amount custom_boxes \
         custom_box_weight_kg custom_ci_number custom_msaerp_ci_id custom_allocated_advance_bank \
         custom_allocated_advance_cash custom_payment_stream custom_msaerp_advance_id \
         custom_parent_customer; do \
  hits=\$(grep -rl \"\$f\" . 2>/dev/null | grep -v __pycache__); \
  [ -n \"\$hits\" ] && { echo \"COLLISION: \$f\"; echo \"\$hits\"; }; \
done; echo 'scan done'"
```

**Beklenen çıktı:** sadece `scan done` (hiçbir `COLLISION:` satırı yok).
**Bu makinede (2026-07-09) yapılan tarama:** 0 çakışma. Django'nun 16 alanı stabler kodunun hiçbir
yerinde (patch / fixture / doctype JSON) geçmiyor. Stabler'ın çakışabilecek en yakın patch'i
`v25_purchase_dimension_fields` → `custom_length/width/height/pieces` (Purchase Order/Invoice Item)
ekliyor; farklı adlar, çakışma yok.

**Emniyet ağı — kurulum ÖNCESİ Django alanlarının canlı sayımını al** (kurulum sonrası ile kıyaslamak için):

```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com execute \
  frappe.client.get_count --args '[\"Custom Field\", {\"fieldname\": [\"like\", \"custom_%\"]}]'"
```

**Kaydet:** kurulum öncesi Custom Field sayısı = __________ (§5'te tekrar sayıp Django'nunkilerin
kaybolmadığını doğrulayacaksın).

---

## 2. Backup (geri dönüş noktası — atlanmaz)

### 2.1 Site DB + dosya yedeği

```bash
ssh ice-production "cd /home/frappe/frappe-bench && \
  sudo -u frappe bench --site msa.erpstable.com backup --with-files"
```

Yedeğin yerini yazdır ve doğrula:

```bash
ssh ice-production "ls -lht /home/frappe/frappe-bench/sites/msa.erpstable.com/private/backups/ | head -5"
```

**Beklenen:** yeni `*-database.sql.gz`, `*-files.tar`, `*-private-files.tar` (dakikalar içinde, taze timestamp).

### 2.2 Yedeği kutu-dışına kopyala (sunucu ölürse diye)

```bash
mkdir -p ~/msa-preinstall-backup && \
scp "ice-production:/home/frappe/frappe-bench/sites/msa.erpstable.com/private/backups/$(ssh ice-production \
  'ls -t /home/frappe/frappe-bench/sites/msa.erpstable.com/private/backups/*-database.sql.gz | head -1' \
  | xargs basename)" ~/msa-preinstall-backup/
# files tar'ları da istersen aynı desenle çek.
ls -lh ~/msa-preinstall-backup/
```

### 2.3 apps/stabler dizin tar'ı (deploy_stabler.sh konvansiyonu — kod rollback noktası)

Kod bu install ile değişmiyor ama konvansiyon gereği anlık tar al (aynı komut deploy script'lerinde):

```bash
ssh ice-production "tar czf /root/stabler-app-\$(date +%F-%H%M).tgz \
  -C /home/frappe/frappe-bench/apps stabler && ls -lh /root/stabler-app-*.tgz | tail -1"
```

---

## 3. Kurulum penceresi

> **Canlı satış sitesi.** Pencereyi **düşük trafikte** (akşam geç / hafta sonu) planla. Toplam
> beklenen kesinti: install + migrate sırasında msa yanıt verir ama **`bench restart`** anında
> **~22 kiracının hepsinde 5–30 sn'lik blip** olur. Bu tek gerçek kesinti anıdır.

### 3.1 Bakım modu değerlendirmesi (opsiyonel)

install-app + migrate şema değişikliği yapar; teorik olarak eşzamanlı satış yazımı ile yarışabilir.
Riski sıfırlamak istersen kısa bakım modu:

```bash
# YALNIZ msa'yı bakıma al (diğer 21 kiracı etkilenmez)
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com set-maintenance-mode on"
```

Bakım modunu install+migrate SONRASI, smoke testlerden ÖNCE kapatacaksın (§3.6). Düşük trafik
penceresinde bakım modu **opsiyoneldir** — install-app'in çoğu işi custom field/DDL ekleme, mevcut
satış verisini kilitlemez. Karar operatörün.

### 3.2 install-app

```bash
ssh ice-production "cd /home/frappe/frappe-bench && \
  sudo -u frappe bench --site msa.erpstable.com install-app stabler"
```

Bu komut: `stabler`'ı msa'nın `installed_apps`'ine ekler, doctype'ları senkronlar, fixtures'ı yükler,
ve app'in patch'lerini çalıştırır. Hata olursa **DUR** ve §6 rollback'e geç.

### 3.3 migrate (patch'ler + şema)

`install-app` genelde patch'leri çalıştırır; garantiye almak ve v39 (`[post_model_sync]`) dahil her
şeyin oturması için migrate'i açıkça koştur:

```bash
ssh ice-production "cd /home/frappe/frappe-bench && \
  sudo -u frappe bench --site msa.erpstable.com migrate"
```

**İzle:** 39 patch (v01–v39). CLAUDE.md kuralı: patches.txt'te v39 hariç hepsi model-sync ÖNCESİ
çalışır; hepsi idempotent olmalı. Migrate "unknown column" ile abort ederse → o patch guard'sız yeni
kolon okuyor demektir; log'u kaydet, §6'ya geç. Temiz install'da bu beklenmez.

### 3.4 build (muhtemelen gereksiz)

anjan zaten stabler kullandığından SPA bundle'ı (`dist/`) prod'da hazır. Yine de emin olmak istersen:

```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench build --app stabler"
```

Kod değişmediyse bu adımı **atlayabilirsin** — build tüm bench için ortak asset üretir, msa'ya özel değil.

### 3.5 restart (blast radius: TÜM kiracılar)

```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench restart"
```

**UYARI:** `bench restart` tüm bench'i (gunicorn + workers + scheduler) yeniden başlatır →
**22 kiracının hepsinde kısa blip.** Düşük trafikte çalıştır. install-app yeni bir `before_request`
hook'unu (desk_gate) ve scheduler_events'i msa için ancak restart'tan sonra tam devreye alır — bu yüzden
restart §4/§5 etkilerinin başladığı andır.

### 3.6 Bakım modunu kapat (açtıysan)

```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com set-maintenance-mode off"
```

---

## 4. Kurulum sonrası yapılandırma

### 4.1 MSA şirketi için Stabler Company Modules — tüm modüller KAPALI başlat

Migration planı K1(d): "enable_imports dışındaki stabler modülleri msa'da kapalı başlar." Ama
`imports` modülü bu app'te henüz YOK (gelecek migration Faz 1–5). Dolayısıyla go-live'da msa için
**tüm modül toggle'ları OFF** olmalı — böylece msa kullanıcıları henüz hiçbir stabler modülü görmez ve
mevcut satış operasyonu SPA'dan etkilenmez.

> **Neden default'a güvenmiyoruz:** Company Modules doctype default'ları çoğu modül için `"1"` (açık).
> Yeni bir Company Modules satırı Company seçilince bu default'larla gelir. msa için satırı **elle
> oluşturup hepsini OFF** yapmalısın.

Şu `enable_*` alanlarının **hepsini 0** yap (doctype JSON'daki tam liste):

`enable_money`, `enable_sales`, `enable_purchasing`, `enable_inventory`, `enable_manufacturing`,
`enable_hr`, `enable_stock_reservation`, `enable_compliance`, `enable_field_sales`, `enable_marketing`,
`enable_crm`, `enable_service`, `enable_bpm`, `enable_tender`, `enable_remittance`, `enable_installment`.

> `enable_service` ve `enable_tender` default'u zaten `0`; diğer 14'ü default `1` → hepsini elle 0'la.

Stabler Company Modules **child table** olduğundan (istable) doğrudan değil, parent Stabler Settings
üzerinden yönetilir. En güvenli yol bir script ile MSA satırını ekleyip tüm toggle'ları kapatmak:

```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com console" <<'PY'
import frappe
COMPANY = "MSA"   # ← msa'daki gerçek Company adını doğrula: bench --site msa.erpstable.com execute \
                  #    frappe.client.get_list --args '["Company"]'
s = frappe.get_single("Stabler Settings")
row = next((r for r in s.company_modules if r.company == COMPANY), None)
if row is None:
    row = s.append("company_modules", {"company": COMPANY})
for f in [
    "enable_money","enable_sales","enable_purchasing","enable_inventory","enable_manufacturing",
    "enable_hr","enable_stock_reservation","enable_compliance","enable_field_sales","enable_marketing",
    "enable_crm","enable_service","enable_bpm","enable_tender","enable_remittance","enable_installment",
]:
    row.set(f, 0)
s.save(ignore_permissions=True)
frappe.db.commit()
print("MSA company modules row -> all OFF")
PY
```

> Önce **gerçek Company adını doğrula** — yorumdaki komutla. "MSA" varsayımını kod'a gömme.

### 4.2 desk_gate — msa Desk kullanıcıları `/app` erişimini KAYBEDER (KRİTİK)

**Ne oluyor:** `stabler/middleware/desk_gate.py` app-global bir `before_request` hook'u
(`hooks.py:13 before_request = ["stabler.middleware.desk_gate.gate_desk"]`). Frappe `before_request`
hook'ları **site'ın installed_apps'ine göre** çözülür → stabler msa'ya kurulunca bu hook msa'nın HER
isteğinde çalışır. Mantık: yol `/app` veya `/desk` ile başlıyorsa ve kullanıcı **System Manager /
Administrator DEĞİLSE** → `frappe.PermissionError` (403 "Not Permitted").

**Sonuç (cevap: EVET):** restart'tan sonra, msa'da bugün ERPNext Desk (`/app/...`) kullanan
**System Manager olmayan her kullanıcı** (satışçı, muhasebeci, depo) Desk'ten **anında 403 alır.**
Modüller de OFF olduğundan (§4.1) SPA'da da neredeyse hiçbir şey göremezler → efektif olarak kilitlenirler.

**Django entegrasyonu ETKİLENMEZ:** desk_gate yalnız `/app` ve `/desk` öneklerini kapar. Django app
ERPNext'e `/api/method/...` ve `/api/resource/...` üzerinden token ile konuşur → bu yollar gate'li
DEĞİL. Django→ERPNext yazımı çalışmaya devam eder (§5.2'de doğrulanır).

**Kurulum ÖNCESİ envanter al** — kaç ve kim etkilenecek:

```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com console" <<'PY'
import frappe
users = frappe.get_all("User", filters={"enabled":1, "user_type":"System User"}, pluck="name")
locked = [u for u in users if u not in ("Administrator",) and "System Manager" not in frappe.get_roles(u)]
print(f"Toplam aktif system user: {len(users)}")
print(f"desk_gate ile KİLİTLENECEK (System Manager olmayan): {len(locked)}")
for u in locked: print("  -", u)
PY
```

**Mitigasyon seçenekleri (kurulum kararından ÖNCE net olmalı):**

1. **Kabul et + SPA'ya taşı (temiz hedef).** msa kullanıcıları zaten SPA'ya geçecekse: onları
   uyar, /stabler'a yönlendir. Ama §4.1 modülleri OFF → önce en az bir modülü (ör. satış) açman
   gerekir yoksa SPA boş. **Go-live'da modüller OFF isteniyorsa bu seçenek kullanıcıları boş SPA'da
   bırakır** — go-live cutover'a kadar Desk lazımsa seçenek 2/3.
2. **Etkilenen kilit kullanıcılara geçici System Manager ver** (Desk erişimi korunur). Kaba ama hızlı;
   cutover'da geri al. `System Manager` çok geniş yetki → yalnız güvenilen az sayıda kullanıcı için.
3. **desk_gate'i site bazında geçici devre dışı bırak (kod değişikliği).** `gate_desk`'e bir
   `site_config` bayrağı ekle (ör. `if frappe.conf.get("disable_desk_gate"): return`) ve msa'nın
   `site_config.json`'ına `"disable_desk_gate": 1` koy. **DİKKAT:** `before_request` app-global; bu
   kod değişikliği prod'a deploy edilir ve anjan'ı da etkiler — ama `frappe.conf` site-bazlı olduğu
   için davranış yalnız bayrağı olan site'ta değişir (anjan'da bayrak yok → gate aynen çalışır). Bu
   kod değişikliği ayrı bir PR + `deploy_full.sh` gerektirir; runbook kapsamı dışı ama en temiz
   "Desk'i açık tut" çözümü.

**Tavsiye:** go-live'da modüller OFF olacaksa ve msa kullanıcıları hâlâ Desk'te çalışıyorsa →
**seçenek 3** (site-config bayrağı) veya cutover'ı modül açılışıyla eşle. Kararı burada yaz:
seçilen mitigasyon = __________.

### 4.3 Stabler Settings default'ları

msa için Stabler Settings'in tehlikeli/gürültülü default'larını gözden geçir (tam alan listesi
`stabler_settings.json`'da). Kurulumda özellikle şunlara bak:

- `onec_mode` — **default boş → "file"** (kod: `stabler/integrations/one_c/hooks.py`). "file" iken
  saatlik `hourly_sync` sadece yerel dosya-drop dizinini tarar (yoksa no-op). **`"rest"` YAPMA** —
  aksi halde msa yapılandırılmamış 1C REST'e vurmaya başlar. Boş bırak.
- `enable_scheduled_backup` — msa'da zaten kendi backup rejimi varsa çift backup yaratmamak için
  bilinçli seç.
- `cost_visible_roles`, `enforce_sod`, `enable_period_close`, approval threshold'ları — msa'da
  stabler modülleri OFF olduğu sürece bunlar tetiklenmez; go-live migration'ında ayarlanır. Şimdilik
  default bırak, **açma.**

---

## 5. Smoke testleri

### 5.1 /stabler SPA msa domaininde yükleniyor mu?

Tarayıcıda (hard refresh, Cmd+Shift+R): `https://msa.erpstable.com/stabler`
- Login sonrası SPA kabuğu açılmalı. Modüller OFF olduğundan (§4.1) menü büyük ölçüde boş —
  **bu beklenen.** Boş beyaz ekran / 500 değil, stabler kabuğu görünmeli.
- API tabanı: `https://msa.erpstable.com/api/method/stabler.api.organization.get_enabled_modules`
  (veya SPA network sekmesinde ilk çağrı) 200 dönmeli, MSA için boş/kapalı modül listesi.

### 5.2 Mevcut Django→ERPNext entegrasyonu hâlâ çalışıyor mu?

Django app cutover'a kadar msa'ya yazmaya devam eder → kurulum bunu bozmamalı. desk_gate `/api/*`'ı
kapamaz; doğrula. Django'nun kullandığı **mevcut API token** ile bir salt-okunur endpoint dene:

```bash
# Token'ı Django ortamından al (settings / .env: ERPNEXT_API_KEY:ERPNEXT_API_SECRET).
curl -s -H "Authorization: token <API_KEY>:<API_SECRET>" \
  "https://msa.erpstable.com/api/resource/Purchase%20Order?limit_page_length=1" | head -c 400; echo
```

**Beklenen:** `{"data":[...]}` (200). 403 gelirse → token/permission sorunu (desk_gate DEĞİL, çünkü
`/api/resource` gate'li değil); Django token'ının rollerini kontrol et.

Django alanlarının kurulumdan sağ çıktığını da doğrula (§1.5 sayımıyla kıyasla):

```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com execute \
  frappe.client.get_count --args '[\"Custom Field\", {\"fieldname\": [\"like\", \"custom_%\"]}]'"
# Bu sayı §1.5 öncesi sayı + stabler'ın eklediği alanlar kadar ARTMALI, Django'nunkiler DÜŞMEMELİ.
```

Nokta kontrol — bir Django alanı hâlâ duruyor mu:

```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com execute \
  frappe.client.get_count --args '[\"Custom Field\", {\"dt\":\"Purchase Order\",\"fieldname\":\"custom_docs_total\"}]'"
# Beklenen: 1
```

### 5.3 Satış operasyonu etkilenmedi mi?

- SPA satış modülü OFF olduğundan satış AKIŞI ERPNext Desk / Django üzerinden gidiyor. Desk erişimi
  olan bir System Manager ile: `/app/sales-invoice` listesi yükleniyor mu, son bir SI açılıyor mu?
- Alternatif (Desk kilitliyse) API ile:

```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com execute \
  frappe.client.get_list --args '[\"Sales Invoice\", {\"docstatus\":1}, [\"name\",\"grand_total\",\"posting_date\"], \"posting_date desc\", 3]'"
```

**Beklenen:** son 3 submitted SI döner, tutarlar makul. Kurulum SI verisine dokunmadı.

### 5.4 Scheduler etkisi — msa'da hangi job'lar AKTİFLEŞİR ve hangileri güvensiz

install + restart sonrası Frappe, stabler'ın `scheduler_events`'ini msa için **Scheduled Job Type**
kayıtlarına dönüştürür. msa'da stabler operasyonel verisi OLMADIĞINDAN bazıları gereksiz dış API'ye
vurur. Tam liste (`stabler/hooks.py`):

| Sıklık | Job | msa'da güvenli mi? |
|---|---|---|
| hourly | `stabler.tasks.uzex_poll.fetch_and_store` | **RİSKLİ** — her saat UZEX etender API'sine ağ çağrısı. Yeni Deal yalnız `frappe.conf.uzex_keywords` eşleşirse yaratılır (msa'da yoksa Deal yaratmaz), ama **API'ye yine de vurur** ve kimlik bilgisi yoksa hata loglar. **Durdur.** |
| hourly | `stabler.integrations.one_c.hooks.hourly_sync` | Orta — `onec_mode` "file" (default) iken sadece yerel dizin tarar (no-op). REST'e vurmaz. Yine de gereksizse **durdur.** |
| hourly | `stabler.integrations.didox.hooks.sync_pending_statuses` | Güvenli — yalnız `didox_doc_id`'li "Sent" ЭСФ satırlarını yoklar; taze msa'da yok → no-op. |
| daily | `stabler.tasks.cbu_rate_refresh.fetch_and_store` | Görece zararsız — CBU'dan USD/EUR/RUB/**CNY** alıp msa'ya Currency Exchange satırı yazar (idempotent). Kaynak liste `_TRACKED`; USDT CBU'da yayınlanmadığı için burada YOK, dönem kapanışında elle girilir (`docs/runbooks/period-close.md`). Genelde İSTENİR. İstemiyorsan durdur. |
| daily | `stabler.tasks.roi_refresh.daily` | Güvenli — stabler verisi yoksa no-op/boş. |
| daily | `stabler.service.schedule_engine.generate_rolling_schedule_rows` | Güvenli — Service modülü OFF; veri yok → no-op. |
| daily | `stabler.tasks.gl_integrity.nightly_scan` | Orta — msa'nın GERÇEK GL'ini tarar (salt-okunur, tutarsızlık loglar). Zararsız ama log gürültüsü yaratabilir. |
| daily | `stabler.api.backup.run_scheduled_backup` | `enable_scheduled_backup` OFF ise no-op (§4.3). |
| daily | `stabler.integrations.timepay.sync/processor` | Güvenli — timepay yapılandırılmadıysa no-op. |
| daily | `stabler.api.audit.seal_audit_log` | Güvenli — audit zincirini mühürler; zararsız. |
| weekly | `stabler.api.backup.apply_retention_policy` | backup OFF ise no-op. |

**En az `uzex_poll`'u (ve tercihen `one_c hourly_sync`'i) msa için durdur** — stabler operasyonel
verisi gelene (go-live migration) kadar. Frappe'de tek tek job durdurma = ilgili **Scheduled Job Type**
satırında `stopped=1`:

```bash
ssh ice-production "cd /home/frappe/frappe-bench && sudo -u frappe bench --site msa.erpstable.com console" <<'PY'
import frappe
STOP = [
    "stabler.tasks.uzex_poll.fetch_and_store",
    "stabler.integrations.one_c.hooks.hourly_sync",
    # İstersen ekle: "stabler.tasks.cbu_rate_refresh.fetch_and_store",
    # "stabler.tasks.gl_integrity.nightly_scan",
]
for method in STOP:
    name = frappe.db.get_value("Scheduled Job Type", {"method": method})
    if name:
        frappe.db.set_value("Scheduled Job Type", name, "stopped", 1)
        print("stopped:", method)
    else:
        print("NOT FOUND (henüz oluşmamış olabilir):", method)
frappe.db.commit()
PY
```

> **Not:** `bench --site msa.erpstable.com disable-scheduler` KULLANMA — o msa'nın TÜM scheduler'ını
> (ERPNext'in kendi job'ları dahil, canlı satış sitesinde) kapatır. Sadece stabler job'larını
> `stopped=1` ile hedefle. Job'lar restart + ilk scheduler tick sonrası oluşur; "NOT FOUND" görürsen
> birkaç dakika sonra tekrar çalıştır.

Alternatif kalıcı yol: msa'nın `site_config.json`'ına gate bayrağı (`uzex_keywords`'ü boş bırakmak
zaten yeni Deal yaratmayı engeller; kimlik bilgisi yoksa poll'un kendisi de erken çıkar). Ama en net
kontrol yukarıdaki `stopped=1`.

---

## 6. Rollback

### 6.1 Karar kriterleri (ne zaman geri al)

- install-app veya migrate **abort** etti (ör. patch "unknown column") ve ileri düzeltme belirsiz.
- Smoke §5.2: Django→ERPNext entegrasyonu bozuldu (Django yazamıyor) → **derhal rollback** (canlı
  satış yazımı kesilmiş demektir).
- Smoke §5.3: satış verisi bozulmuş / SI'lar açılmıyor → **derhal rollback**.
- §1.5 sonrası Django custom field sayısı DÜŞTÜ (alanlar ezilmiş) → rollback + inceleme.
- desk_gate kilidi kabul edilemez ve §4.2 mitigasyonu hazır değil → uninstall veya bayrak fix.

### 6.2 En hafif geri alma — sadece uninstall-app

Eğer sorun stabler-özgü ve msa'nın ERPNext verisi SAĞLAMSA, DB restore'a gerek yok; app'i kaldır:

```bash
ssh ice-production "cd /home/frappe/frappe-bench && \
  sudo -u frappe bench --site msa.erpstable.com uninstall-app stabler"
```

**⚠️ uninstall-app CAVEAT'leri:**
- **stabler DocType'larının tablolarını DÜŞÜRÜR** (`Stabler Settings`, `Stabler Company Modules`,
  `CRM Deal`, tüm `stabler_*` ve Stabler modülü doctype'ları). Bu tablolardaki veri **kalıcı kaybolur.**
  Taze install'da bu tablolar zaten boş/config → veri kaybı kapsamı = §4.1'de girdiğin MSA modül
  satırı + varsa test kayıtları. **msa'nın ERPNext core verisi (SI/PO/PE/Customer/GL) stabler
  doctype'ı DEĞİL → uninstall onlara dokunmaz.**
- Stabler'ın **core doctype'lara eklediği custom field'lar** (dimension, tender, uzex vb.) uninstall'da
  her zaman temizlenmeyebilir — `bench --site … uninstall-app stabler --dry-run` ile önce ne
  düşeceğini gör:
  ```bash
  ssh ice-production "cd /home/frappe/frappe-bench && \
    sudo -u frappe bench --site msa.erpstable.com uninstall-app stabler --dry-run"
  ```
- **Django'nun custom field'ları farklı app'e ait DEĞİL** (fixture değil, Django API'siyle elle
  yaratıldı, `module`'leri stabler değil) → stabler uninstall onları hedeflemez. §5.2 nokta kontrolüyle
  uninstall SONRASI da `custom_docs_total` vb. hâlâ 1 döndüğünü doğrula.
- uninstall sonrası `sudo -u frappe bench restart` (desk_gate hook'unu msa'dan kaldırmak için — restart'a
  kadar eski worker'lar hook'u tutabilir). Restart tekrar tüm kiracıları bliple.

### 6.3 Tam DB restore (veri bozulduysa)

Django/satış verisi bozulduysa uninstall yetmez — §2 yedeğinden site'ı geri yükle:

```bash
# msa'yı bakıma al, sonra restore
ssh ice-production "cd /home/frappe/frappe-bench && \
  sudo -u frappe bench --site msa.erpstable.com set-maintenance-mode on && \
  sudo -u frappe bench --site msa.erpstable.com restore \
    /home/frappe/frappe-bench/sites/msa.erpstable.com/private/backups/<TIMESTAMP>-database.sql.gz \
    --with-public-files /home/frappe/frappe-bench/sites/msa.erpstable.com/private/backups/<TIMESTAMP>-files.tar \
    --with-private-files /home/frappe/frappe-bench/sites/msa.erpstable.com/private/backups/<TIMESTAMP>-private-files.tar"
```

> `<TIMESTAMP>`'i §2.1 çıktısından doldur. Restore, msa'yı kurulum-öncesi haline tam döndürür (stabler
> installed_apps'ten de düşer). Sonra `set-maintenance-mode off` + `bench restart`.
> **Point-of-no-return:** migration planı §8 — ilk canlı stabler-üretimi Sales Invoice'tan SONRA
> tar-restore yok. Bu install aşamasında henüz oraya gelinmedi, restore güvenli.

### 6.4 Kod tar rollback (yalnız kod bozulduysa — bu install'da beklenmez)

```bash
ssh ice-production "cd /home/frappe/frappe-bench/apps && \
  tar xzf /root/stabler-app-<TS>.tgz && chown -R frappe:frappe stabler && \
  cd /home/frappe/frappe-bench && sudo -u frappe bench build --app stabler && sudo -u frappe bench restart"
```

---

## Kurulum sonrası çıktı kaydı (doldur)

- Preflight tarih/saat: __________
- frappe __________ / erpnext __________ sürüm
- Kurulum-öncesi Custom Field sayısı (§1.5): __________ · sonrası (§5.2): __________
- desk_gate kilitlenecek kullanıcı sayısı (§4.2): __________ · seçilen mitigasyon: __________
- MSA Company adı doğrulandı: __________ · tüm modüller OFF: [ ]
- Durdurulan scheduler job'ları (§5.4): __________
- Smoke §5.1/5.2/5.3 geçti: [ ] / [ ] / [ ]
- Yedek dosyaları (§2): __________
```
