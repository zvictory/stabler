# Hisobot: "Sales by Customer" Outstanding ≠ Customer Center Balance

**Savol:** Report'dagi OUTSTANDING va Customer Center'dagi BALANCE nega bir-biriga
to'g'ri kelmaydi, qaysi biri haqiqiy?

**Qisqa javob:** Customer Center'dagi BALANCE **haqiqiy** qarz. Report'dagi OUTSTANDING
xato (ko'pincha oshirib ko'rsatadi), chunki u butunlay boshqa narsani sanaydi.

---

## 1. Ikki raqam — ikki xil manba

| | Customer Center — BALANCE | Report — OUTSTANDING |
|---|---|---|
| Manba | `tabGL Entry` party balansi | `tabSales Invoice.outstanding_amount` yig'indisi |
| Formula | `SUM(debit − credit)`, `party_type='Customer'`, `is_cancelled=0` | `SUM(outstanding_amount)` |
| Davr | **Butun tarix** (sana filtri yo'q) | Faqat `posting_date BETWEEN from..to` |
| Voucherlar | **Hammasi**: invoice, Payment Entry, Journal Entry, avans, credit note | **Faqat** Sales Invoice |
| Ishora | Belgilangan (+ = mijoz qarzdor, − = biz qarzdormiz) | Doim musbat |
| Valyuta | Hisob valyutasi (`balance_acc`, сўм) + PE drift tuzatmasi | Invoice valyutasi, lekin jadval base'da (`$`) ko'rsatyapti |

Ya'ni bittasi — **mijozning hozirgi real saldosi**, ikkinchisi — **tanlangan davrdagi
to'lanmagan invoyslar yig'indisi**. Bular tabiatan teng bo'lishi shart emas.

## 2. Nega farq bunchalik katta (ANJAN: 2.55 mlrd vs 7.08 mlrd)

Uchta sabab, eng kuchlisidan boshlab:

**(a) Taqsimlanmagan to'lovlar va JE-kreditlar.** ANJAN ledgerida katta Payment Entry'lar
va Journal Entry'lar bor (masalan `ACC-JV-2026-06785` = 122 mln kredit, qator-qator
Payment Entry'lar). Agar to'lov aniq bir invoyaga **biriktirilmagan** bo'lsa (on-account /
avans / JE orqali kredit), invoyning `outstanding_amount` maydoni **kamaymaydi** — lekin GL
party balansi bu kreditni **netlaydi**. Natijada: invoyslar yig'indisi (7.08 mlrd) real
saldodan (2.55 mlrd) yuqori. Ayirma (~4.5 mlrd) — aynan shu taqsimlanmagan kreditlar.

**(b) Sana filtri.** Report faqat `from..to` (01.01–29.06.2026) oralig'idagi invoyslarni
oladi. Bu oraliqdan tashqaridagi eski to'lanmagan invoyslar yoki kreditlar hisobga
olinmaydi — GL balans esa ularni o'z ichiga oladi.

**(c) Faqat invoice.** Mustaqil Journal Entry'lar (debit ham, kredit ham), avanslar, credit
note'lar — bularning hammasi GL balansga ta'sir qiladi, lekin invoice-outstanding
yig'indisiga **umuman kirmaydi**.

## 3. Critique team xulosasi

**Financial Advisor (buxgalteriya to'g'riligi):** Mijozning qarz balansi — bu *ledger* (GL)
identifikatori, invoice-darajadagi maydon emas. `outstanding_amount` faqat to'lov o'sha
invoyaga biriktirilganda yangilanadi; biriktirilmagan kreditlar uни chetlab o'tadi. Shuning
uchun debitorlik qarzini har doim **GL party balansidan** olish kerak. Report'dagi
"Outstanding" buxgalteriya ma'nosida debitorlik qarzi emas — u "ochiq invoyslar nominal
qiymati". Bu raqam bo'yicha undirish/qaror qabul qilish — xato.

**ERP Domain Expert:** ERPNext'da to'g'ri debitorlik manbai — Accounts Receivable / GL party
ledger, `Sales Invoice.outstanding` emas. Stabler'ning Customer Center'i to'g'ri qilgan:
`SUM(debit−credit)` butun tarix bo'yicha + Payment Entry account-currency drift tuzatmasi.
Report esa eski "invoyslar yig'indisi" yondashuvида qolib ketgan.

**Reporting / Data integrity:** Bitta jadvalda **davrga bog'langan** "Sales" bilan
**butun-tarix** "real balance"ni aralashtirish me'yoriy holat (mijoz "shu davrda qancha oldi"
+ "hozir qancha qarzi bor"). Lekin ustun nomi aniq bo'lishi shart: "Outstanding" emas,
**"Balance (joriy)"**. Aks holda foydalanuvchi davrga bog'langan deb o'ylaydi.

**UX:** Ikki ekranda bir mijoz uchun ikki xil raqam ko'rsatish — ishonchni buzadi.
Foydalanuvchi "qaysi birini olay?" deb so'rayapti — bu to'g'ridan-to'g'ri shu chalkashlikning
belgisi. Yagona haqiqat manbai bo'lishi kerak.

## 4. Tavsiya (haqiqiy balans, Customer Center kabi)

`stabler/api/reports.py` → `sales_by_customer`:

1. **OUTSTANDING ustunini GL party balansidan ol** — `Sales Invoice.outstanding_amount`
   yig'indisidan voz kech. `list_customers_with_balances` dagi aynan o'sha kichik so'rovni
   (`SUM(debit−credit)` party=Customer, `is_cancelled=0`, **sanasiz**, + PE drift tuzatmasi)
   LEFT JOIN qilib har mijozning real saldosini chiqar. Bu Customer Center bilan **1:1** mos
   keladi.
2. **"Sales" ustuni davrga bog'langan qoladi** (shu davrdagi `SUM(grand_total)`) — bu
   to'g'ri va foydali. Faqat ustunlar izohida "Sales = davr, Balance = joriy (butun tarix)"
   deb belgila.
3. Ustun nomini **"Outstanding" → "Balance"** (joriy) qilib o'zgartir, chalkashlikni yo'q qil.
4. **Valyuta:** real balansni hisob valyutasida (`balance_acc`, сўм) qaytar va har qatorni
   o'z valyutasida formatla (ReportTable per-row currency tuzatmasi bilan birga) — `$` (base)
   ketadi.
5. **Ishora:** belgilangan saldo (+ qarzdor / − avans). Customer Center'dagi rang mantig'ini
   takrorla.

Natijada report va Customer Center bir xil "haqiqiy balans"ni ko'rsatadi.

## 5. Yon eslatma (alohida, hali deploy bo'lmagan)

Skrinshotlardagi `$` belgisi — oldin tuzatgan ReportTable per-row currency o'zgarishi **hali
prodga chiqmagani** uchun. Bu balans nomuvofiqligi bilan bog'liq emas; deploydan keyin
yo'qoladi. Yuqoridagi (4.4) tavsifi uни butunlay yopadi.

---

**Qaror:** Customer Center'dagi BALANCE — yagona haqiqat manbai. Report'ni o'shaga moslang
(yuqoridagi 4-bo'lim). Tasdiqlasangiz, shu o'zgartirishni bajaraman.
