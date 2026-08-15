<section id="actions">
<div class="panel">
  <h2>Sync with the band</h2>
  <p class="panel-lead">Wear the band and keep your phone's Bluetooth off. Each sync resumes from the last stored point — no duplicates.</p>
  <div class="syncopts">
    <button class="syncopt" onclick="sync('quick')">
      <span class="syncopt-name">Quick measure</span>
      <span class="syncopt-desc">Heart rate, SpO2, stress + latest history</span>
      <span class="syncopt-time">≈ 1 min</span>
    </button>
    <button class="syncopt" onclick="sync('full')">
      <span class="syncopt-name">Full measure</span>
      <span class="syncopt-desc">Heart rate, SpO2, blood pressure, stress + latest history</span>
      <span class="syncopt-time">≈ 3 min</span>
    </button>
    <button class="syncopt" onclick="sync('history')">
      <span class="syncopt-name">History only</span>
      <span class="syncopt-desc">Download unread on-device history, no live measures</span>
      <span class="syncopt-time">≈ 2 min</span>
    </button>
  </div>
  <div id="status" class="status-box" aria-live="polite"></div>
</div>

<div class="panel">
  <h2>AI analysis</h2>
  <p class="panel-lead">Sends the last year's (365 days) data summary to <?= htmlspecialchars(OPENROUTER_MODEL) ?> via OpenRouter for a health analysis. The report is saved in the database (<code>ai_report</code> table). May take a few seconds — and it's the only feature that sends data off your machine, only when you press it.</p>
  <div class="btns">
    <button onclick="aiAnalyze()">🧠 Analyze with AI</button>
  </div>
  <div id="aistatus" class="status-box" aria-live="polite"></div>
  <?php $lrShort = $lastReport ? ($lastReport['report_short'] ?: $lastReport['report']) : '';
        $lrFull  = $lastReport ? $lastReport['report'] : '';
        $lrDiet  = $lastReport ? ($lastReport['report_diet'] ?? '') : ''; ?>
  <div id="aimeta" class="hint"<?= $lastReport ? '' : ' style="display:none"' ?>><?php if ($lastReport): ?>Last report · <?= htmlspecialchars(tlocal($lastReport['ts'])) ?> · <?= htmlspecialchars($lastReport['model']) ?><?= $lastReport['tokens_out'] ? ' · ' . (int)$lastReport['tokens_out'] . ' tokens' : '' ?><?php endif; ?></div>
  <div id="aireport" class="report"><?= $lrShort ?></div>
  <div class="btns" id="aibtns" style="margin-top:12px;<?= $lastReport ? '' : 'display:none' ?>">
    <button type="button" class="alt" data-label="full analysis" onclick="toggleBox('aifull', this)">View full analysis</button>
    <button type="button" class="alt" data-label="dietary and supplement advice" onclick="toggleBox('aidiet', this)"<?= $lrDiet ? '' : ' style="display:none"' ?>>View dietary and supplement advice</button>
  </div>
  <div id="aifull" class="report" style="display:none"><?= $lrFull ?></div>
  <div id="aidiet" class="report" style="display:none"><?= $lrDiet ?></div>
</div>
</section>