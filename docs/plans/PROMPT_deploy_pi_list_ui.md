# Deploy prompt — Stabler `f3db611` (PI listesi UI)

Bu dosyanın tamamını Claude Code'a yapıştır, `~/frappe-bench-local/apps/stabler` içinden.
Sıradan çıkma, ilk hatada dur.

---

## Ne gidiyor

Tek commit: **`f3db611` — Proforma Invoices listesi sunum düzeni.**

Değişen dosyalar:
- `stabler/public/js/pages/imports/ProformaInvoices.vue`
- `stabler/translations/{en,ru,uz,uzc,tr}.csv` (4 yeni string × 5 dil)

- Items / kutu / kg / incoterm / avans / PI grubu tek gri metadata satırına indi
- FCL yalnızca sıfırdan büyükse yazılıyor (her satırda `0.0 FCL` yazıyordu)
- Docs farkı etiketli ve işaretli: `−$980 168 docs` (turuncu etiketsiz rozet yerine)
- Invoiced% tek bar + `97% · 22 CI`; bar <%100 sarı, %100 yeşil
- `grp()` artık kullanıcı diline uyuyor (sabit `ru-RU` kaldırıldı)
- Link CI butonu satır hover'ında beliriyor (dokunmatikte hep görünür)

**Sadece sunum.** API yok, doctype yok, patch yok, veri yok.

## Şema etkisi

**Yok.** `patches.txt` ve doctype JSON'ları değişmedi.
→ **`bench migrate` ÇALIŞTIRMA.** Hiçbir sitede.

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

Kardeş dizin veya `stable-erp-website/` görürsen **dur**. Beklenen:
`ProformaInvoices.vue` + 5 CSV. Özeti bana göster.

## Adım 3 — rsync + chown

Aynı komut `n` olmadan (`-rltz`), ardından:

```bash
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
```

## Adım 4 — build

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
```

Hata verirse dur ve çıktıyı göster — Vue derleme değişikliği, kırılırsa burada kırılır.

## Adım 5 — restart

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

Her kiracıda kısa kesinti — düşük trafikli bir an seç.

## Adım 6 — göz kontrolü

`https://msa.erpstable.com/stabler#/imports/proformas` (hard refresh: Cmd+Shift+R).
Şunları doğrula:

1. **Satır yüksekliği düştü** — önce ~5 PI görünüyordu, şimdi belirgin şekilde daha fazlası.
2. **Metadata satırı**: referansın altında tek gri satır — `26 items · 96 912 bx ·
   1 932 016 kg · CIF · 30% advance · PI 2 HMA`. Rozet yığını yok.
3. **`0.0 FCL` hiçbir yerde görünmüyor.** FCL girilmiş bir PI varsa orada görünmeli.
4. **Docs farkı**: tutarın altında `−$980 168 docs` (turuncu). Farkı olmayan
   satırda `docs match` yazıyor. Hiçbir yerde `+$...` rozeti kalmadı.
5. **Invoiced%**: tek bar. %100 olanlar yeşil, %97 sarı. Altında `97% · 22 CI`.
6. **Sayı formatı tutarlı**: üstteki kartlar ile tablodaki kg/kutu aynı ayırıcıyı
   kullanıyor (dil ayarına göre).
7. **Link CI**: satır üstüne gelince beliriyor, tıklayınca supersede modalı açılıyor.
   Satıra tıklayınca PI detayına gidiyor (buton tıklaması detaya gitmemeli).
8. **Filtreler** (statü / tedarikçi / PI grubu) ve arama hâlâ çalışıyor.

Dil değiştirip (ru veya uz) tekrar bak: `docs`, `docs match`, `advance`,
`Agreed / docs` çevrilmiş görünmeli, İngilizce kalmamalı.

## Geri alma

Adım 1'deki tar'ı geri yükle, `chown -R frappe:frappe`,
`bench build --app stabler`, `bench restart`.

## Yapma

- `bench migrate` çalıştırma.
- Adım 2 çıktısını göstermeden Adım 3'e geçme.
- Build hatasını geçiştirme.
