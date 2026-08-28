# Kimlik bilgisi maruziyeti — müdahale runbook'u

**Kayıtlar:** `stabler-b7v` (phpMyAdmin kaldır) + `stabler-ake` (P1, parola rotasyonu)
**Tarih:** 2026-08-07 · **Hedef:** `ice-production`, `/home/frappe/frappe-bench`, ~22 kiracı

Bu dosyanın tamamını Claude Code'a yapıştır. **ONAY yazan yerde dur ve sor.**
Her faz önce **salt okuma**. 22 kiracının veritabanı erişimi söz konusu — acele etme.

---

## Sıra neden bu

Açık kapıyla parola değiştirmek yeni parolayı da sızdırır. Bu yüzden:

```
keşif → vektörü kapat (phpMyAdmin) → rotate → doğrula → uygulama sırları
```

Ters sıra (önce rotate) 12 günlük pencerede olan neyse onu bir kez daha yaşatır.

## ⚠ Kapsam raporda yazandan büyük — önce bunu oku

Maruziyet "22 sitenin DB parolası" diye kaydedilmiş. Ama `site_config.json`
okunabildiyse aynı dosyadaki **`encryption_key`** de okunabildi. Frappe o anahtarla
veritabanındaki **saklı parolaların hepsini** şifreler:

- E-posta hesabı parolaları (SMTP/IMAP)
- Entegrasyon kimlik bilgileri — Telegram bot token'ları, Google Drive OAuth,
  yedekleme hedefleri
- `Access Token` / `API Secret` tutan her doctype

Yani DB parolasını döndürmek **tek başına yetmez**: anahtar sızdıysa DB'deki şifreli
sırlar da çözülebilir durumda. Faz 5 bunu ele alıyor. Faz 0'da envanterini çıkaracağız,
sonra neyi döndüreceğine birlikte karar vereceğiz.

---

# FAZ 0 — Keşif (SALT OKUMA, hiçbir şey değiştirme)

```bash
ssh ice-production 'set -e
echo "=== phpMyAdmin / phpPgAdmin izleri:"
ls -la /etc/nginx/conf.d/ 2>/dev/null | grep -i "phpmyadmin\|phppgadmin" || echo "  conf.d: yok"
grep -rl "phpmyadmin\|phppgadmin" /etc/nginx/ 2>/dev/null | head -20 || echo "  nginx: referans yok"
ls -d /usr/share/phpmyadmin /usr/share/phppgadmin /var/www/phpmyadmin 2>/dev/null || echo "  dizin: yok"
dpkg -l 2>/dev/null | grep -i "phpmyadmin\|phppgadmin" || echo "  paket: yok"
echo
echo "=== dinleyen portlar:"
ss -tlnp 2>/dev/null | awk "NR==1 || /LISTEN/"
echo
echo "=== ufw:"
ufw status numbered 2>/dev/null || echo "  ufw yok/kapalı"
'
```

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && set -e
echo "=== siteler:"; ls sites/ | grep -v "^assets$\|common_site_config.json\|apps.txt\|apps.json\|\.build"
echo; echo "=== site sayisi:"; ls sites/ | grep -c "\." || true
echo; echo "=== her sitenin db_name + db_password uzunlugu (PAROLA BASILMIYOR):"
for s in $(ls sites/ | grep "\."); do
  [ -f "sites/$s/site_config.json" ] || continue
  python3 - "$s" <<PY
import json,sys
s=sys.argv[1]
c=json.load(open(f"sites/{s}/site_config.json"))
print(f"{s:34} db={c.get(\"db_name\",\"?\"):20} pwlen={len(c.get(\"db_password\") or \"\")} enc_key={\"VAR\" if c.get(\"encryption_key\") else \"yok\"}")
PY
done
'
```

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && set -e
echo "=== common_site_config icinde sir var mi (anahtar adlari, deger YOK):"
python3 -c "
import json
c=json.load(open(\"sites/common_site_config.json\"))
for k in sorted(c):
    v=c[k]
    print(f\"  {k} = {type(v).__name__}\" + (\" (DOLU)\" if isinstance(v,str) and v else \"\"))
"
echo; echo "=== dosya izinleri:"
ls -l sites/common_site_config.json
for s in $(ls sites/ | grep "\." | head -5); do ls -l "sites/$s/site_config.json"; done
'
```

