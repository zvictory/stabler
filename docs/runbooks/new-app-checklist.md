# Yeni uygulama kontrol listesi (vibe-coded app'ler için)

> **Neden bu dosya var:** 27 Haziran – 5 Ağustos 2026 arasında `ice-production`
> sunucusu 39 gün boyunca root seviyesinde ele geçirilmiş durumdaydı (LD_PRELOAD
> rootkit'i, UID-0 arka kapı hesabı, dakikada bir çalışan dropper, sıfırlanmış
> `rsyslogd`). İhlalin asıl sebebi bir CVE değil, **ayrıcalık mimarisiydi**:
> 8 Next.js uygulamasının hepsi PM2 altında `root` olarak çalışıyordu, yani
> herhangi birindeki tek bir RCE doğrudan root demekti.
>
> Kalıcı korunma tek seferlik bir sertleştirme değil, **bir sonraki app'in doğru
> doğması**. Bu liste onun için.
>
> Tam gerekçe ve sunucu tarafı iş: `docs/plans/` altındaki 2026-08-05 tarihli
> sertleştirme planı.

---

## 1. Root asla

Her yeni app kendi sistem kullanıcısını alır:

```bash
useradd --system --no-create-home --shell /usr/sbin/nologin app-<isim>
```

Uygulama dizininin sahibi `root` kalır; app kullanıcısı yalnızca **okur**.
Yazması gereken yollar (`.next/cache`, yüklemeler) tek tek `chown` edilir ve
unit'te `ReadWritePaths=` ile açılır. Başka hiçbir yere yazamaz.

## 2. `127.0.0.1`'e bind et

Dışarıya açılım **yalnızca nginx üzerinden**. Yeni ufw kuralı açma.

- `next start` için: `-H 127.0.0.1`
- Next.js **standalone** çıktısı (`output: "standalone"`) için bayrak yoktur —
  bind adresi `HOSTNAME` env değişkeninden okunur. `HOSTNAME=127.0.0.1` sır
  dosyasına yazılmazsa app sessizce `0.0.0.0`'a açılır. (Bu tuzağa `medins-next`
  ve `wms-web` fiilen düşmüştü.)

Doğrulama: `ss -ltnp | grep <port>` çıktısında `0.0.0.0` **görünmemeli**.

## 3. Sırlar `/etc/app-secrets/<app>.env` içinde

Mode `0600 root:root`. systemd `EnvironmentFile=` bu dosyayı ayrıcalık
düşürmeden **önce**, root olarak okur — yani app kullanıcısının dosyayı okuma
yetkisi olmasına gerek yoktur. Bir path-traversal açığı sırlara ulaşamaz.

Uygulama dizininde `.env`, `.env.production`, `ecosystem.config.js` **kalmaz**.
Cutover sonrası journal'da şunu görürsün, **beklenen davranıştır**:

```
⨯ Failed to load env from .env.production Error: EACCES: permission denied
```

Ama önce kanonik dosyanın anahtar ve değerlerinin birebir aynı olduğunu kanıtla —
`comm -13` ile anahtar farkı, sonra değer karşılaştırması.

Kanıt: `sudo -u app-<isim> cat /etc/app-secrets/<app>.env` → `Permission denied`.

## 4. Unit dosyası şablondan türetilir

