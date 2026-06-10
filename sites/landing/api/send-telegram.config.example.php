<?php
/**
 * Скопируйте этот файл как send-telegram.config.php и заполните значения.
 * Файл send-telegram.config.php не должен попадать в публичный репозиторий.
 *
 * chat_id — число (например 123456789), НЕ @username.
 * Узнать свой id: бот @userinfobot или @RawDataBot в Telegram.
 * Перед первой отправкой откройте диалог с вашим ботом и нажмите «Старт» (/start).
 */
return [
    'bot_token' => 'YOUR_BOT_TOKEN_FROM_BOTFATHER',
    'chat_id'   => 'YOUR_NUMERIC_TELEGRAM_USER_OR_GROUP_ID',
];
