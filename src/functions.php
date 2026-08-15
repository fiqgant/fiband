<?php
/**
 * FiBand - shared helper functions.
 *
 * All formatting, timezone conversion, sleep rendering and OpenAI/OpenRouter
 * plumbing lives here so templates stay readable and the front controller thin.
 */

declare(strict_types=1);

/* ---------------------------------------------------------------------------
 * AI: report table + OpenRouter call
 * ------------------------------------------------------------------------ */

/** Creates the ai_report table (and migrates older schemas). */
function ensure_ai_report(PDO $pdo): void {
    $pdo->exec("CREATE TABLE IF NOT EXISTS ai_report (
        id            BIGINT AUTO_INCREMENT PRIMARY KEY,
        ts            DATETIME NOT NULL,
        model         VARCHAR(64),
        days          INT,
        prompt        MEDIUMTEXT,
        report_short  MEDIUMTEXT,
        report        MEDIUMTEXT,
        report_diet   MEDIUMTEXT,
        tokens_in     INT,
        tokens_out    INT,
        INDEX (ts)
    ) CHARACTER SET utf8mb4");
    // migrations for tables created before the new columns were added
    foreach (['report_short' => 'days', 'report_diet' => 'report'] as $colName => $after) {
        if (!$pdo->query("SHOW COLUMNS FROM ai_report LIKE '$colName'")->fetch()) {
            $pdo->exec("ALTER TABLE ai_report ADD COLUMN $colName MEDIUMTEXT AFTER $after");
        }
    }
}

/** Per-day personal notes table (lazily created: works even without collect.py). */
function ensure_day_notes(PDO $pdo): void {
    $pdo->exec("CREATE TABLE IF NOT EXISTS day_notes (
        note_date   DATE NOT NULL PRIMARY KEY,
        note        TEXT,
        updated_at  DATETIME NOT NULL
    ) CHARACTER SET utf8mb4");
}

/**
 * Cleans up the HTML produced by the model before saving/displaying it:
 * strips any Markdown fences, the document wrapper, and unsafe tags/attributes.
 */
function clean_ai_html(string $s): string {
    $s = trim($s);
    $s = preg_replace('/^```[a-zA-Z]*\s*/', '', $s);   // leading ```html
    $s = preg_replace('/\s*```$/', '', $s);            // trailing ```
    if (preg_match('/<body[^>]*>(.*)<\/body>/is', $s, $m)) $s = $m[1];  // keep only the body
    $s = preg_replace('#<(script|style)\b[^>]*>.*?</\1>#is', '', $s);   // strip script/style
    $s = preg_replace('/\son\w+\s*=\s*("[^"]*"|\'[^\']*\')/i', '', $s); // strip inline on*= handlers
    return trim($s);
}

/**
 * Some models (e.g. DeepSeek) insert *literal* newline/tab/CR characters inside JSON
 * string values instead of escaping them (\n, \t, \r): the standard forbids this and
 * json_decode fails. Here we re-escape them, but ONLY while inside a string, leaving
 * the structure untouched. Safe on UTF-8: we only act on ASCII control bytes.
 */
function json_fix_ctrl(string $s): string {
    $out = '';
    $in = false;   // are we inside a JSON string?
    $esc = false;  // was the previous character an escaping backslash?
    $n = strlen($s);
    for ($i = 0; $i < $n; $i++) {
        $ch = $s[$i];
        if ($in) {
            if ($esc)            { $out .= $ch; $esc = false; continue; }
            if ($ch === '\\')    { $out .= $ch; $esc = true;  continue; }
            if ($ch === '"')     { $out .= $ch; $in = false;  continue; }
            if ($ch === "\n")    { $out .= '\\n'; continue; }
            if ($ch === "\r")    { $out .= '\\r'; continue; }
            if ($ch === "\t")    { $out .= '\\t'; continue; }
            $out .= $ch;
        } else {
            if ($ch === '"') $in = true;
            $out .= $ch;
        }
    }
    return $out;
}

