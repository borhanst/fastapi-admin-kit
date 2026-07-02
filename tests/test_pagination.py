"""Tests for pagination strategies."""

from __future__ import annotations

import base64
import json

import pytest
from sqlalchemy import Column, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base

from fastapi_admin_kit.pagination import (
    CursorPagination,
    DynamicPagination,
    OffsetPagination,
    PaginationResult,
)

Base = declarative_base()


class Item(Base):
    __tablename__ = "test_items"

    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    value = Column(Integer, default=0)


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine):
    async with AsyncSession(engine) as sess:
        yield sess


@pytest.fixture
async def populated_session(session):
    for i in range(50):
        session.add(Item(name=f"item_{i:03d}", value=i * 10))
    await session.commit()
    return session


class TestPaginationResult:
    def test_defaults(self):
        result = PaginationResult(items=[], total=0, per_page=20)
        assert result.page is None
        assert result.total_pages is None
        assert result.next_cursor is None
        assert result.has_next is False
        assert result.mode == "offset"


class TestOffsetPagination:
    @pytest.mark.asyncio
    async def test_first_page(self, populated_session):
        stmt = select(Item).order_by(Item.id)
        pagination = OffsetPagination()
        result = await pagination.paginate(stmt, populated_session, per_page=10, page=1)

        assert len(result.items) == 10
        assert result.total == 50
        assert result.page == 1
        assert result.total_pages == 5
        assert result.mode == "offset"

    @pytest.mark.asyncio
    async def test_last_page(self, populated_session):
        stmt = select(Item).order_by(Item.id)
        pagination = OffsetPagination()
        result = await pagination.paginate(stmt, populated_session, per_page=10, page=5)

        assert len(result.items) == 10
        assert result.page == 5

    @pytest.mark.asyncio
    async def test_beyond_last_page(self, populated_session):
        stmt = select(Item).order_by(Item.id)
        pagination = OffsetPagination()
        result = await pagination.paginate(stmt, populated_session, per_page=10, page=999)

        assert result.page == 5  # clamped to last page

    @pytest.mark.asyncio
    async def test_empty_results(self, engine):
        async with AsyncSession(engine) as sess:
            stmt = select(Item).order_by(Item.id)
            pagination = OffsetPagination()
            result = await pagination.paginate(stmt, sess, per_page=10, page=1)

            assert result.items == []
            assert result.total == 0
            assert result.total_pages == 1

    @pytest.mark.asyncio
    async def test_single_page(self, engine):
        async with AsyncSession(engine) as sess:
            sess.add(Item(name="only", value=1))
            await sess.commit()

            stmt = select(Item).order_by(Item.id)
            pagination = OffsetPagination()
            result = await pagination.paginate(stmt, sess, per_page=20, page=1)

            assert len(result.items) == 1
            assert result.total_pages == 1


