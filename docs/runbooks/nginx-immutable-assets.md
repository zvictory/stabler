# nginx — hash'li asset'lere `immutable` cache (7 kiracı)

> **Neden bu dosya var:** bu değişiklik **app deposunun dışında**, `/etc/nginx/conf.d/`
> altında yaşıyor. `deploy_stabler.sh` ona dokunmaz, `bench build` onu geri getirmez.
> Sunucu yeniden kurulur ya da conf'lar elden geçirilirse **sessizce kaybolur** ve
> kimse fark etmez — sadece her sayfa açılışı bir tur daha yavaşlar.
>
> Uygulandı: **2026-08-07**, 7 stabler kiracısının hepsinde.
> Yedekler: `/etc/nginx/conf.d/<conf>.bak-immutable-20260807-104750`.

## Sorun

Bundle yanıtında **hiç `Cache-Control` yok** — yalnız `etag` + `last-modified`.
Tarayıcı her açılışta koşulsuz bir doğrulama isteği atıyor: 304 dönüyor, 0 bayt
geliyor, ama laptop→prod RTT'si ~350 ms olduğu için **tam bir tur harcanıyor**.
Ölçülen: 304 ms'lik boşuna bekleme, her açılışta, her kiracıda.

## Değişiklik

Her kiracının conf'unda, mevcut `location /assets` bloğunun **önüne** bir regex
location. nginx'te regex location prefix location'ı **dosya sırasından bağımsız
olarak** yener, ama okunurluk için yine de üste konuyor:

```nginx
# Hash'li build ciktisi: dosya adi icerik hash'i tasir -> bayat kod riski yok.
# Hash'siz yollar (vendor/, css, gorseller) asagidaki /assets blogundan
# servis edilmeye devam eder; onlara immutable vermek deploy sonrasi bayat
# dosya demek olurdu.
location ~ ^/assets/[^/]+/dist/ {
    try_files $uri =404;
    add_header Cache-Control "public, max-age=31536000, immutable";
}
```

**`expires 1y` YOK — bilerek.** `expires` kendi başına bir `Cache-Control` üretir;
`add_header` ile birlikte kullanılınca yanıtta **iki tane** `Cache-Control` başlığı
çıkar. Emsal prod conf'u (`next.erpstable.com.conf:45`) de `add_header`'ı tek başına
kullanıyor — ona uyuldu.

**Neden yalnız `*/dist/`:** `sites/assets/*/dist` altındaki **127 dosyanın 127'si**
de içerik hash'i taşıyor (ölçüldü 2026-08-07, hash'siz sıfır dosya). Yani bir deploy
sonrası dosya adı değişir, tarayıcı yeni adı ister; bayat kod servis etmek fiziksel
olarak mümkün değil. `/assets/stabler/js/vendor/apexcharts.min.js` gibi **hash'siz**
yollar dokunulmadan eski bloktan servis edilmeye devam eder — onlara `immutable`
vermek "deploy ettim ama kullanıcıda eski dosya duruyor" demek olurdu.

## Uygulama

Script idempotent: blok zaten varsa dosyaya dokunmaz, yalnız gerçekten
değiştirdiklerinin yedeğini alır.

```bash
ssh ice-production 'cat > /root/nginx_immutable.py' < docs/runbooks/nginx_immutable.py
ssh ice-production 'python3 /root/nginx_immutable.py && nginx -t && systemctl reload nginx'
```

`scp` bu sunucuda 255 / "Connection closed" ile düşüyor — yukarıdaki `cat >`
yönlendirmesi çalışan yol.

`reload`, `restart` **değil**: açık bağlantılar kesilmez, hiçbir kiracı blip almaz.

İlk koşunun çıktısı: `degisti (7)`, `atlandi (0)`, `BASARISIZ(0)`.
İkinci koşuda `atlandi (7)` beklenir.

## Doğrulama

```bash
# 1. Hash'li bundle -> immutable GORUNMELI
ssh ice-production 'cd /home/frappe/frappe-bench && for s in $(ls sites | grep "\."); do
  bench --site "$s" list-apps 2>/dev/null | grep -q "^stabler" || continue
  printf "%-28s " "$s"
  curl -skI --resolve "$s:443:173.212.195.32" \
    "https://$s/assets/stabler/dist/js/stabler.bundle.TSCFYWAN.js" \
    | grep -i "^cache-control" || echo "(YOK - HATA)"
done'

# 2. Hash'siz vendor dosyasi -> Cache-Control BOS KALMALI
ssh ice-production 'curl -skI --resolve anjan.erpstable.com:443:173.212.195.32 \
  https://anjan.erpstable.com/assets/stabler/js/vendor/apexcharts.min.js | grep -i "^cache-control"'
# cikti bos olmali

# 3. stabler kiracilarinin hepsi ayakta
ssh ice-production 'cd /home/frappe/frappe-bench && for s in $(ls sites | grep "\."); do
  bench --site "$s" list-apps 2>/dev/null | grep -q "^stabler" || continue
  curl -sko /dev/null -w "%{http_code} $s\n" --resolve "$s:443:173.212.195.32" \
    "https://$s/api/method/ping"; done'
```

**`--resolve` IP'si `127.0.0.1` DEĞİL.** Conf'lar `listen 173.212.195.32:443`
diyor; `127.0.0.1`'e resolve edince istek eşleşmeyen bir default server bloğuna
düşer ve Frappe'nin kendi `cache-control: private,max-age=300,...` başlığıyla
404 döner — bu, değişikliğin çalışmadığı sanılmasına yol açar (2026-08-07'de bir
kere yol açtı).

Tarayıcı tarafı beklenen davranış: **1. yükleme** bir kez 183 ms'lik doğrulama
turu atar (başlıkları tazeler), **2. ve sonraki** yüklemelerde `transferSize: 0`,
`deliveryType: "cache"`, süre 0 ms — **hiç ağ isteği yok**.

## Geri alma

```bash
ssh ice-production 'cd /etc/nginx/conf.d
  for f in *.bak-immutable-20260807-104750; do cp -a "$f" "${f%.bak-immutable-*}"; done
  nginx -t && systemctl reload nginx'
```

## Sunucu yeniden kurulursa

`docs/runbooks/nginx_immutable.py`'yi kopyala ve koş. Script anchor olarak
`location /assets {` satırını arar; conf'lar bu bloğu kaybederse `BASARISIZ`
listesinde raporlar ve dosyaya dokunmaz.
