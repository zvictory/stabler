# Kiracı modül denetim raporu — 2026-07-27

**Salt okunur denetim. Hiçbir bayrak değiştirilmedi, hiçbir kod dokunulmadı.**
Karar bu rapor okunduktan sonra verilecek (Faz F Adım 2).

Yöntem: her sitede `tabStabler Company Modules` bayrakları okundu, ardından her
açık modülün **sinyal tablosunda** `COUNT(*)` alındı. Sayımlar site DB'si
genelinde; her sitede tek company olduğu için company kırılımı gerekmedi.

---

## 1. Önce iki düzeltme

**a) "14/17 modül `default=1`" bilgisi eskimiş.** `stabler_company_modules.json`
bugün 18 bayrağın yalnızca **4'ünde** `default=1` tutuyor (money, sales,
purchasing, inventory). Yönetişim belgesinin P0.1 maddesi **18 Tem'de zaten
uygulanmış** (`fb63f8f feat(modules): opt-in module defaults (lean ERP core) +
tenant audit`). Yani "yeni company her şeyi açık doğar" sorunu kapanmış durumda.

**b) Kalan sorun geriye dönük olan.** Doctype default'u mevcut satırlara
uygulanmaz — o commit'in kendi notu da bunu söylüyor: *"The existing 7 tenants
already have all-on rows, so they need a one-time audit + per-tenant disable."*
**Bu rapor tam olarak o tek seferlik denetim.**

---

## 2. Sonuç matrisi

`~` işaretli sayımlar **paylaşılan doctype** üzerinden gelir (tender → `CRM Deal`,
remittance → `Journal Entry`, installment → `Payment Schedule`). Bu modüllerin
kendi tablosu yok; sayı "modül kullanılıyor" kanıtı **değildir**, sadece fikir verir.

| Site | Aktif kul. | Son aktiflik | Açık | Gerçekten kullanılan | **Açık ama boş** |
|---|---|---|---|---|---|
| **anjan** | 34 | 27 Tem | 6 | money 16 092 · sales 14 510 · inventory 8 858 · manufacturing 3 654 · purchasing 1 840 · hr 433 | **yok** |
| **msa** | 6 | 27 Tem | 5 | money 5 311 · sales 4 149 · imports 418 | purchasing, inventory |
| **mikas** | 5 | 27 Tem | 5 | crm 14 · sales 3 · purchasing 3 · *(tender 14~ = aynı 14 CRM Deal)* | money |
| **dts** | 4 | 25 Tem | 5 | agreements 92 · money 1 · sales 1 | purchasing, inventory |
| **laminor** | 4 | 22 Tem | 5 | **hiçbiri** | money, sales, purchasing, inventory, imports |
| **smartbox** | 3 | 14 Tem | **17** | sales 1 · crm 14 *(hepsi tek günde)* | **12 modül** |
| **horeca** | 2 | 3 Haz | 5 | **hiçbiri** | money, sales, inventory, field_sales, service |

---

## 3. Okunuşu

**anjan tertemiz.** 6 modül açık, 6'sı da yoğun kullanımda. Hedef durum bu.

**smartbox tek gerçek "çöp" vakası.** 18 modülün 17'si açık; sadece 1 satış
faturası ve 14 CRM Deal var — o 14 kaydın **hepsi 2026-06-07'de, tek günde**
oluşmuş (mikas'ta aynı 14 kayıt 2 May – 23 Tem'e yayılmış, yani orası gerçek
kullanım). Smartbox'ın verisi demo/seed görünüyor. `remittance 5~` ve
`installment 3~` sinyalleri paylaşılan tablolardan geliyor, kanıt değil.
**12 modül boşuna açık.**

**horeca ve laminor'da hiçbir modülde tek satır yok.** İkisi de canlı veri
girmemiş. laminor 22 Tem'de, horeca 3 Haz'da giriş yapmış — yani hesaplar var,
iş akışı yok. Burada mesele modül fazlalığı değil, **kiracının hiç başlamamış
olması**. Modül kapatmak önce bu soruyu cevaplamayı gerektirir: bu iki kiracı
canlıya geçecek mi, yoksa demo mu?

