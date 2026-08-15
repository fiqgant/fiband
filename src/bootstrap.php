<?php
/**
 * FiBand - bootstrap.
 *
 * Single entry point that wires up config, database and shared helpers.
 * Included by the front controller (index.php) before anything else.
 */

declare(strict_types=1);

require __DIR__ . '/config.php';
require __DIR__ . '/db.php';
require __DIR__ . '/functions.php';
require __DIR__ . '/dashboard.php';