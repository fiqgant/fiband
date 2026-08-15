<?php
/**
 * FiBand - action: ?action=ai_prompt
 *
 * AI analysis of health trends (last 6 months).
 * Aggregates the last 6 months of health data and builds a two-tier prompt —
 * full detail on the last 7 days + a concise daily recap of the previous
 * months — sends it to OpenRouter and saves the report and prompt in the
 * ai_report table. A copy of the prompt is kept in prompt.txt for debugging.
 */

declare(strict_types=1);

set_time_limit(0);                 // the model's response can take several seconds
ignore_user_abort(true);
header('Content-Type: application/json');
try {
    $pdo = db();
    $root     = dirname(__DIR__, 2);
    $startUtc = (new DateTime('now', new DateTimeZone('UTC')))->modify('-6 month')->format('Y-m-d H:i:s');
    $startDate = (new DateTime('now', new DateTimeZone(FIBAND_TZ)))->modify('-6 month')->format('Y-m-d');

    // Group by local day (FIBAND_TZ) if MySQL's timezone tables are loaded,
    // otherwise fall back to the UTC day.
    $tzOk = $pdo->query("SELECT CONVERT_TZ('2024-06-01 12:00:00','+00:00','" . FIBAND_TZ . "')")->fetchColumn() !== null;
    $LD = $tzOk ? "DATE(CONVERT_TZ(ts,'+00:00','" . FIBAND_TZ . "'))" : "DATE(ts)";

    $days = [];  // 'YYYY-MM-DD' => ['hr'=>..., 'spo2'=>..., 'sleep'=>..., ...]
    $put = function (string $d, string $key, $val) use (&$days) {
        if (!isset($days[$d])) $days[$d] = [];
        $days[$d][$key] = $val;
    };
    $agg = function (string $sql) use ($pdo, $startUtc) {
        $st = $pdo->prepare($sql);
        $st->execute([$startUtc]);
        return $st;
    };

    // Heart rate: daily min/max robust to the 5th/95th percentile, so a single
    // sensor glitch (e.g. one isolated 40 bpm sample) doesn't define the day's
    // extremes. Below 12 samples the day is unreliable → use raw MIN/MAX instead.
    foreach ($agg(
        "SELECT d, ROUND(AVG(bpm)) a,
                ROUND(CASE WHEN COUNT(*) >= 12 THEN MIN(CASE WHEN pr >= 0.05 THEN bpm END) ELSE MIN(bpm) END) mn,
                ROUND(CASE WHEN COUNT(*) >= 12 THEN MAX(CASE WHEN pr <= 0.95 THEN bpm END) ELSE MAX(bpm) END) mx
           FROM (SELECT $LD d, bpm, PERCENT_RANK() OVER (PARTITION BY $LD ORDER BY bpm) pr
                   FROM hr_samples WHERE ts >= ?) s
          GROUP BY d") as $r) $put($r['d'], 'hr', $r);
    // SpO2: reports the minimum (alert value), but robust to the 5th percentile to
    // discard single dips caused by poor sensor contact.
    foreach ($agg(
        "SELECT d, ROUND(AVG(spo2),1) a,
                ROUND(CASE WHEN COUNT(*) >= 12 THEN MIN(CASE WHEN pr >= 0.05 THEN spo2 END) ELSE MIN(spo2) END) mn
           FROM (SELECT $LD d, spo2, PERCENT_RANK() OVER (PARTITION BY $LD ORDER BY spo2) pr
                   FROM spo2_samples WHERE ts >= ?) s
          GROUP BY d") as $r) $put($r['d'], 'spo2', $r);
    // Stress: reports the peak, robust to the 95th percentile to discard single spurious spikes.
    foreach ($agg(
        "SELECT d, ROUND(AVG(score)) a,
                ROUND(CASE WHEN COUNT(*) >= 12 THEN MAX(CASE WHEN pr <= 0.95 THEN score END) ELSE MAX(score) END) mx
           FROM (SELECT $LD d, score, PERCENT_RANK() OVER (PARTITION BY $LD ORDER BY score) pr
                   FROM stress_samples WHERE ts >= ?) s
          GROUP BY d") as $r) $put($r['d'], 'stress', $r);
    foreach ($agg("SELECT $LD d, ROUND(AVG(ms)) a FROM hrv_samples WHERE ts >= ? GROUP BY d") as $r) $put($r['d'], 'hrv', $r);
    foreach ($agg("SELECT $LD d, SUM(steps) steps, SUM(calories) cal, SUM(distance) dist FROM step_samples WHERE ts >= ? GROUP BY d") as $r) $put($r['d'], 'steps', $r);
    foreach ($agg("SELECT $LD d, ROUND(AVG(value)) sys, ROUND(AVG(value2)) dia FROM measurements WHERE metric='blood_pressure' AND ts >= ? GROUP BY d") as $r) $put($r['d'], 'bp', $r);

    // Sleep: sleep_date is already a local date; sum the minutes for each stage.
    $st = $pdo->prepare("SELECT sleep_date d, stage, SUM(minutes) m FROM sleep_segments WHERE sleep_date >= ? GROUP BY sleep_date, stage");
    $st->execute([$startDate]);
    foreach ($st as $r) {
        $d = $r['d'];
        if (!isset($days[$d]['sleep'])) $days[$d]['sleep'] = ['light'=>0,'deep'=>0,'rem'=>0,'awake'=>0,'total'=>0];
        $days[$d]['sleep'][$r['stage']] = (int)$r['m'];
        $days[$d]['sleep']['total'] += (int)$r['m'];
    }
    ksort($days);

    // Personal notes written by the user for individual days (qualitative context).
    ensure_day_notes($pdo);
    $noteSt = $pdo->prepare("SELECT note_date, note FROM day_notes WHERE note_date >= ? ORDER BY note_date");
    $noteSt->execute([$startDate]);
    $userNotes = [];
    foreach ($noteSt as $r) {
        $n = trim(preg_replace('/\s+/u', ' ', (string)$r['note']));   // single line in the prompt
        if ($n !== '') $userNotes[$r['note_date']] = $n;
    }

    // Helpers for the yearly stats and the CSV cells.
    $col = function (string $grp, string $key) use ($days) {
        $out = [];
        foreach ($days as $d) if (isset($d[$grp][$key]) && $d[$grp][$key] !== null) $out[] = (float)$d[$grp][$key];
        return $out;
    };
    $num = fn($v) => $v === null ? '' : rtrim(rtrim(number_format((float)$v, 1, '.', ''), '0'), '.');
    $avg = fn(array $a) => $a ? $num(array_sum($a) / count($a)) : '—';
    $mn  = fn(array $a) => $a ? $num(min($a)) : '—';
    $mx  = fn(array $a) => $a ? $num(max($a)) : '—';
    $sum = fn(array $a) => $a ? $num(array_sum($a)) : '—';
    $g   = function (array $row, string $grp, string $key) use ($num) {
        return isset($row[$grp][$key]) && $row[$grp][$key] !== null ? $num($row[$grp][$key]) : '';
    };

    $first = $days ? array_key_first($days) : '—';
    $last  = $days ? array_key_last($days)  : '—';
    $sleepTotals = $col('sleep', 'total');

    // ----- Prompt construction -----
    $P  = "YOU ARE A DOCTOR AND HEALTH DATA ANALYST.\n\n";
    $P .= "Analyze the health data collected by a fitness band (model H59) for a single user over the last 6 months. Evaluate the data exclusively from a health standpoint.\n\n";
    $P .= "== INSTRUCTIONS ==\n";
    $P .= "1. Summarize the overall health status that emerges from the data.\n";
    $P .= "2. Identify trends over time (improvements or declines) for each metric.\n";
    $P .= "3. Flag anomalous values or potential warning signs (e.g. low SpO2, elevated resting heart rate, declining HRV, insufficient sleep, high blood pressure), distinguishing PERSISTENT anomalies from isolated values that may be sensor artifacts (see DATA QUALITY NOTE).\n";
    $P .= "4. Highlight possible correlations between metrics (e.g. high stress ↔ low HRV ↔ poor sleep).\n";
    $P .= "5. Provide practical, personalized advice to improve these parameters.\n";
    $P .= "6. Clearly indicate when it would be advisable to consult a doctor.\n";
    $P .= "7. Take into account the PERSONAL NOTES written by the user (dedicated section below): use them to interpret the observed values (e.g. physical activity, travel, diet, stress, illness) and to make the analysis and advice more relevant to their real life. Distinguish what is explained by a note (expected) from what remains unexplained (worth investigating).\n";
    $P .= "Respond in English, in a way that is clear and understandable even to a non-expert.\n";
    $P .= "IMPORTANT: this is an informational analysis and does NOT replace medical advice.\n\n";
    $P .= "== RESPONSE FORMAT ==\n";
    $P .= "Respond EXCLUSIVELY with a valid JSON object (no text outside the JSON, no ``` fences), with exactly these three keys:\n";
    $P .= "{\"quick_analysis\": \"...\", \"full_analysis\": \"...\", \"dietary_advice\": \"...\"}\n";
    $P .= "- \"quick_analysis\": a CONCISE summary (max ~120 words) with the 2-4 most important points and any warning signs.\n";
    $P .= "- \"full_analysis\": a detailed analysis covering all 6 points from the instructions above.\n";
    $P .= "- \"dietary_advice\": practical dietary advice and possible supplements, based SPECIFICALLY on this user's data (e.g. HRV, stress, sleep, heart rate, physical activity). For each food/supplement, briefly explain its purpose in relation to the observed data. Remember that supplements should only be taken after consulting a doctor and do not replace a balanced diet.\n";
    $P .= "The value of ALL three keys must be vanilla HTML (no Markdown), using only these tags: <h3>, <h4>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>.\n";
    $P .= "In the full analysis, use <h3> for each section and <table> for numeric comparisons.\n";
    $P .= "Do NOT include inline CSS, style attributes, the tags <html>/<head>/<body>/<style>/<script>, images, or external links.\n";
    $P .= "Escape any quotes inside the HTML as required by the JSON format. All text in English.\n\n";
    $P .= "== METRICS AND UNITS ==\n";
    $P .= "- Heart rate (HR): beats per minute (bpm). Typical resting range 60-100.\n";
    $P .= "- SpO2: blood oxygen saturation (%). Normal >= 95%.\n";
    $P .= "- Stress: index 0-100 (higher = more stress).\n";
    $P .= "- HRV: heart rate variability (ms). Higher = generally better.\n";
    $P .= "- Steps / Calories (kcal) / Distance (m): daily physical activity.\n";
    $P .= "- Sleep: total minutes and breakdown by stage (light, deep, REM, awake).\n";
    $P .= "- Blood pressure (BP): systolic/diastolic (mmHg). Reference ~120/80.\n\n";
    $P .= "== DATA QUALITY NOTE ==\n";
    $P .= "The data comes from a wrist-worn optical sensor (H59) that can occasionally produce ISOLATED erroneous readings (momentary non-physiological dips or spikes). To limit their effect, the daily min/max values reported here are NOT the absolute daily minimum/maximum but the 5th/95th percentile: so hr_min ≈ resting heart rate and hr_max ≈ peak under exertion, already cleaned of individual glitches.\n";
    $P .= "As a result:\n";
    $P .= "- Treat as reliable mainly the PERSISTENT or RECURRING anomalies (over multiple hours or days), not single out-of-range values.\n";
    $P .= "- If a value appears clinically implausible and is not confirmed by context (nearby days, other correlated metrics), treat it as a likely sensor artifact and flag it as such, without asserting it as certain or raising an alarm based on it alone.\n\n";
    $P .= "== PERIOD SUMMARY ==\n";
    $P .= "Range: from $first to $last — " . count($days) . " days with data.\n";
    $P .= "Heart rate: average {$avg($col('hr','a'))} bpm (daily min {$mn($col('hr','mn'))}, peak {$mx($col('hr','mx'))}).\n";
    $P .= "SpO2: average {$avg($col('spo2','a'))}% (minimum {$mn($col('spo2','mn'))}%).\n";
    $P .= "Stress: average {$avg($col('stress','a'))} (peak {$mx($col('stress','mx'))}).\n";
    $P .= "HRV: average {$avg($col('hrv','a'))} ms.\n";
    $P .= "Steps: total {$sum($col('steps','steps'))}, average {$avg($col('steps','steps'))}/day.\n";
    $P .= "Blood pressure: average {$avg($col('bp','sys'))}/{$avg($col('bp','dia'))} mmHg.\n";
    $sleepAvgMin = $sleepTotals ? array_sum($sleepTotals) / count($sleepTotals) : null;
    $P .= "Sleep: average " . ($sleepAvgMin !== null ? round($sleepAvgMin / 60, 1) . "h" : "—") . " per night (" . count($sleepTotals) . " nights recorded).\n\n";
    // Daily data on TWO levels: full detail on the last 7 days (for actionable
    // advice) and a concise recap of the previous months (for trends). The
    // recent 7 days are EXCLUDED from the recap to avoid duplicating the same days.
    $cut7   = (new DateTime('now', new DateTimeZone(FIBAND_TZ)))->modify('-7 day')->format('Y-m-d');
    $recent = array_filter($days, fn($d) => $d >  $cut7, ARRAY_FILTER_USE_KEY);
    $older  = array_filter($days, fn($d) => $d <= $cut7, ARRAY_FILTER_USE_KEY);

    $P .= "The daily data is on TWO levels: the LAST 7 DAYS in full detail (use these for actionable advice) and the PREVIOUS MONTHS as a concise recap (use this for long-term trends). The recent 7 days are NOT repeated in the recap.\n\n";

    $P .= "== LAST 7 DAYS (detail, CSV) ==\n";
    $P .= "date,hr_avg,hr_min,hr_max,spo2_avg,spo2_min,stress_avg,stress_max,hrv_avg,steps,kcal,dist_m,sleep_tot_min,sleep_light,sleep_deep,sleep_rem,sleep_awake,bp_sys,bp_dia\n";
    foreach ($recent as $d => $row) {
        $sl = $row['sleep'] ?? null;
        $P .= implode(',', [
            $d,
            $g($row,'hr','a'), $g($row,'hr','mn'), $g($row,'hr','mx'),
            $g($row,'spo2','a'), $g($row,'spo2','mn'),
            $g($row,'stress','a'), $g($row,'stress','mx'),
            $g($row,'hrv','a'),
            $g($row,'steps','steps'), $g($row,'steps','cal'), $g($row,'steps','dist'),
            $sl ? $sl['total'] : '', $sl ? $sl['light'] : '', $sl ? $sl['deep'] : '', $sl ? $sl['rem'] : '', $sl ? $sl['awake'] : '',
            $g($row,'bp','sys'), $g($row,'bp','dia'),
        ]) . "\n";
    }
    if (!$recent) $P .= "(no data in the last 7 days)\n";

    $P .= "\n== PREVIOUS MONTHS (daily recap, CSV) ==\n";
    $P .= "date,hr_avg,hr_min,hr_max,spo2_avg,spo2_min,stress_avg,hrv_avg,steps,sleep_tot_min\n";
    foreach ($older as $d => $row) {
        $sl = $row['sleep'] ?? null;
        $P .= implode(',', [
            $d,
            $g($row,'hr','a'), $g($row,'hr','mn'), $g($row,'hr','mx'),
            $g($row,'spo2','a'), $g($row,'spo2','mn'),
            $g($row,'stress','a'),
            $g($row,'hrv','a'),
            $g($row,'steps','steps'),
            $sl ? $sl['total'] : '',
        ]) . "\n";
    }
    if (!$older) $P .= "(no data in the previous months)\n";

    $P .= "\n== USER'S PERSONAL NOTES (qualitative context) ==\n";
    $P .= "Notes written by the user to explain what happened on certain days or time windows (physical activity, events, travel, diet, illness...). These are NOT clinical data but real-world context: use them to interpret the numbers and personalize advice and flags (e.g. many steps and a high heart rate on a day noted \"run\" are expected; poor sleep noted \"travel\" is not a warning sign). Format: one line per day, \"date: note\".\n";
    if ($userNotes) {
        foreach ($userNotes as $d => $n) $P .= "$d: $n\n";
    } else {
        $P .= "(no notes entered by the user)\n";
    }

    $P .= "== END OF DATA ==\n\nNow proceed with the health analysis following the instructions above.\n";

    @file_put_contents($root . '/prompt.txt', $P);   // debug copy of the sent prompt

    // Call to the model: expects a JSON with quick_analysis + full_analysis.
    $ai = openrouter_chat($P, true);
    $content = preg_replace('/^```[a-zA-Z]*\s*/', '', trim($ai['content']));
    $content = preg_replace('/\s*```$/', '', $content);
    $parsed = json_decode($content, true);
    if (!is_array($parsed)) {                          // second attempt: re-escape literal control characters
        $parsed = json_decode(json_fix_ctrl($content), true);
    }
    if (is_array($parsed) && isset($parsed['quick_analysis'], $parsed['full_analysis'])) {
        $short = clean_ai_html((string)$parsed['quick_analysis']);
        $full  = clean_ai_html((string)$parsed['full_analysis']);
        $diet  = clean_ai_html((string)($parsed['dietary_advice'] ?? ''));
    } else {
        // fallback: the model did not return the expected JSON
        $full  = clean_ai_html($content);
        $short = $full;
        $diet  = '';
    }

    ensure_ai_report($pdo);
    $st = $pdo->prepare("INSERT INTO ai_report (ts, model, days, prompt, report_short, report, report_diet, tokens_in, tokens_out)
                         VALUES (?,?,?,?,?,?,?,?,?)");
    $st->execute([
        (new DateTime('now', new DateTimeZone('UTC')))->format('Y-m-d H:i:s'),
        OPENROUTER_MODEL, count($days), $P, $short, $full, $diet, $ai['tokens_in'], $ai['tokens_out'],
    ]);
    echo json_encode([
        'ok'         => true,
        'id'         => (int)$pdo->lastInsertId(),
        'model'      => OPENROUTER_MODEL,
        'days'       => count($days),
        'tokens_in'  => $ai['tokens_in'],
        'tokens_out' => $ai['tokens_out'],
        'short'      => $short,
        'full'       => $full,
        'diet'       => $diet,
    ]);
} catch (Throwable $e) {
    echo json_encode(['ok' => false, 'errors' => [$e->getMessage()]]);
}
exit;