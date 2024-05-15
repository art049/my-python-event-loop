"""This module is a copy of the original selector_transport.py from the asyncio package.
Some methods were not exposed in the original module, so they are added here.
"""

import collections
import itertools
import os
import selectors
import socket
import warnings
from asyncio import base_events
from asyncio import constants
from asyncio import futures
from asyncio import protocols
from asyncio import transports
from asyncio import trsock
from asyncio.log import logger

_HAS_SENDMSG = hasattr(socket.socket, "sendmsg")

if _HAS_SENDMSG:
    try:
        SC_IOV_MAX = os.sysconf("SC_IOV_MAX")
    except OSError:
        # Fallback to send
        _HAS_SENDMSG = False


def _test_selector_event(selector, fd, event):
    # Test if the selector is monitoring 'event' events
    # for the file descriptor 'fd'.
    try:
        key = selector.get_key(fd)
    except KeyError:
        return False
    else:
        return bool(key.events & event)


class _SelectorTransport(transports._FlowControlMixin, transports.Transport):
    max_size = 256 * 1024  # Buffer size passed to recv().

    # Attribute used in the destructor: it must be set even if the constructor
    # is not called (see _SelectorSslTransport which may start by raising an
    # exception)
    _sock = None

    def __init__(self, loop, sock, protocol, extra=None, server=None):
        super().__init__(extra, loop)
        self._extra["socket"] = trsock.TransportSocket(sock)
        try:
            self._extra["sockname"] = sock.getsockname()
        except OSError:
            self._extra["sockname"] = None
        if "peername" not in self._extra:
            try:
                self._extra["peername"] = sock.getpeername()
            except socket.error:
                self._extra["peername"] = None
        self._sock = sock
        self._sock_fd = sock.fileno()

        self._protocol_connected = False
        self.set_protocol(protocol)

        self._server = server
        self._buffer = collections.deque()
        self._conn_lost = 0  # Set when call to connection_lost scheduled.
        self._closing = False  # Set when close() called.
        self._paused = False  # Set when pause_reading() called

        # TODO: might be needed to reenable and implement on the server
        # Exception handling is needed for this to properly brake the loop
        # if self._server is not None:
        #     self._server._attach()

        # TODO: do we really need this?
        # loop._transports[self._sock_fd] = self

    def __repr__(self):
        info = [self.__class__.__name__]
        if self._sock is None:
            info.append("closed")
        elif self._closing:
            info.append("closing")
        info.append(f"fd={self._sock_fd}")
        # test if the transport was closed
        if self._loop is not None and not self._loop.is_closed():
            polling = _test_selector_event(
                self._loop._selector, self._sock_fd, selectors.EVENT_READ
            )
            if polling:
                info.append("read=polling")
            else:
                info.append("read=idle")

            polling = _test_selector_event(
                self._loop._selector, self._sock_fd, selectors.EVENT_WRITE
            )
            if polling:
                state = "polling"
            else:
                state = "idle"

            bufsize = self.get_write_buffer_size()
            info.append(f"write=<{state}, bufsize={bufsize}>")
        return "<{}>".format(" ".join(info))

    def abort(self):
        self._force_close(None)

    def set_protocol(self, protocol):
        self._protocol = protocol
        self._protocol_connected = True

    def get_protocol(self):
        return self._protocol

    def is_closing(self):
        return self._closing

    def is_reading(self):
        return not self.is_closing() and not self._paused

    def pause_reading(self):
        if not self.is_reading():
            return
        self._paused = True
        self._loop._remove_reader(self._sock_fd)
        if self._loop.get_debug():
            logger.debug("%r pauses reading", self)

    def resume_reading(self):
        if self._closing or not self._paused:
            return
        self._paused = False
        self._add_reader(self._sock_fd, self._read_ready)
        if self._loop.get_debug():
            logger.debug("%r resumes reading", self)

    def close(self):
        if self._closing:
            return
        self._closing = True
        self._loop._remove_reader(self._sock_fd)
        if not self._buffer:
            self._conn_lost += 1
            self._loop._remove_writer(self._sock_fd)
            self._loop.call_soon(self._call_connection_lost, None)

    def __del__(self, _warn=warnings.warn):
        if self._sock is not None:
            _warn(f"unclosed transport {self!r}", ResourceWarning, source=self)
            self._sock.close()

    def _fatal_error(self, exc, message="Fatal error on transport"):
        # Should be called from exception handler only.
        if isinstance(exc, OSError):
            if self._loop.get_debug():
                logger.debug("%r: %s", self, message, exc_info=True)
        else:
            self._loop.call_exception_handler(
                {
                    "message": message,
                    "exception": exc,
                    "transport": self,
                    "protocol": self._protocol,
                }
            )
        self._force_close(exc)

    def _force_close(self, exc):
        if self._conn_lost:
            return
        if self._buffer:
            self._buffer.clear()
            self._loop._remove_writer(self._sock_fd)
        if not self._closing:
            self._closing = True
            self._loop._remove_reader(self._sock_fd)
        self._conn_lost += 1
        self._loop.call_soon(self._call_connection_lost, exc)

    def _call_connection_lost(self, exc):
        try:
            if self._protocol_connected:
                self._protocol.connection_lost(exc)
        finally:
            self._sock.close()
            self._sock = None
            self._protocol = None
            self._loop = None
            server = self._server
            if server is not None:
                server._detach()
                self._server = None

    def get_write_buffer_size(self):
        return sum(map(len, self._buffer))

    def _add_reader(self, fd, callback, *args):
        if not self.is_reading():
            return
        self._loop._add_reader(fd, callback, *args)


