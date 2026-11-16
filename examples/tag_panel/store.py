"""Durable local tags and assignments, independent of image files and cache."""

import os
import sqlite3
from contextlib import closing, contextmanager
from uuid import uuid4

from picer.i18n import tr


class TagStore:
    def __init__(self, path):
        self.path = path
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS tags "
                "(id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT UNIQUE NOT NULL, "
                "color TEXT NOT NULL, visible INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS links "
                "(path TEXT NOT NULL, kind TEXT NOT NULL, tag TEXT NOT NULL "
                "REFERENCES tags(id) ON DELETE CASCADE, PRIMARY KEY(path,kind,tag))"
            )

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def tags(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM tags ORDER BY name_key,id")]

    def save(self, name, color, visible=True, tag_id=None):
        name = name.strip()
        if not name or len(name) > 64 or any(ord(char) < 32 for char in name):
            raise ValueError(tr("标签名称须为 1–64 个字符"))
        if (
            len(color) != 7
            or color[0] != "#"
            or any(char not in "0123456789abcdefABCDEF" for char in color[1:])
        ):
            raise ValueError(tr("标签颜色无效"))
        tag_id = tag_id or uuid4().hex
        with self.connection() as db:
            existing = db.execute("SELECT id FROM tags WHERE id=?", (tag_id,)).fetchone()
            if not existing and db.execute("SELECT count(*) FROM tags").fetchone()[0] >= 2048:
                raise ValueError(tr("标签库已达到 2048 个标签"))
            try:
                db.execute(
                    "INSERT INTO tags VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                    "name=excluded.name,name_key=excluded.name_key,"
                    "color=excluded.color,visible=excluded.visible",
                    (tag_id, name, name.casefold(), color.upper(), bool(visible)),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(tr("已存在同名标签")) from error
        return tag_id

    def assigned(self, path, kind):
        with self.connection() as db:
            return {
                row[0]
                for row in db.execute(
                    "SELECT tag FROM links WHERE path=? AND kind=?", self.key(path, kind)
                )
            }

    @staticmethod
    def key(path, kind):
        if kind not in ("image", "folder"):
            raise ValueError(kind)
        return os.path.normcase(os.path.abspath(path)), kind

    def assign(self, path, kind, tag_id, enabled):
        with self.connection() as db:
            parameters = (*self.key(path, kind), tag_id)
            db.execute(
                "INSERT OR IGNORE INTO links VALUES (?,?,?)"
                if enabled
                else "DELETE FROM links WHERE path=? AND kind=? AND tag=?",
                parameters,
            )

    def delete(self, tag_id):
        with self.connection() as db:
            db.execute("DELETE FROM tags WHERE id=?", (tag_id,))
