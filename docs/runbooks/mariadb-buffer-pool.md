# MariaDB — `innodb_buffer_pool_size` 128 MB → 2 GB (22 kiracı)

> **Neden bu dosya var:** bu ayar **app deposunun dışında**,
> `/etc/mysql/mariadb.conf.d/50-server.cnf` içinde yaşıyor. `deploy_stabler.sh` ona
> dokunmaz, `bench build` onu geri getirmez, `bench migrate` görmez. Sunucu yeniden
> kurulur ya da MariaDB paketi conf'u ezerse **sessizce 128 MB'a düşer** ve kimse
> fark etmez — sadece her sorgu diskten okumaya başlar.
>
> Uygulandı: **2026-08-07 12:24 CEST**. Yedek:
> `/root/50-server.cnf.bak-2026-08-07-1221`.

## Sorun

Prod MariaDB **paket varsayılanı olan 128 MB** ile koşuyordu — `50-server.cnf`'de
ayar hiç yazılı değildi, yalnız `#innodb_buffer_pool_size = 8G` diye bir yorum satırı
duruyordu. Buna karşılık sunucudaki toplam InnoDB verisi **3,59 GB** (22 şema; en
büyüğü 1,71 GB).

Ölçülen sonuçlar (değişiklikten önce, 72 saatlik uptime):

| Belirti | Değer |
|---|---|
| Fiziksel okuma oranı | **%3,18** (44,3 M okuma / 1,40 Mrd istek) |
| mariadbd swap'ta | **585 MB** |
| Sistem swap kullanımı | 2,2 GB / 4 GB |

Yani veritabanı, RAM'de tutabileceği sayfaları diskten okuyor ve üstüne kendi
sayfaları swap'a itiliyordu.

## Değişiklik

`/etc/mysql/mariadb.conf.d/50-server.cnf`, `[mariadbd]` bloğunda, yorum satırının
yerine:

```ini
innodb_buffer_pool_size     = 2G
innodb_buffer_pool_size_max = 4G   # dinamik resize tavani (11.4: sadece baslangicta kurulur)
```

**Neden 2G, `8G` değil:** yorum satırındaki 8G, 12 GB'lık bu makinede — üstelik swap
zaten 2,2 GB kullanımdayken — OOM riski demekti. 3,59 GB'lık toplam veri setine karşı
2 GB fazlasıyla yeterli: değişiklikten sonra havuzun **%80'i boş kaldı** (aşağıya bak).

**`innodb_buffer_pool_size_max` neden var — bu sürümün tuzağı:**
MariaDB 11.4'te `innodb_buffer_pool_size` `READ_ONLY=NO` görünür, yani "dinamik,
restart gerekmez" sanılır. **Gerekir.** Dinamik değişimin tavanını
`innodb_buffer_pool_size_max` belirler ve o `READ_ONLY=YES` — yalnız başlangıçta
kurulur. Ayarlanmadığında başlangıçtaki `buffer_pool_size` değerine sabitlenir.

Sonuç: 128 MB ile açılmış bir sunucuda

```sql
SET GLOBAL innodb_buffer_pool_size = 1073741824;
```

