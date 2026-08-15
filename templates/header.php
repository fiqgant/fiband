<header class="masthead"><div class="wrap masthead-in">
  <div class="brand">
    <h1>FiBand</h1>
  </div>
  <nav class="pagenav">
    <?php $navPages = ['overview'=>'Overview','charts'=>'Charts','sleep'=>'Sleep','diary'=>'Diary','log'=>'Log','actions'=>'Actions'];
          foreach ($navPages as $k => $lbl): ?>
    <a href="?page=<?= $k ?>"<?= $page===$k ? ' class="on"' : '' ?>><?= $lbl ?></a>
    <?php endforeach; ?>
  </nav>
</div></header>

<div class="wrap">

<?php if ($err): ?>
  <div class="err">Database error: <?= htmlspecialchars($err) ?></div>
<?php endif; ?>