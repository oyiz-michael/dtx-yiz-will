from flask import Flask, jsonify
from prometheus_flask_exporter import PrometheusMetrics
import os

app = Flask(__name__)
metrics = PrometheusMetrics(app)

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
