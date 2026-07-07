# UZEX teklif imzası — E-IMZO uyarlanabilirlik etüdü (WP-306)

**Tarih:** 08.07.2026 · **Kapsam:** `public/js/lib/eimzo.js` (didox için kullanılan E-IMZO akışı) UZEX tender teklif gönderimine uyarlanabilir mi? · **Karar:** Kısmen — imza teknik olarak üretilebilir, **portala otomatik gönderim YAPILMAZ** (insan portalda imzalar/yükler).

## 1. Mevcut E-IMZO akışı (didox)

`eimzo.js` yerel E-IMZO masaüstü uygulamasının CAPIWS websocket köprüsüne (`wss://127.0.0.1:64646/service/cryptapi`) bağlanır. Özel anahtar tarayıcıyı/E-IMZO sürecini **asla terk etmez**:

```
isAvailable() → listKeys() → loadKey(entry) → createPkcs7(keyId, dataBase64) → PKCS#7 (base64)
```

Didox'ta bu imzalı PKCS#7 zarfı sunucuya iletilir ve Didox API'sine POST edilir (`integrations/didox/client.py`). Yani zaten: **belgeyi base64'le → E-IMZO ile imzala → imzalı zarfı bir operatöre gönder** deseni çalışıyor.

## 2. UZEX'e uyarlama — teknik analiz

| Adım | Didox | UZEX teklif | Uyarlanabilir mi? |
|---|---|---|---|
| Belge hazırlama | ЭСФ JSON | bid paketi (docx/JSON) — **WP-306 `bid_package` üretiyor** | ✅ hazır |
| E-IMZO imzası | `createPkcs7(keyId, b64)` | aynı çağrı, girdi = bid belgesi b64 | ✅ teknik olarak aynı |
| İmzalı zarfın gönderimi | Didox REST `send()` | **UZEX'in yazma/gönderme API'si BELGESİZ** — WP-300 yalnız read uçları buldu (`TradeList`/`GetTrade`) | ❌ yok |
| Yasal bağlayıcılık | Didox operatörü | teklif imzası UZEX portalının **kendi** E-IMZO akışında yapılır | ❌ portal içi |

**Kritik engel:** UZEX teklif gönderimi portalın kendi Angular SPA'sında, kendi CAPIWS/E-IMZO entegrasyonu + kendi imza formatı (muhtemelen belge + ayrık imza + oturum token'ı) ile yapılıyor. Gönderim ucunun sözleşmesi (endpoint, payload şeması, imza sarma biçimi) **elimizde yok** (WP-300 doğruladı). Bu format tahmin edilerek imza gönderilirse hem teknik hem **hukuki** olarak geçersiz/riskli olur.

## 3. Tavsiye

**Şimdilik:** Stabler paketi hazırlar (`bid_package` → docx + P&L/Остаток verisi, Deal'e File olarak eklenir). İnsan bu paketi **UZEX portalında** kendi E-IMZO anahtarıyla imzalar ve yükler. Otomatik gönderim yok — bu bilinçli kapsam ve hukuki sınır.

**Opsiyonel (düşük değer, arşiv amaçlı):** Stabler, `eimzo.js`'in mevcut `createPkcs7` akışını yeniden kullanarak üretilen bid docx'ini **kayıt için** imzalayıp imzalı PKCS#7'yi Deal'e ekleyebilir (didox'takiyle aynı kod). Bu, portaldaki resmi imzanın yerine geçmez; yalnız iç denetim izi sağlar. Efor: ~yarım gün (docx'i b64'le → `createPkcs7` → File attach). Portal gönderimi için hiçbir katkısı yoktur.

**Otomatik gönderim için gereken (gelecekte):** (1) UZEX resmi entegrasyon/API başvurusu → yazma ucu + imza formatı sözleşmesi; (2) portalın kabul ettiği imza sarma biçiminin doğrulanması (sandbox); (3) hukuk onayı (imza sorumluluğu). Bunlar gelmeden gönderim otomatikleştirilemez.

## 4. Riskler
1. **Belgesiz gönderim ucu** → tahmini payload = geçersiz teklif + hukuki risk. Kesinlikle yapılmaz.
2. **E-IMZO masaüstü bağımlılığı** → imza yalnız kullanıcının makinesinde; sunucu tarafı imza mümkün değil (özel anahtar yerelde). Zaten insan-onaylı akışla uyumlu.
3. **İmza formatı değişimi** → portal güncellenirse tahmini entegrasyon kırılır; resmi API bunu sözleşmeyle sabitler.

## 5. Sonuç
`eimzo.js` **teknik olarak** UZEX bid belgesini imzalayabilir (didox ile aynı CAPIWS akışı), ancak **gönderim ucu olmadığı** için uçtan uca otomasyon mümkün ve uygun değil. WP-306 kapsamı doğru: **sistem paketi hazırlar, insan portalda imzalar/gönderir.** Resmi API başvurusu (STATE.md §6 açık döngü) bu kararı ileride değiştirebilecek tek girdidir.
