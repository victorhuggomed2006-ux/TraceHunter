"""Generate demo traces (one with an error) to try the web interface.

Run:  python examples/demo_data.py demo.db   and then   python -m tracehunter demo.db
"""

import sys

from tracehunter import SQLiteTraceRepository, Tracer


def main(path: str) -> None:
    tracer = Tracer(SQLiteTraceRepository(path))
    for i in range(5):
        with tracer.trace(f"question {i}"):
            with tracer.span("retrieve documents", {"query": f"question {i}"}):
                with tracer.span("embed query"):
                    pass
            with tracer.span("call model", {"model": "demo"}) as span:
                span.complete({"tokens": 100 + i})
    try:
        with tracer.trace("flow with an error"):
            with tracer.span("call tool"):
                raise TimeoutError("tool did not answer")
    except TimeoutError:
        pass  # the error is recorded in the trace


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "demo.db"
    main(target)
    print(f"Demo traces saved to {target}.")
