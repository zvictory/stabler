"""Tasarım göçünün getirdiği yeni dizgeleri beş çeviri dosyasına ekler.

Neden ayrı bir betik: bu csv'ler şu anda BAŞKA bir oturum tarafından
değiştirilmiş durumda (harvest yeniden çalışmış, satır sonları LF'e dönmüş,
~9700 satır fark). Bu yüzden csv'ler benim commit'ime dahil edilemez —
edilirse o oturumun yarım işi de içeri girer. Betik idempotent: var olan
anahtarı atlar, iki kez çalıştırmak zarar vermez. Çeviriler kaybolursa
(checkout, harvest) tekrar çalıştırmak yeterli.
"""

import csv
import io
import pathlib
import sys

# source -> (tr, ru, uz, uzc).  en hedefi = kaynağın kendisi.
# Ekran ekran büyüyor: her taşınan sayfa kendi bloğunu ekliyor.
ROWS = {
	# ══ Operasyon Masası ══════════════════════════════════════════════
	"What should I do today?": (
		"Bugün ne yapmalıyım?",
		"Что мне делать сегодня?",
		"Bugun nima qilishim kerak?",
		"Бугун нима қилишим керак?",
	),
	"Last read": ("Son okuma", "Последнее чтение", "Oxirgi o'qish", "Охирги ўқиш"),
	"Role view": ("Rol görünümü", "Представление роли", "Rol ko'rinishi", "Рол кўриниши"),
	"Failed to load operations desk.": (
		"Operasyon masası yüklenemedi.",
		"Не удалось загрузить операционный стол.",
		"Operatsion stol yuklanmadi.",
		"Операцион стол юкланмади.",
	),
	"Access denied to tender module.": (
		"Tender modülüne erişim yok.",
		"Нет доступа к модулю тендеров.",
		"Tender moduliga ruxsat yo'q.",
		"Тендер модулига рухсат йўқ.",
	),
	"Please select an active company.": (
		"Lütfen aktif bir şirket seçin.",
		"Выберите активную компанию.",
		"Faol kompaniyani tanlang.",
		"Фаол компанияни танланг.",
	),
	"All items in this view are up to date.": (
		"Bu görünümdeki her şey güncel.",
		"Всё в этом представлении актуально.",
		"Bu ko'rinishdagi hamma narsa dolzarb.",
		"Бу кўринишдаги ҳамма нарса долзарб.",
	),
	# ── sayaç şeridi: başlık · alt yazı · kural satırı ──────────────────
	"must close today": (
		"bugün kapanmalı",
		"должно закрыться сегодня",
		"bugun yopilishi kerak",
		"бугун ёпилиши керак",
	),
	"due date is today": (
		"son tarihi bugün olan işler",
		"срок — сегодня",
		"muddati bugun",
		"муддати бугун",
	),
	"past due": ("geciken", "просрочено", "kechikkan", "кечиккан"),
	"due date passed, still open": (
		"son tarih geçti, hâlâ açık",
		"срок прошёл, всё ещё открыто",
		"muddat o'tdi, hali ochiq",
		"муддат ўтди, ҳали очиқ",
	),
	"decision is yours": ("karar sende", "решение за вами", "qaror sizda", "қарор сизда"),
	"approval assigned to you": (
		"onay sana atanmış",
		"утверждение назначено вам",
		"tasdiqlash sizga biriktirilgan",
		"тасдиқлаш сизга бириктирилган",
	),
	"no action from you": (
		"senden aksiyon yok",
		"от вас действий не требуется",
		"sizdan harakat talab qilinmaydi",
		"сиздан ҳаракат талаб қилинмайди",
	),
	"you requested, someone else answers": (
		"sen istedin, başkası cevaplıyor",
		"вы запросили, отвечает другой",
		"siz so'radingiz, boshqasi javob beradi",
		"сиз сўрадингиз, бошқаси жавоб беради",
	),
	# ── bantlar ─────────────────────────────────────────────────────────
	"Today": ("Bugün", "Сегодня", "Bugun", "Бугун"),
	"Soon": ("Yaklaşan", "Скоро", "Yaqinlashayotgan", "Яқинлашаётган"),
	"Watching": ("İzlemede", "Наблюдение", "Kuzatuvda", "Кузатувда"),
	"Next up": ("Sıradaki iş", "Следующее", "Navbatdagi ish", "Навбатдаги иш"),
	"due date passed — act today": (
		"son tarih geçti — bugün müdahale",
		"срок прошёл — действовать сегодня",
		"muddat o'tdi — bugun harakat",
		"муддат ўтди — бугун ҳаракат",
	),
	"within this week": (
		"bu hafta içinde",
		"в течение этой недели",
		"shu hafta ichida",
		"шу ҳафта ичида",
	),
	"no action, awaiting outcome": (
		"aksiyon yok, sonuç bekleniyor",
		"действий нет, ожидается результат",
		"harakat yo'q, natija kutilmoqda",
		"ҳаракат йўқ, натижа кутилмоқда",
	),
	# ── satır içi kısa işaretler (renk tek başına taşımasın diye) ────────
	"OVD": ("GEC", "ПРС", "KCH", "КЧК"),
	"TDY": ("BUG", "СЕГ", "BGN", "БГН"),
	"SOON": ("YAK", "СКР", "YQN", "ЯҚН"),
	"WCH": ("İZL", "НБЛ", "KZT", "КЗТ"),
	"APR": ("ONY", "УТВ", "TSD", "ТСД"),
	"PAST DUE": ("GEÇTİ", "ПРОСРОЧЕНО", "MUDDAT O'TDI", "МУДДАТ ЎТДИ"),
	"TODAY": ("BUGÜN", "СЕГОДНЯ", "BUGUN", "БУГУН"),
	"DUE": ("VADE", "СРОК", "MUDDAT", "МУДДАТ"),
	"unassigned": ("atanmadı", "не назначено", "biriktirilmagan", "бириктирилмаган"),
	# ── yan sütun ───────────────────────────────────────────────────────
	"Waiting for your signature": (
		"İmzanı bekliyor",
		"Ждёт вашей подписи",
		"Imzoyingizni kutmoqda",
		"Имзоингизни кутмоқда",
	),
	"Decisions are waiting on you": (
		"Karar sende bekliyor",
		"Решения ждут вас",
		"Qarorlar sizni kutmoqda",
		"Қарорлар сизни кутмоқда",
	),
	"Nothing moves forward until these are answered.": (
		"Bunlar cevaplanmadan hiçbir şey ilerlemiyor.",
		"Пока на них не ответят, ничего не движется.",
		"Bularga javob berilmaguncha hech narsa oldinga siljimaydi.",
		"Буларга жавоб берилмагунча ҳеч нарса олдинга силжимайди.",
	),
	"Open lots": ("Açık lotlar", "Открытые лоты", "Ochiq lotlar", "Очиқ лотлар"),
	"Bar is relative to the busiest queue": (
		"Çubuk en yoğun kuyruğa göre",
		"Полоса — относительно самой загруженной очереди",
		"Chiziq eng band navbatga nisbatan",
		"Чизиқ энг банд навбатга нисбатан",
	),
	"red = has overdue": (
		"kırmızı = gecikeni var",
		"красный = есть просроченные",
		"qizil = kechikkani bor",
		"қизил = кечиккани бор",
	),
	"Next 7 days": ("Önümüzdeki 7 gün", "Следующие 7 дней", "Keyingi 7 kun", "Кейинги 7 кун"),
	"Bid · delivery · due": (
		"Teklif · teslim · vade",
		"Заявка · поставка · срок",
		"Taklif · yetkazib berish · muddat",
		"Таклиф · етказиб бериш · муддат",
	),

	# ══ Direktör panosu ═══════════════════════════════════════════════
	"Every lot is counted in exactly one stage": (
		"Her lot tek bir aşamada sayılır",
		"Каждый лот считается ровно в одном этапе",
		"Har lot faqat bitta bosqichda sanaladi",
		"Ҳар лот фақат битта босқичда саналади",
	),
	"Numbers are read from ERP records — the rule under each says what it counted": (
		"Sayılar ERP kayıtlarından okunur — altındaki kural ne saydığını söyler",
		"Числа читаются из записей ERP — правило под каждым говорит, что оно посчитало",
		"Raqamlar ERP yozuvlaridan o'qiladi — ostidagi qoida nimani sanaganini aytadi",
		"Рақамлар ERP ёзувларидан ўқилади — остидаги қоида нимани санаганини айтади",
	),
	"lots in the pipeline": ("lot işlemde", "лотов в работе", "lot ishlanmoqda", "лот ишланмоқда"),
	"seen through to awaiting result": (
		"görüldü → sonuç bekleniyor arası tüm lotlar",
		"от «увидели» до «ждём результат»",
		"ko'rildi → natija kutilmoqda oralig'idagi lotlar",
		"кўрилди → натижа кутилмоқда оралиғидаги лотлар",
	),
	"win rate": ("kazanma oranı", "доля побед", "yutuq ulushi", "ютуқ улуши"),
	"won": ("kazanıldı", "выиграно", "yutildi", "ютилди"),
	"lost": ("kaybedildi", "проиграно", "yo'qotildi", "йўқотилди"),
	"needs action today — lands on the desk": (
		"bugün müdahale gerekiyor — masaya düşer",
		"нужно действие сегодня — попадает на стол",
		"bugun harakat kerak — stolga tushadi",
		"бугун ҳаракат керак — столга тушади",
	),
	"contracted": ("sözleşmeli", "законтрактовано", "shartnomaviy", "шартномавий"),
	"sum of every open tender's value": (
		"açık tüm tenderlerin değer toplamı",
		"сумма стоимости всех открытых тендеров",
		"barcha ochiq tenderlar qiymati yig'indisi",
		"барча очиқ тендерлар қиймати йиғиндиси",
	),
	"on revenue": ("ciro üzerinden", "от выручки", "tushumdan", "тушумдан"),
	"average across tenders that have pricing": (
		"fiyatlaması olan tenderlerin ortalaması",
		"среднее по тендерам с расчётом цены",
		"narxi hisoblangan tenderlar o'rtachasi",
		"нархи ҳисобланган тендерлар ўртачаси",
	),
	"net remaining": ("net kalan", "чистый остаток", "sof qoldiq", "соф қолдиқ"),
	"what is still to be collected after landed cost": (
		"landed maliyetten sonra tahsil edilecek tutar",
		"сколько ещё предстоит собрать после landed-затрат",
		"landed xarajatdan keyin yig'iladigan summa",
		"landed харажатдан кейин йиғиладиган сумма",
	),
	"tenders carry unverified history — the number is there but the record behind it is incomplete.": (
		"tenderin geçmişi doğrulanmamış — rakam var ama arkasındaki kayıt eksik.",
		"тендеров с непроверенной историей — число есть, но запись за ним неполная.",
		"tenderning tarixi tasdiqlanmagan — raqam bor, lekin ortidagi yozuv to'liq emas.",
		"тендернинг тарихи тасдиқланмаган — рақам бор, лекин ортидаги ёзув тўлиқ эмас.",
	),
	"Linked ERP documents": (
		"Bağlı ERP belgeleri", "Связанные документы ERP",
		"Bog'langan ERP hujjatlari", "Боғланган ERP ҳужжатлари",
	),
	"Linked directly to ERP records": (
		"Doğrudan ERP kayıtlarına bağlı",
		"Напрямую связано с записями ERP",
		"To'g'ridan-to'g'ri ERP yozuvlariga bog'langan",
		"Тўғридан-тўғри ERP ёзувларига боғланган",
	),
	"tenders": ("tender", "тендеров", "tender", "тендер"),
}

