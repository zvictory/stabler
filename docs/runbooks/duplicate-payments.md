# Aynı ödeme iki kez: gönderim başarısız olduğunda ne yapmalı

> **Neden bu dosya var:** Para formlarında bir gönderimin **hata vermesi**, hiçbir
> şeyin yazılmadığının kanıtı değildir. İstek sunucuya ulaşıp kaydı gerçekten
> oluşturmuş ve yalnızca **yanıt** kaybolmuş olabilir — paylaşılan bench'te
> gunicorn/nginx timeout'u tam olarak bunu üretir. Form dolu kaldığı için en
> doğal refleks Submit'e tekrar basmaktır ve sunucu tarafında bunu durduran
> hiçbir şey yoktur: ikinci kayıt, ilkinden yalnızca seri numarasıyla ayrılır.
>
> İdempotentlik kurulu 2026-08-20'de bu sınıfı ölçtü. Kalıcı çözüm, dokümanın
> payload'dan türeyen benzersiz bir anahtar taşımasıdır (`custom_idempotency_key`,
> doctype değişikliği + her stabler sitesinde migrate). Bu runbook, o gelene kadar geçerli
> olan operatör davranışını yazar.

## Gider ve transfer (`/money/expenses`, `/money/transfers`)

Gönderim hata verdiğinde form kırmızı uyarının altında şu cümleyi gösterir:
*"Gider zaten kaydedilmiş olabilir. Yeniden göndermeden önce gider listesini açıp
kontrol edin."*

Sırasıyla:

1. **Tekrar Submit'e basma.**
2. Aynı ekranın listesini aç ve **bugünün tarihinde**, aynı tutarlı bir kayıt var
   mı bak. Gider kayıtlarının `cheque_no` alanı `Exp-<tarih>` biçimindedir ve o
   tarihteki **her** gider aynı değeri taşır — yani bu alan bir anahtar değildir,
   ayırt etmek için tutara, hesaba ve satırlara bakman gerekir.
3. Kayıt varsa: iş bitmiştir, formu kapat.
4. Kayıt yoksa: yeniden gönder.

İki kez yazıldıysa fazlalığı **iptal et** (`Cancel`), silme — denetim izi kalsın.

## Fatura ödemesi (`PaymentModal`, `/money/...` fatura ekranları)

Bu uçta artık bir sunucu guard'ı var: bir faturaya bağlı **gönderilmemiş** bir
Payment Entry varken ikincisi reddedilir ve mevcut olanın adı mesajda verilir
(`stabler/api/money.py` → `_assert_no_pending_payment`).

Bu mesajı gördüğünde:

1. Mesajdaki `PE-…` adını aç.
2. Onay bekliyorsa: onaycıya bırak, yeni ödeme oluşturma.
3. Terk edilmiş bir taslaksa: sil, sonra yeniden dene.

**Guard'ın kapsamadığı durum:** gerçekten eşzamanlı iki istek (iki sekme, aynı
saniye) ikisi de "taslak yok" okuyup ikisi de yazabilir. Guard, operatörün
*ardışık* tekrarını keser — pratikte görülen tek vaka odur.

**Bilerek dar tutuldu:** *gönderilmiş* bir ödeme ikinciyi engellemez, çünkü o
taksitli ödemenin meşru hâlidir — `outstanding_amount`'ı zaten düşürmüştür, yani
ödeyen kalan tutarı görerek karar verir. Tehlikeli olan, hiçbir sayıyı
oynatmadığı için faturayı hâlâ "ödenmemiş" gösteren **taslaktır**.

## İlgili

- İdempotentlik kurulu raporu — güvenli sayılan uçlar, sıra ve reddedilen öneriler
- `stabler/api/_common.py:53-67` — `check_concurrency`, mevcut dokümanların savunması
- `stabler/tests/test_concurrency_token_call_sites.py` — istemcinin token göndermeyi
  unutmasını `make check` içinde kırmızıya çeviren kapı
