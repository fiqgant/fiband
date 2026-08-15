</div>

<?php if ($page === 'charts'): ?>
<script>
window.FIBAND_DATA = {
  longRange: <?= $longRange ? 'true' : 'false' ?>,
  hrLabels:    <?= json_encode(array_map(fn($r)=>tlabel($r['ts'], $longRange), $hr)) ?>,
  hrVals:      <?= json_encode(array_map(fn($r)=>(int)$r['bpm'], $hr)) ?>,
  stepLabels:  <?= json_encode(array_map(fn($r)=>tlabel($r['ts'], $longRange), $steps)) ?>,
  stepVals:    <?= json_encode(array_map(fn($r)=>(int)$r['steps'], $steps)) ?>,
  stepDayLabels: <?= json_encode(array_map(fn($r)=>date('d/m', strtotime($r['d'])), $stepsByDay)) ?>,
  stepDayVals:   <?= json_encode(array_map(fn($r)=>(int)$r['s'], $stepsByDay)) ?>,
  bpLabels:    <?= json_encode(array_map(fn($r)=>tlabel($r['ts'], $longRange), $series['blood_pressure'])) ?>,
  bpSys:       <?= json_encode(array_map(fn($r)=>(int)$r['value'], $series['blood_pressure'])) ?>,
  bpDia:       <?= json_encode(array_map(fn($r)=>(int)$r['value2'], $series['blood_pressure'])) ?>,
  spo2Labels:  <?= json_encode(array_map(fn($r)=>tlabel($r['ts'], $longRange), $spo2hist)) ?>,
  spo2Vals:    <?= json_encode(array_map(fn($r)=>(int)$r['spo2'], $spo2hist)) ?>,
  stressLabels:<?= json_encode(array_map(fn($r)=>tlabel($r['ts'], $longRange), $stressHist)) ?>,
  stressVals:  <?= json_encode(array_map(fn($r)=>(int)$r['score'], $stressHist)) ?>,
  hrvLabels:   <?= json_encode(array_map(fn($r)=>tlabel($r['ts'], $longRange), $hrv)) ?>,
  hrvVals:     <?= json_encode(array_map(fn($r)=>(int)$r['ms'], $hrv)) ?>
};
</script>
<?php endif; ?>
<script src="assets/js/app.js"></script>
</body>
</html>