class _SelectorSocketTransport(_SelectorTransport):
    _start_tls_compatible = True
    _sendfile_compatible = constants._SendfileMode.TRY_NATIVE

    def __init__(self, loop, sock, protocol, waiter=None, extra=None, server=None):
        self._read_ready_cb = None
        super().__init__(loop, sock, protocol, extra, server)
        self._eof = False
        self._empty_waiter = None
        if _HAS_SENDMSG:
            self._write_ready = self._write_sendmsg
        else:
            self._write_ready = self._write_send
        # Disable the Nagle algorithm -- small writes will be
        # sent without waiting for the TCP ACK.  This generally
        # decreases the latency (in some cases significantly.)
        base_events._set_nodelay(self._sock)

        self._loop.call_soon(self._protocol.connection_made, self)
        # only start reading when connection_made() has been called
        self._loop.call_soon(self._add_reader, self._sock_fd, self._read_ready)
        if waiter is not None:
            # only wake up the waiter when connection_made() has been called
            self._loop.call_soon(futures._set_result_unless_cancelled, waiter, None)

    def set_protocol(self, protocol):
        if isinstance(protocol, protocols.BufferedProtocol):
            self._read_ready_cb = self._read_ready__get_buffer
        else:
            self._read_ready_cb = self._read_ready__data_received

        super().set_protocol(protocol)

    def _read_ready(self):
        self._read_ready_cb()

    def _read_ready__get_buffer(self):
        if self._conn_lost:
            return

        try:
            buf = self._protocol.get_buffer(-1)
            if not len(buf):
                raise RuntimeError("get_buffer() returned an empty buffer")
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            self._fatal_error(exc, "Fatal error: protocol.get_buffer() call failed.")
            return

        try:
            nbytes = self._sock.recv_into(buf)
        except (BlockingIOError, InterruptedError):
            return
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            self._fatal_error(exc, "Fatal read error on socket transport")
            return

        if not nbytes:
            self._read_ready__on_eof()
            return

        try:
            self._protocol.buffer_updated(nbytes)
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            self._fatal_error(
                exc, "Fatal error: protocol.buffer_updated() call failed."
            )

    def _read_ready__data_received(self):
        if self._conn_lost:
            return
        try:
            data = self._sock.recv(self.max_size)
        except (BlockingIOError, InterruptedError):
            return
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            self._fatal_error(exc, "Fatal read error on socket transport")
            return

        if not data:
            self._read_ready__on_eof()
            return

        try:
            self._protocol.data_received(data)
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            self._fatal_error(exc, "Fatal error: protocol.data_received() call failed.")

    def _read_ready__on_eof(self):
        if self._loop.get_debug():
            logger.debug("%r received EOF", self)

        try:
            keep_open = self._protocol.eof_received()
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            self._fatal_error(exc, "Fatal error: protocol.eof_received() call failed.")
            return

        if keep_open:
            # We're keeping the connection open so the
            # protocol can write more, but we still can't
            # receive more, so remove the reader callback.
            self._loop._remove_reader(self._sock_fd)
        else:
            self.close()

    def write(self, data):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(
                f"data argument must be a bytes-like object, "
                f"not {type(data).__name__!r}"
            )
        if self._eof:
            raise RuntimeError("Cannot call write() after write_eof()")
        if self._empty_waiter is not None:
            raise RuntimeError("unable to write; sendfile is in progress")
        if not data:
            return

        if self._conn_lost:
            if self._conn_lost >= constants.LOG_THRESHOLD_FOR_CONNLOST_WRITES:
                logger.warning("socket.send() raised exception.")
            self._conn_lost += 1
            return

        if not self._buffer:
            # Optimization: try to send now.
            try:
                n = self._sock.send(data)
            except (BlockingIOError, InterruptedError):
                pass
            except (SystemExit, KeyboardInterrupt):
                raise
            except BaseException as exc:
                self._fatal_error(exc, "Fatal write error on socket transport")
                return
            else:
                data = memoryview(data)[n:]
                if not data:
                    return
            # Not all was written; register write handler.
            self._loop._add_writer(self._sock_fd, self._write_ready)

        # Add it to the buffer.
        self._buffer.append(data)
        self._maybe_pause_protocol()

    def _get_sendmsg_buffer(self):
        return itertools.islice(self._buffer, SC_IOV_MAX)

    def _write_sendmsg(self):
        assert self._buffer, "Data should not be empty"
        if self._conn_lost:
            return
        try:
            nbytes = self._sock.sendmsg(self._get_sendmsg_buffer())
            self._adjust_leftover_buffer(nbytes)
        except (BlockingIOError, InterruptedError):
            pass
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            self._loop._remove_writer(self._sock_fd)
            self._buffer.clear()
            self._fatal_error(exc, "Fatal write error on socket transport")
            if self._empty_waiter is not None:
                self._empty_waiter.set_exception(exc)
        else:
            self._maybe_resume_protocol()  # May append to buffer.
            if not self._buffer:
                self._loop._remove_writer(self._sock_fd)
                if self._empty_waiter is not None:
                    self._empty_waiter.set_result(None)
                if self._closing:
                    self._call_connection_lost(None)
                elif self._eof:
                    self._sock.shutdown(socket.SHUT_WR)

    def _adjust_leftover_buffer(self, nbytes: int) -> None:
        buffer = self._buffer
        while nbytes:
            b = buffer.popleft()
            b_len = len(b)
            if b_len <= nbytes:
                nbytes -= b_len
            else:
                buffer.appendleft(b[nbytes:])
                break

    def _write_send(self):
        assert self._buffer, "Data should not be empty"
        if self._conn_lost:
            return
        try:
            buffer = self._buffer.popleft()
            n = self._sock.send(buffer)
            if n != len(buffer):
                # Not all data was written
                self._buffer.appendleft(buffer[n:])
        except (BlockingIOError, InterruptedError):
            pass
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            self._loop._remove_writer(self._sock_fd)
            self._buffer.clear()
            self._fatal_error(exc, "Fatal write error on socket transport")
            if self._empty_waiter is not None:
                self._empty_waiter.set_exception(exc)
        else:
            self._maybe_resume_protocol()  # May append to buffer.
            if not self._buffer:
                self._loop._remove_writer(self._sock_fd)
                if self._empty_waiter is not None:
                    self._empty_waiter.set_result(None)
                if self._closing:
                    self._call_connection_lost(None)
                elif self._eof:
                    self._sock.shutdown(socket.SHUT_WR)

    def write_eof(self):
        if self._closing or self._eof:
            return
        self._eof = True
        if not self._buffer:
            self._sock.shutdown(socket.SHUT_WR)

    def writelines(self, list_of_data):
        if self._eof:
            raise RuntimeError("Cannot call writelines() after write_eof()")
        if self._empty_waiter is not None:
            raise RuntimeError("unable to writelines; sendfile is in progress")
        if not list_of_data:
            return
        self._buffer.extend([memoryview(data) for data in list_of_data])
        self._write_ready()
        # If the entire buffer couldn't be written, register a write handler
        if self._buffer:
            self._loop._add_writer(self._sock_fd, self._write_ready)

    def can_write_eof(self):
        return True

    def _call_connection_lost(self, exc):
        super()._call_connection_lost(exc)
        if self._empty_waiter is not None:
            self._empty_waiter.set_exception(
                ConnectionError("Connection is closed by peer")
            )

    def _make_empty_waiter(self):
        if self._empty_waiter is not None:
            raise RuntimeError("Empty waiter is already set")
        self._empty_waiter = self._loop.create_future()
        if not self._buffer:
            self._empty_waiter.set_result(None)
        return self._empty_waiter

    def _reset_empty_waiter(self):
        self._empty_waiter = None

    def close(self):
        self._read_ready_cb = None
        self._write_ready = None
        super().close()
