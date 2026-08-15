<section id="overview" class="cards">
  <div class="card"><div class="lbl">Heart Rate</div><div class="big"><?= card_val($latest,'heart_rate') ?><span class="u"> bpm</span></div></div>
  <div class="card"><div class="lbl">SpO2</div><div class="big"><?= $latestSpo2 !== false ? intval($latestSpo2) : card_val($latest,'spo2') ?><span class="u"> %</span></div></div>
  <div class="card"><div class="lbl">Blood Pressure</div><div class="big"><?= card_val($latest,'blood_pressure') ?><span class="u"> mmHg</span></div></div>
  <div class="card"><div class="lbl">Stress</div><div class="big"><?= $latestStress !== false ? intval($latestStress) : card_val($latest,'stress') ?></div></div>
  <div class="card"><div class="lbl">HRV</div><div class="big"><?= $latestHrv !== false ? intval($latestHrv) : '—' ?><span class="u"> ms</span></div></div>
  <div class="card"><div class="lbl">Sleep</div><div class="big"><?= $sleepPeriodTotal ? intdiv($sleepPeriodTotal,60).'<span class="u">h </span>'.($sleepPeriodTotal%60).'<span class="u">m</span>' : '—' ?></div></div>
  <div class="card"><div class="lbl">Battery</div><div class="big"><?= card_val($latest,'battery') ?><span class="u"> %</span></div></div>
</section>

<div class="sectionlbl">This period vs previous period</div>
<section id="week" class="weekgrid">
  <div class="card">
    <div class="lbl">Resting HR</div>
    <div class="big"><?= $weekly['hr']['min'] !== null ? intval($weekly['hr']['min']) : '—' ?><span class="u"> bpm</span></div>
    <div class="sub">avg <?= $weekly['hr']['avg'] !== null ? round($weekly['hr']['avg']) : '—' ?> bpm</div>
    <?= delta_badge($weekly['hr']['delta_pct'], true) ?>
  </div>
  <div class="card">
    <div class="lbl">Steps / Day</div>
    <div class="big"><?= number_format($weekSteps['daily_avg']) ?></div>
    <div class="sub"><?= number_format($weekSteps['total']) ?> total this period</div>
    <?= delta_badge($weekSteps['delta_pct']) ?>
  </div>
  <div class="card">
    <div class="lbl">Best Day</div>
    <div class="big"><?= $weekSteps['best_day_steps'] ? number_format($weekSteps['best_day_steps']) : '—' ?><span class="u"> steps</span></div>
    <div class="sub"><?= $weekSteps['best_day'] ? (new DateTime($weekSteps['best_day']))->format('d/m') : 'no data yet' ?></div>
  </div>
  <div class="card">
    <div class="lbl">SpO2 Avg</div>
    <div class="big"><?= $weekly['spo2']['avg'] !== null ? round($weekly['spo2']['avg'], 1) : '—' ?><span class="u"> %</span></div>
    <div class="sub">min <?= $weekly['spo2']['min'] !== null ? intval($weekly['spo2']['min']) : '—' ?>%</div>
    <?= delta_badge($weekly['spo2']['delta_pct']) ?>
  </div>
  <div class="card">
    <div class="lbl">Stress Avg</div>
    <div class="big"><?= $weekly['stress']['avg'] !== null ? round($weekly['stress']['avg']) : '—' ?></div>
    <div class="sub">peak <?= $weekly['stress']['max'] !== null ? intval($weekly['stress']['max']) : '—' ?></div>
    <?= delta_badge($weekly['stress']['delta_pct'], true) ?>
  </div>
  <div class="card">
    <div class="lbl">HRV Avg</div>
    <div class="big"><?= $weekly['hrv']['avg'] !== null ? round($weekly['hrv']['avg']) : '—' ?><span class="u"> ms</span></div>
    <div class="sub">range <?= $weekly['hrv']['min'] !== null ? intval($weekly['hrv']['min']) : '—' ?>&ndash;<?= $weekly['hrv']['max'] !== null ? intval($weekly['hrv']['max']) : '—' ?></div>
    <?= delta_badge($weekly['hrv']['delta_pct']) ?>
  </div>
  <div class="card">
    <div class="lbl">Sleep / Night</div>
    <div class="big"><?= $weekSleep['avg_min'] !== null ? hhmm((int)round($weekSleep['avg_min'])) : '—' ?></div>
    <div class="sub">avg this period</div>
    <?= delta_badge($weekSleep['delta_pct']) ?>
  </div>
  <div class="card streak">
    <div class="lbl">Active Streak</div>
    <div class="big"><?= $streak ?><span class="u"> day<?= $streak === 1 ? '' : 's' ?></span></div>
    <div class="sub">consecutive days logged</div>
  </div>
</section>