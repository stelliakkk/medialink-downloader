"""Persistent download requests. Playback URLs and credentials belong to the worker."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import sqlite3

from .models import Output, Part, Video


class State(Enum):
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


TERMINAL = (State.DONE, State.FAILED, State.CANCELLED, State.INTERRUPTED)


@dataclass(frozen=True, slots=True)
class Request:
    bvid: str
    page: int
    title: str
    part: str
    quality: int | None
    output: Output
    folder: Path
    cid: int | None = None

    @classmethod
    def for_part(cls, video: Video, part: Part, quality: int | None, output: Output, folder: Path):
        return cls(video.bvid, part.number, video.title, part.name,
                   None if output is Output.AUDIO else quality, output, folder.absolute(), part.cid)

    @property
    def url(self) -> str:
        return f"https://www.bilibili.com/video/{self.bvid}/?p={self.page}"

    @property
    def folder_key(self) -> str:
        return os.path.normcase(os.path.normpath(self.folder))

    @property
    def display(self) -> str:
        suffix = f" · {self.part}" if self.part and self.part != self.title else ""
        return f"{self.title}  ·  P{self.page:02d}{suffix}"


@dataclass(frozen=True, slots=True)
class SavedMedia:
    files: tuple[Path, ...]
    quality: int | None = None
    label: str = ""

    @property
    def exists(self) -> bool:
        return bool(self.files) and all(path.is_file() for path in self.files)


@dataclass(frozen=True, slots=True)
class Task:
    id: int
    request: Request
    state: State
    finished: str | None
    media: SavedMedia
    message: str

    @property
    def can_retry(self) -> bool:
        return self.state in (State.FAILED, State.CANCELLED, State.INTERRUPTED) or (
            self.state is State.DONE and not self.media.exists
        )


@dataclass(frozen=True, slots=True)
class Enqueued:
    added: int
    duplicates: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TaskStore:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, timeout=5)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY,
                    bvid TEXT NOT NULL,
                    page INTEGER NOT NULL,
                    cid INTEGER,
                    title TEXT NOT NULL,
                    part TEXT NOT NULL,
                    quality INTEGER,
                    output TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    folder_key TEXT NOT NULL,
                    state TEXT NOT NULL,
                    finished TEXT,
                    actual_quality INTEGER,
                    quality_label TEXT NOT NULL DEFAULT '',
                    files TEXT NOT NULL DEFAULT '[]',
                    message TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS task_identity ON tasks(bvid,page,output,folder_key);
                CREATE INDEX IF NOT EXISTS task_state ON tasks(state,id);
                CREATE INDEX IF NOT EXISTS task_history_order ON tasks(finished DESC,id DESC)
                    WHERE state NOT IN ('waiting','running');
            """)
            if not any(column["name"] == "cid" for column in self.db.execute("PRAGMA table_info(tasks)")):
                self.db.execute("ALTER TABLE tasks ADD COLUMN cid INTEGER")

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        request = Request(row["bvid"], row["page"], row["title"], row["part"], row["quality"],
                          Output(row["output"]), Path(row["folder"]), row["cid"])
        media = SavedMedia(tuple(Path(value) for value in json.loads(row["files"])),
                           row["actual_quality"], row["quality_label"])
        return Task(row["id"], request, State(row["state"]), row["finished"], media, row["message"])

    def active(self) -> tuple[Task, ...]:
        rows = self.db.execute("SELECT * FROM tasks WHERE state IN ('waiting','running') ORDER BY id")
        return tuple(map(self._task, rows))

    def history(self, state: State | None = None, *, limit: int = -1, offset: int = 0) -> tuple[Task, ...]:
        where = " AND state=?" if state is not None else ""
        params = (state.value, limit, offset) if state is not None else (limit, offset)
        rows = self.db.execute(f"""
            SELECT * FROM tasks WHERE state NOT IN ('waiting','running')
            {where} ORDER BY finished DESC, id DESC LIMIT ? OFFSET ?
        """, params)
        return tuple(map(self._task, rows))

    def get(self, task_id: int) -> Task | None:
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self._task(row) if row is not None else None

    def recover(self) -> None:
        with self.db:
            self.db.execute(
                "UPDATE tasks SET state=?,finished=?,message=? WHERE state='running'",
                (State.INTERRUPTED.value, _now(), "上次退出前未确认完成，可重新入队。"),
            )

    def enqueue(self, requests: list[Request]) -> Enqueued:
        added = 0
        with self.db:
            # Lock before reading candidates so separate transactions cannot add duplicate jobs.
            self.db.execute("BEGIN IMMEDIATE")
            for request in requests:
                if self._duplicate(request):
                    continue
                self.db.execute("""
                    INSERT INTO tasks(bvid,page,cid,title,part,quality,output,folder,folder_key,state)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (request.bvid, request.page, request.cid, request.title, request.part, request.quality,
                      request.output.value, str(request.folder), request.folder_key, State.WAITING.value))
                added += 1
        return Enqueued(added, len(requests) - added)

    def _duplicate(self, request: Request) -> bool:
        rows = self.db.execute("""
            SELECT * FROM tasks
            WHERE bvid=? AND page=? AND output=? AND folder_key=?
              AND (cid IS NULL OR ? IS NULL OR cid=?)
              AND state IN ('waiting','running','done')
        """, (request.bvid, request.page, request.output.value, request.folder_key, request.cid, request.cid))
        for row in rows:
            if row["state"] != State.DONE.value:
                if row["quality"] == request.quality:
                    return True
            elif request.quality in (row["quality"], row["actual_quality"]):
                if self._task(row).media.exists:
                    return True
        return False

    def claim(self) -> Task | None:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT 1 FROM tasks WHERE state='running' LIMIT 1").fetchone():
                return None
            row = self.db.execute("SELECT * FROM tasks WHERE state='waiting' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                return None
            self.db.execute("UPDATE tasks SET state='running' WHERE id=?", (row["id"],))
            running = self.db.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone()
        return self._task(running)

    def remove_waiting(self, task_id: int) -> bool:
        with self.db:
            return self.db.execute("""
                UPDATE tasks SET state='cancelled',finished=?,message=?
                WHERE id=? AND state='waiting'
            """, (_now(), "已从等待队列移除。", task_id)).rowcount == 1

    def finish(self, task_id: int, state: State, media: SavedMedia, message: str) -> None:
        if state not in TERMINAL or (state is State.DONE) != bool(media.files):
            raise ValueError("Invalid task result")
        with self.db:
            updated = self.db.execute("""
                UPDATE tasks SET state=?,finished=?,actual_quality=?,quality_label=?,files=?,message=?
                WHERE id=? AND state='running'
            """, (state.value, _now(), media.quality, media.label,
                  json.dumps([str(path) for path in media.files], ensure_ascii=False), message, task_id))
            if updated.rowcount != 1:
                raise ValueError("Only an active task can finish")
