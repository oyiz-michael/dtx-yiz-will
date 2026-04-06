from flask import Flask, jsonify
from prometheus_flask_exporter import PrometheusMetrics
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
import os

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

VERSION = os.getenv("APP_VERSION", "v1")

@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "message": "Welcome to the DTX app!",
        "version": VERSION
    })

@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200

@app.route("/data")
def data():
    return jsonify({
        "items": ["item1", "item2", "item3"],
        "version": VERSION
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
