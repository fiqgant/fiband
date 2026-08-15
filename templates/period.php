<section class="panel period-panel">
  <h2>Period</h2>
  <div class="btns">
    <?php foreach (['today','24h','7d','30d'] as $rk): ?>
      <a class="rbtn<?= $range===$rk ? ' on' : '' ?>" href="?page=<?= htmlspecialchars($page) ?>&range=<?= $rk ?>"><?= $RANGES[$rk] ?></a>
    <?php endforeach; ?>
  </div>
  <form method="get" class="customrange">
    <input type="hidden" name="page" value="<?= htmlspecialchars($page) ?>">
    <input type="hidden" name="range" value="custom">
    <span>Custom:</span>
    <label>From <input type="date" name="from" value="<?= htmlspecialchars($custom_from) ?>"></label>
    <label>To <input type="date" name="to" value="<?= htmlspecialchars($custom_to) ?>"></label>
    <button<?= $range==='custom' ? ' style="background:var(--acc)"' : '' ?>>Apply</button>
  </form>
</section>