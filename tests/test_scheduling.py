from unittest import mock
from freezegun import freeze_time

from asyncio import AbstractEventLoop


def test_call_soon(loop: AbstractEventLoop):
    callback = mock.Mock()
    loop.call_soon(callback)
    loop._run_once()
    assert callback.called


def test_call_at(loop: AbstractEventLoop):
    callback = mock.Mock()
    with freeze_time() as frozen_time:
        loop.call_at(loop.time() + 1, callback)
        loop._run_once()
        assert not callback.called
        frozen_time.tick(2)
        loop._run_once()
        assert callback.called


def test_call_later(loop: AbstractEventLoop):
    callback = mock.Mock()
    with freeze_time() as frozen_time:
        loop.call_later(1, callback)
        loop._run_once()
        assert not callback.called
        frozen_time.tick(2)
        loop._run_once()
        assert callback.called
