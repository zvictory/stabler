# Prompt — Hesap planı numaralandırma, YALNIZCA mikas

Bu dosyanın tamamını Claude Code'a yapıştır. Sıradan çıkma, ilk hatada dur.

---

Sen `mikas.erpstable.com` sitesinde hesap planına (Chart of Accounts) numara
ekleyeceksin. **Sadece bu site.** Bench 7 stabler sitesi barındırıyor; başka
hiçbir siteye dokunma. Her `bench` komutunda `--site mikas.erpstable.com`
olduğunu iki kez kontrol et.

## Neden dikkatli olmak gerekiyor

ERPNext'te "hesap numaralarını aç" diye bir ayar yoktur. Numara, Account
kaydındaki `account_number` alanıdır ve dolduğunda ERPNext hesabın **docname'ini
yeniden adlandırır**: `Kassa - MIK` → `1110 - Kassa - MIK`. Yani bu bir toplu
rename operasyonudur; GL Entry, Payment Entry, Journal Entry ve tüm Link
alanları güncellenir. Yedeksiz geri dönüşü yoktur.

Ön inceleme yapıldı: Stabler'ın mikas'ta kullandığı hesap referanslarının hepsi
Link alanı (`Stabler Kassir Account.account`, `Stabler Settings`'teki hesaplar),
Frappe bunları rename sırasında otomatik günceller. Kassa shadow ledger'ı
muhasebeye dokunmaz. Yani kassa botunun kırılmasını beklemiyoruz — ama Adım 7'de
yine de doğrulayacaksın.

## Adım 1 — hedefi doğrula

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && \
  bench --site mikas.erpstable.com list-apps | grep -q stabler && echo "stabler OK" ; \
  bench --site mikas.erpstable.com execute frappe.client.get_list \
    --kwargs "{\"doctype\":\"Company\",\"fields\":[\"name\",\"abbr\",\"default_currency\"]}"'
```

Şirket adını ve kısaltmasını (abbr) not et. Birden fazla şirket varsa **dur** ve
hangisi olduğunu bana sor.

## Adım 2 — mevcut durumu çıkar

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com console' <<'PY'
import frappe
rows = frappe.db.sql("""
  SELECT name, account_name, account_number, root_type, is_group, lft, parent_account
  FROM `tabAccount` WHERE company=%s ORDER BY lft
""", (frappe.db.get_value("Company", {}, "name"),), as_dict=True)
numbered = [r for r in rows if r.account_number]
print(f"toplam hesap: {len(rows)} | zaten numarali: {len(numbered)}")
for r in rows:
    print(f"{'  '*0}{r.lft:>5} {'[G]' if r.is_group else '   '} {r.root_type or '':<11} "
          f"{(r.account_number or '-'):>6}  {r.name}")
PY
```

Çıktının tamamını bana göster. **Zaten numaralı hesap varsa dur** — kısmi
numaralandırma başka bir karar gerektirir, bana sor.

## Adım 3 — yedek (zorunlu, tek geri dönüş yolu)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && \
  bench --site mikas.erpstable.com backup --with-files && \
  ls -lht sites/mikas.erpstable.com/private/backups/ | head -3'
```

Yedek dosya adını bana bildir. Yedek alınmadıysa devam etme.

## Adım 4 — numaralandırma önerisi ÜRET, uygulama

Standart aralıklar, `lft` sırasında ağacı gezerek:

| root_type | aralık |
|---|---|
| Asset | 1000 |
| Liability | 2000 |
| Equity | 3000 |
| Income | 4000 |
| Expense | 5000 |

Kural: her root altında gruplar 100'er, yaprak hesaplar 10'ar artsın (ileride
araya hesap eklenebilsin diye boşluk bırak).

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com console' <<'PY'
import frappe
company = frappe.db.get_value("Company", {}, "name")
BASE = {"Asset":1000, "Liability":2000, "Equity":3000, "Income":4000, "Expense":5000}
rows = frappe.db.sql("""SELECT name, account_name, account_number, root_type, is_group, lft
                        FROM `tabAccount` WHERE company=%s ORDER BY lft""",
                     (company,), as_dict=True)
counters, plan = {}, []
for r in rows:
    rt = r.root_type
    if not rt:
        plan.append((r.name, None, "ATLANDI (root_type yok)")); continue
    c = counters.setdefault(rt, {"group": BASE[rt], "leaf": BASE[rt]})
    if r.is_group:
        c["group"] += 100; c["leaf"] = c["group"]; num = c["group"]
    else:
        c["leaf"] += 10; num = c["leaf"]
    plan.append((r.name, str(num), f"{num} - {r.account_name} - {frappe.db.get_value('Company', company, 'abbr')}"))
print(f"{'MEVCUT AD':<48} {'NO':>6}  YENI AD")
for old, num, new in plan:
    print(f"{old:<48} {(num or '-'):>6}  {new}")
print(f"\ntoplam {len([p for p in plan if p[1]])} hesap numaralanacak")
PY
```

**Bu adım hiçbir şey yazmaz.** Çıktının tamamını bana göster ve onayımı bekle.
Numaralandırma mantığını değiştirmemi isteyebilirim.

## Adım 5 — uygula (yalnızca ben "onay" dedikten sonra)

Adım 4'teki aynı planı üret, sonra uygula. Yapraklardan başlamak gerekmiyor;
ERPNext parent/child rename'i kendi halleder. Tek tek kaydet, hata olursa dur.

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com console' <<'PY'
import frappe
company = frappe.db.get_value("Company", {}, "name")
BASE = {"Asset":1000, "Liability":2000, "Equity":3000, "Income":4000, "Expense":5000}
rows = frappe.db.sql("""SELECT name, root_type, is_group, lft FROM `tabAccount`
                        WHERE company=%s ORDER BY lft""", (company,), as_dict=True)
counters, done, failed = {}, 0, []
for r in rows:
    if not r.root_type:
        continue
    c = counters.setdefault(r.root_type, {"group": BASE[r.root_type], "leaf": BASE[r.root_type]})
    if r.is_group:
        c["group"] += 100; c["leaf"] = c["group"]; num = c["group"]
    else:
        c["leaf"] += 10; num = c["leaf"]
    try:
        doc = frappe.get_doc("Account", r.name)
        if doc.account_number:
            continue                      # idempotent: zaten numarali
        doc.account_number = str(num)
        doc.save()
        done += 1
    except Exception as e:
        failed.append((r.name, str(e)[:120]))
frappe.db.commit()
print(f"numaralandirildi: {done}")
for n, e in failed:
    print("  HATA:", n, "->", e)
PY
```

Hata listesi boş değilse **dur** ve bana göster.

## Adım 6 — sonucu doğrula

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com console' <<'PY'
import frappe
company = frappe.db.get_value("Company", {}, "name")
rows = frappe.db.get_all("Account", {"company": company},
                         ["name","account_number","root_type"], order_by="lft")
missing = [r.name for r in rows if not r.account_number]
print(f"toplam {len(rows)} | numarasiz {len(missing)}")
print("numarasiz kalanlar:", missing[:20])
# kirik referans var mi
orphan = frappe.db.sql("""SELECT DISTINCT gle.account FROM `tabGL Entry` gle
    LEFT JOIN `tabAccount` a ON a.name = gle.account
    WHERE gle.company=%s AND a.name IS NULL""", (company,), as_dict=True)
print("kirik GL Entry hesap referansi:", orphan or "yok")
PY
```

`kirik GL Entry hesap referansi` **"yok"** olmalı. Değilse hemen bana bildir,
Adım 3 yedeğinden geri döneceğiz.

## Adım 7 — kassa botu ve Stabler kontrolü

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com console' <<'PY'
import frappe
for r in frappe.get_all("Stabler Kassir Account", fields=["name","account"]):
    exists = frappe.db.exists("Account", r.account)
    print(f"{'OK ' if exists else 'KIRIK'} {r.name} -> {r.account}")
PY
```

Hepsi `OK` olmalı — Link alanları rename ile birlikte güncellenmiş olmalı.
Ardından Telegram kassa botunda **bir kirim işlemi** yap ve menüde bakiyelerin
doğru geldiğini gör. Stabler SPA'da `#/money/accounts` sayfasını aç, hesapların
listelendiğini doğrula.

## Bilinmesi gerekenler

- **Numara ekranda görünmez.** Numara `name`'e (docname) giriyor, `account_name`
  alanı eskisi gibi kalıyor. Stabler UI'ı ve kassa botu `account_name`
  gösterdiği için arayüzde numara çıkmaz. Numaraların görünmesini istiyorsan bu
  ayrı bir iş — bana söyle, `money.py` ve bot tarafında gösterimi değiştiririm.
- **Bu bir kod değişikliği değil.** Sadece mikas'ın veritabanındaki veri
  değişiyor. rsync/build/restart **gerekmez**, diğer 6 tenant etkilenmez.
- **Geri alma:** Adım 3'teki yedeği geri yükle
  (`bench --site mikas.erpstable.com restore <dosya>`). Kısmi geri alma yok.

## Yapma

- Başka bir siteye `--site` verme.
- Adım 4 çıktısını bana göstermeden Adım 5'i çalıştırma.
- Hata listesi doluyken devam etme.
- `frappe.db.sql` ile `tabAccount.name` alanını elle UPDATE etme — rename'i
  ERPNext'in kendi `doc.save()` yolu yapmalı, yoksa referanslar kırılır.
