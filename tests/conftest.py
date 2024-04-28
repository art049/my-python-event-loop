from asyncio import SelectorEventLoop
import pytest
from loop import MyEventLoop


@pytest.fixture(
    scope="function",
    params=[
        pytest.param(MyEventLoop, id="my"),
        pytest.param(
            SelectorEventLoop,
            id="selector",
        ),
    ],
)
def loop(request):
    return request.param()
