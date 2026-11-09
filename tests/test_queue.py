from dataclasses import replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication

from bili_downloader.models import Output, Part, UserError, check_cancelled
from bili_downloader.queue import DownloadQueue, execute_request
from bili_downloader.tasks import Request, SavedMedia, State, TaskStore


class QueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.store = TaskStore(self.folder / "tasks.sqlite3")
        self.addCleanup(self.store.close)
        self.first = Request("BV1eknB6DE37", 1, "测试", "上集", 80, Output.VIDEO, self.folder)
        self.second = replace(self.first, page=2)

    def make_queue(self, operation):
        queue = DownloadQueue(self.store, lambda: {}, execute=operation)
        self.addCleanup(self.stop, queue)
        return queue

    def stop(self, queue):
        queue.shutdown()
        self.wait(lambda: queue.worker is None)
        self.app.processEvents()

    def wait(self, predicate):
        deadline = monotonic() + 5
        while not predicate():
            self.app.processEvents()
            if monotonic() > deadline:
                self.fail("Queue did not settle")
            sleep(0.005)

    def succeed(self, request):
        file = self.folder / f"{request.page}.mp4"
        file.touch()
        return SavedMedia((file,), 80, "1080P 高清")

    def test_failure_does_not_stop_following_task_and_can_retry(self):
        order = []

        def execute(request, _cookies, _task):
            order.append(request.page)
            if order == [1]:
                raise UserError("媒体暂不可用")
            return self.succeed(request)

        queue = self.make_queue(execute)
        queue.enqueue([self.first, self.second])
        self.wait(lambda: len(self.store.history()) == 2)
        records = {item.request.page: item for item in self.store.history()}
        self.assertEqual(order, [1, 2])
        self.assertEqual(records[1].state, State.FAILED)
        self.assertEqual(records[2].state, State.DONE)
        queue.enqueue([records[1].request])
        self.wait(lambda: len(self.store.history()) == 3)
        self.assertEqual(order, [1, 2, 1])

    def test_pause_waits_for_current_then_resume_dispatches_next(self):
        release = Event()

        def execute(request, _cookies, task):
            if request.page == 1:
                while not release.wait(0.01):
                    check_cancelled(task.cancel)
            return self.succeed(request)

        queue = self.make_queue(execute)
        queue.enqueue([self.first, self.second])
        self.wait(lambda: queue.worker is not None)
        queue.set_paused(True)
        release.set()
        self.wait(lambda: queue.worker is None)
        self.assertEqual([item.state for item in self.store.active()], [State.WAITING])
        queue.set_paused(False)
        self.wait(lambda: len(self.store.history()) == 2)

    def test_cancel_current_advances_queue(self):
        def execute(request, _cookies, task):
            if request.page == 1:
                task.cancel.wait(3)
                check_cancelled(task.cancel)
            return self.succeed(request)

        queue = self.make_queue(execute)
        queue.enqueue([self.first, self.second])
        self.wait(lambda: queue.worker is not None)
        queue.cancel()
        self.wait(lambda: len(self.store.history()) == 2)
        self.assertEqual({item.request.page: item.state for item in self.store.history()},
                         {1: State.CANCELLED, 2: State.DONE})

    def test_shutdown_preserves_waiting_and_records_active_cancellation(self):
        def execute(request, _cookies, task):
            task.cancel.wait(3)
            check_cancelled(task.cancel)
            return self.succeed(request)

        queue = self.make_queue(execute)
        queue.enqueue([self.first, self.second])
        self.wait(lambda: queue.worker is not None)
        self.stop(queue)
        self.assertEqual([item.state for item in self.store.active()], [State.WAITING])
        self.assertEqual(self.store.history()[0].state, State.CANCELLED)

    def test_restored_queue_requires_continue(self):
        self.store.enqueue([self.first])
        queue = self.make_queue(lambda request, *_: self.succeed(request))
        self.assertTrue(queue.paused)
        self.app.processEvents()
        self.assertIsNone(queue.worker)
        queue.set_paused(False)
        self.wait(lambda: len(self.store.history()) == 1)

    def test_cancellation_after_publish_keeps_the_completed_record(self):
        published = Event()

        def execute(request, _cookies, task):
            result = self.succeed(request)
            published.set()
            task.cancel.wait(3)
            return result

        queue = self.make_queue(execute)
        queue.enqueue([self.first])
        self.wait(published.is_set)
        queue.cancel()
        self.wait(lambda: len(self.store.history()) == 1)
        saved = self.store.history()[0]
        self.assertEqual(saved.state, State.DONE)
        self.assertTrue(saved.media.exists)

    def test_history_write_failure_pauses_until_record_is_saved(self):
        queue = self.make_queue(lambda request, *_: self.succeed(request))
        errors = []
        queue.error.connect(errors.append)
        with patch.object(self.store, "finish", side_effect=sqlite3.OperationalError("fixture")):
            queue.enqueue([self.first, self.second])
            self.wait(lambda: bool(errors))
        self.assertTrue(queue.paused)
        self.assertEqual([item.state for item in self.store.active()], [State.RUNNING, State.WAITING])
        queue.set_paused(False)
        self.wait(lambda: len(self.store.history()) == 2)

    def test_changed_part_identity_stops_before_downloading(self):
        request = replace(self.first, cid=123)
        with patch("bili_downloader.queue.Bilibili") as api, patch("bili_downloader.queue.save_media") as save:
            api.return_value.__enter__.return_value.resolve.return_value = (None, Part(1, 456, "替换片段", 10))
            with self.assertRaisesRegex(UserError, "分 P 已调整"):
                execute_request(request, {}, SimpleNamespace(cancel=Event()))
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
