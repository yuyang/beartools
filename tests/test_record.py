"""RecordManager 测试用例"""

import asyncio
import os
from pathlib import Path
import tempfile

import pytest

from beartools.record import RecordManager


class TestRecordManager:
    """RecordManager 测试类"""

    def setup_method(self) -> None:
        """每个测试前创建临时数据库"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_cwd = Path.cwd()
        os.chdir(self.temp_dir.name)

        # 重置单例状态
        RecordManager._instance = None
        RecordManager._initialized = False

        self.record_manager = RecordManager()

    def teardown_method(self) -> None:
        """每个测试后清理"""
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    @pytest.mark.asyncio
    async def test_init_creates_table(self) -> None:
        """测试初始化会自动创建表"""
        await self.record_manager.init()

        # 验证数据库文件和目录存在
        db_path = Path.cwd() / "data" / "record" / "beartools.db"
        assert db_path.exists()

    @pytest.mark.asyncio
    async def test_mark_and_get_by_url(self) -> None:
        """测试标记和查询记录"""
        await self.record_manager.init()

        # 插入记录
        success = await self.record_manager.mark_by_url(url="https://example.com/test", name="测试记录", id="test123")
        assert success is True

        # 查询记录
        record = await self.record_manager.get_by_url("https://example.com/test")
        assert record is not None
        assert record.id == "test123"
        assert record.name == "测试记录"
        assert record.url == "https://example.com/test"
        assert isinstance(record.update_time, object)

        # 查询不存在的记录
        record_none = await self.record_manager.get_by_url("https://example.com/nonexistent")
        assert record_none is None

    @pytest.mark.asyncio
    async def test_update_existing_record(self) -> None:
        """测试更新已存在的记录，update_time会更新"""
        await self.record_manager.init()

        # 第一次插入
        await self.record_manager.mark_by_url(url="https://example.com/test", name="初始名称", id="id1")
        record1 = await self.record_manager.get_by_url("https://example.com/test")

        # 等待一点时间
        await asyncio.sleep(0.1)

        # 第二次更新
        await self.record_manager.mark_by_url(url="https://example.com/test", name="更新后的名称", id="id2")
        record2 = await self.record_manager.get_by_url("https://example.com/test")

        assert record1 is not None
        assert record2 is not None
        assert record2.name == "更新后的名称"
        assert record2.id == "id2"
        assert record2.update_time > record1.update_time

    @pytest.mark.asyncio
    async def test_get_all_order_and_limit(self) -> None:
        """测试get_all按更新时间倒序，最多返回100条"""
        await self.record_manager.init()

        # 插入105条记录
        for i in range(105):
            await self.record_manager.mark_by_url(url=f"https://example.com/test{i}", name=f"测试记录{i}", id=f"id{i}")
            # 每条间隔一点时间，确保时间顺序
            await asyncio.sleep(0.01)

        records = await self.record_manager.get_all()

        # 验证只返回100条
        assert len(records) == 100

        # 验证是按时间倒序（id从大到小，因为后面插入的id更大）
        for i in range(100):
            assert records[i].id == f"id{104 - i}"
