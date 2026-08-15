<?php
/**
 * FiBand - configuration.
 *
 * Loads the `.env` file (KEY=VALUE parser, no external dependencies) and
 * exposes the application constants. Variables already present in the
 * environment take precedence over the `.env` file.
 */

declare(strict_types=1);

function load_env(string $path): void {
    if (!is_file($path)) return;
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#' || !str_contains($line, '=')) continue;
        [$k, $v] = explode('=', $line, 2);
        $k = trim($k);
        if (getenv($k) === false) putenv("$k=" . trim($v));
    }
}

load_env(__DIR__ . '/../.env');

define('DB_HOST', getenv('DB_HOST') ?: '127.0.0.1');
define('DB_NAME', getenv('DB_NAME') ?: 'fiband');
define('DB_USER', getenv('DB_USER') ?: 'root');
define('DB_PASS', getenv('DB_PASS') ?: '');
define('OPENROUTER_API_KEY', getenv('OPENROUTER_API_KEY') ?: '');
define('OPENROUTER_MODEL', getenv('OPENROUTER_MODEL') ?: 'deepseek/deepseek-v4-pro');

/* Local timezone used to display/group the data. */
define('FIBAND_TZ', getenv('FIBAND_TZ') ?: 'Asia/Jakarta');