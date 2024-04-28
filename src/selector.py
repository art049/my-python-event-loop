from collections.abc import Mapping
from selectors import _EventMask, BaseSelector, SelectorKey
from typing import Any


class MySelector(BaseSelector):

    def __init__():


    def register(self, fileobj: int, events: int, data: Any = None) -> SelectorKey:
        ...

    def unregister(self, fileobj: _EventMask) -> SelectorKey:
        return super().unregister(fileobj)

    def get_map(self) -> Mapping[int, SelectorKey]:
        return super().get_map()






