"""Device-local durable photo annotations, shared across revocable panels."""

import math
import os
import sqlite3
from contextlib import closing
from pathlib import Path

CATEGORIES = (
    ("red", "红色", "#F65B62"),
    ("orange", "橙色", "#FF9D42"),
    ("yellow", "黄色", "#F4D94D"),
    ("green", "绿色", "#59CD72"),
    ("blue", "蓝色", "#488FFF"),
    ("purple", "紫色", "#A271F1"),
)
COLORS = frozenset(row[0] for row in CATEGORIES)


class AnnotationStore:
    def __init__(self, path, legacy=None):
        self.path, self.values, self.error = Path(path), {}, ""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS photos "
                    "(path TEXT PRIMARY KEY, rating REAL, color TEXT NOT NULL)"
                )
                db.execute("CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY)")
                if not db.execute("SELECT 1 FROM migrations WHERE name='info-v1'").fetchone():
                    legacy = legacy if isinstance(legacy, dict) else {}
                    ratings, colors = legacy.get("ratings", {}), legacy.get("color_labels", {})
                    ratings = ratings if isinstance(ratings, dict) else {}
                    colors = colors if isinstance(colors, dict) else {}
                    for name in ratings.keys() | colors.keys():
                        if not isinstance(name, str) or not name or "\0" in name:
                            continue
                        rating, color = ratings.get(name), colors.get(name, "")
                        if type(rating) not in (int, float) or not 0 <= rating <= 5:
                            rating = None
                        elif rating is not None:
                            rating = round(max(0, min(5, rating)) * 2) / 2
                        color = color if isinstance(color, str) and color in COLORS else ""
                        db.execute(
                            "INSERT OR IGNORE INTO photos VALUES (?, ?, ?)",
                            (os.path.abspath(name), rating, color),
                        )
                    db.execute("INSERT INTO migrations VALUES ('info-v1')")
                self.values = {
                    name: (rating, color)
                    for name, rating, color in db.execute("SELECT path,rating,color FROM photos")
                }
        except (OSError, sqlite3.Error) as error:
            # Never replace a damaged database or prevent unrelated viewing features.
            self.error = str(error)

    def snapshot(self):
        return {
            path: {"rating": rating, "color": color}
            for path, (rating, color) in self.values.items()
        }

    def set(self, path, *, rating=None, color=None):
        path = os.path.abspath(os.fspath(path))
        if "\0" in path:
            raise ValueError("图片路径无效")
        if rating is not None and (
            type(rating) not in (int, float)
            or not 0 <= rating <= 5
            or not math.isfinite(rating)
            or rating * 2 != int(rating * 2)
        ):
            raise ValueError("评分须为 0 至 5，步长为 0.5")
        if color is not None and (not isinstance(color, str) or color not in COLORS | {""}):
            raise ValueError("未知颜色分类")
        if self.error:
            raise ValueError("标注库无法写入：" + self.error)
        previous = self.values.get(path, (None, ""))
        value = (
            previous[0] if rating is None else float(rating),
            previous[1] if color is None else color,
        )
        if value == previous and path in self.values:
            return False
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO photos VALUES (?, ?, ?) ON CONFLICT(path) "
                "DO UPDATE SET rating=excluded.rating,color=excluded.color",
                (path, *value),
            )
        self.values[path] = value
        return True
