from asyncio import AbstractEventLoop, events
import types


@types.coroutine
def next_tick_generator():
    yield


async def next_tick_future(loop: AbstractEventLoop | None = None):
    # Normally we shouldn't need to pass the loop as an argument
    # but this helps us to test the function in isolation
    if loop is None:
        loop = events.get_running_loop()
    future = loop.create_future()
    loop.call_soon(future.set_result, None)
    return await future


async def sleep(seconds: float, loop: AbstractEventLoop | None = None):
    if seconds <= 0:
        # this should purely defer the future resolution to the next tick
        return await next_tick_future(loop)

    if loop is None:
        loop = events.get_running_loop()

    future = loop.create_future()
    loop.call_later(seconds, future.set_result, None)
    return await future


async def gather(*futures, loop: AbstractEventLoop | None = None):
    # This would be fun to implement and explain
    ...


async def wait():
    # This would be even more fun to implement and explain
    ...
