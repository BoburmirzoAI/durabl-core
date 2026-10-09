/**
 * Umumiy log ko'rsatuvchi.
 *
 * Amalda bu `jobs/JobLogViewer` ning o'zi — alohida nusxa YARATILMAYDI.
 * Komponent dastlab job detali uchun yozilgan, keyin umumiy bo'ldi
 * (executions, admin, DLQ ham shuni ishlatadi), shuning uchun bu yerda
 * faqat umumiy nom ostida qayta eksport qilinadi.
 *
 * Imkoniyatlari: oqim filtri (all/stdout/stderr), matn qidiruvi va
 * ajratish, qator raqamlari, vaqt belgilari, `wrap` almashtirgichi,
 * keyingi xatoga sakrash, avtomatik siljish, nusxalash, yuklab olish,
 * 5000 qatordan oshganda kesish.
 */
export { JobLogViewer as LogViewer } from '@/components/jobs/JobLogViewer'