**purchasing/inventory üç sitede boş** (msa, dts + laminor). msa için bu beklenen:
satın almayı `imports` (Proforma Invoice, 418 kayıt) üzerinden yürütüyorlar, klasik
Purchase Invoice akışını kullanmıyorlar. Yine de kapatmadan önce sahibine sorulmalı
— boş olması "gelecek ay kullanılmayacak" demek değil.

**mikas'ta `money` açık ama boş.** CLAUDE.md matrisinde kassa botu mikas'a ait
görünüyor; Payment Entry sayısı 0. Ya bot henüz canlı değil ya da matris yanlış.

---

## 4. Sahiplik matrisi ile uyuşmayanlar

CLAUDE.md'deki tablo ile veri iki yerde çakışıyor:

- **`imports` = msa** deniyor, ama **laminor**'da da açık (0 kayıt). Ya kapatılmalı
  ya matris güncellenmeli.
- **`agreements`** matriste hiç geçmiyor, ama **dts**'in en çok kullandığı modül
  (92 kayıt). Matrise eklenmeli: agreements → dts.
- **laminor** ve **smartbox** iş modeli matriste hâlâ *(confirm)* — bu rapor da
  cevaplayamıyor, çünkü ikisinin de anlamlı verisi yok. Sahiplerinden sorulmalı.

---

## 5. Öneri (karar sizin)

Riski düşükten yükseğe:

1. **smartbox** — 12 boş modülü kapat. Tek gerçek kazanç burada; veri demo, kimse
   etkilenmez. Kalan: money, sales, purchasing, inventory (+ crm istenirse).
2. **laminor** — `imports` kapatılsın (matris ihlali + 0 kayıt). Diğer 4 çekirdek
   modül, kiracı canlıya geçecekse kalsın.
3. **horeca** — kiracının durumu netleşene kadar **dokunma**. 5 modülün 5'i boş ama
   field_sales/service tam da HoReCa'nın iş modeli; kapatmak canlıya geçişi bloke eder.
4. **msa / dts** — purchasing+inventory kapatma **yalnızca sahibi onaylarsa**.
5. **mikas** — `money` sorusu (kassa botu canlı mı?) sahibine sorulacak, sonra karar.
6. **anjan** — hiçbir şey yapma.

Her kapatma `organization.update_company_modules` üzerinden, kiracı başına tek tek.
Kapatma **veri silmez** — yalnızca SPA'da sayfayı gizler ve rolü kaldırır; geri
açmak tek tıktır. Bu yüzden geri alınabilir bir işlem, ama yine de sahibi onayı
şart.

---

## 6. Bu raporun kapsamadığı

- **Şema çöpü kapsam dışı.** Modül kapatmak, o modülün tablolarını kiracının DB'sinden
  **kaldırmaz**. 78 doctype `migrate` ile 7 DB'nin hepsinde oluşmaya devam eder;
  smartbox'ın 12 modülü kapatılsa da tabloları yerinde durur (boş oldukları için
  maliyeti ihmal edilebilir). Gerçek şema izolasyonu ancak ayrı bench/fork ile olur —
  bu programın kapsamında değil.
- **Sızıntı testi yok.** "Modül kapalıyken endpoint gerçekten boş/403 dönüyor mu"
  sorusu ölçülmedi. Yönetişim belgesi P1.4 bunu CI testi olarak öneriyor; bu rapor
  yalnızca bayrak + veri durumunu gösterir, gating'in doğru çalıştığını **kanıtlamaz**.
- Sayımlar tek sinyal tablosuna dayanıyor. Bir modül, seçtiğim tabloya yazmadan
  başka bir yerde kullanılıyor olabilir; "açık ama boş" bir **hipotez**, kesin
  hüküm değil. Sahibi onayı bu yüzden gerekli.
