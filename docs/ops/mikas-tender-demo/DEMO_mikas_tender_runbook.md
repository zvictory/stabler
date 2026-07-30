# Mikas tender demosu — operasyon runbook'u (tam döngü)

Sunum hikâyesi ve sahne anlatımı: `mikas_tender_demo_story.html` (altı perde).
Bu dosya sadece operasyon: kur, doğrula, sun, temizle.

Sahne: `https://mikas.erpstable.com/stabler` — **admin değil, Sales Manager rollü
kullanıcıyla** (admin her menüyü görür, tenant deneyimini bozar).

---

## Bu akşam (10 dk)

`scp` bu sunucuda kapalı (`Connection closed`, exit 255) — dosyayı ssh üzerinden boru ile gönder:

```bash
ssh ice-production 'cat > /home/frappe/frappe-bench/apps/stabler/stabler/tmp_demo.py \
  && chown frappe:frappe /home/frappe/frappe-bench/apps/stabler/stabler/tmp_demo.py' \
  < DEMO_mikas_full_tender_seed.py

ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com execute stabler.tmp_demo.seed'
```

Çıktıdaki **deal adını not al** — perde 3/4 URL'lerine girecek.

Sonra **doğrula — 13/13 PASS görmeden sahneye çıkma:**

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com execute stabler.tmp_demo.verify'
```

verify, demo ekranlarının uçlarını **iş sırasıyla** çağırır: intake+go → 5 teklif /
3 ülke / tek Cheapest → bid pricing'in sourcing maliyetine oturduğu (landed_goods =
en ucuz teklif) ve motorun fiyatı geri-hesapladığı → sunum damgası → result=won ve
won_price = hesaplanan fiyat → panoda SO kartı → deal-etiketli PO + vendor compare →
direktör panosu.

Son prova: dili kontrol et (sunum ru ise sağ alttan değiştir), altı perdenin URL'lerini sırayla aç.

## Sunum sırası (perde → URL) — SOURCING SUNUMDAN ÖNCE

1. **İhaleyi gördük** — `#/tender/my-tenders` → Intake sekmesi (go kararı, teklif değil)
2. **Sourcing** — `#/tender/sourcing?deal=<DEAL>` (5/5 + 3/2 rozetleri: "kaça alırız?")
3. **Değerlendirme → fiyat** — aynı ekran Cheapest → `#/tender/po-control?deal=<DEAL>`
   Bid pricing: maliyet sourcing'den, %15 marj, motor ihale fiyatını geri-hesaplar
4. **İhaleye sunduk** — Intake'te sunum damgası (submitted_at/by + UZEX ref)
5. **Kazandık** — `#/tender/board` (SO kartı, Procurement kolonunda)
6. **Yürütme** — `#/tender/po-control` **taslak PO'yu sahnede canlı submit et**
   → `#/tender/director` ile kapat (portföy, win-rate, teminat iade)

Ne söyleyeceğin ve muhtemel sorulara hazır cevaplar: story HTML'inde perde perde yazılı.

## Portföy demosu — 2025–2026 dolu pano (opsiyonel ama sunumda çok iyi durur)

Tek tender'lık döngüye ek olarak, huni/pano "gerçek hayat" gibi görünsün diye
~27 UTY tender'lık portföy yükler: her aşamada deal, son 90 günde 4 kazanç +
3 kayıp (win-rate dolu), 2025/2026 başından 4 Paid/Closed arşiv, politika-eksik
sourcing rozetleri, süre riski. Deterministik (aynı komut aynı portföyü kurar).

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com execute stabler.tmp_demo.seed_portfolio'
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com execute stabler.tmp_demo.verify_portfolio'
```

**Sıra zorunlu: `seed()` her zaman `seed_portfolio()`'dan önce.** `seed()` registry
doluysa iptal eder, `seed_portfolio()` etmez — portföyü önce kurarsan tek-tender
hikâyesi (yukarıdaki altı perde) bir daha kurulamaz, `cleanup()` gerekir.

`seed_portfolio()` her deal'den sonra commit atar; yarıda kalan bir koşu yazdığı
deal'leri geride bırakır. İkinci koşu üstüne bir portföy daha yığar ve erken
aşamalar sessizce ikiye katlanır — eşikler `>=` olduğu için verify bunu görmez.
Bu yüzden fonksiyon registry'de birden fazla deal görürse iptal eder; hata
alırsan **önce `cleanup()`**, sonra baştan.

verify_portfolio 12 kontrol koşar — hepsi PASS olmalı; özellikle şunu pinler:
**huninin son basamağı = kazanılan sayısı** (kaybedilenler sayılmaz) ve 2025
arşivi dönem win-rate'ini şişirmez. Temizlik aynı `cleanup()` — portföy dahil
her ZDEMO kaydını siler.

Not: tarih damgaları (go/sunum/sonuç) portföyde bilerek geçmişe yazılır — bu
SADECE demo scriptinde var; canlı akış damgaları her zaman sunucu saatiyle atar.

## Sunumdan sonra

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com execute stabler.tmp_demo.cleanup'
ssh ice-production 'rm /home/frappe/frappe-bench/apps/stabler/stabler/tmp_demo.py'
```

Tüm `ZDEMO` kayıtları silinir (PO → SQ → SO → Deal → Supplier → Customer → Item
ters bağımlılık sırasıyla); registry temizlenir, "zero residue" yazana kadar bekle.

## Bilinen sınırlar (soru gelirse dürüst cevap)

- SPA'da vendor teklifi giriş formu henüz yok — teklifler deal'e etiketle geliyor;
  hızlı giriş formu yol haritasında.
- Landed editor'da gerçekleşen (actual) kolonu GL belgesinden gelir; demo verisinde
  actual yok, plan kolonu dolu. "Gerçek hayatta burası GL'den otomatik dolar" de.