**Çıktının üçünü de bana göster.** Şunları birlikte okuyacağız:
- phpMyAdmin gerçekten kurulu mu, hangi include'lar var
- Kaç site var, hangileri stabler taşıyor
- `site_config.json` dosyalarının izinleri (644 ise zaten herkes okuyabiliyor — ayrı bulgu)
- `common_site_config.json`'da hangi sırlar duruyor

**ONAY almadan FAZ 1'e geçme.**

---

# FAZ 1 — Vektörü kapat (phpMyAdmin / phpPgAdmin)

## 1.1 Yedek

```bash
ssh ice-production 'set -e
mkdir -p /root/sec-2026-08-07
tar czf /root/sec-2026-08-07/nginx-before.tgz /etc/nginx 2>/dev/null
ls -lh /root/sec-2026-08-07/nginx-before.tgz
'
```

## 1.2 Include'ları kaldır

Faz 0'da bulunan dosyalara göre (isimleri **oradan al**, buraya sabit yazma):

```bash
ssh ice-production 'set -e
cd /etc/nginx
# include satirlarini once GOSTER
grep -rn "phpmyadmin\|phppgadmin" . || echo "referans yok"
'
```

Bulunan her include satırını **yorum satırına al** (silme — geri alması kolay olsun),
`.inc` dosyalarını `/root/sec-2026-08-07/` altına taşı.

```bash
ssh ice-production 'nginx -t'
```

`nginx -t` **başarılı değilse DUR** ve çıktıyı bana getir. Başarılıysa:

```bash
ssh ice-production 'systemctl reload nginx && systemctl is-active nginx'
```

`reload` kullan, `restart` değil — bağlantılar kopmaz.

## 1.3 Paketi kaldır (kuruluysa)

```bash
ssh ice-production 'apt-get remove --purge -y phpmyadmin phppgadmin 2>&1 | tail -5'
```

## 1.4 Doğrula

```bash
ssh ice-production 'set -e
curl -sS -o /dev/null -w "phpmyadmin -> %{http_code}\n" http://127.0.0.1/phpmyadmin/ || true
cd /home/frappe/frappe-bench
for s in $(ls sites | grep "\."); do
  bench --site "$s" list-apps 2>/dev/null | grep -q "^stabler" || continue
  curl -sS -o /dev/null -w "$s -> %{http_code}\n" "https://$s/stabler" || true
done
'
```

Beklenen: phpMyAdmin **404/403**, listelenen her stabler sitesi **200**. Bir site düştüyse **DUR**,
`nginx-before.tgz`'i geri yükle, bana getir.

**Sonucu bana göster. ONAY almadan FAZ 2'ye geçme.**

---

# FAZ 2 — Rotasyon hazırlığı (hâlâ yazma yok)

## 2.1 MySQL root erişimini teyit et

```bash
ssh ice-production 'mysql -u root -p -e "SELECT VERSION(); SELECT COUNT(*) AS users FROM mysql.user;" 2>&1 | tail -5'
```

Root parolası gerekiyor — **bana sorma, sen giremezsen kullanıcıya sor.**
Root parolası da bu maruziyetin içindeyse **onu da döndürmemiz gerekir** (Faz 4).

