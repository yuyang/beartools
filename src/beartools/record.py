"""记录管理模块

基于SQLite实现的URL记录管理器，支持URL的增删改查操作。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import aiosqlite


class Record(NamedTuple):
    """记录数据结构"""

    id: str
    name: str
    url: str
    update_time: datetime


class RecordManager:
    """记录管理器

    管理record表，支持URL的查询、标记和全量查询。
    数据保存在 ./data/record/beartools.db 中。
    """

    _instance: RecordManager | None = None
    _initialized: bool = False

    def __new__(cls) -> RecordManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self.db_path = Path.cwd() / "data" / "record" / "beartools.db"
        self._lock = asyncio.Lock()
        self._initialized = True

    async def _ensure_db_dir(self) -> None:
        """确保数据库目录存在"""
        db_dir = self.db_path.parent
        if not db_dir.exists():
            db_dir.mkdir(parents=True, exist_ok=True)

    async def _init_table(self) -> None:
        """初始化表结构，不存在则创建，存在则迁移字段"""
        await self._ensure_db_dir()

        async with aiosqlite.connect(self.db_path) as conn:
            # 创建表（如果不存在）
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS record (
                    id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL PRIMARY KEY,
                    update_time TEXT NOT NULL
                )
            """)

            # 检查是否有update_time字段，没有则添加（兼容旧版本表）
            async with conn.execute("PRAGMA table_info(record)") as cursor:
                columns: list[str] = [row[1] for row in await cursor.fetchall()]  # type: ignore[misc]
                if "update_time" not in columns:
                    await conn.execute("ALTER TABLE record ADD COLUMN update_time TEXT NOT NULL DEFAULT ''")

            await conn.commit()

    async def init(self) -> None:
        """初始化管理器，确保表存在"""
        await self._init_table()

    async def get_by_url(self, url: str) -> Record | None:
        """根据URL查询记录

        Args:
            url: 要查询的URL

        Returns:
            Record | None: 找到返回Record对象，否则返回None
        """
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    "SELECT id, name, url, update_time FROM record WHERE url = ?", (url,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        update_time = datetime.fromisoformat(row["update_time"])  # type: ignore[misc]
                        return Record(id=row["id"], name=row["name"], url=row["url"], update_time=update_time)  # type: ignore[misc]
                    return None

    async def mark_by_url(self, url: str, name: str, id: str) -> bool:
        """标记URL记录，存在则更新，不存在则插入

        Args:
            url: 要标记的URL（唯一索引）
            name: 记录名称
            id: 记录ID

        Returns:
            bool: 操作成功返回True，失败返回False
        """
        async with self._lock:
            try:
                now = datetime.now(UTC).isoformat()
                async with aiosqlite.connect(self.db_path) as conn:
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO record (id, name, url, update_time)
                        VALUES (?, ?, ?, ?)
                    """,
                        (id, name, url, now),
                    )
                    await conn.commit()
                    return True
            except Exception:
                return False

    async def get_all(self) -> list[Record]:
        """查询最近100条记录，按更新时间倒序排列

        Returns:
            list[Record]: 记录列表，最多100条，按update_time从新到旧排序
        """
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    "SELECT id, name, url, update_time FROM record ORDER BY update_time DESC LIMIT 100"
                ) as cursor:
                    rows = await cursor.fetchall()
                    records = []
                    for row in rows:
                        update_time = datetime.fromisoformat(row["update_time"])  # type: ignore[misc]
                        records.append(Record(id=row["id"], name=row["name"], url=row["url"], update_time=update_time))  # type: ignore[misc]
                    return records


# 全局单例
record_manager = RecordManager()
