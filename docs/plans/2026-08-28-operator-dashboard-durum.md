# operator-dashboard — bugünkü durum ve Stabler'la ilişkisi

**Tarih:** 2026-08-28 · **Ölçen:** Claude, Zafar'ın talebiyle
**Kaynak paket:** `operator-dashboard-2026-08-23.rar`, Zafar'ın Downloads klasöründe.
**Bu depoda hiçbir izi yok** — `grep -r "operator-dashboard"` boş döner.

Bu doküman bir karar değil, bir **envanter**. Yazılma sebebi: bu iş Stabler ekibinin
gündeminde ama Stabler deposunda hiç görünmüyor; hangi işin gerçekten yapıldığını
öğrenmek için her seferinde arşiv açmak gerekiyordu.

---

## Ne olduğu

Stabler'dan **ayrı** bir uygulama: React 19 + Vite 8 + Tailwind v4, arayüzü Özbekçe,
kendi git deposu var. Bir üretim sistemi değil, **çalışan bir demo**.

| | |
|---|---|
| Depolama | yalnız `localStorage`, `opdash_v1_` öneki |
| Backend | **yok** |
| Yetki kontrolü | yalnız frontend |
| Kullanıcı listesi | şifrelenmemiş, kodda |
| Girişler | `rahbar` / `nazoratchi` / `iadmin`, parola `demo123` |

Bu sınırların üçü de README'nin kendi ilanı; kodda doğrulandı.

## Beyan mı, gerçek mi — denetim sonucu

`BAJARILGAN_ISHLAR.md` altı faz, on commit ve ~8 500 satır beyan ediyordu. Arşivin
içinde `.git` olduğu için beyana güvenmek gerekmedi:

- **11 commit** — biri `9cfdffc` ilk import (Bekmurod, 21.08), onu on özellik commit'i
  izliyor (Odilbek, 21–24.08).
- **9 198 satır eklenmiş** — kendi raporu satır sayısında mütevazı davranmış.
- **Altı fazın altısı da kodda.** Beyan doğru.

| Faz | Kanıt |
|---|---|
| 1 · Kritik düzeltmeler (K1, K2) | `ce468f4` · `src/utils/rahbarXulosa.js:43` — anahtar artık `${r.sana}__${r.bolim}__${r.liniya}__${r.smena}`, yani **tarih anahtarın içinde**; 26–78 kat şişme gerçekten kapanmış |
| 2 · Üretim akışı, 6 talep | `714f130` · `src/utils/yakunlash.js:51-55` — zaman balansı (`Tam − Nazariy − Σplanlı − Σplansız = 0 ±1dk`) kaydetmeyi **kilitliyor** · `VaqtKiritish.jsx`, `PauzaModal.jsx` |
| 3 · Taslak modu + admin tahriri | `871e29a` · `YakunTahrirModal.jsx` (134 satır) |
| 4 · KPI modülü | `bb762f6`, `a4883f3` · `src/utils/kpiProfil.js` (369 satır) — "kategori yüzdeleri toplamı" modeli kodda |
| 5 · Hammadde sipariş akışı | `0dfcddc`, `e647421`, `a9ca7c0` · `src/utils/zakaz.js` (206 satır) |
| 6 · Günlük üretim planı | `9271dbe` · `src/utils/kunlikReja.js` (112 satır) + `IshlabChiqarishRejasi.jsx` (749 satır) |

## Ölçülemeyen tek şey

**Kaç gerçek kullanıcısı var — ölçülemez.** Veri `localStorage`'da yaşıyor, sunucu
kaydı yok. Bu bir eksiklik değil, mimarinin doğrudan sonucu: kimse kaç kişinin
kullandığını söyleyemez, çünkü söyleyecek bir yer yok.

## Stabler'la ilişkisi — açık karar

Projenin kendi yol haritası, F4'te backend adayı olarak **ERPNext**'i gösteriyor. Yani
bu demonun kendisi, bir gün Stabler'a bağlanmayı öngörüyor. Bugün bağlı değil.

**Karar gereken:** üretim verisi kimden, hangi ekrandan toplanacak?

- Cevap **"operatörden"** ise: bu uygulamanın backend'i Stabler olmalı, fire ve duruş
  oraya akmalı, ve `localStorage` bir geçiş aşaması olarak ele alınmalı.
- Cevap **"yöneticiden"** ise: kiosk yatırımı durmalı ve bu demo demo olarak kalmalı.

Bu, `2026-08-28-manufacturing-is-emirleri-durum.md`'deki engelin **aynısıdır**.
Manufacturing tarafındaki ölçüm cevabı zorlaştırıyor: anjan'da 3 725 üretim girişinin
3 688'i iki yönetici hesabından geliyor, fire ve duruş sıfır. Yani bugün fiilen
"yöneticiden" toplanıyor — ama iki paket birden "operatörden" varsayımıyla yazılmış.

## Kapsam notu

Bu turda operator-dashboard'u Stabler'a taşımak **yapılmadı** ve önerilmiyor. Burada
bir karar sorusu olarak duruyor, bir uygulama planı olarak değil. Taşıma kararı
verilirse ilk iş `localStorage` şemasını bir doctype eşlemesine çevirmek olur; o
çalışma bu dokümanın kapsamı dışında.