LANGS = {"en": None, "tr": 0, "ru": 1, "uz": 2, "uzc": 3}


def main(root: pathlib.Path) -> int:
	base = root / "stabler" / "translations"
	total = 0
	for lang, idx in LANGS.items():
		path = base / f"{lang}.csv"
		# newline="" ŞART (ve open() ile, çünkü Path.read_text bu argümanı
		# ancak 3.13+ kabul ediyor): varsayılan evrensel satır sonu çevirisi CRLF'i
		# okurken LF'e indiriyor, geri yazarken de öyle bırakıyor. Bu dosyalar
		# .gitattributes gereği CRLF; çeviri yapılırsa 9700 satırlık sahte
		# fark üretiyor. (Bir kez böyle kırıldı.)
		with path.open(encoding="utf-8-sig", newline="") as fh:
			raw = fh.read()
		rows = [r for r in csv.reader(io.StringIO(raw)) if r]
		have = {r[0] for r in rows}
		# Satır sonu stilini dosyadan öğren; üçüncü bir stil eklemeyelim.
		terminator = "\r\n" if "\r\n" in raw else "\n"

		def target(src, vals):
			return src if idx is None else vals[idx]

		# 1) Anahtar var ama hedefi BOŞ — SATIR DÜZEYİNDE yerinde doldur.
		#    Dosyanın tamamını csv.writer ile yeniden yazmak cazip ama
		#    tehlikeli: tırnaklama farkları binlerce satırlık sahte diff
		#    üretir ve bu dosya zaten başka bir oturum tarafından kirletilmiş.
		#    Dolu bir hedefe asla dokunulmuyor — başkasının çevirisini ezmek
		#    sessiz bir kayıptır.
		filled = 0
		lines = raw.splitlines(keepends=True)
		for i, line in enumerate(lines):
			stripped = line.rstrip("\r\n")
			for src in ROWS:
				# yalnız "anahtar," ya da "anahtar" biçimindeki BOŞ hedefler
				if stripped in (src, src + ","):
					buf = io.StringIO(newline="")
					csv.writer(buf, lineterminator="").writerow(
						[src, target(src, ROWS[src])]
					)
					lines[i] = buf.getvalue() + line[len(stripped):]
					filled += 1
					break
		if filled:
			raw = "".join(lines)
			with path.open("w", encoding="utf-8", newline="") as fh:
				fh.write(raw)

		# 2) Anahtar hiç yok — sona ekle.
		added = [(src, target(src, vals))
		         for src, vals in ROWS.items() if src not in have]
		if added:
			buf = io.StringIO(newline="")
			csv.writer(buf, lineterminator=terminator).writerows(added)
			prefix = "" if raw.endswith(("\n", "\r")) else terminator
			with path.open("a", encoding="utf-8", newline="") as fh:
				fh.write(prefix + buf.getvalue())

		if not (added or filled):
			print(f"{lang}: değişiklik yok")
			continue
		print(f"{lang}: {len(added)} eklendi · {filled} boş hedef dolduruldu")
		total += len(added) + filled
	print(f"toplam {total}")
	return 0


if __name__ == "__main__":
	sys.exit(main(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")))