Şablon: sunucuda `/etc/systemd/system/app-template.service.example`.
Sertleştirme satırlarını **silme**. Sapma yapıyorsan gerekçesini unit'in içine
yorum olarak yaz (mevcut unit'lerin hepsinde örneği var).

**Tuzak:** `MemoryDenyWriteExecute=yes` **kullanılmaz** — V8 JIT'i kırar, Node
açılmaz. Şablonda bilerek yok.

**Tuzak:** Sistem kullanıcısının ev dizini yoktur. `tsx`/`esbuild`/`npm` bir
önbellek dizini isterse açılış patlar. Çözüm: `Environment=HOME=/tmp`
(`PrivateTmp=yes` sayesinde bu `/tmp` servise özeldir).

**Tuzak:** npm workspace'lerde `node_modules` app dizininde değil, workspace
kökünde hoist edilmiş olabilir (`/opt/wms/node_modules/...`). `ProtectSystem=strict`
oradan okumayı engellemez, ama `ExecStart` yolunu ölçerek yaz — çalışan sürecin
komutunu `/proc/<pid>/cmdline` ile birebir kopyala.

## 5. `npm audit --omit=dev` temiz olmadan deploy yok

High/critical varsa önce çöz. Haftalık timer bunu zaten tarayıp raporluyor
(`secops-depscan.timer` → `/usr/local/sbin/secops-depscan.sh`, pazartesi 06:30);
deploy'u şimdilik **durdurmuyor** — yani sorumluluk sende.

Yeni app'i `secops-depscan.sh` içindeki `APPS` listesine ekle. `package-lock.json`
yoksa taranamaz ve rapor bunu "TARANAMADI" diye yazar — lock dosyasını commit'le.
Python tarafı `pip-audit --path <site-packages>` ile **ortam kipinde** koşar;
`pip-audit -r freeze.txt` bu sunucuda Frappe'nin git tabanlı paketleri yüzünden
`ResolutionImpossible` verip sessizce "0 zafiyet" raporlar — o yola dönme.

## 6. AI'ın ürettiği route listesini elle oku

Kimlik doğrulaması olmayan `/api/admin`, `/debug`, `/api/exec`, `/api/cron`
tarzı uçlar vibe-coding'in klasik çıktısıdır. Her route için "bu ucu kimlik
doğrulamadan çağırırsam ne olur" sorusunu cevapla.

## 7. `child_process`, `exec`, `eval`, dinamik `import()` geçen her satırı elle oku

Kullanıcı girdisi bunlardan birine ulaşıyorsa RCE'dir. Grep şart:

```bash
grep -rnE "child_process|\bexec\(|execSync|\beval\(|import\(" src/ app/ --include='*.ts' --include='*.tsx'
```

## 8. Dosya yüklemeleri app dizininin **dışında**

Yüklenenler çalıştırılamaz bir yolda durur (ör. `/var/lib/app-<isim>/uploads`),
nginx tarafından `alias` ile servis edilir.

> **Bilinen ihlal:** `evercold` bugün `public/uploads` (433 dosya) ve
> `public/delivery-photos` (100 dosya) ile app dizininin içinde tutuyor.
> Ayrı bir işte dışarı taşınmalı.

Ayrıca app dizininde **arşiv/yedek tarball bırakma** — `evercold` web kökünde
1,7 GB yedek ve içinde sır barındıran bir `deploy.tar.gz` taşıyordu.

## 9. Deploy sonrası `systemd-analyze security app-<isim>` < 5.0

Referans: bugün üretimdeki 7 app'in hepsi **1.3 OK**. Eski `pm2-root` ≈ 9.6
"UNSAFE" idi.

## 10. Yeni app'i izleme tabanına ekle

```bash
/usr/local/sbin/secops-report.sh --accept-baseline
```

Yeni port, yeni unit ve yeni kullanıcı böylece "kabul edilmiş normal" olur;
aksi hâlde günlük rapor her gün aynı yanlış pozitifi üretir ve gerçek bir
değişiklik gürültüde kaybolur.

Denetim kuralı da eklemen gerekiyorsa: `/etc/audit/rules.d/99-secops.rules`
dosyası `-e 2` ile **kilitli** — düzenledikten sonra sunucuyu yeniden başlatman
şart, `auditctl` ile canlıya alınamaz. Bu bilerek böyle.

---

## Hızlı cutover reçetesi

```bash
# 1. ölç: canli surecin komutu, portu, bind adresi, env i
ss -ltnpH "( sport = :<port> )"
tr '\0' '\n' < /proc/<pid>/environ
readlink /proc/<pid>/cwd

# 2. kanonik sir dosyasini dogrula (anahtar + deger farki yok mu)
# 3. unit i yaz, sozdizimini sina
systemd-analyze verify /etc/systemd/system/app-<isim>.service

# 4. devret
systemctl daemon-reload && systemctl enable --now app-<isim>

# 5. dogrula
ss -ltnpH "( sport = :<port> )"          # 127.0.0.1 mi
systemd-analyze security app-<isim>      # < 5.0 mi
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/
journalctl -u app-<isim> -n 30 --no-pager

# 6. DB kullanan app ise GERCEK bir sorgu tetikle — "Ready in 2.6s" DB'ye
#    baglandigini kanitlamaz, Next.js lazy connect yapar.

# 7. uygulama ici sir dosyalarini arsivle + sil, servisi yeniden baslat
```
