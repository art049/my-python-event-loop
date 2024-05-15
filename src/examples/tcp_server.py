"""
Usage:
    python3 -m examples.unix_server
Client:
    socat - UNIX-CONNECT:/tmp/echo.sock
"""

from asyncio import Protocol
import asyncio


class HelloWorldProtocol(Protocol):
    def connection_made(self, transport):
        self.transport = transport

    def connection_lost(self, exc):
        self.transport = None

    def data_received(self, data):
        string = data.decode().strip()
        print(f"Received data: {string}")
        if string == "hello":
            self.transport.write(b"world")
            self.transport.close()


USE_MY_ASYNCIO = True

if USE_MY_ASYNCIO:
    print("Using custom asyncio implementation")
    from loop import MyEventLoop

    loop = MyEventLoop()
else:
    print("Using asyncio module")
    loop = asyncio.new_event_loop()

loop.create_task(loop.create_unix_server(HelloWorldProtocol, "/tmp/echo.sock"))
loop.run_forever()
