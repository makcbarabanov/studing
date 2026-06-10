/**
 * Сохранение анкеты «Творец» с лендинга в Google Таблицу.
 *
 * НАСТРОЙКА (один раз):
 * 1) Создайте таблицу: https://sheets.google.com — в первой строке заголовки:
 *    Дата | Имя | Мечта | Канал | Контакт
 * 2) Скопируйте ID таблицы из URL: https://docs.google.com/spreadsheets/d/ВОТ_ЭТОТ_ID/edit
 * 3) Вставьте ID ниже в SHEET_ID.
 * 4) Расширения → Apps Script → вставьте этот файл → Сохранить.
 * 5) Развернуть → Новое развертывание → тип «Веб-приложение»:
 *    выполнять от моего имени, доступ: «Все» (или «Все, у кого есть ссылка»).
 * 6) Скопируйте URL веб-приложения в index.html → window.ISLAND_GOOGLE_APPS_SCRIPT_URL
 *
 * ОПЦИОНАЛЬНО: задайте FORM_SECRET и тот же текст в window.ISLAND_FORM_SECRET на сайте —
 * тогда посторонние не смогут слать мусор без секрета.
 */
var SHEET_ID = 'ВСТАВЬТЕ_ID_ТАБЛИЦЫ';
/** Пустая строка = проверка отключена */
var FORM_SECRET = '';

/**
 * Браузер открывает веб-приложение через GET — без doGet была бы ошибка «doGet not found».
 * Сама анкета с лендинга шлётся методом POST (doPost).
 */
function doGet() {
  return jsonOut({
    ok: true,
    info: 'Остров: веб-приложение работает. Данные принимает только POST с формы на сайте.',
  });
}

function doPost(e) {
  try {
    if (!e || !e.parameter) {
      return jsonOut({ ok: false, error: 'no data' });
    }
    if (FORM_SECRET && String(e.parameter.secret || '') !== FORM_SECRET) {
      return jsonOut({ ok: false, error: 'forbidden' });
    }
    var name = String(e.parameter.name || '').trim();
    var dream = String(e.parameter.dream || '').trim();
    var contact = String(e.parameter.contact || '').trim();
    var channel = String(e.parameter.channel || '').trim();
    if (!name || !dream || !contact || !channel) {
      return jsonOut({ ok: false, error: 'incomplete' });
    }
    if (SHEET_ID.indexOf('ВСТАВЬТЕ') !== -1) {
      return jsonOut({ ok: false, error: 'SHEET_ID not set in Code.gs' });
    }
    var sheet = SpreadsheetApp.openById(SHEET_ID).getSheets()[0];
    sheet.appendRow([new Date(), name, dream, channel, contact]);
    return jsonOut({ ok: true });
  } catch (err) {
    return jsonOut({ ok: false, error: String(err && err.message ? err.message : err) });
  }
}

function jsonOut(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
