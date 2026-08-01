"""Tender aşama süreleri — saf eşik ve gecikme matematiği.

Frappe'siz: bir anlaşmanın bir aşamada ne kadar beklediğini ve bunun geç olup
olmadığını söyleyen kural, site olmadan tüketilerek test edilebilsin diye.

NEDEN AŞAMA BAŞINA VE NEDEN HEPSİNE DEĞİL
-----------------------------------------
Süreç akışı ekranının tek işi "nerede takıldık" sorusuna cevap vermek. Bunun
için her aşamanın kendi sabrı olmalı: teklif toplamak (`sourcing`) doğası
gereği haftalar sürer, fiyatlanmış bir teklifi göndermek (`priced`) günler.
Tek bir global eşik ikisini de yanlış ölçer — sourcing'i sürekli kırmızı,
priced'ı hiç kırmızı olmayan hâle getirir.

`won` ve `lost` bilinçli olarak eşiksiz. Sonuçlanmış bir anlaşma beklemiyor;
ona "45 gündür bu aşamada" demek doğru ama ANLAMSIZ, "geç" demek ise yanlış.
Eşiksiz aşama hiçbir zaman gecikmiş sayılmaz.
"""

from __future__ import annotations

from datetime import date, datetime

#: Aşama başına varsayılan sabır, GÜN. Kiracı bunları Stabler Settings'ten
#: değiştirebiliyor; buradakiler hiçbir şey ayarlanmamışken geçerli olan
#: değerler, yani ekran ilk gün de anlamlı çalışsın diye.
#:
#: Sayılar Mikas'ın tender akışından: go/no-go kararı birkaç gün, teklif seti
#: toplamak iki hafta (beş tedarikçi, iki ülke), fiyatlanmış teklifi göndermek
#: birkaç gün, sonucu beklemek bir ay.
DEFAULT_STAGE_SLA_DAYS = {
	"seen": 3,
	"go": 5,
	"sourcing": 14,
	"priced": 3,
	"submitted": 30,
	# Terminal — eşik YOK. Sözlükte hiç bulunmamaları kasıtlı: 0 yazmak
	# "sıfır gün sabır" demek olurdu ve her kazanılan işi gecikmiş gösterirdi.
}


def _as_date(value) -> date | None:
	"""Datetime, date veya ISO metni → date. Çözemediğini None döner."""
	if value is None or value == "":
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	text = str(value).strip()
	if not text:
		return None
	try:
		return datetime.fromisoformat(text.replace(" ", "T")[:19]).date()
	except ValueError:
		return None


def days_in_stage(entered_at, today) -> int | None:
	"""Aşamaya girildiğinden bu yana geçen tam gün.

	    `entered_at` yoksa None — "bilmiyoruz" ile "sıfır gündür" aynı şey değil.
	    Sıfır döndürmek, damgası olmayan her eski anlaşmayı bugün taşınmış gibi
	    gösterirdi ve ekran taptaze bir hat uydururdu.

	Gelecek bir damga (saat kayması, elle düzeltme) negatif değil sıfır sayılır.
	"""
	start = _as_date(entered_at)
	now = _as_date(today)
	if start is None or now is None:
		return None
	return max(0, (now - start).days)


def sla_for(stage: str, overrides: dict | None = None) -> int | None:
	"""Bu aşamanın gün eşiği; eşiksizse None.

	`overrides` kiracının ayarı. 0 ve negatif "eşik yok" demek: yönetici bir
	aşamayı takipten çıkarmak istediğinde alanı boşaltıyor ya da sıfırlıyor,
	ve sıfır sabır her anlaşmayı anında gecikmiş yapardı.
	"""
	value = (overrides or {}).get(stage, DEFAULT_STAGE_SLA_DAYS.get(stage))
	try:
		value = int(value)
	except (TypeError, ValueError):
		return None
	return value if value > 0 else None


def overdue_by(stage: str, entered_at, today, overrides: dict | None = None) -> int:
	"""Eşiği kaç gün AŞTI. Geç değilse ya da ölçülemiyorsa 0.

	Sıfır dönmek "sorun yok" demek; çağıran tarafın ayrıca `days_in_stage`i
	None mu diye sorması gerekiyor, çünkü "geç değil" ile "bilmiyoruz" farklı
	şeyler ve ikisini tek sayıya sıkıştırmak ekranı yalancı yapar.
	"""
	limit = sla_for(stage, overrides)
	if limit is None:
		return 0
	waited = days_in_stage(entered_at, today)
	if waited is None:
		return 0
	return max(0, waited - limit)


def severity(stage: str, entered_at, today, overrides: dict | None = None) -> str:
	"""Katmanın önem dili: crit · today · soon · info.

	Eşik aşıldıysa crit; eşiğin son gününde today; son çeyreğine girildiyse
	soon; kalanı info. Eşiksiz ya da ölçülemeyen her şey info — bilmediğimiz
	bir şeyi uyarıya çevirmek, ekranı gürültüye boğar.
	"""
	limit = sla_for(stage, overrides)
	waited = days_in_stage(entered_at, today)
	if limit is None or waited is None:
		return "info"
	if waited > limit:
		return "crit"
	if waited == limit:
		return "today"
	# Son çeyrek: 14 günlük eşikte 11. günden itibaren. En az 1 gün önce
	# uyarabilmek için tavan değil taban alınıyor.
	if waited >= limit - max(1, limit // 4):
		return "soon"
	return "info"