/** Calls the OpenRouter chat completion API. */
function openrouter_chat(string $prompt, bool $json = false): array {
    if (OPENROUTER_API_KEY === '') {
        throw new RuntimeException('OPENROUTER_API_KEY missing: add it to the .env file');
    }
    $body = [
        'model'    => OPENROUTER_MODEL,
        'messages' => [['role' => 'user', 'content' => $prompt]],
    ];
    if ($json) $body['response_format'] = ['type' => 'json_object'];
    $payload = json_encode($body);
    $ch = curl_init('https://openrouter.ai/api/v1/chat/completions');
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => $payload,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 300,
        CURLOPT_HTTPHEADER     => [
            'Authorization: Bearer ' . OPENROUTER_API_KEY,
            'Content-Type: application/json',
            'HTTP-Referer: http://127.0.0.1:8080',
            'X-Title: FiBand',
        ],
    ]);
    $resp = curl_exec($ch);
    if ($resp === false) {
        throw new RuntimeException('Network error contacting OpenRouter: ' . curl_error($ch));
    }
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $j = json_decode($resp, true);
    if ($code !== 200) {
        throw new RuntimeException('OpenRouter returned an error: ' . ($j['error']['message'] ?? ('HTTP ' . $code)));
    }
    $content = $j['choices'][0]['message']['content'] ?? '';
    if ($content === '') {
        throw new RuntimeException('Empty response from OpenRouter');
    }
    return [
        'content'    => $content,
        'tokens_in'  => $j['usage']['prompt_tokens'] ?? null,
        'tokens_out' => $j['usage']['completion_tokens'] ?? null,
    ];
}

/* ---------------------------------------------------------------------------
 * Timezone helpers (timestamps are stored in UTC, displayed in the local TZ)
 * ------------------------------------------------------------------------ */

/** UTC timestamp from the DB -> local label (e.g. "H:i" or "d/m H:i"). */
function tlabel(string $ts, bool $long = false): string {
    $d = new DateTime($ts, new DateTimeZone('UTC'));
    $d->setTimezone(new DateTimeZone(FIBAND_TZ));
    return $d->format($long ? 'd/m H:i' : 'H:i');
}

/** UTC timestamp from the DB -> full local date and time. */
function tlocal(string $ts): string {
    $d = new DateTime($ts, new DateTimeZone('UTC'));
    $d->setTimezone(new DateTimeZone(FIBAND_TZ));
    return $d->format('d/m/Y H:i:s');
}

/* ---------------------------------------------------------------------------
 * Dashboard helpers
 * ------------------------------------------------------------------------ */

function card_val(array $latest, string $key, string $suffix = ''): string {
    if (!isset($latest[$key])) return '—';
    $r = $latest[$key];
    if ($key === 'blood_pressure') return intval($r['value']) . '/' . intval($r['value2']);
    return rtrim(rtrim(number_format($r['value'], 1, '.', ''), '0'), '.') . $suffix;
}

/** Display label for the data type (the on-demand metrics are already in English in the DB). */
function tipo_label(?string $t): string {
    return ['heart_rate'=>'Heart Rate', 'blood_pressure'=>'Blood Pressure', 'spo2'=>'SpO2',
            'stress'=>'Stress', 'battery'=>'Battery'][$t] ?? (string)$t;
}

/** Sleep totals per stage (minutes) from a list of segments. */
function sleep_totals(array $segs): array {
    $t = ['light'=>0, 'deep'=>0, 'rem'=>0, 'awake'=>0, 'total'=>0];
    foreach ($segs as $s) { $t[$s['stage']] = ($t[$s['stage']] ?? 0) + (int)$s['minutes']; $t['total'] += (int)$s['minutes']; }
    return $t;
}

/** Minutes -> "Xh YYm". */
function hhmm(int $min): string { return intdiv($min, 60) . 'h ' . str_pad((string)($min % 60), 2, '0', STR_PAD_LEFT) . 'm'; }

/**
 * Sleep panel body (totals + hypnogram + time axis + stats) for a SINGLE night.
 */
