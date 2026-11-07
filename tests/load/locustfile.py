"""Load test for the UI/API. Usage: locust -f tests/load/locustfile.py --host http://127.0.0.1:8000"""

from locust import HttpUser, between, task


class Visitor(HttpUser):
    """Simulate someone opening the trace list and the details of the first one."""

    wait_time = between(0.5, 2)

    @task(3)
    def list_traces(self) -> None:
        self.client.get("/api/traces")

    @task(1)
    def open_first_trace(self) -> None:
        traces = self.client.get("/api/traces").json()
        if traces:
            self.client.get(f"/api/traces/{traces[0]['trace_id']}", name="/api/traces/[id]")

    @task(1)
    def index(self) -> None:
        self.client.get("/")
