"""Minimal interface every download destination must implement."""

from abc import ABC, abstractmethod

from d2a.core.message import Message


class Destination(ABC):
    """Minimal interface every download destination must implement."""

    @abstractmethod
    def download(self, messages: list[Message]) -> None:
        ...
