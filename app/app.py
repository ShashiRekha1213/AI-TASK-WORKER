"""Simulated internal company system: a small payables web app (Flask).

Pages:  /payables/new (form)   /payables (list)
API:    /api/payables (JSON read-back, used by the verifier)
Admin:  /admin/reset, /admin/seed, /admin/fault  (test-only fault injection)
"""

import re, threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from werkzeug.serving import make_server
from . import db
from config import APP_HOST, APP_PORT

import logging

logging.getLogger("werkzeug").setLevel(logging.ERROR)
app = Flask(__name__)
FAULTS = {"fail_next_submit": 0, "rename_submit": False}


def _validate(form):
    errors = []
    if not form.get("vendor", "").strip():
        errors.append("Vendor is required.")
    if not form.get("invoice_no", "").strip():
        errors.append("Invoice number is required.")
    try:
        if float(form.get("amount", "")) <= 0:
            raise ValueError
    except ValueError:
        errors.append("Amount must be a positive number (digits only, e.g. 1234.50).")
    d = form.get("due_date", "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        errors.append("Due date must be in YYYY-MM-DD format.")
    else:
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            errors.append("Due date is not a valid date.")
    return errors


@app.get("/")
def index():
    return render_template("payables.html", rows=db.all_rows(), message=None)


@app.route("/payables/new", methods=["GET", "POST"])
def new_payable():
    ctx = dict(rename=FAULTS["rename_submit"], errors=[], values={}, success=None)
    if request.method == "POST":
        ctx["values"] = request.form
        if FAULTS["fail_next_submit"] > 0:
            FAULTS["fail_next_submit"] -= 1
            ctx["errors"] = ["503 Service Temporarily Unavailable - nothing was saved, please try again."]
            return render_template("new_payable.html", **ctx), 503
        errors = _validate(request.form)
        if errors:
            ctx["errors"] = errors
            return render_template("new_payable.html", **ctx), 400
        db.add(
            request.form["vendor"].strip(),
            request.form["invoice_no"].strip(),
            float(request.form["amount"]),
            request.form["due_date"],
        )
        ctx.update(success="Payable saved successfully.", values={})
    return render_template("new_payable.html", **ctx)


@app.get("/payables")
def payables():
    return render_template("payables.html", rows=db.all_rows(), message=None)


@app.get("/api/payables")
def api_payables():
    return jsonify(db.all_rows())


@app.post("/admin/reset")
def admin_reset():
    db.reset()
    FAULTS.update(fail_next_submit=0, rename_submit=False)
    return jsonify(ok=True)


@app.post("/admin/seed")
def admin_seed():
    r = request.get_json()
    db.add(r["vendor"], r["invoice_no"], float(r["amount"]), r["due_date"])
    return jsonify(ok=True)


@app.post("/admin/fault")
def admin_fault():
    FAULTS.update(request.get_json())
    return jsonify(FAULTS)


class ServerThread(threading.Thread):
    def __init__(self, host=APP_HOST, port=APP_PORT):
        super().__init__(daemon=True)
        self.srv = make_server(host, port, app, threaded=True)

    def run(self):
        self.srv.serve_forever()

    def stop(self):
        self.srv.shutdown()


def start_server():
    db.init()
    t = ServerThread()
    t.start()
    return t


if __name__ == "__main__":
    db.init()
    print(f"Company app running at http://{APP_HOST}:{APP_PORT}")
    app.run(host=APP_HOST, port=APP_PORT)
