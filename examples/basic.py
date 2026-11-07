"""Minimal example: instrument a fictional RAG flow and record it in tracehunter.db.

Run:  python examples/basic.py   and then   python -m tracehunter tracehunter.db
"""

from tracehunter import SQLiteTraceRepository, Tracer

tracer = Tracer(SQLiteTraceRepository("tracehunter.db"))


@tracer.observe()
def retrieve(question: str, api_key: str) -> list:
    """Pretend to fetch documents; the api_key argument is masked in the record."""
    return ["doc-1", "doc-2"]


@tracer.observe(capture_io=False)
def private_step(text: str) -> str:
    """Record neither arguments nor result."""
    return text.upper()


def main() -> None:
    with tracer.trace("answer a question"):
        docs = retrieve("what is RAG?", api_key="sk-not-recorded")
        with tracer.span("call model", {"prompt": f"context: {docs}"}) as span:
            private_step("sensitive")
            span.complete({"tokens": 120})


if __name__ == "__main__":
    main()
    print("Trace saved to tracehunter.db. Open it with: python -m tracehunter tracehunter.db")
