from flask import Flask, jsonify, make_response, request
from prometheus_flask_exporter import PrometheusMetrics
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
import os
import random
import time
import threading

app = Flask(__name__)
metrics = PrometheusMetrics(app)


def configure_tracing(default_service_name: str):
    resource = Resource.create(
        {SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", default_service_name)}
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=os.getenv(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "http://tempo.monitoring.svc.cluster.local:4318/v1/traces",
        )
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FlaskInstrumentor().instrument_app(app)


configure_tracing("dtx-app-broken")

tracer = trace.get_tracer("dtx.app.broken")
VERSION = os.getenv("APP_VERSION", "v2-broken")

# Simulate a memory leak
_leak = []

def leak_memory():
    while True:
        _leak.append(" " * 1024 * 100)  # leak 100KB every 2 seconds
        time.sleep(2)

threading.Thread(target=leak_memory, daemon=True).start()


def current_trace_id() -> str:
    span = trace.get_current_span()
    context = span.get_span_context()
    if not context.is_valid:
        return "no-trace"
    return format(context.trace_id, "032x")


@app.after_request
def add_trace_headers(response):
    response.headers["X-Trace-Id"] = current_trace_id()
    return response


def simulate_dependency(span_name: str, min_ms: int, max_ms: int) -> int:
    with tracer.start_as_current_span(span_name) as span:
        latency_ms = random.randint(min_ms, max_ms)
        time.sleep(latency_ms / 1000.0)
        span.set_attribute("app.simulated_latency_ms", latency_ms)
        return latency_ms

@app.route("/")
def home():
    with tracer.start_as_current_span("home.logic") as span:
        span.set_attribute("app.version", VERSION)
        simulate_dependency("home.fetch_profile", 30, 130)

        # 50% chance of returning a 500
        if random.random() < 0.5:
            span.set_attribute("app.failure", True)
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Internal Server Error",
                        "version": VERSION,
                        "trace_id": current_trace_id(),
                    }
                ),
                500,
            )

        return jsonify(
            {
                "status": "ok",
                "message": "Welcome to the DTX broken app!",
                "version": VERSION,
                "trace_id": current_trace_id(),
            }
        )

@app.route("/health")
def health():
    with tracer.start_as_current_span("health.logic") as span:
        # health check randomly fails too
        if random.random() < 0.4:
            span.set_attribute("app.health_failure", True)
            return jsonify({"status": "unhealthy", "reason": "random failure", "trace_id": current_trace_id()}), 500
        return jsonify({"status": "healthy", "trace_id": current_trace_id()}), 200

@app.route("/data")
def data():
    with tracer.start_as_current_span("data.logic") as span:
        fetch_ms = simulate_dependency("data.fetch_inventory", 800, 2600)
        process_ms = simulate_dependency("data.process_inventory", 300, 900)
        # additional random delay to create interesting trace variability
        jitter_ms = random.randint(500, 2000)
        time.sleep(jitter_ms / 1000.0)
        span.set_attribute("data.jitter_ms", jitter_ms)
        return jsonify(
            {
                "items": ["item1", "item2", "item3"],
                "version": VERSION,
                "trace_id": current_trace_id(),
                "timings_ms": {
                    "fetch_inventory": fetch_ms,
                    "process_inventory": process_ms,
                    "jitter": jitter_ms,
                },
            }
        )


@app.route("/chaos")
def chaos():
    failure_rate = max(0.0, min(float(request.args.get("failure_rate", "0.35")), 1.0))
    steps = max(1, min(int(request.args.get("steps", "4")), 12))
    with tracer.start_as_current_span("chaos.logic") as span:
        span.set_attribute("chaos.failure_rate", failure_rate)
        span.set_attribute("chaos.steps", steps)
        stage_timings = []
        for index in range(steps):
            stage_name = f"chaos.step.{index + 1}"
            stage_timings.append(
                {
                    "stage": stage_name,
                    "latency_ms": simulate_dependency(stage_name, 40, 180),
                }
            )

        if random.random() < failure_rate:
            span.set_attribute("chaos.failed", True)
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Chaos endpoint failed by design",
                        "trace_id": current_trace_id(),
                        "steps": steps,
                        "stage_timings": stage_timings,
                    }
                ),
                500,
            )

        return jsonify(
            {
                "status": "ok",
                "message": "Chaos endpoint completed",
                "trace_id": current_trace_id(),
                "steps": steps,
                "stage_timings": stage_timings,
            }
        )


@app.route("/ui")
def ui():
    html = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>DTX Broken App Trace Playground</title>
    <style>
      body { font-family: ui-sans-serif, -apple-system, sans-serif; margin: 2rem; background: #fff7ed; color: #1f2937; }
      h1 { margin-bottom: 0.3rem; }
      p { margin-top: 0; }
      .row { display: flex; flex-wrap: wrap; gap: 0.6rem; margin-bottom: 1rem; }
      button { padding: 0.6rem 0.9rem; border-radius: 0.6rem; border: 1px solid #fdba74; background: #ffedd5; cursor: pointer; }
      button:hover { background: #fed7aa; }
      pre { background: #111827; color: #f3f4f6; padding: 1rem; border-radius: 0.75rem; overflow: auto; min-height: 220px; }
      .hint { font-size: 0.9rem; color: #7c2d12; }
    </style>
  </head>
  <body>
    <h1>DTX Broken App Trace Playground</h1>
    <p>Generate slow and failing traces intentionally for Tempo demos.</p>
    <div class="row">
      <button onclick="callApi('/')">Call /</button>
      <button onclick="callApi('/data')">Call /data (slow)</button>
      <button onclick="callApi('/chaos?steps=6&failure_rate=0.5')">Call /chaos</button>
      <button onclick="callApi('/health')">Call /health</button>
    </div>
    <div class="hint">In Grafana Tempo, filter service.name=dtx-app-broken and compare successful vs failed spans.</div>
    <pre id="out">Waiting for request...</pre>
    <script>
      async function callApi(path) {
        const t0 = performance.now();
        const res = await fetch(path);
        const body = await res.json();
        const elapsed = (performance.now() - t0).toFixed(1);
        const traceId = res.headers.get('X-Trace-Id') || 'none';
        document.getElementById('out').textContent = JSON.stringify({
          path,
          status: res.status,
          elapsed_ms: Number(elapsed),
          trace_id_header: traceId,
          body,
        }, null, 2);
      }
    </script>
  </body>
</html>
"""
    return make_response(html, 200)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
