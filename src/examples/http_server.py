from fastapi import FastAPI
from hypercorn import Config
from hypercorn.asyncio import serve

from loop import MyEventLoop

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello World"}


loop = MyEventLoop()
config = Config()
loop.run_until_complete(serve(app, config))
