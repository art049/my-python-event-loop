from asyncio import BaseEventLoop, AbstractEventLoop
from datetime import timedelta
import my_asyncio
from freezegun import freeze_time


def test_non_async_coro(loop: BaseEventLoop):
    async def coro():
        return 42

    task = loop.create_task(coro())
    assert not task.done()
    loop._run_once()
    assert task.done()
    assert task.result() == 42


def test_next_tick_generator(loop: BaseEventLoop):
    async def coro():
        await my_asyncio.next_tick_generator()
        return 42

    task = loop.create_task(coro())
    loop._run_once()
    assert not task.done()
    loop._run_once()
    assert task.done()
    assert task.result() == 42


def test_next_tick_future(loop: BaseEventLoop):
    async def coro():
        return await my_asyncio.next_tick_future(loop)

    task = loop.create_task(coro())
    loop._run_once()
    assert not task.done()
    loop._run_once()
    assert task.done()
    assert task.result() is None


def test_async_coro(loop: AbstractEventLoop):
    async def coro():
        await my_asyncio.sleep(1)
        return 42

    task = loop.create_task(coro())
    loop.run_until_complete(task)
    assert task.done()
    assert task.result() == 42


def test_sleep(loop: AbstractEventLoop):
    async def coro():
        await my_asyncio.sleep(1, loop)
        return 42

    with freeze_time() as frozen_time:
        task = loop.create_task(coro())
        loop._run_once()
    assert not task.done()
    with freeze_time(frozen_time.time_to_freeze + timedelta(seconds=2)):
        loop._run_once()
        assert task.done()
        assert task.result() == 42
