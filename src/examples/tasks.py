from ..loop import MyEventLoop
from .. import my_asyncio


async def main():
    print("Hello")
    await my_asyncio.sleep(1)
    print("World")


if __name__ == "__main__":
    loop = MyEventLoop()
    loop.run_until_complete(main())
