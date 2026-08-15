<section id="sleep">
<div class="panel">
  <h2>Sleep<?= $sleepDate ? ' · ' . htmlspecialchars(date('d/m/Y', strtotime($sleepDate))) : '' ?></h2>
  <?php if ($sleepSegs): ?>
    <?= sleep_panel_body($sleepSegs, $sleepStart, $TZL) ?>
  <?php else: ?>
    <div class="hint">No sleep data yet. Wear the band at night, then press "History only".</div>
  <?php endif; ?>
</div>

<?php if ($sleepDays): ?>
<div class="panel">
  <h2>Sleep · day-by-day check <span class="sleeprange"><?= count($sleepDays) ?> nights in period</span></h2>
  <p class="hint">Visual check of the data passed to the AI analysis. A night longer than ~16h, or identical to the previous one, is almost certainly a band reading error (not real sleep).</p>
  <?php $prevSig = null;
    foreach ($sleepDays as $day):
        $tot = sleep_totals($day['segs']);
        $sig = md5(json_encode($day['segs']));
        $dupOfPrev = ($sig === $prevSig);
        $tooLong = $tot['total'] > 16 * 60;
        $prevSig = $sig;
  ?>
    <div class="sleepday<?= ($tooLong || $dupOfPrev) ? ' bad' : '' ?>">
      <h3><?= htmlspecialchars(date('d/m/Y', strtotime($day['date']))) ?>
        <span class="hint" style="font-weight:400"><?= count($day['segs']) ?> segments</span>
        <?php if ($tooLong): ?><span class="flag">⚠ <?= round($tot['total'] / 60, 1) ?>h · impossible</span><?php endif; ?>
        <?php if ($dupOfPrev): ?><span class="flag">⧉ identical to the previous day</span><?php endif; ?>
      </h3>
      <?= sleep_panel_body($day['segs'], $day['start'], $TZL) ?>
    </div>
  <?php endforeach; ?>
</div>
<?php endif; ?>
</section>