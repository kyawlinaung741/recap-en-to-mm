"""Bounded producer/consumer pipeline for Recap's segment-based render stages.

The producer (normally sequential TTS + timing) runs on the caller thread.
The consumer (normally FFmpeg segment rendering) runs on one worker thread.
A bounded queue applies back-pressure so audio/video work cannot grow without
limit in RAM or on disk. Results are returned in input order.
"""
from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterable
from typing import TypeVar

ItemT = TypeVar("ItemT")
PayloadT = TypeVar("PayloadT")
ResultT = TypeVar("ResultT")

_STOP = object()


def run_ordered_pipeline(
    items: Iterable[ItemT],
    *,
    produce: Callable[[ItemT], PayloadT],
    consume: Callable[[PayloadT], ResultT],
    max_pending: int = 2,
    should_stop: Callable[[], bool] | None = None,
) -> list[ResultT]:
    """Run one producer and one consumer concurrently with bounded buffering.

    The producer is deliberately single-threaded (safe for TTS engines);
    consume runs on a dedicated worker. Results preserve source order.
    """
    if max_pending < 1:
        raise ValueError("max_pending must be at least 1")

    pending: queue.Queue[object] = queue.Queue(maxsize=int(max_pending))
    stopped = threading.Event()
    results: list[tuple[int, ResultT]] = []
    worker_errors: list[BaseException] = []
    producer_stopped = False

    def consumer_loop() -> None:
        try:
            while True:
                entry = pending.get()
                try:
                    if entry is _STOP:
                        return
                    index, payload = entry  # type: ignore[misc]
                    results.append((index, consume(payload)))  # type: ignore[arg-type]
                finally:
                    pending.task_done()
        except BaseException as exc:
            worker_errors.append(exc)
            stopped.set()

    worker = threading.Thread(
        target=consumer_loop,
        name="recap-render-consumer",
        daemon=True,
    )
    worker.start()

    producer_error: BaseException | None = None
    produced_count = 0
    try:
        for item in items:
            if stopped.is_set():
                producer_stopped = True
                break
            if should_stop is not None and should_stop():
                producer_stopped = True
                stopped.set()
                break
            payload = produce(item)
            while not stopped.is_set():
                if should_stop is not None and should_stop():
                    producer_stopped = True
                    stopped.set()
                    break
                try:
                    pending.put((produced_count, payload), timeout=0.1)
                    produced_count += 1
                    break
                except queue.Full:
                    continue
            if stopped.is_set():
                producer_stopped = True
                break
    except BaseException as exc:
        producer_error = exc
        stopped.set()
    finally:
        if worker.is_alive():
            while worker.is_alive():
                try:
                    pending.put(_STOP, timeout=0.1)
                    break
                except queue.Full:
                    if worker_errors:
                        break
        worker.join()

    if worker_errors:
        raise worker_errors[0]
    if producer_error is not None:
        raise producer_error
    if producer_stopped or (should_stop is not None and should_stop()):
        raise InterruptedError("Parallel pipeline stopped by request.")

    ordered = sorted(results, key=lambda pair: pair[0])
    if len(ordered) != produced_count:
        raise RuntimeError(
            f"Parallel pipeline lost results: produced={produced_count}, consumed={len(ordered)}"
        )
    return [value for _, value in ordered]
