from flask import Flask, jsonify
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

VERSION = os.getenv("APP_VERSION", "v2-broken")

# Simulate a memory leak
_leak = []

def leak_memory():
    while True:
        _leak.append(" " * 1024 * 100)  # leak 100KB every 2 seconds
        time.sleep(2)

threading.Thread(target=leak_memory, daemon=True).start()

@app.route("/")
def home():
    # 50% chance of returning a 500
    if random.random() < 0.5:
        return jsonify({"status": "error", "message": "Internal Server Error"}), 500

    return jsonify({
        "status": "ok",
        "message": "Welcome to the DTX app!",
        "version": VERSION
    })

@app.route("/health")
def health():
    # health check randomly fails too
    if random.random() < 0.4:
        return jsonify({"status": "unhealthy", "reason": "random failure"}), 500
    return jsonify({"status": "healthy"}), 200

@app.route("/data")
def data():
    # simulate slow response
    time.sleep(random.uniform(3, 8))
    return jsonify({
        "items": ["item1", "item2", "item3"],
        "version": VERSION
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