**hata vermez**, `Warning 1292 Truncated incorrect innodb_buffer_pool_size value`
diye bir uyarı bırakır ve değer 128 MB'ta kalır. `SHOW WARNINGS` çekilmezse bu
tamamen sessizdir (2026-08-07'de tam olarak böyle oldu).

`size_max = 4G` bu yüzden konuldu: bundan sonra 4 GB'a kadar büyütme **restart'sız**
yapılabilir. Ayrılan 4 GB sanal adres alanıdır; fiziksel bellek yalnız
`buffer_pool_size` kadar commit edilir — restart sonrası ölçülen RSS 271 MB bunu
doğruladı.

## Uygulama

```bash
# 1. Yedek
ssh ice-production 'cp -a /etc/mysql/mariadb.conf.d/50-server.cnf \
  /root/50-server.cnf.bak-$(date +%F-%H%M)'

# 2. Duzenle (yorum satirinin yerine iki satir)
#    50-server.cnf icindeki  #innodb_buffer_pool_size = 8G  satiri degistirilir.

# 3. Config'i restart ETMEDEN dogrula -- mariadbd conf'u ayristirir ve
#    cozulmus degerleri basar. Hatali conf burada yakalanir.
ssh ice-production 'mariadbd --help --verbose 2>/dev/null \
  | grep -E "^innodb-buffer-pool-size(-max)? "'
# beklenen:
#   innodb-buffer-pool-size       2147483648
#   innodb-buffer-pool-size-max   4294967296

# 4. Restart -- BU ADIM 22 KIRACIYI birden keser (olculen: 5 sn)
ssh ice-production 'systemctl restart mariadb'
```

**`bench restart` DEĞİL.** Bu bir MariaDB restart'ı; gunicorn/RQ tarafına
dokunulmaz, Frappe bağlantıları kendiliğinden yeniden kurulur. Ama kesinti
bench-genelinden de geniştir: bu makinedeki **her site** (yalnız stabler
kiracısı değil) etkilenir. Düşük trafik saati tercih edilir.

## Doğrulama

```bash
# 1. Ayar aktif mi
ssh ice-production 'mysql -e "SELECT @@innodb_buffer_pool_size/1024/1024/1024 pool_gb,
                                     @@innodb_buffer_pool_size_max/1024/1024/1024 max_gb;"'
# beklenen: 2.0 / 4.0

# 2. Havuz gercekten kullaniliyor mu + fiziksel okuma orani
ssh ice-production 'mysql -e "SHOW GLOBAL STATUS WHERE Variable_name IN (
  \"Innodb_buffer_pool_pages_total\",\"Innodb_buffer_pool_pages_data\",
  \"Innodb_buffer_pool_pages_free\",\"Innodb_buffer_pool_reads\",
  \"Innodb_buffer_pool_read_requests\");"'
# reads / read_requests  ->  %1'in ALTINDA olmali

# 3. mariadbd swap'tan cikti mi
ssh ice-production 'awk "/^VmRSS|^VmSwap/{print \$1, int(\$2/1024) \" MB\"}" \
  /proc/$(pgrep -x mariadbd)/status'
# VmSwap: 0 MB beklenir

# 4. stabler kiracilarinin hepsi ayakta
ssh ice-production 'cd /home/frappe/frappe-bench && for s in $(ls sites | grep "\."); do
  bench --site "$s" list-apps 2>/dev/null | grep -q "^stabler" || continue
  curl -sko /dev/null -w "%{http_code} $s\n" --resolve "$s:443:127.0.0.1" \
    "https://$s/api/method/ping"; done'
```

2026-08-07'de restart'tan 161 sn sonra ölçülen:

| Ölçüt | Öncesi | Sonrası |
|---|---|---|
| Havuz | 128 MB | 2 076 MB (129 792 sayfa) |
| Kullanılan / boş | %11,6 boş | 361 MB dolu / **1 667 MB boş** |
| Fiziksel okuma oranı | %3,18 | **%0,18** |
| mariadbd swap | 585 MB | **0** |
| Sistem swap | 2 228 MB | 1 656 MB |
| Restart süresi | — | 5 sn |

## Bu değişikliğin **çözmediği** şey

Dürüstlük kaydı — beklenti buydu, ölçüm başka söyledi.

`list_customers_with_balances`'in iki ağır sorgusu (`gl_rows`, `drift_rows`) bu
değişiklikten sonra da yavaş kaldı. Havuz artık %99,8 isabet ediyor, yani **disk
I/O tamamen bitti** — kalan süre CPU'da geçiyor: `tabGL Entry`'de 103–178 bin
index kaydını tarayıp `GROUP BY party` ile toplamak. Bunu buffer pool değil,
**sorgu/index tasarımı** düzeltir → `stabler-a05`.

> **Rakam düzeltmesi (2026-08-07, aynı gün, sonraki ölçüm).** Burada bir ara
> `gl_rows ~1,9 sn` / `drift_rows ~1,0 sn` yazıyordu. Bunlar restart'ın hemen
> ardından, **havuz daha soğukken** alınmıştı. Havuz ısındıktan sonra aynı iki
> sorgu (sorgu önbelleği KAPALI) **~292 ms** ve **~530 ms**; uç noktanın tamamı
> ~1030 ms. Ders: bu dosyadaki her süre için **önbellek modu + soğuk/sıcak**
> durumu birlikte yazılmalı, yoksa sayı bir sonraki okuyucuyu yanıltıyor.
>
> `stabler-a05` bu ölçümlerin üstüne iki bileşik index ekledi
> (`stabler.patches.v77_gl_entry_party_indexes`): uç nokta ~1030 → **~730 ms**
> (%29), index alanı 159 → 185 MB.

Ölçülen ek ayrıntı: sorgudaki 1328 elemanlı `party IN (...)` listesi planı
`party_type_party_index` yerine `party` index'ine kaydırıyor ve 178 543 satır
taratıyor; `IN` kalkınca plan `party_type_party_index`'e dönüp 103 608 satıra
iniyor (~1 100 ms → ~950 ms). Küçük ama gerçek; `IN` listesinin gerçekten
gerekli olup olmadığı `stabler-a05` kapsamında.

## Birlikte gözden geçirilecekler (yapılmadı, karar bekliyor)

| Ayar | Durum | Not |
|---|---|---|
| `query_cache_type = ON`, `size = 16 MB` | **dokunulmadı** | Değişiklikten önce `Qcache_lowmem_prunes` 1,83 M / `Qcache_inserts` 2,34 M = **%78 eviction** — cache sürekli dolup boşalıyor. Standart tavsiye kapatmaktır, ama ölçüm ters yönü gösterdi: cache açıkken uç nokta 18–97 ms, kapalıyken 3 100–3 800 ms. Kapatmadan önce **yük altında** yeniden ölçülmeli. |
| `innodb_io_capacity` = 200 / max 2000 | **dokunulmadı** | Disk SSD (`ROTA=0`); 200 HDD dönemi varsayılanı. Büyüyen havuzun flush hacmi için düşük kalabilir. |
| `innodb_log_file_size` = 96 MB | **dokunulmadı** | Klasik kural redo ≈ havuzun %25–50'si → 2G havuz için 512 MB–1 GB. Bu sürümde `READ_ONLY=NO`, yani restart'sız değiştirilebilir. |
| `tmp_table_size` / `max_heap_table_size` = 16 MB | **dokunulmadı** | `Created_tmp_disk_tables` / `Created_tmp_tables` = **%46** — geçici tabloların neredeyse yarısı diske taşıyor. |

## Geri alma

```bash
ssh ice-production 'cp -a /root/50-server.cnf.bak-2026-08-07-1221 \
    /etc/mysql/mariadb.conf.d/50-server.cnf
  mariadbd --help --verbose >/dev/null 2>&1 && systemctl restart mariadb'
```

## Sunucu yeniden kurulursa

`50-server.cnf`'nin `[mariadbd]` bloğuna yukarıdaki iki satırı ekle ve
MariaDB'yi restart et. Boyutu makinenin RAM'ine göre yeniden seç: bu sunucuda
12 GB RAM / 3,59 GB veri için 2G seçildi. **`size_max`'i baştan `size`'ın iki
katı ver** — yoksa ileride büyütmek yine restart gerektirir ve
`SET GLOBAL` sessizce başarısız olur.
