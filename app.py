"""Flask entry point wiring the rotables optimizer engine to a simple UI."""

from flask import Flask, jsonify, render_template, request

from rotables_optimizer.app import SimulationRunner

app = Flask(__name__)
runner = SimulationRunner()


@app.route("/")
def index():
    return render_template("index.html", status=runner.status())


@app.post("/api/simulation/start")
def start_simulation():
    started = runner.start()
    status = runner.status()
    status["started"] = started

    http_status = 202 if started else 409
    return jsonify(status), http_status


@app.get("/api/simulation/status")
def simulation_status():
    return jsonify(runner.status())


@app.post("/api/simulation/reset")
def reset_simulation():
    reset_ok = runner.reset()
    status = runner.status()
    status["reset"] = reset_ok

    http_status = 200 if reset_ok else 409
    return jsonify(status), http_status


@app.errorhandler(Exception)
def handle_error(exc):  # noqa: D401
    """Return JSON errors to the front-end."""
    return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
