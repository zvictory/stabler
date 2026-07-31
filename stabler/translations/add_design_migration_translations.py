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

	# ══ Tender hattı ve dönüşüm hunisi (TenderFunnel) ══════════════════
	"Execution": ("İcra", "Исполнение", "Ijro", "Ижро"),
	"active contracts": ("aktif sözleşme", "активных контрактов", "faol shartnoma", "фаол шартнома"),
	"delivery or collection still running": (
		"teslim veya tahsilat devam ediyor",
		"поставка или сбор ещё идут",
		"yetkazib berish yoki yig'ish davom etmoqda",
		"етказиб бериш ёки йиғиш давом этмоқда",
	),
	"lots": ("lot", "лотов", "lot", "лот"),
	"Conversion funnel": ("Dönüşüm hunisi", "Воронка конверсии", "Konversiya voronkasi", "Конверсия воронкаси"),
	"conversion": ("geçiş", "конверсия", "konversiya", "конверсия"),
	"resolved": ("sonuçlanan", "завершено", "yakunlangan", "якунланган"),
	"Where we lose them": (
		"Nerede kaybediyoruz", "Где мы их теряем",
		"Ularni qayerda yo'qotamiz", "Уларни қаерда йўқотамиз",
	),
	"Reading the funnel": (
		"Huninin okuması", "Чтение воронки",
		"Voronkaning o'qilishi", "Воронканинг ўқилиши",
	),
	"No stage lost a lot in this window.": (
		"Bu pencerede hiçbir aşama lot kaybetmedi.",
		"В этом окне ни один этап не потерял лот.",
		"Bu oynada hech bir bosqich lot yo'qotmadi.",
		"Бу ойнада ҳеч бир босқич лот йўқотмади.",
	),
	"Seen but never decided — the GO/NO-GO queue is where they stalled.": (
		"Görüldü ama karar verilmedi — GO/NO-GO kuyruğunda takıldılar.",
		"Увидели, но не решили — застряли в очереди GO/NO-GO.",
		"Ko'rildi, lekin qaror qilinmadi — GO/NO-GO navbatida qoldi.",
		"Кўрилди, лекин қарор қилинмади — GO/NO-GO навбатида қолди.",
	),
	"Decided but sourcing never started — not one quotation was collected.": (
		"Karar alındı ama sourcing başlamadı — tek teklif bile toplanmadı.",
		"Решение принято, но сорсинг не начался — ни одного предложения.",
		"Qaror qabul qilindi, lekin sourcing boshlanmadi — bitta ham taklif yo'q.",
		"Қарор қабул қилинди, лекин sourcing бошланмади — битта ҳам таклиф йўқ.",
	),
	"Priced but never submitted — the bid window closed on a finished price.": (
		"Fiyatlandı ama gönderilmedi — teklif penceresi bitmiş fiyatın üstüne kapandı.",
		"Цена рассчитана, но заявку не подали — окно закрылось на готовой цене.",
		"Narx hisoblandi, lekin taklif yuborilmadi — oyna tayyor narx ustida yopildi.",
		"Нарх ҳисобланди, лекин таклиф юборилмади — ойна тайёр нарх устида ёпилди.",
	),
	"Submitted and lost — the bid was in, the result went the other way.": (
		"Gönderildi ve kaybedildi — teklif verilmişti, sonuç ters çıktı.",
		"Подали и проиграли — заявка была, результат оказался другим.",
		"Yuborildi va yutqazildi — taklif berilgan edi, natija boshqacha chiqdi.",
		"Юборилди ва ютқазилди — таклиф берилган эди, натижа бошқача чиқди.",
	),
	# ══ Login ekranı ══════════════════════════════════════════════════
	"Sign in": ("Oturum aç", "Вход", "Kirish", "Кириш"),
	"Sign in to your account": (
		"Hesabınıza girin", "Войдите в аккаунт",
		"Hisobingizga kiring", "Ҳисобингизга киринг",
	),
	"Signing in…": ("Giriş yapılıyor…", "Выполняется вход…", "Kirilmoqda…", "Кирилмоқда…"),
	"No account? Ask your system administrator for an invite.": (
		"Hesabınız yoksa sistem yöneticinizden davet isteyin.",
		"Нет аккаунта? Запросите приглашение у системного администратора.",
		"Hisobingiz yo'q bo'lsa, tizim administratoridan taklif so'rang.",
		"Ҳисобингиз йўқ бўлса, тизим администраторидан таклиф сўранг.",
	),
	"Username or Email": (
		"Kullanıcı adı veya e-posta", "Имя пользователя или e-mail",
		"Foydalanuvchi nomi yoki e-pochta", "Фойдаланувчи номи ёки е-почта",
	),
	"Password": ("Şifre", "Пароль", "Parol", "Парол"),
	"name.surname or name@company.uz": (
		"ad.soyad ya da ad@sirket.uz", "имя.фамилия или имя@company.uz",
		"ism.familiya yoki ism@kompaniya.uz", "исм.фамилия ёки исм@компания.uz",
	),
	"enter password": ("şifre girin", "введите пароль", "parolni kiriting", "паролни киритинг"),
	"password entered": ("şifre girildi", "пароль введён", "parol kiritildi", "парол киритилди"),
	"Show password": ("Şifreyi göster", "Показать пароль", "Parolni ko'rsatish", "Паролни кўрсатиш"),
	"Hide password": ("Şifreyi gizle", "Скрыть пароль", "Parolni yashirish", "Паролни яшириш"),
	"Remember me on this device": (
		"Bu cihazda hatırla", "Запомнить на этом устройстве",
		"Bu qurilmada eslab qol", "Бу қурилмада эслаб қол",
	),
	"Please enter both username/email and password.": (
		"Lütfen kullanıcı adı/e-posta ve şifreyi girin.",
		"Введите имя пользователя/e-mail и пароль.",
		"Foydalanuvchi nomi/e-pochta va parolni kiriting.",
		"Фойдаланувчи номи/е-почта ва паролни киритинг.",
	),
	"Invalid username or password.": (
		"Kullanıcı adı veya şifre hatalı.",
		"Неверное имя пользователя или пароль.",
		"Foydalanuvchi nomi yoki parol noto'g'ri.",
		"Фойдаланувчи номи ёки парол нотўғри.",
	),
	# Sol panel — marka metni
	"ERP Platform": ("ERP Platformu", "ERP-платформа", "ERP Platforma", "ERP Платформа"),
	"Sales · Purchasing · Warehouse · Production · Finance": (
		"Satış · Satınalma · Depo · Üretim · Finans",
		"Продажи · Закупки · Склад · Производство · Финансы",
		"Sotuv · Xarid · Ombor · Ishlab chiqarish · Moliya",
		"Сотув · Харид · Омбор · Ишлаб чиқариш · Молия",
	),
	"One business,": ("Tüm işletme,", "Весь бизнес —", "Butun biznes,", "Бутун бизнес,"),
	"one record.": ("tek kayıt.", "одна запись.", "bitta yozuv.", "битта ёзув."),
	"Orders, stock, purchasing, production and accounting run on one data model. Every number on screen has a document behind it.": (
		"Sipariş, stok, satınalma, üretim ve muhasebe tek veri modelinde çalışır. Ekranda gördüğünüz her sayının arkasında bir belge kaydı vardır.",
		"Заказы, склад, закупки, производство и учёт работают на одной модели данных. За каждым числом на экране стоит документ.",
		"Buyurtma, ombor, xarid, ishlab chiqarish va hisob bitta ma'lumot modelida ishlaydi. Ekrandagi har bir raqam ortida hujjat bor.",
		"Буюртма, омбор, харид, ишлаб чиқариш ва ҳисоб битта маълумот моделида ишлайди. Экрандаги ҳар бир рақам ортида ҳужжат бор.",
	),
	"One data model": ("Tek veri modeli", "Одна модель данных", "Bitta ma'lumot modeli", "Битта маълумот модели"),
	"tied to a document": ("belgeye bağlı", "привязано к документу", "hujjatga bog'langan", "ҳужжатга боғланган"),
	"Role-based access": ("Rol bazlı erişim", "Доступ по ролям", "Rol asosidagi kirish", "Рол асосидаги кириш"),
	"permission checked": ("yetki denetimi", "проверка прав", "ruxsat tekshiruvi", "рухсат текшируви"),
	"Audit trail": ("Denetim izi", "Журнал аудита", "Audit izi", "Аудит изи"),
	"every action recorded": ("her işlem kayıtlı", "каждое действие записано", "har amal qayd etilgan", "ҳар амал қайд этилган"),
	"Language": ("Dil", "Язык", "Til", "Тил"),
	# ══ Satış siparişi · satır düzenleyici ═════════════════════════════
	"Measurements": ("Ölçüler", "Размеры", "O'lchamlar", "Ўлчамлар"),
	"computed": ("hesaplandı", "рассчитано", "hisoblandi", "ҳисобланди"),
	"measure unit · fixed": (
		"ölçü birimi · sabit",
		"единица измерения · фиксирована",
		"o'lchov birligi · qat'iy",
		"ўлчов бирлиги · қатъий",
	),
	"Product · stock": ("Ürün · stok", "Товар · склад", "Mahsulot · ombor", "Маҳсулот · омбор"),
	"Unit price": ("Birim fiyat", "Цена за единицу", "Birlik narxi", "Бирлик нархи"),
	"Search a product — code, name or barcode · Enter to add": (
		"Ürün ara — kod, ad veya barkod · eklemek için Enter",
		"Поиск товара — код, название или штрихкод · Enter для добавления",
		"Mahsulot qidirish — kod, nom yoki shtrix-kod · qo'shish uchun Enter",
		"Маҳсулот қидириш — код, ном ёки штрих-код · қўшиш учун Enter",
	),
	"No products match that search": (
		"Bu aramaya uyan ürün yok",
		"Нет товаров по этому запросу",
		"Bu qidiruvga mos mahsulot yo'q",
		"Бу қидирувга мос маҳсулот йўқ",
	),
	"pick a product above": (
		"yukarıdan bir ürün seçin",
		"выберите товар выше",
		"yuqoridan mahsulot tanlang",
		"юқоридан маҳсулот танланг",
	),
	"checking stock…": (
		"stok kontrol ediliyor…",
		"проверка остатка…",
		"ombor tekshirilmoqda…",
		"омбор текширилмоқда…",
	),
	"available": ("uygun", "доступно", "mavjud", "мавжуд"),
	"needs": ("gereken", "нужно", "kerak", "керак"),
	"price": ("fiyat", "цена", "narx", "нарх"),
	"Remove line": ("Satırı kaldır", "Удалить строку", "Qatorni o'chirish", "Қаторни ўчириш"),
	"REMOVE": ("KALDIR", "УДАЛИТЬ", "O'CHIRISH", "ЎЧИРИШ"),
	"Decrease": ("Azalt", "Уменьшить", "Kamaytirish", "Камайтириш"),
	"Increase": ("Artır", "Увеличить", "Ko'paytirish", "Кўпайтириш"),
	"Discount column": ("İskonto sütunu", "Колонка скидки", "Chegirma ustuni", "Чегирма устуни"),
	# ══ Ölçü sütunu tercihi (kiracı bayrağı + form toggle) ═════════════
	"Measurement columns": (
		"Ölçü sütunları", "Колонки размеров", "O'lcham ustunlari", "Ўлчам устунлари",
	),
	"A line on this order is priced by size, so the measurement columns cannot be hidden.": (
		"Bu siparişteki bir kalem ölçüye göre fiyatlanıyor, ölçü sütunları gizlenemez.",
		"Одна из позиций заказа считается по размеру — колонки размеров скрыть нельзя.",
		"Bu buyurtmadagi bir qator o'lchamga qarab narxlanadi, o'lcham ustunlarini yashirib bo'lmaydi.",
		"Бу буюртмадаги бир қатор ўлчамга қараб нархланади, ўлчам устунларини яшириб бўлмайди.",
	),
	"Dimensional Sales Lines": (
		"Ölçülü satış satırları", "Позиции продаж по размеру",
		"O'lchamli sotuv qatorlari", "Ўлчамли сотув қаторлари",
	),
	"Direct Invoicing": (
		"Doğrudan faturalama", "Прямое выставление счетов",
		"To'g'ridan-to'g'ri hisob-faktura", "Тўғридан-тўғри ҳисоб-фактура",
	),
	# ══ Tender CRM · kanban + çekmece ══════════════════════════════════
	"Deal pipeline": ("Anlaşma hattı", "Воронка сделок", "Bitim quvuri", "Битим қувури"),
	"Every card is an ERP deal record": (
		"Her kart bir ERP anlaşma kaydı",
		"Каждая карточка — запись сделки в ERP",
		"Har karta — ERPdagi bitim yozuvi",
		"Ҳар карта — ERPдаги битим ёзуви",
	),
	"Columns are stages; drag a card to move it": (
		"Kolonlar aşamalar; kartı sürükleyerek taşıyın",
		"Колонки — этапы; перетащите карточку, чтобы переместить",
		"Ustunlar — bosqichlar; kartani sudrab ko'chiring",
		"Устунлар — босқичлар; картани судраб кўчиринг",
	),
	"Deal no, buyer, lot…": (
		"Anlaşma no, müşteri, lot…",
		"Номер сделки, покупатель, лот…",
		"Bitim raqami, xaridor, lot…",
		"Битим рақами, харидор, лот…",
	),
	"Pipeline": ("Hat", "Воронка", "Quvur", "Қувур"),
	"open deals": ("açık anlaşma", "открытых сделок", "ochiq bitim", "очиқ битим"),
	"Sourcing policy": ("Tedarik politikası", "Политика закупок", "Xarid siyosati", "Харид сиёсати"),
	"quote set complete": ("teklif seti tam", "комплект предложений собран", "taklif to'plami to'liq", "таклиф тўплами тўлиқ"),
	"at least 5 quotations from 2 countries": (
		"en az 2 ülkeden 5 teklif",
		"минимум 5 предложений из 2 стран",
		"kamida 2 mamlakatdan 5 taklif",
		"камида 2 мамлакатдан 5 таклиф",
	),
	"at risk or expired": ("riskli veya süresi geçmiş", "под риском или просрочено", "xavf ostida yoki muddati o'tgan", "хавф остида ёки муддати ўтган"),
	"bid deadline within 48 hours or already passed": (
		"teklif son tarihi 48 saat içinde veya geçmiş",
		"срок подачи в пределах 48 часов или уже прошёл",
		"taklif muddati 48 soat ichida yoki o'tib ketgan",
		"таклиф муддати 48 соат ичида ёки ўтиб кетган",
	),
	"document set complete": ("belge seti tam", "комплект документов собран", "hujjatlar to'plami to'liq", "ҳужжатлар тўплами тўлиқ"),
	"every required document attached": (
		"gereken her belge eklenmiş",
		"все требуемые документы приложены",
		"barcha zarur hujjatlar biriktirilgan",
		"барча зарур ҳужжатлар бириктирилган",
	),
	"quotes": ("teklif", "предложений", "taklif", "таклиф"),
	"no value yet": ("tutar yok", "суммы пока нет", "summa hali yo'q", "сумма ҳали йўқ"),
	"empty": ("boş", "пусто", "bo'sh", "бўш"),
	"Quote set": ("Teklif seti", "Комплект предложений", "Taklif to'plami", "Таклиф тўплами"),
	"policy met": ("politika sağlandı", "политика соблюдена", "siyosat bajarildi", "сиёсат бажарилди"),
	"below policy": ("politika altı", "ниже политики", "siyosatdan past", "сиёсатдан паст"),
	"Stage progress": ("Aşama ilerlemesi", "Прогресс по этапам", "Bosqich jarayoni", "Босқич жараёни"),
	"Close panel": ("Paneli kapat", "Закрыть панель", "Panelni yopish", "Панелни ёпиш"),
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
