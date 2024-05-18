from asyncio import AbstractEventLoop, Future, events
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


def sleep(seconds: float, loop: AbstractEventLoop | None = None):
    if seconds <= 0:
        # this should purely defer the future resolution to the next tick
        return next_tick_future(loop)

    if loop is None:
        loop = events.get_running_loop()

    future = loop.create_future()
    loop.call_later(seconds, future.set_result, None)
    return future


def gather(*futures: Future, loop: AbstractEventLoop | None = None):
    if loop is None:
        loop = events.get_running_loop()

    gathered = loop.create_future()

    future_count = len(futures)
    completed_count = 0

    def on_done(future):
        nonlocal completed_count
        completed_count += 1
        if completed_count == future_count:
            gathered.set_result([future.result() for future in futures])

    for future in futures:
        future.add_done_callback(on_done)

    return gathered


async def wait():
    # This would be even more fun to implement and explain
    ...
