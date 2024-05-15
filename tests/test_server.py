from asyncio import BaseEventLoop, Protocol
from socket import AF_UNIX, SOCK_STREAM, socket
from tempfile import NamedTemporaryFile


def test_create_unix_server_send_call(loop: BaseEventLoop):
    socket_path = NamedTemporaryFile(suffix=".sock").name
    future = loop.create_future()

    class EchoProtocol(Protocol):
        def connection_made(self, transport):
            self.transport = transport

        def connection_lost(self, exc):
            self.transport = None

        def data_received(self, data):
            print(f"Received data: {data}")
            if data == b"hello":
                future.set_result("world")

    loop.create_task(loop.create_unix_server(EchoProtocol, socket_path))

    # Send some data to the unix server synchronously
    def send_data():
        client = socket(AF_UNIX, SOCK_STREAM)
        client.connect(socket_path)
        client.sendall(b"hello")

    loop.call_soon(send_data)

    result = loop.run_until_complete(future)
    assert result == "world"
