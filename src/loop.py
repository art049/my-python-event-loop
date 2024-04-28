from asyncio import AbstractEventLoop, Future, Handle, TimerHandle, tasks
import bisect
from collections import deque
from collections.abc import Callable
from contextvars import Context
import time
from typing import Any


class MyEventLoop(AbstractEventLoop):
    def __init__(self):
        self._should_stop = False
        self._running = False
        self._scheduled_handles = deque[TimerHandle]()
        self._ready_handles = deque[Handle]()

    def call_soon(
        self,
        callback: Callable[..., object],
        *args: Any,
        context: Context | None = None,
    ) -> Handle:
        handle = Handle(callback, args, self, context)
        self._ready_handles.append(handle)
        return handle

    def call_at(
        self,
        when: float,
        callback: Callable[..., object],
        *args: Any,
        context: Context | None = None,
    ) -> TimerHandle:
        timer_handle = TimerHandle(
            when=when,
            callback=callback,
            args=args,
            loop=self,
        )
        print(f"Created timer handle {timer_handle}")
        bisect.insort(self._scheduled_handles, timer_handle)
        timer_handle._scheduled = True
        return timer_handle

    def call_later(
        self,
        delay: float,
        callback: Callable[..., object],
        *args: Any,
        context: Context | None = None,
    ) -> TimerHandle:
        return self.call_at(self.time() + delay, callback, *args, context=context)

    def time(self) -> float:
        return time.monotonic()

    # Task running methods

    def run_forever(self):
        self._running = True
        try:
            while not self._should_stop:
                self._run_once()
        finally:
            self._running = False

    def _run_once(self):
        now = self.time()
        while (
            len(self._scheduled_handles) > 0
            and self._scheduled_handles[0].when() <= now
        ):
            handle = self._scheduled_handles.popleft()
            print(f"Adding handle {handle} to ready queue")
            self._ready_handles.append(handle)

        while len(self._ready_handles) > 0:
            handle = self._ready_handles.popleft()
            print(f"Running handle {handle}")
            handle._run()

    def run_until_complete(self, future_: Future):
        future = tasks.ensure_future(future_, loop=self)
        # future.add_done_callback(lambda _: print("Future is done"))
        self._running = True
        try:
            while not future.done():
                self._run_once()
        finally:
            self._running = False

    def is_running(self):
        return self._running

    def stop(self):
        self._should_stop = True

    def close(self):
        assert not self._running, "Cannot close a running event loop"
        # TODO: clear task queues and shutdown executor

    def get_debug(self) -> bool:
        # FIXME: this should depend on the calls to set_debug and the PYTHONASYNCIODEBUG env var
        return True
