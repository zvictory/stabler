# Deploy prompt — Stabler `50fffe3` (hesap planı UI)

Bu dosyanın tamamını Claude Code'a yapıştır, `~/frappe-bench-local/apps/stabler` içinden.

---

Küçük bir frontend değişikliği deploy edeceksin. Sıradan çıkma, ilk hatada dur.

## Ne gidiyor

Tek commit: **`50fffe3` — hesap planı (Money → Chart of Accounts) sunum düzeni.**
Tek dosya değişti: `stabler/public/js/pages/money/Accounts.vue`.

- Hesap kodu kendi sütununa alındı, monospace + `tabular-nums` ile hizalandı
- İki bakiye sütunu tek sütuna indirildi; baz para birimi yalnızca gerçekten
  farklıysa küçük gri `≈` satırı olarak görünüyor
- `root_type` rozeti kaldırıldı, `account_type` kaldı
- Tutar hücrelerine `text-nowrap`, negatif bakiyeler kırmızı
- Arama artık `account_number` alanını da eşleştiriyor

**Sadece sunum.** API yok, doctype yok, patch yok, veri yok.

## Şema etkisi

**Yok.** `patches.txt` değişmedi, doctype JSON değişmedi.
→ **`bench migrate` GEREKMEZ.** Hiçbir sitede çalıştırma.

## Adım 1 — yedek

```bash
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lht /root/stabler-app-*.tgz | head -1'
```

## Adım 2 — rsync DRY RUN

Bench **`apps/`** dizininden çalıştır. `apps/stabler/` içinden çalıştırırsan
`stabler/` iç Python modülüne çözülür ve sahte bir toplu silme listesi üretir.

```bash
cd ~/frappe-bench-local/apps
rsync -rltzn --no-owner --no-group \
  --exclude '.git' --exclude 'node_modules' --exclude 'dist' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.claude' \
  --exclude '.tx_*.json' --exclude 'graphify-out' --exclude '.smoke' \
  --exclude 'tests' --exclude '*.tgz' --exclude '.DS_Store' \
  --exclude '.worktrees' --exclude '.superpowers' --exclude '.obsidian' \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
```

Çıktıda `stable-erp-website/` veya herhangi bir kardeş dizin görürsen **dur**.
Beklenen: yalnızca `Accounts.vue` ve birkaç meta dosya. Özeti bana göster.

## Adım 3 — rsync + chown

Aynı komut, `n` olmadan (`-rltz`), ardından:

```bash
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
```

## Adım 4 — build

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
```

Hata verirse dur ve çıktıyı bana göster — bu bir Vue derleme değişikliği,
kırılırsa burada kırılır.

## Adım 5 — restart

`.py` değişmedi, yani teknik olarak gerekmez; ama asset hash'inin
oturmasi için yine de yap. **7 tenant'ta kısa bir kesinti olur** —
düşük trafikli bir an seç.

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

## Adım 6 — göz kontrolü

Tarayıcıda `https://mikas.erpstable.com/stabler#/money/accounts` aç
(hard refresh: Cmd+Shift+R). Şunları doğrula ve bana bildir:

1. **Kod sütunu en solda**, tüm satırlarda aynı hizada — 1000 / 1100 / 1200 /
   1210 dikey olarak hizalı. Girinti yalnızca hesap adında.
2. **Tek bakiye sütunu.** `Kassa Som` gibi UZS hesaplarda tek satır tutar,
   tekrar yok. `USD Kassa` gibi dövizli hesapta üstte `$0.00`, altında küçük
   gri `≈ 0 сўм`.
3. **Negatif bakiye kırmızı** ve tek satırda — `−150 000 сўм` iki satıra
   kırılmıyor.
4. **Type sütununda** yalnızca Cash / Bank / Receivable görünüyor, her satırda
   tekrar eden "Asset" yok.
5. **Arama kutusuna `1420` yaz** — Kassa Som gelmeli.
6. Ağaç aç/kapa, "Expand all", yaprak satıra tıklayınca defter açılması hâlâ
   çalışıyor.

Sonra numarasız bir tenant'ta da bak (ör. `anjan.erpstable.com` — hesapları
numaralandırılmadıysa): **Kod sütunu boş olmalı, sayfa bozulmamalı.**

## Geri alma

Adım 1'deki tar'ı geri yükle, `chown -R frappe:frappe`,
`bench build --app stabler`, `bench restart`. Veri etkilenmediği için
geri dönüş temizdir.

## Yapma

- `bench migrate` çalıştırma — gereksiz ve 7 siteyi boşuna riske atar.
- Adım 2 çıktısını bana göstermeden Adım 3'e geçme.
- Build hatasını "muhtemelen önemsiz" diye geçme.
