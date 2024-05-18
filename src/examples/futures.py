from loop import MyEventLoop


def on_future_done(future):
    print(f"Future is done! Result: {future.result()}")


loop = MyEventLoop()

future = loop.create_future()

future.add_done_callback(on_future_done)

loop.call_later(1, future.set_result, 42)
loop.run_until_complete(future)
