from asyncio.unix_events import _UnixSelectorEventLoop
import pytest

from src.loop import MyEventLoop
from src.my_asyncio import gather, next_tick_future, sleep


@pytest.fixture(
    scope="function",
)
def loop(request):
    return MyEventLoop()


def test_sleep_future(loop, benchmark):
    @benchmark
    def _():
        loop.run_until_complete(sleep(0, loop))


def test_schedule_soon(loop, benchmark):
    @benchmark
    def _():
        loop.call_soon(lambda: None)


def test_schedule_later(loop, benchmark):
    @benchmark
    def _():
        loop.call_later(0, lambda: None)


def test_gather_next_tick(loop, benchmark):
    @benchmark
    def _():
        loop.run_until_complete(
            gather(
                loop.create_task(next_tick_future(loop)),
                loop.create_task(next_tick_future(loop)),
                loop.create_task(next_tick_future(loop)),
                loop.create_task(next_tick_future(loop)),
                loop.create_task(next_tick_future(loop)),
                loop=loop,
            )
        )
