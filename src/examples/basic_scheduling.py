from loop import MyEventLoop
import time

t0 = time.time()
loop = MyEventLoop()
loop.call_soon(
    lambda: print(
        "Should be called immediately, "
        f"it's {time.time() - t0:0.02f} seconds since start"
    )
)
loop.call_later(
    5,
    lambda: print(
        "5 seconds should have passed, "
        f"it's {time.time() - t0:0.02f} seconds since start"
    ),
)
print(f"Starting, {time.time() - t0:0.02f} seconds since start")
loop.run_forever()
