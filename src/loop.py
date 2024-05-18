from asyncio import (
    AbstractEventLoop,
    BaseEventLoop,
    BaseProtocol,
    Future,
    Handle,
    TimerHandle,
    events,
    futures,
    tasks,
)
from asyncio.log import logger
import bisect
from collections import deque
import collections
from collections.abc import Callable
import collections.abc
from contextvars import Context
import errno
import itertools
import os
import socket
import stat
import sys
import time
from typing import Any
import selectors

from selector_transport import _SelectorSocketTransport


class MyEventLoop(AbstractEventLoop):
    def __init__(self):
        self._should_stop = False
        self._running = False
        self._task_factory = None
        self._scheduled_handles = deque[TimerHandle]()
        self._ready_handles = deque[Handle]()
        self._selector = selectors.DefaultSelector()

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
        # Move scheduled handles that are ready to the ready queue
        now = self.time()
        while (
            len(self._scheduled_handles) > 0
            and self._scheduled_handles[0].when() <= now
        ):
            handle = self._scheduled_handles.popleft()
            if handle.cancelled():
                print(f"Skipping cancelled handle {handle}")
                continue
            print(f"Adding handle {handle} to ready queue")
            self._ready_handles.append(handle)

        # Select on the selector, effectively adding ready handles
        # Computing the timeout value is interesting
        events = self._selector.select(0)
        self._process_selector_events(events)

        # Run the ready handles
        while len(self._ready_handles) > 0:
            handle = self._ready_handles.popleft()
            print(f"Running handle {handle}")
            handle._run()

    def run_until_complete(self, future_: Future):
        future = tasks.ensure_future(future_, loop=self)
        # future.add_done_callback(lambda _: print("Future is done"))
        self._running = True
        events._set_running_loop(self)
        try:
            while not future.done():
                self._run_once()
        except Exception as e:
            print(f"Exception: {e}")
            raise
        finally:
            self._running = False
            events._set_running_loop(None)
        return future.result()

    def is_running(self):
        return self._running

    def is_closed(self):
        # This is a big assumption, but we'll go with it for now
        return not self._running

    def stop(self):
        self._should_stop = True

    def close(self):
        assert not self._running, "Cannot close a running event loop"
        # TODO: clear task queues and shutdown executor

    def get_debug(self) -> bool:
        # FIXME: this should depend on the calls to set_debug and the PYTHONASYNCIODEBUG env var
        return True

    def create_future(self) -> Future[Any]:
        # We could reimplement our own Future class here, but for now we'll just use the one from asyncio
        return futures.Future(loop=self)

    def create_task(
        self,
        coro,
        *,
        name=None,
        context=None,
    ):
        if self._task_factory is not None:
            task = self._task_factory(self, coro, name=name, context=context)
        else:
            task = tasks.Task(coro, loop=self, name=name, context=context)

        return task

    def set_task_factory(self, factory):
        self._task_factory = factory

    def get_task_factory(self):
        return self._task_factory

    def _timer_handle_cancelled(self, handle):
        # Required when using sleep
        pass

    def _add_reader(self, fd, callback, *args) -> None:
        """This implementation is mostly taken from the BaseSelectorEventLoop one"""
        print(f"Adding reader for fd {fd}")
        handle = Handle(callback, args, self)
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            # Register the file descriptor for read events in the selector
            self._selector.register(fd, selectors.EVENT_READ, (handle, None))
        else:
            # The file descriptor is already registered, add the callback to the existing key
            mask, (previous_handle, writer) = key.events, key.data
            self._selector.modify(fd, mask | selectors.EVENT_READ, (handle, writer))
            if previous_handle is not None:
                previous_handle.cancel()
        return handle

    def _remove_reader(self, fd) -> bool:
        """This implementation is mostly taken from the BaseSelectorEventLoop one
        This function should return True iff the file descriptor was monitored for reads.
        """

        try:
            key = self._selector.get_key(fd)
        except KeyError:
            return False

        mask, (reader, writer) = key.events, key.data
        mask &= ~selectors.EVENT_READ
        if mask == 0:
            # No more events left, remove the file descriptor from the selector
            self._selector.unregister(fd)
        else:
            self._selector.modify(fd, mask, (None, writer))

        if reader is not None:
            # Cancel the existing read handle
            reader.cancel()
            return True
        return False

    def _add_writer(self, fd, callback, *args) -> None:
        """This implementation is mostly taken from the BaseSelectorEventLoop one"""
        handle = Handle(callback, args, self)
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            # Register the file descriptor for write events in the selector
            self._selector.register(fd, selectors.EVENT_WRITE, (None, handle))
        else:
            # The file descriptor is already registered, add the callback to the existing key
            mask, (reader, previous_handle) = key.events, key.data
            self._selector.modify(fd, mask | selectors.EVENT_WRITE, (reader, handle))
            if previous_handle is not None:
                previous_handle.cancel()
        return handle

    def _remove_writer(self, fd) -> bool:
        """This implementation is mostly taken from the BaseSelectorEventLoop one
        This function should return True iff the file descriptor was monitored for writes.
        """

        try:
            key = self._selector.get_key(fd)
        except KeyError:
            return False

        mask, (reader, writer) = key.events, key.data
        mask &= ~selectors.EVENT_WRITE
        if mask == 0:
            # No more events left, remove the file descriptor from the selector
            self._selector.unregister(fd)
        else:
            self._selector.modify(fd, mask, (reader, None))

        if writer is not None:
            # Cancel the existing write handle
            writer.cancel()
            return True
        return False

    def add_writer(self, fd, callback, *args):
        self._add_writer(fd, callback, *args)

    def remove_writer(self, fd):
        self._remove_writer(fd)

    def add_reader(self, fd, callback, *args):
        self._add_reader(fd, callback, *args)

    def remove_reader(self, fd):
        self._remove_reader(fd)

    def _process_selector_events(self, events: list[(selectors.SelectorKey, int)]):
        for key, mask in events:
            fileobj, (reader, writer) = key.fileobj, key.data
            if mask & selectors.EVENT_READ and reader is not None:
                if reader._cancelled:
                    self._remove_reader(fileobj)
                else:
                    self._ready_handles.append(reader)
            if mask & selectors.EVENT_WRITE and writer is not None:
                if writer._cancelled:
                    self._remove_writer(fileobj)
                else:
                    self._ready_handles.append(writer)

    async def create_server(
        self,
        protocol_factory,
        host=None,
        port=None,
        *,
        family=socket.AF_UNSPEC,
        flags=socket.AI_PASSIVE,
        sock=None,
        backlog=100,
        ssl=None,
        reuse_address=None,
        reuse_port=None,
    ):
        """Mostly taken from the BaseEventLoop implementation"""
        if isinstance(ssl, bool):
            raise TypeError("ssl argument must be an SSLContext or None")

        if host is not None or port is not None:
            if sock is not None:
                raise ValueError(
                    "host/port and sock can not be specified at the same time"
                )

            if reuse_address is None:
                reuse_address = os.name == "posix" and sys.platform != "cygwin"
            sockets = []
            if host == "":
                hosts = [None]
            elif isinstance(host, str) or not isinstance(
                host, collections.abc.Iterable
            ):
                hosts = [host]
            else:
                hosts = host

            fs = [
                self._create_server_getaddrinfo(host, port, family=family, flags=flags)
                for host in hosts
            ]
            infos = await tasks.gather(*fs)
            infos = set(itertools.chain.from_iterable(infos))

            completed = False
            try:
                for res in infos:
                    af, socktype, proto, canonname, sa = res
                    try:
                        sock = socket.socket(af, socktype, proto)
                    except socket.error:
                        # Assume it's a bad family/type/protocol combination.
                        if self._debug:
                            logger.warning(
                                "create_server() failed to create "
                                "socket.socket(%r, %r, %r)",
                                af,
                                socktype,
                                proto,
                                exc_info=True,
                            )
                        continue
                    sockets.append(sock)
                    if reuse_address:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)

                    # TODO: might be needed?
                    # if reuse_port:
                    #     _set_reuseport(sock)

                    # Disable IPv4/IPv6 dual stack support (enabled by
                    # default on Linux) which makes a single socket
                    # listen on both address families.
                    _HAS_IPv6 = hasattr(socket, "AF_INET6")
                    if (
                        _HAS_IPv6
                        and af == socket.AF_INET6
                        and hasattr(socket, "IPPROTO_IPV6")
                    ):
                        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, True)
                    try:
                        sock.bind(sa)
                    except OSError as err:
                        msg = "error while attempting " "to bind on address %r: %s" % (
                            sa,
                            err.strerror.lower(),
                        )
                        if err.errno == errno.EADDRNOTAVAIL:
                            # Assume the family is not enabled (bpo-30945)
                            sockets.pop()
                            sock.close()
                            if self._debug:
                                logger.warning(msg)
                            continue
                        raise OSError(err.errno, msg) from None

                if not sockets:
                    raise OSError(
                        "could not bind on any address out of %r"
                        % ([info[4] for info in infos],)
                    )

                completed = True
            finally:
                if not completed:
                    for sock in sockets:
                        sock.close()
        else:
            if sock is None:
                raise ValueError("Neither host/port nor sock were specified")
            if sock.type != socket.SOCK_STREAM:
                raise ValueError(f"A Stream Socket was expected, got {sock!r}")
            sockets = [sock]

        for sock in sockets:
            sock.setblocking(False)

        server = MyServer(
            self,
            sockets,
            protocol_factory,
        )
        server._start_serving()
        # Skip one loop iteration so that all 'loop.add_reader'
        # go through.
        await tasks.sleep(0)

        logger.info("%r is serving", server)
        return server

    async def create_unix_server(
        self,
        protocol_factory,
        path=None,
        *,
        sock=None,
    ):
        """
        Simplified implementation of create_unix_server.
        Many kwargs are not supported here.
        """
        if path is not None:
            if sock is not None:
                raise ValueError("path and sock can not be specified at the same time")

            path = os.fspath(path)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

            # Check for abstract socket. `str` and `bytes` paths are supported.
            if path[0] not in (0, "\x00"):
                try:
                    if stat.S_ISSOCK(os.stat(path).st_mode):
                        os.remove(path)
                except FileNotFoundError:
                    pass
                except OSError as err:
                    # Directory may have permissions only to create socket.
                    print(
                        "Unable to check or remove stale UNIX socket " "%r: %r",
                        path,
                        err,
                    )

            try:
                sock.bind(path)
            except OSError as exc:
                sock.close()
                if exc.errno == errno.EADDRINUSE:
                    # Let's improve the error message by adding
                    # with what exact address it occurs.
                    msg = f"Address {path!r} is already in use"
                    raise OSError(errno.EADDRINUSE, msg) from None
                else:
                    raise
            except:
                sock.close()
                raise
        else:
            if sock is None:
                raise ValueError("path was not specified, and no sock specified")

            if sock.family != socket.AF_UNIX or sock.type != socket.SOCK_STREAM:
                raise ValueError(
                    f"A UNIX Domain Stream Socket was expected, got {sock!r}"
                )

        sock.setblocking(False)
        server = MyServer(
            self,
            [sock],
            protocol_factory,
        )
        # Start serving by default
        server._start_serving()
        # Skip one loop iteration so that all 'loop.add_reader'
        # go through.
        await tasks.sleep(0)

        return server


class MyServer(events.AbstractServer):
    def __init__(
        self,
        loop: BaseEventLoop,
        sockets: list[socket.socket],
        protocol_factory: Callable[[], BaseProtocol],
    ):
        self._loop = loop
        self._sockets = sockets
        self._protocol_factory = protocol_factory

    def _start_serving(self):
        for sock in self._sockets:
            sock.listen(100)  # TODO: Why?
            self._loop.add_reader(sock.fileno(), self._accept_connection, sock)
        print("Started serving")

    def _accept_connection(self, sock: socket.socket):
        print("Accepting connection")
        conn, addr = sock.accept()
        print(f"Accepted connection from {addr}")
        self._loop.create_task(self._register_socket_transport(conn))

    async def _register_socket_transport(self, conn: socket.socket):
        print("Registering socket transport")
        waiter = self._loop.create_future()
        protocol = self._protocol_factory()
        transport = _SelectorSocketTransport(self._loop, conn, protocol, waiter=waiter)
        print("Created transport")
        await waiter
        print("Transport ready")

    def close(self):
        for sock in self._sockets:
            self._loop.remove_reader(sock)
            sock.close()
