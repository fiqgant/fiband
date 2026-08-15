<?php
/**
 * FiBand - dashboard data loader.
 *
 * Resolves the selected period, loads every series the dashboard templates
 * need, computes the weekly stats (fixed 7-day windows) and the last saved
 * AI report, then returns a single array consumed by the front controller
 * (index.php) via extract(). Pure data: templates contain no queries.
 */

declare(strict_types=1);

/**
 * Stats for one samples table over two explicit windows (current vs previous),
 * returning the delta as a percentage of the previous average.
 *
 * @param string $curFrom  start of the current period (inclusive)
 * @param string $curTo    end of the current period (exclusive unless same)
 * @param string $prevFrom start of the previous period (inclusive)
 * @param string $prevTo   end of the previous period (exclusive)
 */
function period_stat(PDO $pdo, string $table, string $col,
                     string $curFrom, string $curTo, string $prevFrom, string $prevTo): array {
    $q = function (string $from, string $to) use ($pdo, $table, $col): array {
        $st = $pdo->prepare("SELECT AVG($col) a, MIN($col) mn, MAX($col) mx, COUNT(*) c FROM $table WHERE ts >= ? AND ts < ?");
        $st->execute([$from, $to]);
        $r = $st->fetch();
        return ['avg' => $r['a'] !== null ? (float)$r['a'] : null, 'min' => $r['mn'] !== null ? (float)$r['mn'] : null,
                'max' => $r['mx'] !== null ? (float)$r['mx'] : null, 'n' => (int)$r['c']];
    };
    $cur = $q($curFrom, $curTo);
    $prev = $q($prevFrom, $prevTo);
    $delta = ($cur['avg'] !== null && $prev['avg']) ? round((($cur['avg'] - $prev['avg']) / $prev['avg']) * 100, 1) : null;
    return ['avg' => $cur['avg'], 'min' => $cur['min'], 'max' => $cur['max'], 'n' => $cur['n'], 'delta_pct' => $delta];
}

/**
 * Loads everything the dashboard templates need for the current request.
 *
 * @return array<string,mixed> view variables (same names templates expect)
 */
