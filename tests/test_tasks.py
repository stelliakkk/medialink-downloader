from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from medialink.models import Output, Source
from medialink.tasks import Request, SavedMedia, State, TaskStore


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.db = self.folder / "tasks.sqlite3"
        self.store = TaskStore(self.db)
        self.addCleanup(self.store.close)
        self.request = Request("BV1eknB6DE37", 1, "测试", "上集", 80, Output.BOTH, self.folder)

    def test_fifo_and_batch_deduplication(self):
        second = replace(self.request, page=2)
        result = self.store.enqueue([self.request, self.request, second])
        self.assertEqual((result.added, result.duplicates), (2, 1))
        first = self.store.claim()
        self.assertEqual(first.request, self.request)
        self.assertIsNone(self.store.claim())
        self.store.finish(first.id, State.FAILED, SavedMedia(()), "测试故障")
        self.assertEqual(self.store.claim().request, second)
        self.assertEqual(self.store.history()[0].message, "测试故障")

    def test_completed_actual_quality_and_missing_output(self):
        auto = replace(self.request, quality=None)
        self.store.enqueue([auto])
        running = self.store.claim()
        video, audio = self.folder / "out.mp4", self.folder / "out.mp3"
        video.touch()
        audio.touch()
        self.store.finish(running.id, State.DONE, SavedMedia((video, audio), 80, "1080P 高清"), "")
        self.assertEqual(self.store.enqueue([self.request, auto]).duplicates, 2)
        history = self.store.history()[0]
        self.assertEqual(history.media.quality, 80)
        self.assertFalse(history.can_retry)
        audio.unlink()
        self.assertTrue(history.can_retry)
        self.assertEqual(self.store.enqueue([self.request]).added, 1)

    def test_output_and_folder_are_part_of_duplicate_key(self):
        result = self.store.enqueue([
            self.request, replace(self.request, output=Output.VIDEO),
            replace(self.request, folder=self.folder / "other"), replace(self.request, quality=64),
        ])
        self.assertEqual(result.added, 4)

    def test_replaced_part_is_not_a_duplicate(self):
        old = replace(self.request, cid=123)
        new = replace(self.request, cid=456)
        self.assertEqual(self.store.enqueue([old, new, new]).added, 2)
        self.assertEqual([item.request.cid for item in self.store.active()], [123, 456])

    def test_waiting_removal_preserves_history(self):
        self.store.enqueue([self.request, replace(self.request, page=2)])
        active = self.store.claim()
        waiting = self.store.active()[1]
        self.assertFalse(self.store.remove_waiting(active.id))
        self.assertTrue(self.store.remove_waiting(waiting.id))
        self.assertFalse(self.store.remove_waiting(waiting.id))
        removed = self.store.history()[0]
        self.assertEqual(removed.state, State.CANCELLED)
        self.assertTrue(removed.can_retry)
        self.assertEqual(self.store.enqueue([removed.request]).added, 1)

    def test_restart_recovers_only_the_running_task(self):
        self.store.enqueue([self.request, replace(self.request, page=2)])
        first = self.store.claim()
        reopened = TaskStore(self.db)
        self.addCleanup(reopened.close)
        reopened.recover()
        self.assertEqual([(item.request.page, item.state) for item in reopened.active()], [(2, State.WAITING)])
        recovered = reopened.history()[0]
        self.assertEqual((recovered.id, recovered.state), (first.id, State.INTERRUPTED))
        self.assertTrue(recovered.can_retry)

    def test_batch_rolls_back_if_second_insert_fails(self):
        self.store.db.execute("""
            CREATE TRIGGER abort_second BEFORE INSERT ON tasks WHEN NEW.page=2
            BEGIN SELECT RAISE(ABORT, 'simulated disk constraint'); END
        """)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.enqueue([self.request, replace(self.request, page=2)])
        self.assertEqual(self.store.active(), ())

    def test_finished_task_cannot_be_finished_again(self):
        self.store.enqueue([self.request])
        active = self.store.claim()
        self.store.finish(active.id, State.CANCELLED, SavedMedia(()), "取消")
        with self.assertRaises(ValueError):
            self.store.finish(active.id, State.FAILED, SavedMedia(()), "错误")
        self.assertEqual(self.store.history()[0].state, State.CANCELLED)

    def test_claim_excludes_other_connections(self):
        self.store.enqueue([self.request, replace(self.request, page=2)])
        other = TaskStore(self.db)
        self.addCleanup(other.close)
        self.assertIsNotNone(self.store.claim())
        self.assertIsNone(other.claim())

    def test_history_filters_before_pagination(self):
        self.store.enqueue([replace(self.request, page=page) for page in range(1, 5)])
        for state in (State.FAILED, State.CANCELLED, State.FAILED):
            item = self.store.claim()
            self.store.finish(item.id, state, SavedMedia(()), "测试")
        self.assertEqual([item.request.page for item in self.store.history(State.FAILED, limit=1)], [3])
        self.assertEqual([item.request.page for item in self.store.history(State.FAILED, limit=1, offset=1)], [1])
        self.assertEqual(len(self.store.history()), 3)

    def test_platforms_have_separate_duplicate_keys(self):
        dy = replace(self.request, source=Source.DOUYIN)
        result = self.store.enqueue([self.request, dy, dy])
        self.assertEqual((result.added, result.duplicates), (2, 1))
        self.assertEqual([item.request.source for item in self.store.active()], [Source.BILIBILI, Source.DOUYIN])

    def test_migrates_legacy_history_and_waiting_rows(self):
        self.store.enqueue([self.request, replace(self.request, page=2)])
        finished = self.store.claim()
        path = self.folder / "old.mp4"
        path.touch()
        self.store.finish(finished.id, State.DONE, SavedMedia((path,), 80, "1080P 高清"), "")
        self.store.db.executescript("""
            DROP INDEX task_source_identity;
            ALTER TABLE tasks DROP COLUMN source;
            ALTER TABLE tasks RENAME COLUMN video_id TO bvid;
            CREATE INDEX task_identity ON tasks(bvid,page,output,folder_key);
        """)
        migrated = TaskStore(self.db)
        self.addCleanup(migrated.close)
        completed, = migrated.history()
        waiting, = migrated.active()
        self.assertEqual((completed.id, completed.request, completed.media.files), (finished.id, self.request, (path,)))
        self.assertEqual((waiting.request.page, waiting.request.source), (2, Source.BILIBILI))
        self.assertEqual(migrated.enqueue([self.request]).duplicates, 1)


if __name__ == "__main__":
    unittest.main()
