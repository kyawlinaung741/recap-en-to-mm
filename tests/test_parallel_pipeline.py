import threading
import time
import unittest
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from parallel_pipeline import run_ordered_pipeline


class ParallelPipelineTests(unittest.TestCase):
    def test_producer_and_consumer_overlap_and_keep_order(self):
        consumer_started = threading.Event()

        def produce(value):
            if value == 2:
                self.assertTrue(consumer_started.wait(1.0))
            return value * 10

        def consume(value):
            consumer_started.set()
            time.sleep(0.01)
            return value + 1

        result = run_ordered_pipeline(
            range(5), produce=produce, consume=consume, max_pending=2
        )
        self.assertEqual(result, [1, 11, 21, 31, 41])

    def test_consumer_exception_is_returned_to_caller(self):
        def consume(value):
            if value == 2:
                raise ValueError("render failed")
            return value

        with self.assertRaisesRegex(ValueError, "render failed"):
            run_ordered_pipeline(
                range(10), produce=lambda value: value,
                consume=consume, max_pending=1
            )

    def test_invalid_queue_size(self):
        with self.assertRaises(ValueError):
            run_ordered_pipeline(
                [], produce=lambda value: value,
                consume=lambda value: value, max_pending=0
            )

    def test_producer_exception_is_returned_to_caller(self):
        def produce(value):
            if value == 2:
                raise RuntimeError("tts failed")
            return value

        with self.assertRaisesRegex(RuntimeError, "tts failed"):
            run_ordered_pipeline(
                range(10), produce=produce,
                consume=lambda value: value, max_pending=1
            )

    def test_stop_requested_before_production(self):
        produced = []

        def produce(value):
            produced.append(value)
            return value

        with self.assertRaises(InterruptedError):
            run_ordered_pipeline(
                range(5), produce=produce, consume=lambda value: value,
                max_pending=1, should_stop=lambda: True
            )
        self.assertEqual(produced, [])


if __name__ == "__main__":
    unittest.main()