function dashboard_data(): array {
    /* ---------- Selected period ---------- */
    $RANGES = ['today' => 'Today', '24h' => 'Last 24h', '7d' => '7 days', '30d' => '30 days', 'custom' => 'Custom'];
    $range = array_key_exists($_GET['range'] ?? '', $RANGES) ? $_GET['range'] : '24h';
    $TZL = new DateTimeZone(FIBAND_TZ);
    $UTC = new DateTimeZone('UTC');
    $now = new DateTime('now', $UTC);
    $start = null; $end = null;
    switch ($range) {
        case 'today':
            $d = new DateTime('now', $TZL); $d->setTime(0, 0, 0); $d->setTimezone($UTC);
            $start = $d->format('Y-m-d H:i:s'); break;
        case '7d':  $start = (clone $now)->modify('-7 day')->format('Y-m-d H:i:s'); break;
        case '30d': $start = (clone $now)->modify('-30 day')->format('Y-m-d H:i:s'); break;
        case 'custom':
            $f = DateTime::createFromFormat('Y-m-d', $_GET['from'] ?? '', $TZL) ?: new DateTime('now', $TZL);
            $t = DateTime::createFromFormat('Y-m-d', $_GET['to'] ?? '', $TZL) ?: new DateTime('now', $TZL);
            $f->setTime(0, 0, 0); $t->setTime(23, 59, 59);
            $f->setTimezone($UTC); $t->setTimezone($UTC);
            $start = $f->format('Y-m-d H:i:s'); $end = $t->format('Y-m-d H:i:s'); break;
        case '24h': default:
            $start = (clone $now)->modify('-24 hour')->format('Y-m-d H:i:s'); break;
    }
    // SQL condition on the period (values built by us, not from raw input)
    $cond = "ts >= '$start'" . ($end ? " AND ts <= '$end'" : "");
    $longRange = !in_array($range, ['today', '24h']);  // date-included labels for long periods
    $custom_from = $_GET['from'] ?? (new DateTime('now', $TZL))->format('Y-m-d');
    $custom_to   = $_GET['to']   ?? (new DateTime('now', $TZL))->format('Y-m-d');
    $pl = $RANGES[$range];

    /* ---------- Data loading ---------- */
    $err = null;
    $latest = []; $hr = []; $steps = []; $stepsByDay = []; $recent = []; $stressHist = []; $hrv = []; $allrows = [];
    $spo2hist = []; $sleepSegs = []; $sleepDate = null; $sleepStart = null; $sleepDays = []; $sleepPeriodTotal = 0;
    $latestStress = false; $latestHrv = false; $latestSpo2 = false;
    $series = ['spo2' => [], 'blood_pressure' => []];
    $daysWithData = []; $dayNotes = [];   // diary: days with data + personal notes
    try {
        $pdo = db();
        // Local day (FIBAND_TZ) for grouping, falling back to UTC if MySQL's
        // timezone tables aren't loaded.
        $tzOk = $pdo->query("SELECT CONVERT_TZ('2024-06-01 12:00:00','+00:00','" . FIBAND_TZ . "')")->fetchColumn() !== null;
        $LD = $tzOk ? "DATE(CONVERT_TZ(ts,'+00:00','" . FIBAND_TZ . "'))" : "DATE(ts)";
        // latest per metric within the selected period, falling back to the
        // all-time latest when the period has no measurement for that metric
        $q = $pdo->query("SELECT m.metric, m.value, m.value2, m.unit, m.ts
                          FROM measurements m
                          JOIN (SELECT metric, MAX(id) id FROM measurements WHERE $cond GROUP BY metric) x
                            ON m.id = x.id");
        foreach ($q as $r) { $latest[$r['metric']] = $r; }
        $qAll = $pdo->query("SELECT m.metric, m.value, m.value2, m.unit, m.ts
                             FROM measurements m
                             JOIN (SELECT metric, MAX(id) id FROM measurements GROUP BY metric) x
                               ON m.id = x.id");
        foreach ($qAll as $r) { if (!isset($latest[$r['metric']])) $latest[$r['metric']] = $r; }

        foreach ($pdo->query("SELECT ts, bpm FROM hr_samples WHERE $cond ORDER BY ts") as $r) $hr[] = $r;
        foreach ($pdo->query("SELECT ts, steps FROM step_samples WHERE $cond ORDER BY ts") as $r) $steps[] = $r;
        // Steps summed per local day: used by the chart when the period spans multiple days.
        foreach ($pdo->query("SELECT $LD d, SUM(steps) s FROM step_samples WHERE $cond GROUP BY d ORDER BY d") as $r)
            $stepsByDay[] = ['d' => $r['d'], 's' => (int)$r['s']];
        foreach ($pdo->query("SELECT ts, score FROM stress_samples WHERE $cond ORDER BY ts") as $r) $stressHist[] = $r;
        foreach ($pdo->query("SELECT ts, ms FROM hrv_samples WHERE $cond ORDER BY ts") as $r) $hrv[] = $r;
        foreach ($pdo->query("SELECT ts, spo2 FROM spo2_samples WHERE $cond ORDER BY ts") as $r) $spo2hist[] = $r;
        // latest sample of each sensor in the period, falling back to the all-time latest
        $latestVal = function (string $table, string $col) use ($pdo, $cond): mixed {
            $v = $pdo->query("SELECT $col FROM $table WHERE $cond ORDER BY ts DESC LIMIT 1")->fetchColumn();
            if ($v === false) $v = $pdo->query("SELECT $col FROM $table ORDER BY ts DESC LIMIT 1")->fetchColumn();
            return $v;
        };
        $latestStress = $latestVal('stress_samples', 'score');
        $latestHrv    = $latestVal('hrv_samples', 'ms');
        $latestSpo2   = $latestVal('spo2_samples', 'spo2');
        // sleep: latest available day (stages are per-day, not per-period)
        $sleepDate = $pdo->query("SELECT MAX(sleep_date) FROM sleep_segments")->fetchColumn();
        if ($sleepDate) {
            $st = $pdo->prepare("SELECT idx, stage, minutes FROM sleep_segments WHERE sleep_date=? ORDER BY idx");
            $st->execute([$sleepDate]);
            $sleepSegs = $st->fetchAll();
            $ss = $pdo->prepare("SELECT start_ts FROM sleep_sessions WHERE sleep_date=?");
            $ss->execute([$sleepDate]);
            $sleepStart = $ss->fetchColumn() ?: null;
        }
        // sleep: all nights in the selected period, for the day-by-day check.
        // sleep_date is a local date; map the UTC range boundaries to local dates.
        $sleepFrom = (new DateTime($start, $UTC))->setTimezone($TZL)->format('Y-m-d');
        $sleepTo   = (new DateTime($end ?: 'now', $end ? $UTC : $TZL))->setTimezone($TZL)->format('Y-m-d');
        $sleepDays = [];
        $st = $pdo->prepare("SELECT s.sleep_date d, s.idx, s.stage, s.minutes, ss.start_ts
                             FROM sleep_segments s
                             LEFT JOIN sleep_sessions ss ON ss.sleep_date = s.sleep_date
                             WHERE s.sleep_date BETWEEN ? AND ?
                             ORDER BY s.sleep_date, s.idx");
        $st->execute([$sleepFrom, $sleepTo]);
        foreach ($st as $r) {
            $d = $r['d'];
            if (!isset($sleepDays[$d])) $sleepDays[$d] = ['date' => $d, 'start' => $r['start_ts'], 'segs' => []];
            $sleepDays[$d]['segs'][] = ['idx' => $r['idx'], 'stage' => $r['stage'], 'minutes' => $r['minutes']];
            $sleepPeriodTotal += (int)$r['minutes'];
        }
        foreach (array_keys($series) as $metric) {
            $st = $pdo->prepare("SELECT ts, value, value2 FROM measurements
                                 WHERE metric = ? AND $cond ORDER BY ts");
            $st->execute([$metric]);
            $series[$metric] = $st->fetchAll();
        }
        $recent = $pdo->query("SELECT ts, metric, value, value2, unit FROM measurements
                               ORDER BY id DESC LIMIT 30")->fetchAll();
        // single table: all data saved (history + measurements) for the period, most recent first
        $allrows = $pdo->query(
            "SELECT ts, 'Heart Rate' tipo, bpm v1, NULL v2, NULL v3, 'bpm' unit FROM hr_samples WHERE $cond
             UNION ALL SELECT ts, 'Steps', steps, calories, distance, 'steps' FROM step_samples WHERE $cond
             UNION ALL SELECT ts, 'Stress', score, NULL, NULL, '' FROM stress_samples WHERE $cond
             UNION ALL SELECT ts, 'HRV', ms, NULL, NULL, 'ms' FROM hrv_samples WHERE $cond
             UNION ALL SELECT ts, metric, value, value2, NULL, unit FROM measurements WHERE $cond
             ORDER BY ts DESC LIMIT 1000")->fetchAll();

        // ----- Diary: days with at least one data point (last 6 months) + personal notes -----
        // Independent of the period selected above: the diary feeds the AI analysis (6 months).
        // Groups by local day ($LD, defined above) the same way the AI prompt does.
        $noteStartUtc  = (new DateTime('now', $UTC))->modify('-6 month')->format('Y-m-d H:i:s');
        $noteStartDate = (new DateTime('now', $TZL))->modify('-6 month')->format('Y-m-d');
        foreach ([['hr_samples','Heart Rate'], ['step_samples','Steps'], ['stress_samples','Stress'],
                  ['hrv_samples','HRV'], ['spo2_samples','SpO2'], ['measurements','Measurements']] as [$tbl, $lbl]) {
            $st = $pdo->prepare("SELECT DISTINCT $LD d FROM $tbl WHERE ts >= ?");
            $st->execute([$noteStartUtc]);
            foreach ($st as $r) { $daysWithData[$r['d']][] = $lbl; }
        }
        $st = $pdo->prepare("SELECT DISTINCT sleep_date d FROM sleep_segments WHERE sleep_date >= ?");
        $st->execute([$noteStartDate]);
        foreach ($st as $r) { $daysWithData[$r['d']][] = 'Sleep'; }
        krsort($daysWithData);   // most recent days first
        ensure_day_notes($pdo);
        foreach ($pdo->query("SELECT note_date, note FROM day_notes") as $r) { $dayNotes[$r['note_date']] = $r['note']; }
    } catch (Throwable $e) {
        $err = $e->getMessage();
    }

    /* ---------- Period stats (selected period vs the previous period of equal length) ---------- */
    $empty = ['avg' => null, 'min' => null, 'max' => null, 'n' => 0, 'delta_pct' => null];
    $weekly = ['hr' => $empty, 'spo2' => $empty, 'stress' => $empty, 'hrv' => $empty];
    $weekSteps = ['total' => 0, 'daily_avg' => 0, 'best_day' => null, 'best_day_steps' => 0, 'delta_pct' => null];
    $weekSleep = ['avg_min' => null, 'delta_pct' => null];
    $streak = 0;
    if (isset($pdo)) {
        try {
            // previous period: same length as the selected one, ending at its start
            $dur = (($end ? strtotime($end) : time()) - strtotime($start)) ?: 86400;
            $prevStart = date('Y-m-d H:i:s', strtotime($start) - $dur);
            $prevEnd = $start;
            $curEnd = $end ?: (new DateTime('now', $UTC))->format('Y-m-d H:i:s');

            $weekly['hr']     = period_stat($pdo, 'hr_samples', 'bpm', $start, $curEnd, $prevStart, $prevEnd);
            $weekly['spo2']   = period_stat($pdo, 'spo2_samples', 'spo2', $start, $curEnd, $prevStart, $prevEnd);
            $weekly['stress'] = period_stat($pdo, 'stress_samples', 'score', $start, $curEnd, $prevStart, $prevEnd);
            $weekly['hrv']    = period_stat($pdo, 'hrv_samples', 'ms', $start, $curEnd, $prevStart, $prevEnd);

            // steps: sum-based (not avg) — period total, daily average, best day
            $sumSteps = function (string $from, string $to) use ($pdo): int {
                $st = $pdo->prepare("SELECT COALESCE(SUM(steps),0) s FROM step_samples WHERE ts >= ? AND ts < ?");
                $st->execute([$from, $to]);
                return (int)$st->fetchColumn();
            };
            $curSteps = $sumSteps($start, $curEnd);
            $prevSteps = $sumSteps($prevStart, $prevEnd);
            $st = $pdo->prepare("SELECT $LD d, SUM(steps) s FROM step_samples WHERE ts >= ? AND ts < ? GROUP BY d ORDER BY s DESC LIMIT 1");
            $st->execute([$start, $curEnd]); $best = $st->fetch();
            $days = max(1, (int)round($dur / 86400));
            $weekSteps = [
                'total' => $curSteps,
                'daily_avg' => (int)round($curSteps / $days),
                'best_day' => $best ? $best['d'] : null,
                'best_day_steps' => $best ? (int)$best['s'] : 0,
                'delta_pct' => $prevSteps ? round((($curSteps - $prevSteps) / $prevSteps) * 100, 1) : null,
            ];

            // sleep: average minutes/night in the period vs the previous period
            // (sleep_date is a local date; short ranges like 24h still map cleanly)
            $sleepAvg = function (string $from, string $to) use ($pdo): ?float {
                $st = $pdo->prepare("SELECT SUM(minutes) m FROM sleep_segments WHERE sleep_date >= ? AND sleep_date < ? GROUP BY sleep_date");
                $st->execute([$from, $to]);
                $rows = $st->fetchAll(PDO::FETCH_COLUMN);
                return $rows ? array_sum($rows) / count($rows) : null;
            };
            $curFromD  = (new DateTime($start, $UTC))->setTimezone($TZL)->format('Y-m-d');
            $curToD    = (new DateTime($curEnd, $UTC))->setTimezone($TZL)->format('Y-m-d');
            $prevFromD = (new DateTime($prevStart, $UTC))->setTimezone($TZL)->format('Y-m-d');
            $prevToD   = (new DateTime($prevEnd, $UTC))->setTimezone($TZL)->format('Y-m-d');
            $curSleep = $sleepAvg($curFromD, $curToD);
            $prevSleep = $sleepAvg($prevFromD, $prevToD);
            $weekSleep = [
                'avg_min' => $curSleep,
                'delta_pct' => ($curSleep !== null && $prevSleep) ? round((($curSleep - $prevSleep) / $prevSleep) * 100, 1) : null,
            ];

            // active streak: consecutive local days (today backwards) with at least one data point
            $cursor = new DateTime('now', $TZL);
            while (isset($daysWithData[$cursor->format('Y-m-d')])) { $streak++; $cursor->modify('-1 day'); }
        } catch (Throwable $e) { /* period stats stay at defaults */ }
    }

    // last saved AI report (separate try: the table might not exist yet)
    $lastReport = null;
    if (isset($pdo)) {
        try {
            $lastReport = $pdo->query("SELECT ts, model, report_short, report, report_diet, tokens_in, tokens_out
                                       FROM ai_report ORDER BY id DESC LIMIT 1")->fetch();
        } catch (Throwable $e) { /* no report yet */ }
    }

    return [
        'RANGES' => $RANGES, 'range' => $range, 'TZL' => $TZL, 'now' => $now,
        'start' => $start, 'end' => $end, 'cond' => $cond, 'longRange' => $longRange,
        'custom_from' => $custom_from, 'custom_to' => $custom_to, 'pl' => $pl,
        'err' => $err, 'latest' => $latest, 'hr' => $hr, 'steps' => $steps, 'stepsByDay' => $stepsByDay,
        'recent' => $recent, 'stressHist' => $stressHist, 'hrv' => $hrv, 'allrows' => $allrows,
        'spo2hist' => $spo2hist, 'sleepSegs' => $sleepSegs, 'sleepDate' => $sleepDate,
        'sleepStart' => $sleepStart, 'sleepDays' => $sleepDays, 'sleepPeriodTotal' => $sleepPeriodTotal,
        'latestStress' => $latestStress, 'latestHrv' => $latestHrv, 'latestSpo2' => $latestSpo2,
        'series' => $series, 'daysWithData' => $daysWithData, 'dayNotes' => $dayNotes,
        'weekly' => $weekly, 'weekSteps' => $weekSteps, 'weekSleep' => $weekSleep, 'streak' => $streak,
        'lastReport' => $lastReport,
    ];
}