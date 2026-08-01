"""Süreç akışının adım performansı — saf toplama.

"Nerede takıldık" sorusunun cevabı üç sayıdan çıkıyor: o adımda kaç açık iş
var, ortalama ne kadar beklemişler, ve bu eşiğin neresinde. Üçünü de burada,
Frappe olmadan hesaplıyoruz ki kural site açmadan tüketilerek test edilebilsin.

BİLİNMEYEN, SIFIR DEĞİLDİR
Damgası olmayan anlaşma — v66'dan önce taşınmış her kayıt — beklemesi
ölçülemeyen anlaşmadır. Onu ortalamaya 0 gün olarak katmak, ortalamayı aşağı
çeker ve tıkanmış bir adımı sağlıklı gösterir. O yüzden ortalama YALNIZ
ölçülebilenlerden hesaplanıyor ve kaç tanesinin ölçülemediği ayrıca
raporlanıyor: ekran "3 kayıtta damga yok" diyebilsin, sessizce yuvarlamasın.
"""

from __future__ import annotations

from . import _tender_sla as sla

#: Adım tablosunun sırası. `_funnel.ORDER` iş sırası; sonuçlanmış aşamalar
#: burada yok çünkü tablo BEKLEYEN işi anlatıyor.
WORKING_STAGES = ("seen", "go", "sourcing", "priced", "submitted")


def step_rows(deals, today, overrides=None) -> list[dict]:
	"""Aşama başına satır: açık sayısı, ortalama bekleme, SLA durumu.

	`deals`: {"stage": str, "entered_at": Any} dizisi. Bilinmeyen aşamalar
	yok sayılıyor — tabloya uydurma bir kulvar eklemek yerine.
	"""
	buckets: dict[str, list] = {stage: [] for stage in WORKING_STAGES}
	for deal in deals:
		stage = str(deal.get("stage") or "")
		if stage in buckets:
			buckets[stage].append(sla.days_in_stage(deal.get("entered_at"), today))

	rows = []
	for stage in WORKING_STAGES:
		waits = buckets[stage]
		measured = [w for w in waits if w is not None]
		limit = sla.sla_for(stage, overrides)
		average = round(sum(measured) / len(measured), 1) if measured else None
		rows.append(
			{
				"stage": stage,
				"open": len(waits),
				"unmeasured": len(waits) - len(measured),
				"avg_days": average,
				"worst_days": max(measured) if measured else None,
				"sla_days": limit,
				"state": _state(average, limit, len(waits)),
			}
		)
	return rows


def _state(average, limit, open_count) -> str:
	"""Tasarımın üç durumu: in · edge · out; artı iki dürüstlük durumu.

	`empty` ile `unknown` ayrı: boş bir adımda bekleyen iş YOK, ölçülemeyen bir
	adımda bekleyen iş VAR ama ne kadar beklediğini bilmiyoruz. İkisini tek
	kelimede toplamak, tıkanmış olabilecek bir adımı boş göstermek demek.

	Bilinmeyeni "içinde" saymak da olmaz — ekranın en dürüst olması gereken
	yerinde iyimser bir yalan olurdu.
	"""
	if not open_count:
		return "empty"
	if average is None or limit is None:
		return "unknown"
	if average > limit:
		return "out"
	# Son çeyrek — `_tender_sla.severity` ile aynı taban, aynı sebeple:
	# kısa eşiklerde tam çeyrek sıfır gün eder ve uyarı hiç çıkmaz.
	if average >= limit - max(1, limit // 4):
		return "edge"
	return "in"


def bottleneck(rows) -> str | None:
	"""Bugün tıkanan tek adım — tasarımda kırmızı çerçeveli düğüm.

	Eşiği en çok AŞAN adım; hiçbiri aşmıyorsa None. Oran kullanılıyor, fark
	değil: 30 günlük eşiği 3 gün aşan `submitted` ile 3 günlük eşiği 3 gün aşan
	`priced` aynı değil, ikincisi iki katına çıkmış demektir.
	"""
	worst, worst_ratio = None, 1.0
	for row in rows:
		if row["state"] != "out" or not row["sla_days"]:
			continue
		ratio = row["avg_days"] / row["sla_days"]
		if ratio > worst_ratio:
			worst, worst_ratio = row["stage"], ratio
	return worst