class TestCursorPagination:
    def _encode(self, value):
        return base64.b64encode(json.dumps(value).encode()).decode()

    def _decode(self, cursor):
        return json.loads(base64.b64decode(cursor))

    @pytest.mark.asyncio
    async def test_first_page(self, populated_session):
        stmt = select(Item).order_by(Item.id)
        pagination = CursorPagination()
        pk_col = Item.id
        result = await pagination.paginate(
            stmt, populated_session, per_page=10, pk_col=pk_col, model=Item
        )

        assert len(result.items) == 10
        assert result.total == 50
        assert result.has_next is True
        assert result.next_cursor is not None
        assert result.mode == "cursor"

    @pytest.mark.asyncio
    async def test_cursor_encoding(self, populated_session):
        stmt = select(Item).order_by(Item.id)
        pagination = CursorPagination()
        result = await pagination.paginate(
            stmt, populated_session, per_page=10, pk_col=Item.id, model=Item
        )

        cursor_val = self._decode(result.next_cursor)
        assert cursor_val == 10  # last item id on first page

    @pytest.mark.asyncio
    async def test_forward_pagination(self, populated_session):
        stmt = select(Item).order_by(Item.id)
        pagination = CursorPagination()

        # First page
        result1 = await pagination.paginate(
            stmt, populated_session, per_page=10, pk_col=Item.id, model=Item
        )
        assert result1.items[0].id == 1
        assert result1.items[-1].id == 10

        # Second page using cursor
        stmt2 = select(Item).order_by(Item.id)
        result2 = await pagination.paginate(
            stmt2,
            populated_session,
            per_page=10,
            after=result1.next_cursor,
            pk_col=Item.id,
            model=Item,
        )
        assert result2.items[0].id == 11
        assert result2.items[-1].id == 20

    @pytest.mark.asyncio
    async def test_no_next_on_last_page(self, populated_session):
        stmt = select(Item).order_by(Item.id)
        pagination = CursorPagination()
        # Get last page worth of items
        stmt = stmt.where(Item.id > 40)
        result = await pagination.paginate(
            stmt, populated_session, per_page=10, pk_col=Item.id, model=Item
        )

        assert len(result.items) == 10
        assert result.has_next is False
        assert result.next_cursor is None

    @pytest.mark.asyncio
    async def test_custom_cursor_column(self, populated_session):
        stmt = select(Item).order_by(Item.value)
        pagination = CursorPagination(cursor_column="value")
        result = await pagination.paginate(
            stmt, populated_session, per_page=10, model=Item
        )

        assert len(result.items) == 10
        assert result.has_next is True

        # Verify cursor encodes the value column
        cursor_val = self._decode(result.next_cursor)
        assert cursor_val == 90  # last item's value (item_9 has value 90)


class TestDynamicPagination:
    @pytest.mark.asyncio
    async def test_uses_offset_for_small_dataset(self, populated_session):
        stmt = select(Item).order_by(Item.id)
        pagination = DynamicPagination(threshold=100)
        result = await pagination.paginate(
            stmt, populated_session, per_page=10, page=1,
            pk_col=Item.id, model=Item,
        )

        # 50 items < 100 threshold, should use offset
        assert result.mode == "dynamic_offset"
        assert result.page == 1
        assert result.total_pages == 5

    @pytest.mark.asyncio
    async def test_uses_cursor_for_large_dataset(self, engine):
        async with AsyncSession(engine) as sess:
            # Insert 150 items
            for i in range(150):
                sess.add(Item(name=f"item_{i:03d}", value=i))
            await sess.commit()

            stmt = select(Item).order_by(Item.id)
            pagination = DynamicPagination(threshold=100)
            result = await pagination.paginate(
                stmt, sess, per_page=10, page=1,
                pk_col=Item.id, model=Item,
            )

            # 150 items > 100 threshold, should use cursor
            assert result.mode == "dynamic_cursor"
            assert result.has_next is True
            assert result.next_cursor is not None

    @pytest.mark.asyncio
    async def test_custom_threshold(self, engine):
        async with AsyncSession(engine) as sess:
            for i in range(25):
                sess.add(Item(name=f"item_{i}", value=i))
            await sess.commit()

            stmt = select(Item).order_by(Item.id)
            # threshold=20, 25 items > 20, should use cursor
            pagination = DynamicPagination(threshold=20)
            result = await pagination.paginate(
                stmt, sess, per_page=10, page=1,
                pk_col=Item.id, model=Item,
            )

            assert result.mode == "dynamic_cursor"

    @pytest.mark.asyncio
    async def test_custom_cursor_column(self, engine):
        async with AsyncSession(engine) as sess:
            for i in range(150):
                sess.add(Item(name=f"item_{i}", value=i * 10))
            await sess.commit()

            stmt = select(Item).order_by(Item.value)
            pagination = DynamicPagination(cursor_column="value", threshold=100)
            result = await pagination.paginate(
                stmt, sess, per_page=10, page=1,
                model=Item,
            )

            assert result.mode == "dynamic_cursor"
            assert result.has_next is True
