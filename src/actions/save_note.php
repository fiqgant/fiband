<?php
/**
 * FiBand - action: ?action=save_note
 *
 * Saves/updates a day's personal note (qualitative context later included in
 * the AI analysis prompt). Receives `date` (YYYY-MM-DD) and `note`.
 * An empty note deletes that day's note.
 */

declare(strict_types=1);

header('Content-Type: application/json');
try {
    $date = (string)($_POST['date'] ?? '');
    $d = DateTime::createFromFormat('Y-m-d', $date);
    if (!$d || $d->format('Y-m-d') !== $date) {
        throw new RuntimeException('Invalid date');
    }
    $note = trim((string)($_POST['note'] ?? ''));
    if (function_exists('mb_substr')) $note = mb_substr($note, 0, 2000);  // cap: don't bloat the prompt
    $pdo = db();
    ensure_day_notes($pdo);
    if ($note === '') {
        $pdo->prepare("DELETE FROM day_notes WHERE note_date=?")->execute([$date]);
    } else {
        $now = (new DateTime('now', new DateTimeZone('UTC')))->format('Y-m-d H:i:s');
        $st = $pdo->prepare("INSERT INTO day_notes (note_date, note, updated_at) VALUES (?,?,?)
                             ON DUPLICATE KEY UPDATE note=VALUES(note), updated_at=VALUES(updated_at)");
        $st->execute([$date, $note, $now]);
    }
    echo json_encode(['ok' => true, 'date' => $date, 'has' => $note !== '', 'note' => $note]);
} catch (Throwable $e) {
    echo json_encode(['ok' => false, 'errors' => [$e->getMessage()]]);
}
exit;