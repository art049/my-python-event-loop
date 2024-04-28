from asyncio import AbstractEventLoop
from socket import socketpair
from unittest.mock import Mock


def test_add_reader(loop: AbstractEventLoop):
    rsock, wsock = socketpair()
    mock = Mock()

    loop.add_reader(rsock, mock)
    loop.call_soon(wsock.send, b"hello world")
    loop._run_once()  # This would queue the reader callback
    loop._run_once()
    assert mock.called, "Reader should be called"


def test_remove_reader(loop: AbstractEventLoop):
    rsock, wsock = socketpair()
    rsock.setblocking(False)
    mock = Mock()
    assert not loop.remove_reader(rsock), "Reader cannot be removed"

    loop.add_reader(rsock, mock)
    assert loop.remove_reader(rsock), "Reader should be removed"
    loop.call_soon(wsock.send, b"hello world")

    loop.call_soon(lambda: None)  # Dummy task to ensure run once doesnt block
    loop._run_once()  # This would queue the reader callback
    loop.call_soon(lambda: None)  # Dummy task to ensure run once doesnt block
    loop._run_once()
    assert not mock.called, "Reader should not be called"


def test_add_writer(loop: AbstractEventLoop):
    _, wsock = socketpair()
    mock = Mock()

    # Initially, the writer should be able to write without blocking
    loop.add_writer(wsock, mock)
    loop._run_once()  # This would queue the writer callback if the socket is ready for writing
    assert (
        mock.called
    ), "Writer should be called since socket should be ready for writing immediately"


def test_remove_writer(loop: AbstractEventLoop):
    _, wsock = socketpair()
    mock = Mock()

    assert not loop.remove_writer(wsock), "Writer cannot be removed before adding"

    loop.add_writer(wsock, mock)
    assert loop.remove_writer(wsock), "Writer should be removed after being added"

    loop.call_soon(lambda: None)  # Dummy task to ensure _run_once doesn't block
    loop._run_once()  # This would not queue the writer callback since it's removed
    assert not mock.called, "Writer should not be called after being removed"
