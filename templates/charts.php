<?php $pl = $RANGES[$range]; ?>
<section id="charts">
<div class="panel">
  <h2>Chart display</h2>
  <div class="btns" id="dataModeToggle">
    <a class="rbtn on" href="#" data-mode="real" onclick="setStatMode(false);return false;">Raw data</a>
    <a class="rbtn" href="#" data-mode="stat" onclick="setStatMode(true);return false;">Statistical data</a>
  </div>
  <div class="hint"><strong>Raw data</strong>: unprocessed sensor samples (also shows any artifacts). <strong>Statistical data</strong>: rolling-median filter that removes isolated sensor spikes/dips. Applies to heart rate, SpO2, stress and HRV.</div>
</div>

<?php $stepsDaily = count($stepsByDay) > 1; ?>
<div class="chartrow2">
  <div class="panel">
    <h2>Heart Rate · <?= htmlspecialchars($pl) ?></h2>
    <canvas id="hrChart" height="130"></canvas>
  </div>
  <div class="panel">
    <h2>Steps · <?= htmlspecialchars($pl) ?><?= $stepsDaily ? ' <span class="sleeprange">daily total</span>' : '' ?></h2>
    <canvas id="stepChart" height="130"></canvas>
  </div>
</div>

<div class="grid2">
  <div class="panel">
    <h2>Blood Pressure · <?= htmlspecialchars($pl) ?></h2>
    <canvas id="bpChart" height="160"></canvas>
  </div>
  <div class="panel">
    <h2>SpO2 · <?= htmlspecialchars($pl) ?></h2>
    <canvas id="spo2Chart" height="160"></canvas>
  </div>
  <div class="panel">
    <h2>Stress · <?= htmlspecialchars($pl) ?></h2>
    <canvas id="stressChart" height="160"></canvas>
  </div>
  <div class="panel">
    <h2>HRV · <?= htmlspecialchars($pl) ?></h2>
    <canvas id="hrvChart" height="160"></canvas>
  </div>
</div>
</section>