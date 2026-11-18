"""Persistent download requests. Playback URLs and credentials belong to the worker."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import sqlite3

from .models import AssetOptions, ImageFormat, Output, Part, Source, Video


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
    video_id: str
    page: int
    title: str
    part: str
    quality: int | None
    output: Output
    folder: Path
    cid: int | None = None
    source: Source = Source.BILIBILI
    is_note: bool = False
    asset_options: AssetOptions = AssetOptions()
    best_quality: int | None = None

    @classmethod
    def for_part(cls, video: Video, part: Part, quality: int | None, output: Output, folder: Path, *,
                 asset_options: AssetOptions = AssetOptions(), best_quality: int | None = None):
        return cls(video.video_id, part.number, video.title, part.name,
                   None if output in (Output.AUDIO, Output.ASSETS) else quality, output, folder.absolute(),
                   part.cid if video.source is Source.BILIBILI else None, video.source, video.is_note,
                   asset_options if output is Output.ASSETS else AssetOptions(),
                   best_quality if quality is None and not video.is_note and output in (Output.VIDEO, Output.BOTH) else None)

    @property
    def url(self) -> str:
        return self.source.url(self.video_id, self.page, is_note=self.is_note)

    @property
    def folder_key(self) -> str:
        return os.path.normcase(os.path.normpath(self.folder))

    @property
    def display(self) -> str:
        if self.source is Source.DOUYIN:
            return self.title
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
                    video_id TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'bilibili',
                    is_note INTEGER NOT NULL DEFAULT 0,
                    page INTEGER NOT NULL,
                    cid INTEGER,
                    title TEXT NOT NULL,
                    part TEXT NOT NULL,
                    quality INTEGER,
                    best_quality INTEGER,
                    output TEXT NOT NULL,
                    image_format TEXT NOT NULL DEFAULT 'original',
                    include_clip_covers INTEGER NOT NULL DEFAULT 1,
                    folder TEXT NOT NULL,
                    folder_key TEXT NOT NULL,
                    state TEXT NOT NULL,
                    finished TEXT,
                    actual_quality INTEGER,
                    quality_label TEXT NOT NULL DEFAULT '',
                    files TEXT NOT NULL DEFAULT '[]',
                    message TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS task_state ON tasks(state,id);
                CREATE INDEX IF NOT EXISTS task_history_order ON tasks(finished DESC,id DESC)
                    WHERE state NOT IN ('waiting','running');
            """)
            self.db.execute("BEGIN IMMEDIATE")
            columns = {column["name"] for column in self.db.execute("PRAGMA table_info(tasks)")}
            if "cid" not in columns:
                self.db.execute("ALTER TABLE tasks ADD COLUMN cid INTEGER")
            if "best_quality" not in columns:
                self.db.execute("ALTER TABLE tasks ADD COLUMN best_quality INTEGER")
            if "bvid" in columns and "video_id" not in columns:
                self.db.execute("ALTER TABLE tasks RENAME COLUMN bvid TO video_id")
            if "source" not in columns:
                self.db.execute("ALTER TABLE tasks ADD COLUMN source TEXT NOT NULL DEFAULT 'bilibili'")
            if "is_note" not in columns:
                self.db.execute("ALTER TABLE tasks ADD COLUMN is_note INTEGER NOT NULL DEFAULT 0")
            if "image_format" not in columns:
                self.db.execute("ALTER TABLE tasks ADD COLUMN image_format TEXT NOT NULL DEFAULT 'original'")
            if "include_clip_covers" not in columns:
                self.db.execute("ALTER TABLE tasks ADD COLUMN include_clip_covers INTEGER NOT NULL DEFAULT 1")
            self.db.execute("DROP INDEX IF EXISTS task_identity")
            self.db.execute("""
                CREATE INDEX IF NOT EXISTS task_source_identity ON tasks(source,video_id,page,output,folder_key)
            """)

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        request = Request(row["video_id"], row["page"], row["title"], row["part"], row["quality"],
                          Output(row["output"]), Path(row["folder"]), row["cid"], Source(row["source"]),
                          bool(row["is_note"]),
                          AssetOptions(ImageFormat(row["image_format"]), bool(row["include_clip_covers"])),
                          row["best_quality"])
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
                    INSERT INTO tasks(source,video_id,is_note,page,cid,title,part,quality,output,
                                      image_format,include_clip_covers,folder,folder_key,state,best_quality)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (request.source.value, request.video_id, request.is_note, request.page, request.cid,
                      request.title, request.part, request.quality,
                      request.output.value, request.asset_options.image_format.value, request.asset_options.include_clip_covers,
                      str(request.folder), request.folder_key, State.WAITING.value, request.best_quality))
                added += 1
        return Enqueued(added, len(requests) - added)

    def _duplicate(self, request: Request) -> bool:
        rows = self.db.execute("""
            SELECT * FROM tasks
            WHERE source=? AND video_id=? AND page=? AND output=? AND folder_key=?
              AND image_format=? AND include_clip_covers=?
              AND (cid IS NULL OR ? IS NULL OR cid=?)
              AND state IN ('waiting','running','done')
        """, (request.source.value, request.video_id, request.page, request.output.value,
              request.folder_key, request.asset_options.image_format.value, request.asset_options.include_clip_covers,
              request.cid, request.cid))
        for row in rows:
            if row["state"] != State.DONE.value:
                if row["quality"] == request.quality:
                    return True
            else:
                desired = request.quality
                if desired is None and not request.is_note and request.output in (Output.VIDEO, Output.BOTH):
                    # Unknown current best must not let an old, lower tier block a new download.
                    desired = request.best_quality
                    if desired is None:
                        continue
                    matches = desired == row["actual_quality"]
                else:
                    matches = desired in (row["quality"], row["actual_quality"])
                if matches and self._task(row).media.exists:
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
