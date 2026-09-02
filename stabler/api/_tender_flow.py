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
			# The stamp is kept beside the day count so the worst deal can be
			# handed back to `_tender_sla` for its own verdict — see below.
			entered = deal.get("entered_at")
			buckets[stage].append((sla.days_in_stage(entered, today), entered))

	rows = []
	for stage in WORKING_STAGES:
		waits = buckets[stage]
		measured = [pair for pair in waits if pair[0] is not None]
		limit = sla.sla_for(stage, overrides)
		average = round(sum(days for days, _ in measured) / len(measured), 1) if measured else None
		worst_days, worst_at = max(measured, key=lambda pair: pair[0]) if measured else (None, None)
		rows.append(
			{
				"stage": stage,
				"open": len(waits),
				"unmeasured": len(waits) - len(measured),
				"avg_days": average,
				"worst_days": worst_days,
				# THE AVERAGE CANNOT JUDGE THE WORST DEAL. A step whose average
				# sits inside its threshold can still hold one deal that is past
				# it, and that deal is the whole reason for this screen. The
				# verdict is asked of `_tender_sla` rather than recomputed here:
				# two copies of "the last quarter, floored at one day" drift, and
				# the copy nobody exercises is the one that rots.
				"worst_state": sla.severity(stage, worst_at, today, overrides),
				"worst_over": sla.overdue_by(stage, worst_at, today, overrides),
				"sla_days": limit,
				"sla_source": _sla_source(stage, limit),
				"state": _state(average, limit, len(waits)),
			}
		)
	return rows


def _sla_source(stage: str, limit) -> str:
	"""Where this step's threshold came from: default · tenant · off.

	The screen promises "thresholds come from Stabler Settings, per company",
	and until this key existed nothing told a director whether their company
	had actually chosen the number they were reading.

	WHAT THIS CANNOT SAY. `stage_sla_for` returns the default dict verbatim for
	a company with no settings row, so a tenant who types the built-in number is
	indistinguishable from a tenant who typed nothing. The word returned here is
	therefore a claim about the VALUE ("matches the built-in default"), never
	about who entered it, and the UI wording follows that limit exactly.

	`limit is None` means the company's settings row yielded no positive
	threshold. It is NOT proof that anyone chose that: `stage_sla_for` reads each
	field as `int(getattr(row, f"sla_{stage}_days", 0) or 0)`, so a child table
	that has not migrated yet gives the same 0 as a deliberately cleared field.
	The word is `off` because the EFFECT is identical — a step with no threshold
	can never be late — and the screen's wording says only that.
	"""
	if limit is None:
		return "off"
	return "default" if limit == sla.DEFAULT_STAGE_SLA_DAYS.get(stage) else "tenant"


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
