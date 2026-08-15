<?php
/**
 * FiBand — front controller.
 *
 * Every request lands here:
 *   1. loads the shared bootstrap (config + PDO + helpers),
 *   2. dispatches the AJAX actions (sync / save_note / ai_prompt),
 *   3. otherwise resolves the dashboard data and renders ONE page
 *      (?page=overview|charts|sleep|diary|log|actions, default overview).
 *
 * All heavy lifting lives in src/ and templates/: this file stays thin.
 */

declare(strict_types=1);

require __DIR__ . '/src/bootstrap.php';

/* ---------------------------------------------------------------------------
 * AJAX actions (each script replies with JSON and exits).
 * ------------------------------------------------------------------------ */
$action = $_GET['action'] ?? '';
if ($action !== '') {
    $script = __DIR__ . '/src/actions/' . preg_replace('/[^a-z_]/', '', $action) . '.php';
    if (is_file($script)) {
        require $script;
        exit;
    }
    http_response_code(400);
    header('Content-Type: application/json');
    echo json_encode(['ok' => false, 'errors' => ["unknown action: $action"]]);
    exit;
}

/* ---------------------------------------------------------------------------
 * Page render.
 * ------------------------------------------------------------------------ */
$page = preg_replace('/[^a-z]/', '', $_GET['page'] ?? '');   // 'overview' if empty/unknown
if (!in_array($page, ['overview', 'charts', 'sleep', 'diary', 'log', 'actions'], true)) {
    $page = 'overview';
}

$view = dashboard_data();
extract($view, EXTR_SKIP);

require __DIR__ . '/templates/head.php';
require __DIR__ . '/templates/header.php';

switch ($page) {
    case 'charts':  require __DIR__ . '/templates/period.php';   require __DIR__ . '/templates/charts.php';  break;
    case 'sleep':   require __DIR__ . '/templates/period.php';   require __DIR__ . '/templates/sleep.php';   break;
    case 'log':     require __DIR__ . '/templates/period.php';   require __DIR__ . '/templates/log.php';     break;
    case 'diary':   require __DIR__ . '/templates/diary.php';    break;
    case 'actions': require __DIR__ . '/templates/actions.php';  break;
    default:        require __DIR__ . '/templates/period.php';   require __DIR__ . '/templates/overview.php';
}

require __DIR__ . '/templates/footer.php';
