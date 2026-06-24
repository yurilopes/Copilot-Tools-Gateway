"""Async runtime helpers for synchronous provider methods."""

import asyncio
import threading
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Generic, TypeVar

AsyncResult = TypeVar("AsyncResult")


@dataclass
class AsyncThreadResult(Generic[AsyncResult]):
    value: AsyncResult | None = None
    error: BaseException | None = None


def run_async(coroutine: Coroutine[object, object, AsyncResult]) -> AsyncResult:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    result: AsyncThreadResult[AsyncResult] = AsyncThreadResult()

    def run_in_thread() -> None:
        try:
            result.value = asyncio.run(coroutine)
        except BaseException as exc:
            result.error = exc

    thread = threading.Thread(target=run_in_thread)
    thread.start()
    thread.join()
    if result.error is not None:
        raise result.error
    if result.value is None:
        raise RuntimeError("Async operation finished without a result")
    return result.value
