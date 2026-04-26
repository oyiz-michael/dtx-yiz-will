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


configure_tracing("dtx-app")

tracer = trace.get_tracer("dtx.app")
VERSION = os.getenv("APP_VERSION", "v1")


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
        db_latency = simulate_dependency("home.fetch_profile", 15, 60)
        cache_latency = simulate_dependency("home.cache_read", 5, 25)
        return jsonify({
            "status": "ok",
            "message": "Welcome to the DTX app!",
            "version": VERSION,
            "trace_id": current_trace_id(),
            "timings_ms": {
                "fetch_profile": db_latency,
                "cache_read": cache_latency,
            },
        })

@app.route("/health")
def health():
    with tracer.start_as_current_span("health.logic"):
        return jsonify({"status": "healthy", "trace_id": current_trace_id()}), 200

@app.route("/data")
def data():
    with tracer.start_as_current_span("data.logic") as span:
        span.set_attribute("data.page", 1)
        upstream_latency = simulate_dependency("data.fetch_inventory", 40, 120)
        enrich_latency = simulate_dependency("data.enrich_response", 10, 35)
        return jsonify({
            "items": ["item1", "item2", "item3"],
            "version": VERSION,
            "trace_id": current_trace_id(),
            "timings_ms": {
                "fetch_inventory": upstream_latency,
                "enrich_response": enrich_latency,
            },
        })


@app.route("/journey")
def journey():
    steps = max(1, min(int(request.args.get("steps", "3")), 10))
    stage_timings = []
    with tracer.start_as_current_span("journey.logic") as span:
        span.set_attribute("journey.steps", steps)
        for index in range(steps):
            stage_name = f"journey.step.{index + 1}"
            stage_timings.append(
                {
                    "stage": stage_name,
                    "latency_ms": simulate_dependency(stage_name, 20, 80),
                }
            )
        return jsonify(
            {
                "status": "ok",
                "version": VERSION,
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
    <title>DTX App Trace Playground</title>
    <style>
      body { font-family: ui-sans-serif, -apple-system, sans-serif; margin: 2rem; background: #f5f7fb; color: #1f2937; }
      h1 { margin-bottom: 0.3rem; }
      p { margin-top: 0; }
      .row { display: flex; flex-wrap: wrap; gap: 0.6rem; margin-bottom: 1rem; }
      button { padding: 0.6rem 0.9rem; border-radius: 0.6rem; border: 1px solid #c7d2fe; background: #eef2ff; cursor: pointer; }
      button:hover { background: #e0e7ff; }
      pre { background: #0f172a; color: #e2e8f0; padding: 1rem; border-radius: 0.75rem; overflow: auto; min-height: 220px; }
      .hint { font-size: 0.9rem; color: #475569; }
    </style>
  </head>
  <body>
    <h1>DTX App Trace Playground</h1>
    <p>Generate richer traces with one click and inspect the returned trace ID.</p>
    <div class="row">
      <button onclick="callApi('/')">Call /</button>
      <button onclick="callApi('/data')">Call /data</button>
      <button onclick="callApi('/journey?steps=5')">Call /journey?steps=5</button>
      <button onclick="callApi('/health')">Call /health</button>
    </div>
    <div class="hint">Open Grafana Tempo and filter by service.name=dtx-app while clicking buttons.</div>
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
