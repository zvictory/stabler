# Stabler çok-tenant yönetişimi — özellik sahipliği ve çelişki riski

**Hazırlayan:** Opus 4.8 (senior/staff mühendis gözüyle) · **Tarih:** 2026-07-18
**Soru:** "Tek paylaşılan Stabler app'i 7 farklı işe sahip tenant'a kurulu. Her projeden bir parça değiştirdiğimizde çelişki oluşuyor. Profesyonel takım ne yapar?"

---

## 0. Yönetici özeti

Kısa cevap: **mimariniz aslında doğru yolda, ama iki disiplin eksik.** Stabler zaten olgun bir modül-gating katmanına sahip (17 modül, her biri `company enable_*` + rol ile gate'li) ve kodda `if company == "mikas"` gibi tenant-adı hardcode'u **yok** — her şey `company` ve modül üzerinden parametrize. Bu, çok-tenant SaaS'ın en zor kısmının zaten çözülmüş olduğu anlamına gelir.

Çelişki hissinin iki gerçek kaynağı var:

1. **Modüller default AÇIK geliyor.** 17 modülden 14'ü yeni bir company'de `default=1`. Yani DTS (kayış satışı) tenant'ı, hiç kullanmayacağı Manufacturing / HR / Trade Marketing / Installment modüllerini açık alıyor. Gating var ama default'lar onu baltalıyor → "herkeste her şey görünüyor" hissi.
2. **Paylaşılan çekirdek + paylaşılan sürüm.** Tek bench, tek `bench restart` → 7 tenant'ı aynı anda etkiler; `money.py`/`organization.py`/GL-JE-FX gibi çekirdek tüm tenant'larda çalışır; bir doctype (ör. Import PI Group) migrate sonrası herkesin DB'sinde oluşur. Bir tenant için yapılan çekirdek değişikliği hepsini etkileyebilir.

**Ana tavsiye:** Tek-app-çok-tenant modelinde **kalın** (fork etme), ama üç şeyi kur: (a) modül default'larını **opt-in**'e çevir + her tenant'ın modüllerini denetle, (b) **özellik-sahipliği matrisi**ni CLAUDE.md'ye canlı doküman olarak koy, (c) **çekirdeği** (kernel) en yüksek test barıyla koru ve tenant-özel davranışı koda değil **company-setting**'e bağla. Fork'u yalnızca somut bir tetikleyici gelince düşün.

---

## 1. Gerçeklik: bugünkü mimari

| Boyut | Durum |
|---|---|
| Uygulama | **Tek** paylaşılan Frappe app (`apps/stabler`) + Vue SPA |
| Tenant sayısı | 7 stabler sitesi: `anjan` (ana prod), `dts`, `horeca`, `laminor`, `mikas`, `msa`, `smartbox` (paylaşılan bench'te ~22 tenant içinde) |
| Kod | Paylaşılan — bir `apps/stabler/` değişikliği + `bench restart` **7 sitenin tümünü** aynı anda etkiler |
| Veritabanı | Her tenant **ayrı DB** (per-site). `migrate` per-site çalışır; şema (doctype) paylaşılan → migrate her sitede aynı kolonları açar |
| Sürüm | rsync (git değil) + on-server build + restart. Restart = **tüm** tenant'lara kısa kesinti |
| İzolasyon katmanı | `Stabler Company Modules` doctype'ında `enable_*` bayrakları + `organization.py:_MODULE_ROLES` rol haritası. Görünürlük = `company-enabled AND user-role-allowed` |

Yani: **kod paylaşılır, veri izole, sürüm topludur.** Çelişki riski "kod + sürüm" ekseninde; veri ekseninde değil.

---

## 2. Tenant × iş × modül matrisi

Aşağıdaki, mevcut bilgiye göre "kim hangi modülü sürüyor" haritasıdır. `laminor` ve `smartbox` iş tanımları teyide muhtaç (sahibiyle doğrulanmalı).

| Tenant | İş modeli | Sürdüğü ana modüller | Kapalı olması gerekenler (örnek) |
|---|---|---|---|
| **anjan** | Dondurma üretimi (ana prod) | manufacturing, inventory, sales, money, (hr ayrı app) | imports, tender |
| **msa** | Et ithalat/dağıtım | **imports** (PI, PI Groups, Vendor Category, CI, konteyner), money, purchasing | tender, manufacturing |
| **mikas** | Tender / kassa | **tender**, money (kassa botu), purchasing, crm | imports, manufacturing |
| **dts** | Endüstriyel kayış satışı | sales, inventory, money | manufacturing, hr, imports, tender, installment |
| **horeca** | HoReCa servisleri | service, sales, money, field_sales | manufacturing, imports, tender |
| **laminor** | *(teyit gerek)* | *(teyit gerek)* | *(teyit gerek)* |
| **smartbox** | *(teyit gerek)* | *(teyit gerek)* | *(teyit gerek)* |

> Bu matris **canlı doküman** olmalı — CLAUDE.md'ye taşınıyor (bkz. §8). Bir modül üzerinde çalışırken "bu modülün sahibi tenant kim?" sorusu, değişikliğin kapsamını ve test hedefini belirler.

**Özellik → sahip modül eşlemesi (örnekler):** PI / PI Groups / Vendor Category → `imports` (sahip: **msa**). Tender board / bid pricing / landed → `tender` (sahip: **mikas**). Kassa botu → `money`+`tender` (sahip: **mikas**). Bunların hiçbiri, modül kapalı olan tenant'ta görünmemeli.

---

## 3. Çelişki nereden doğuyor (risk analizi)

Somut mekanizmalar — hisler değil:

1. **Default-on modüller (en büyük ve en kolay düzelen).** 14/17 modül `default=1`. Yeni company hepsini açık alır; DTS'de Manufacturing menüsü, MSA'da Installment görünür. Gating çalışıyor ama yanlış tarafa ayarlı. **Fix: opt-in.**
2. **Paylaşılan çekirdeğin blast-radius'u.** `money.py` (GL/JE/FX anchoring), `organization.py` (gating), `_common.py` her tenant'ta çalışır. MSA için bir para-yolu değişikliği anjan'ın dondurma muhasebesini de etkiler. Çekirdek = tek arıza noktası.
3. **Paylaşılan şema.** Import PI Group doctype'ı migrate sonrası **7 DB'de de** oluşur (msa dışındakilerde boş + gated). Kabul edilebilir, ama paylaşılan bir doctype'a **zorunlu (reqd)** alan eklemek, o modülü kullanmayan tenant'a yük bindirir. Zorunlu alanlar sadece o modülün doctype'larında olmalı.
4. **Toplu sürüm.** Tek `bench restart` 7 tenant'ı birlikte etkiler. MSA için acil bir düzeltme, anjan'ın mesai saatinde kesinti demektir. Sürümün kapsamı asla "tek tenant" değildir.
5. **Tenant-özel dallanma cazibesi.** İleride `if company == "mikas": ...` yazma dürtüsü — bu, çelişkiyi koda gömer. Şu an bundan uzaksınız (kodda yok); **kural olarak yasaklanmalı.**
6. **Test boşluğu.** "Modül X, sahip-olmayan tenant'ta KAPALI ve sızmıyor" diye bir testiniz yok. Bir gating regresyonu sessizce bir tenant'a başka tenant'ın özelliğini açabilir.
7. **Config kodda, veride değil.** Tenant-varyant davranış (para hassasiyeti, dil, kassa sayısı) koda sabit yazılırsa çelişir; `Stabler Company Modules`/company-setting'den okunursa izole kalır. (İyi haber: para hassasiyetini zaten metadata olarak okuyorsunuz — bu doğru desen.)

---

## 4. Zaten doğru olan (temeliniz sağlam)

Panik yok — profesyonel bir takım şunları "already good" diye işaretler:

- **Olgun modül sistemi:** 17 modül, çift gate (company `enable_*` + rol), route `meta.module` guard, admin bypass. Çoğu şirketin çok-tenant'ta aylarca uğraştığı katman sizde çalışıyor.
- **Tenant-adı hardcode YOK.** Tarama `if company == "<tenant>"` bulmadı; her şey `company` parametresi + modül üzerinden. Bu, fork'suz ölçeklenmenin ön koşulu.
- **Company-scoping her endpoint'te.** `_assert_company_scope` / `_assert_<module>_access` tenant izolasyonunu backend'de zorluyor (UX değil, güvenlik katmanı Frappe `has_permission`).
- **Config doctype'ı var.** `Stabler Company Modules` = tenant-varyant davranış için doğru yer; kernel'i kirletmeden konfigüre edilebilir.
- **Additive/idempotent migration disiplini** (has_column guard, pre-model-sync kuralı) zaten CLAUDE.md'de.

Yani soru "mimariyi kurtaralım mı" değil; "iki disiplini ekleyelim mi"dir.

---

## 5. Profesyonel oyun kitabı (öncelikli)

### P0 — Bu hafta

**P0.1 — Modül default'larını opt-in yap + tenant denetimi.**
`Stabler Company Modules`'te çekirdek dışı modüllerin `default`'unu `0`'a çek (money gibi gerçek çekirdek `1` kalabilir). Sonra **her mevcut tenant için** açık modülleri denetle ve §2 matrisine göre gereksizleri kapat. Dikkat: default değişikliği **geçmişe etki etmez** — mevcut tenant'lar zaten açık; bir kerelik denetim/temizlik gerekir (per-site `enable_*` düzeltme). Bu, "herkeste her şey" hissini tek hamlede bitirir.

**P0.2 — Özellik-sahipliği matrisini kalıcılaştır.**
§2 matrisi CLAUDE.md'ye girer (bu turda ekliyorum). Kural: bir modülde çalışırken sahibi tenant(lar) bilinir; değişiklik onların ihtiyacına göre yapılır ve en az bir sahip + bir sahip-olmayan tenant'ta smoke edilir.

### P1 — Bu çeyrek

**P1.1 — "Tenant-özel özellik = module-gated" sertifikasyonu (hard rule).**
Her tenant-özel özellik: (a) `enable_*` + rol arkasında, (b) route `meta.module`, (c) **sahip-olmayan tenant'ın davranışını değiştirmez** (çekirdek yolları aynı kalır). PR review kapısında bu üçü doğrulanır.

**P1.2 — Çekirdeği "kernel" olarak koru.**
`money.py` (GL/JE/FX), `organization.py`, `_common.py`, para/kur mantığı = platform çekirdeği. En yüksek test barı; tenant özelliği çekirdeği **genişletir, fork'lamaz.** Farklı muhasebe ihtiyacı → strateji/konfig (company-setting), asla `if tenant`. Para hassasiyetini metadata'dan okuma deseninizi tüm varyant davranışlara yay.

**P1.3 — Sürüm blast-radius yönetişimi.**
Tek restart 7 tenant demek olduğundan: (a) her deploy'da çekirdek yolları test et, (b) smoke'u **≥2 tenant**'ta yap — biri sahip, biri sahip-olmayan (sızıntı kontrolü), (c) düşük-trafik penceresi / canary tenant (ör. önce smartbox, sonra anjan), (d) migration'lar additive + nullable + guard'lı (zaten kural).

**P1.4 — Sızıntı testi.**
Basit bir test matrisi: "modül X, `enable_x=0` olan bir company'de list/detail endpoint'lerini 403/boş döndürür." Bir gating regresyonunu CI'da yakalar.

### P2 — Olgunlaşma

- **Paylaşılan doctype'a zorunlu alan koyma.** Modül-özel zorunlu alanlar sadece o modülün doctype'larında. Paylaşılan doctype'a eklenen alan nullable olmalı.
- **Config-first varyasyon.** Tüm tenant-varyant davranış `Stabler Company Modules`/company-setting'den okunur; kod sabiti yok.
- **beads/GLM iş akışına bağla:** tenant-özel işleri ayrı worktree + özellik-bayrağıyla; bead spec'inde "sahip tenant" ve "sahip-olmayan smoke" alanları.
- **Aylık "modül sahipliği" gözden geçirmesi** (CODEOWNERS benzeri) — matris güncel kalır.

---

## 6. Ne zaman tenant'ı ayırmalı (fork kriterleri)

Tek-app-çok-tenant'ta **kalmak** varsayılan olmalı (N kod tabanının bakım maliyeti, blast-radius güvenliğinden pahalıdır). Fork'u yalnızca şu **somut** tetikleyiciler gelince düşün:

- **Uzlaşmaz çekirdek ayrışması:** bir tenant'ın muhasebe/para mantığı kernel'i, diğerlerini bozmadan konfigüre edilemiyorsa.
- **Regülasyon/veri izolasyonu:** yasal olarak ayrı kod/altyapı zorunluysa.
- **Bağımsız sürüm temposu:** bir tenant "asla kesinti kabul etmiyorum" diyorsa ve paylaşılan restart kabul edilemezse.
- **Performans/ölçek:** bir tenant'ın yükü paylaşılan bench'i boğuyorsa.

Bunlardan biri gerçekleşene kadar fork = erken optimizasyon. (Anjan-HR'ın zaten ayrı bir app olması, bu ayrımı iş bazında yapabildiğinizi gösteriyor — payroll gerçekten ayrı bir üründü.)

---

## 7. Riskler ve karşı-görüşler (dürüst olmak gerekirse)

- **Aşırı-gating karmaşası:** çok ince modül bölme, config sprawl yaratır. 17 modül şu an makul; daha fazla bölmeden önce ihtiyaç kanıtı iste.
- **Default'u opt-in yapmanın geçiş maliyeti:** mevcut 7 tenant zaten açık modüllerle çalışıyor; default değişikliği onları etkilemez ama bir kerelik denetim iş yükü var. Denetimi yaparken **çalışan bir şeyi yanlışlıkla kapatma** riski — her tenant'ın gerçekten kullandığını kapatmadan önce sahibiyle doğrula.
- **Matris bakım yükü:** güncel tutulmazsa yanıltır. Aylık review'a bağla, yoksa yapma.
- **Canary tenant seçimi:** en küçük/en toleranslı tenant canary olmalı; ana prod (anjan) asla ilk sırada değil.

---

## 8. Somut aksiyon planı

**Bu hafta (P0):**
1. `Stabler Company Modules` default'larını gözden geçir → çekirdek dışını `0`'a çek (kod değişikliği + migrate).
2. 7 tenant'ın açık modüllerini per-site denetle, §2'ye göre fazlalıkları kapat (sahiple doğrulayarak).
3. §2 matrisini CLAUDE.md'ye işle (bu turda yapıldı).

**Bu çeyrek (P1):**
4. PR review kapısına "tenant-özel = module-gated + çekirdek değişmiyor" maddesi.
5. Sızıntı testi (modül-OFF → boş/403).
6. Deploy runbook'una "≥2 tenant smoke (biri sahip-olmayan) + canary sırası" ekle.

**Sürekli (P2):**
7. Config-first varyasyon; paylaşılan doctype'a reqd alan yok.
8. Aylık modül-sahipliği review; beads bead'lerinde "sahip tenant" alanı.

---

## Ek: laminor & smartbox

Bu iki tenant'ın iş modeli ve modül seti dokümanlarda net değil (master-roadmap sadece adlarını listeliyor). §2 matrisini kapatmak için sahipleriyle 2 dakikalık bir teyit yeter: "Bu tenant hangi işi yapıyor, hangi Stabler modüllerini kullanıyor?" Cevap gelince matrise işlenir.
