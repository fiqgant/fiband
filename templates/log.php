<section id="log">
<details class="panel" open>
  <summary><h2>Recent measurements</h2></summary>
  <table>
    <tr><th>When</th><th>Metric</th><th>Value</th></tr>
    <?php foreach ($recent as $r):
        $v = $r['metric'] === 'blood_pressure'
            ? intval($r['value']) . '/' . intval($r['value2'])
            : rtrim(rtrim(number_format($r['value'],1,'.',''),'0'),'.');
    ?>
      <tr><td><?= htmlspecialchars(tlocal($r['ts'])) ?></td><td><?= htmlspecialchars($r['metric']) ?></td>
          <td><?= htmlspecialchars($v) ?> <?= htmlspecialchars($r['unit']) ?></td></tr>
    <?php endforeach; ?>
    <?php if (!$recent): ?><tr><td colspan="3" style="color:var(--mut)">No measurements yet. Press "Quick measure".</td></tr><?php endif; ?>
  </table>
</details>

<details class="panel">
  <summary><h2>All saved data · <?= htmlspecialchars($pl) ?></h2></summary>
  <table>
    <tr><th>When</th><th>Type</th><th>Value</th></tr>
    <?php foreach ($allrows as $r): ?>
      <tr><td><?= htmlspecialchars(tlocal($r['ts'])) ?></td>
          <td><?= htmlspecialchars(tipo_label($r['tipo'])) ?></td>
          <td><?= htmlspecialchars(row_value($r)) ?></td></tr>
    <?php endforeach; ?>
    <?php if (!$allrows): ?><tr><td colspan="3" style="color:var(--mut)">No data in the selected period.</td></tr><?php endif; ?>
  </table>
  <div class="hint"><?= count($allrows) ?> rows in the selected period (max 1000), most recent first. Change the period above to see more days.</div>
</details>
</section>