function sleep_panel_body(array $segs, ?string $startTs, DateTimeZone $TZL): string {
    $tot = sleep_totals($segs);
    $axisStart = $axisEnd = null; $ticks = [];
    if ($startTs && $tot['total']) {
        $axisStart = new DateTime($startTs, new DateTimeZone('UTC')); $axisStart->setTimezone($TZL);
        $axisEnd = (clone $axisStart)->modify("+{$tot['total']} minutes");
        $s0 = (int)$axisStart->format('U'); $s1 = (int)$axisEnd->format('U'); $span = max(1, $s1 - $s0);
        for ($t = (int)(ceil($s0 / 3600) * 3600); $t < $s1; $t += 3600) {
            $td = (new DateTime("@$t"))->setTimezone($TZL);
            $ticks[] = [round(($t - $s0) / $span * 100, 3), $td->format('H:i')];
        }
    }
    ob_start(); ?>
    <div class="sleep-total"><span class="sleep-big"><?= hhmm($tot['total']) ?></span>
      <?php if ($axisStart): ?><span class="sleeprange"><?= $axisStart->format('H:i') ?> &rarr; <?= $axisEnd->format('H:i') ?></span><?php endif; ?>
    </div>
    <div class="hypno">
      <?php foreach ($segs as $s): $w = $tot['total'] ? round($s['minutes'] * 100 / $tot['total'], 3) : 0; ?>
        <div class="seg seg-<?= htmlspecialchars($s['stage']) ?>" style="width:<?= $w ?>%"
             title="<?= htmlspecialchars($s['stage']) ?> &middot; <?= (int)$s['minutes'] ?> min"></div>
      <?php endforeach; ?>
    </div>
    <?php if ($ticks): ?>
    <div class="hypnoaxis">
      <?php foreach ($ticks as [$pos, $lbl]): ?>
        <span class="tick" style="left:<?= $pos ?>%"><?= htmlspecialchars($lbl) ?></span>
      <?php endforeach; ?>
    </div>
    <?php endif; ?>
    <div class="sleepstats">
      <span><span class="dot" style="background:#dceaff"></span>Light <b><?= hhmm($tot['light']) ?></b></span>
      <span><span class="dot" style="background:#2f6fed"></span>Deep <b><?= hhmm($tot['deep']) ?></b></span>
      <span><span class="dot" style="background:#3f8f5f"></span>REM <b><?= hhmm($tot['rem']) ?></b></span>
      <span><span class="dot" style="background:#c98a1f"></span>Awake <b><?= hhmm($tot['awake']) ?></b></span>
    </div>
    <?php
    return ob_get_clean();
}

/** Formatted value for the unified table. */
function row_value(array $r): string {
    if ($r['tipo'] === 'Steps') {
        $s = intval($r['v1']) . ' steps';
        if ($r['v2'] !== null) $s .= ' · ' . intval($r['v2']) . ' kcal';
        if ($r['v3'] !== null) $s .= ' · ' . intval($r['v3']) . ' m';
        return $s;
    }
    if ($r['tipo'] === 'blood_pressure')
        return intval($r['v1']) . '/' . intval($r['v2']) . ' mmHg';
    $n = rtrim(rtrim(number_format($r['v1'], 1, '.', ''), '0'), '.');
    return $n . ($r['unit'] ? ' ' . $r['unit'] : '');
}

/**
 * arrow + green/red badge: $lowerIsBetter flips which direction counts as "good"
 */
function delta_badge(?float $pct, bool $lowerIsBetter = false): string {
    if ($pct === null) return '';
    $up = $pct > 0.05; $down = $pct < -0.05;
    $arrow = $up ? '&#9650;' : ($down ? '&#9660;' : '&#9644;');
    $good = $lowerIsBetter ? $down : $up;
    $bad  = $lowerIsBetter ? $up : $down;
    $cls = $good ? 'good' : ($bad ? 'bad' : 'flat');
    return '<span class="delta ' . $cls . '">' . $arrow . ' ' . number_format(abs($pct), 1) . '%</span>';
}