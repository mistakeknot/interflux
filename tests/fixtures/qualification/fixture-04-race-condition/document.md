# counter.py — Concurrent Event Counter

```python
import threading
import time


class EventCounter:
    def __init__(self):
        self.counts = {}
        self.total = 0

    def record_event(self, event_type):
        if event_type not in self.counts:
            self.counts[event_type] = 0
        self.counts[event_type] += 1
        self.total += 1

    def get_summary(self):
        return {
            "counts": dict(self.counts),
            "total": self.total,
        }


def run_collectors(event_types, iterations=1000):
    counter = EventCounter()
    threads = []

    for event_type in event_types:
        t = threading.Thread(
            target=_collect_events,
            args=(counter, event_type, iterations),
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    return counter.get_summary()


def _collect_events(counter, event_type, n):
    for _ in range(n):
        counter.record_event(event_type)
        time.sleep(0.001)
```
