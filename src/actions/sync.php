<?php
/**
 * FiBand - action: ?action=sync
 *
 * Launches collect.py (the Bluetooth collector) with the requested mode and
 * returns its JSON summary. The measurement can take a few minutes.
 */

declare(strict_types=1);

set_time_limit(0);
ini_set('max_execution_time', '0');
ignore_user_abort(true);
header('Content-Type: application/json');

$mode = in_array($_GET['mode'] ?? '', ['quick', 'full', 'history']) ? $_GET['mode'] : 'quick';
$dir = dirname(__DIR__, 2);
$py = $dir . '/.venv/bin/python';
$cmd = 'cd ' . escapeshellarg($dir) . ' && '
     . escapeshellarg($py) . ' collect.py --mode ' . escapeshellarg($mode)
     . ' 2>> ' . escapeshellarg($dir . '/sync.log');
$out = [];
exec($cmd, $out, $code);
$json = trim(end($out) ?: '');
if ($json === '' || $json[0] !== '{') {
    echo json_encode(['ok' => false, 'errors' => ['No response from the collector. See sync.log'], 'raw' => $json]);
} else {
    echo $json;
}
exit;