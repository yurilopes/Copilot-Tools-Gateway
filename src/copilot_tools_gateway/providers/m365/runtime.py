"""Async runtime helpers for synchronous provider methods."""

import asyncio
import threading
from collections.abc import AsyncIterator, Callable, Coroutine, Iterator
from dataclasses import dataclass
from queue import Queue
from typing import Generic, TypeVar

AsyncResult = TypeVar("AsyncResult")


@dataclass
class AsyncThreadResult(Generic[AsyncResult]):
    value: AsyncResult | None = None
    error: BaseException | None = None


@dataclass(frozen=True)
class AsyncIteratorItem(Generic[AsyncResult]):
    value: AsyncResult


@dataclass(frozen=True)
class AsyncIteratorError:
    error: BaseException


ASYNC_ITERATOR_DONE = object()


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


def run_async_iter(
    factory: Callable[[], AsyncIterator[AsyncResult]],
) -> Iterator[AsyncResult]:
    queue: Queue[AsyncIteratorItem[AsyncResult] | AsyncIteratorError | object] = Queue()

    async def consume() -> None:
        try:
            async for item in factory():
                queue.put(AsyncIteratorItem(item))
        except BaseException as exc:
            queue.put(AsyncIteratorError(exc))
        finally:
            queue.put(ASYNC_ITERATOR_DONE)

    def run_in_thread() -> None:
        asyncio.run(consume())

    thread = threading.Thread(target=run_in_thread)
    thread.start()
    while True:
        item = queue.get()
        if item is ASYNC_ITERATOR_DONE:
            break
        if isinstance(item, AsyncIteratorError):
            thread.join()
            raise item.error
        if isinstance(item, AsyncIteratorItem):
            yield item.value
    thread.join()
