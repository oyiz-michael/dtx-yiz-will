from flask import Flask, jsonify
import os
import random
import time
import threading

app = Flask(__name__)

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
