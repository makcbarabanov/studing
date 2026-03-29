<?php
/**
 * Принимает JSON POST от анкеты «Творец» и отправляет сообщение в Telegram (Bot API).
 */
declare(strict_types=1);

/**
 * @return int Длина строки в символах (UTF-8), без зависимости от mbstring.
 */
function utf8_len(string $s): int
{
    if (function_exists('mb_strlen')) {
        return (int) mb_strlen($s, 'UTF-8');
    }
    return preg_match_all('/./u', $s, $m) ?: 0;
}

header('Content-Type: application/json; charset=utf-8');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['ok' => false, 'error' => 'Method not allowed'], JSON_UNESCAPED_UNICODE);
    exit;
}

$configPath = __DIR__ . '/send-telegram.config.php';
if (!is_file($configPath)) {
    http_response_code(503);
    echo json_encode(['ok' => false, 'error' => 'Сервер не настроен: отсутствует send-telegram.config.php'], JSON_UNESCAPED_UNICODE);
    exit;
}

/** @var array{bot_token: string, chat_id: string} $config */
$config = require $configPath;
$token = isset($config['bot_token']) ? trim((string) $config['bot_token']) : '';
$chatId = isset($config['chat_id']) ? trim((string) $config['chat_id']) : '';
if ($token === '' || $chatId === '') {
    http_response_code(503);
    echo json_encode(['ok' => false, 'error' => 'Неполная конфигурация бота'], JSON_UNESCAPED_UNICODE);
    exit;
}

$raw = file_get_contents('php://input');
$data = json_decode($raw ?? '', true);
if (!is_array($data)) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => 'Некорректный JSON'], JSON_UNESCAPED_UNICODE);
    exit;
}

$name = isset($data['name']) ? trim((string) $data['name']) : '';
$dream = isset($data['dream']) ? trim((string) $data['dream']) : '';
$contact = isset($data['contact']) ? trim((string) $data['contact']) : '';
$channel = isset($data['channel']) ? trim((string) $data['channel']) : '';

$allowedChannels = ['telegram', 'whatsapp', 'vk', 'email', 'post', 'other'];
if ($name === '' || $dream === '' || $contact === '' || $channel === '' || !in_array($channel, $allowedChannels, true)) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => 'Заполните все поля корректно'], JSON_UNESCAPED_UNICODE);
    exit;
}

if (utf8_len($name) > 120 || utf8_len($dream) > 4000 || utf8_len($contact) > 500) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => 'Слишком длинные данные'], JSON_UNESCAPED_UNICODE);
    exit;
}

$channelLabels = [
    'telegram' => 'Telegram',
    'whatsapp' => 'WhatsApp',
    'vk' => 'VK',
    'email' => 'Email',
    'post' => 'Почта России 🐌',
    'other' => 'Другое',
];
$channelLabel = $channelLabels[$channel] ?? $channel;

$text = "🚀 Новый Творец!\n\n"
    . "Имя: {$name}\n"
    . "Мечта: {$dream}\n"
    . "Контакт: {$contact} (через {$channelLabel})\n\n"
    . 'Действуй, пора воплощать!';

$url = 'https://api.telegram.org/bot' . rawurlencode($token) . '/sendMessage';
$payload = [
    'chat_id' => $chatId,
    'text' => $text,
    'disable_web_page_preview' => true,
];

$body = json_encode($payload, JSON_UNESCAPED_UNICODE);
if ($body === false) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'Ошибка формирования запроса'], JSON_UNESCAPED_UNICODE);
    exit;
}

/**
 * POST JSON в Telegram (сначала cURL, иначе file_get_contents — на части хостингов allow_url_fopen выключен).
 */
function telegram_post_json(string $url, string $jsonBody, int $timeout = 15): ?string
{
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        if ($ch === false) {
            return null;
        }
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $jsonBody,
            CURLOPT_HTTPHEADER => ['Content-Type: application/json; charset=utf-8'],
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => $timeout,
            CURLOPT_CONNECTTIMEOUT => 10,
        ]);
        $out = curl_exec($ch);
        $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        if ($out === false || $code < 200 || $code >= 300) {
            return null;
        }
        return $out;
    }

    $ctx = stream_context_create([
        'http' => [
            'method' => 'POST',
            'header' => "Content-Type: application/json; charset=utf-8\r\n",
            'content' => $jsonBody,
            'timeout' => $timeout,
        ],
    ]);

    $response = @file_get_contents($url, false, $ctx);

    return $response === false ? null : $response;
}

$response = telegram_post_json($url, $body);
if ($response === null) {
    http_response_code(502);
    echo json_encode(['ok' => false, 'error' => 'Не удалось связаться с Telegram (сеть или хостинг блокирует исходящие запросы)'], JSON_UNESCAPED_UNICODE);
    exit;
}

$tg = json_decode($response, true);
if (!is_array($tg) || empty($tg['ok'])) {
    $desc = is_array($tg) && isset($tg['description']) ? (string) $tg['description'] : 'unknown';
    http_response_code(502);
    echo json_encode(['ok' => false, 'error' => 'Telegram: ' . $desc], JSON_UNESCAPED_UNICODE);
    exit;
}

echo json_encode(['ok' => true], JSON_UNESCAPED_UNICODE);
