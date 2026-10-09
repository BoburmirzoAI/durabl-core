/**
 * Bir `<path d="...">` ichiga sig'adigan ikonka geometriyalari.
 *
 * Loyihadagi `Icon` yordamchilari bitta `path` satrini qabul qiladi, shuning
 * uchun ko'p qismli ikonka ham BITTA `d` ga yig'iladi (SVG `d` bir nechta
 * sub-path'ni qo'llab-quvvatlaydi).
 */

/**
 * Nusxalash ikonkasi — ikkita to'rtburchak.
 *
 * DIQQAT: ilgari bu yerda faqat orqa varaq (`M5 15V5…`) yozilgan edi, oldingi
 * to'rtburchaksiz. Natijada ikonka kichik "⌐" burchak bo'lib ko'rinardi.
 * Ikkala sub-path ham SHART.
 */
export const ICON_COPY =
  'M11 9h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-7a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2zM5 15V5a2 2 0 0 1 2-2h10'

/** Bajarildi belgisi (nusxalangandan keyin). */
export const ICON_CHECK = 'M5 12l5 5 9-11'

/** Havola / bog'liqlik — correlation ID uchun. */
export const ICON_LINK =
  'M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7'