## 2.2 Kurtarma ağı: mevcut parolaları root-only yedekle

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && set -e
umask 077
mkdir -p /root/sec-2026-08-07
tar czf /root/sec-2026-08-07/site-configs-before.tgz sites/*/site_config.json sites/common_site_config.json
chmod 600 /root/sec-2026-08-07/site-configs-before.tgz
ls -l /root/sec-2026-08-07/site-configs-before.tgz
'
```

Bu dosya rollback'in tek yolu. `chmod 600` ve `/root` altında kalsın; iş bitince
Faz 6'da silinecek.

## 2.3 Rotasyon planını göster (kuru)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && set -e
for s in $(ls sites/ | grep "\."); do
  [ -f "sites/$s/site_config.json" ] || continue
  db=$(python3 -c "import json;print(json.load(open(\"sites/$s/site_config.json\")).get(\"db_name\",\"\"))")
  [ -n "$db" ] && echo "$s -> ALTER USER \"$db\"@\"localhost\""
done
'
```

Listeyi bana göster: kaç site, hangi DB kullanıcıları. **ONAY almadan FAZ 3 yok.**

---

# FAZ 3 — Rotasyon (SİTE SİTE, atomik, her adımda doğrulama)

## Kural

Her site için sıra **şu** ve sadece bu:

1. yeni parola üret (32 karakter, `openssl rand`)
2. `ALTER USER` + `FLUSH PRIVILEGES`
3. `site_config.json`'a yaz (**JSON'u bozma** — python `json` ile yaz, sed ile değil)
4. **bağlantıyı doğrula**
5. doğrulama başarısızsa **o site için** eski parolaya dön ve DUR

Kesinti penceresi adım 2 ile 3 arası, saniyenin altında. Ama **paralel koşma** —
bir site kırılırsa 22'sini birden kırmış olma.

## 3.1 Önce TEK site (en düşük riskli olanla)

Faz 0 listesinden stabler taşımayan, en az kullanılan siteyi seç. Onunla dene:

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bash -s' <<'SH'
set -euo pipefail
SITE="<TEK_SITE>"          # <-- Faz 0 listesinden
CFG="sites/$SITE/site_config.json"
DB=$(python3 -c "import json;print(json.load(open('$CFG'))['db_name'])")
NEW=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)

echo "site=$SITE db=$DB"
read -rsp "MySQL root parolasi: " RP; echo

mysql -u root -p"$RP" -e "ALTER USER '$DB'@'localhost' IDENTIFIED BY '$NEW'; FLUSH PRIVILEGES;"
python3 - "$CFG" "$NEW" <<'PY'
import json,sys
p,new=sys.argv[1],sys.argv[2]
c=json.load(open(p)); c["db_password"]=new
json.dump(c,open(p,"w"),indent=1)
PY
chown frappe:frappe "$CFG"; chmod 600 "$CFG"

# dogrulama: siteyi gercekten acabildik mi
sudo -u frappe bench --site "$SITE" execute frappe.db.get_single_value --args '["System Settings","country"]' >/dev/null \
  && echo "OK  $SITE dogrulandi" \
  || { echo "FAIL $SITE — ROLLBACK GEREK"; exit 1; }
SH
```

`FAIL` görürsen **DUR.** Rollback: `site-configs-before.tgz`'den o sitenin
`site_config.json`'unu geri koy, eski parolayla `ALTER USER` çalıştır, bana getir.

**Tek site başarılıysa sonucu bana göster. ONAY almadan 3.2'ye geçme.**

## 3.2 Kalan siteler (aynı script, döngüde)

Aynı bloğu tüm siteler için döngüye al; **her sitenin sonunda doğrulama**, ilk
`FAIL`'de `exit 1`. Yeni parolaları **hiçbir yere yazdırma** — yalnız
`site_config.json`'a.

Bittiğinde:

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

Frappe işçileri açık bağlantı tutuyor olabilir; restart hepsini yeni kimlikle
kurdurur. **Tüm kiracılar için kısa blip** — düşük trafikte koş.

## 3.3 Doğrula

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && set -e
for s in $(ls sites/ | grep "\."); do
  printf "%-34s " "$s"
  sudo -u frappe bench --site "$s" execute frappe.db.get_single_value --args "[\"System Settings\",\"country\"]" >/dev/null 2>&1 \
    && echo OK || echo "FAIL <<<"
done
for s in $(ls sites/ | grep "\."); do
  bench --site "$s" list-apps 2>/dev/null | grep -q "^stabler" || continue
  curl -sS -o /dev/null -w "$s -> %{http_code}\n" "https://$s/stabler"
done
'
```

Hepsi OK / 200 olmalı. **Sonucu bana göster.**

---

# FAZ 4 — Root ve sistem kimlikleri (karar gerekiyor)

12 günlük root penceresi şunları da kapsıyorsa ayrıca döndürülmeli — Faz 0
çıktısına bakıp **birlikte karar vereceğiz**:

| Kimlik | Nerede | Döndürme |
|---|---|---|
| MySQL **root** parolası | pencerede okunabildiyse | `ALTER USER 'root'@'localhost'` + bench'in kullandığı yerleri güncelle |
| SSH yetkili anahtarları | `/root/.ssh/authorized_keys`, `/home/frappe/.ssh/` | tanımadığın anahtar varsa **hemen** çıkar |
| `frappe` kullanıcı parolası | sistem | sudo erişimi varsa döndür |

```bash
ssh ice-production 'set -e
echo "=== root authorized_keys:"; cat /root/.ssh/authorized_keys 2>/dev/null | awk "{print \$1, \$3}" || echo yok
echo "=== frappe authorized_keys:"; cat /home/frappe/.ssh/authorized_keys 2>/dev/null | awk "{print \$1, \$3}" || echo yok
echo "=== son 30 gun basarili girisler:"; last -n 40 2>/dev/null | head -25
echo "=== sudoers ekleri:"; ls -l /etc/sudoers.d/ 2>/dev/null
'
```

Tanımadığın bir anahtar veya beklenmedik bir giriş görürsen **DUR ve bana söyle** —
o zaman kapsam parola rotasyonundan büyür.

---

# FAZ 5 — Uygulama sırları (`encryption_key` sonucu)

`site_config.json` okunabildiyse `encryption_key` de okunabildi → DB'deki **şifreli
sırlar çözülebilir**. Frappe'nin temiz bir anahtar rotasyonu yok (anahtarı
değiştirirsen saklı parolalar okunamaz hale gelir), o yüzden doğru hamle
**sırların kendisini kaynağında döndürmek**:

## 5.1 Envanter (salt okuma)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site <SITE> console' <<'PY'
import frappe
frappe.set_user("Administrator")
# Sirlarin nerede durdugunu say — DEGER BASMA
rows = frappe.db.sql("""
    SELECT doctype, COUNT(*) n FROM `__Auth`
    WHERE encrypted = 1 GROUP BY doctype
""", as_dict=True)
print("sifreli kayitlar:", rows)
for dt in ("Email Account", "Social Login Key", "Webhook", "Stabler Settings"):
    if frappe.db.exists("DocType", dt):
        print(dt, frappe.db.count(dt))
PY
```

## 5.2 Kaynakta döndürülecekler (Frappe dışı)

Bunlar Frappe'den değil, **sağlayıcıdan** döndürülür — ben yapamam, sen yapacaksın:

- **Telegram bot token'ı** (kassa botu) — @BotFather → `/revoke` → yeni token →
  Stabler Settings'e gir
- **Google Drive / yedekleme OAuth** — Google Cloud Console'dan client secret yenile
- **SMTP / e-posta hesabı parolaları** — sağlayıcıdan yenile, Email Account'a gir
- **UZEX / CBU API anahtarları** (varsa) — sağlayıcıdan yenile

Envanter çıkınca hangilerinin gerçekten dolu olduğunu göreceğiz; boş olanı
döndürmeye gerek yok.

---

# FAZ 6 — Kapanış

```bash
ssh ice-production 'set -e
shred -u /root/sec-2026-08-07/site-configs-before.tgz 2>/dev/null || rm -f /root/sec-2026-08-07/site-configs-before.tgz
ls -l /root/sec-2026-08-07/
'
```

Eski parolaları taşıyan yedeği **doğrulama bittikten sonra** yok et. nginx yedeği
kalsın (sır içermiyor).

Sonra bu runbook'un altına şunu yaz ve commit et:
- ne zaman koşuldu, kaç site döndürüldü
- phpMyAdmin kaldırıldı mı, hangi include'lar
- Faz 4'te ne bulundu (yabancı SSH anahtarı var mıydı)
- Faz 5'te hangi sağlayıcı sırları döndürüldü, hangileri bekliyor
- `bd close stabler-b7v stabler-ake`

---

# Yapma

- Parolaları ekrana, log'a, commit'e, chat'e **yazdırma**.
- Rotasyonu paralel koşma — site site, her birinde doğrulama.
- `sed` ile `site_config.json` düzenleme — JSON'u `python3 json` ile yaz.
- `nginx -t` başarısızken reload etme.
- Faz 0 çıktısını göstermeden Faz 1'e, Faz 2 planını göstermeden Faz 3'e geçme.
- Tek site testi geçmeden 22 siteye dokunma.
- Yabancı SSH anahtarı veya beklenmedik giriş görürsen devam etme — bana söyle.
