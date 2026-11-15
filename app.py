import base64
import json
import os
import re
import urllib.request
from datetime import date
from functools import wraps

import boto3
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from supabase import create_client
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")

BEDROCK_MODEL = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0")

supabase_url = os.environ["SUPABASE_URL"].strip().rstrip("/").removesuffix("/rest/v1")
sb = create_client(supabase_url, os.environ["SUPABASE_KEY"].strip())
bedrock = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))


def current_user():
    """Return the logged-in user row or None."""
    uid = session.get("user_id")
    if not uid:
        return None
    res = sb.table("users").select("id,email,business_name").eq("id", uid).execute()
    return res.data[0] if res.data else None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required."}), 401
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def _b64_encode(obj):
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("utf-8")
    if isinstance(obj, dict):
        return {k: _b64_encode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_b64_encode(v) for v in obj]
    return obj


def call_bedrock(content_blocks, system_text):
    """Send text or document/image blocks to Amazon Bedrock Converse API."""
    token = os.getenv("AWS_BEARER_TOKEN_BEDROCK", "").strip()
    if token:
        region = os.getenv("AWS_REGION", "us-east-1")
        url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{BEDROCK_MODEL}/converse"
        payload = json.dumps({
            "system": [{"text": system_text}],
            "messages": [{"role": "user", "content": _b64_encode(content_blocks)}],
            "inferenceConfig": {"maxTokens": 800, "temperature": 0.2},
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode("utf-8"))
        return resp["output"]["message"]["content"][0]["text"]

    resp = bedrock.converse(
        modelId=BEDROCK_MODEL,
        system=[{"text": system_text}],
        messages=[{"role": "user", "content": content_blocks}],
        inferenceConfig={"maxTokens": 800, "temperature": 0.2},
    )
    return resp["output"]["message"]["content"][0]["text"]


def parse_json_block(text):
    """Extract JSON object from an LLM response."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group(0)) if match else {}


def calc_status(total, paid):
    if paid >= total and total > 0:
        return "paid"
    return "partial" if paid > 0 else "unpaid"


@app.context_processor
def inject_user():
    return {"user": current_user()}


# --- Auth Routes ---

@app.route("/auth")
def auth():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        rows = sb.table("users").select("*").eq("email", email).execute().data
        if not rows or not check_password_hash(rows[0]["password_hash"], password):
            flash("Invalid email or password.", "error")
            return redirect(url_for("login"))
        session["user_id"] = rows[0]["id"]
        flash(f"Welcome back, {rows[0]['business_name']}!", "success")
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        biz_name = request.form.get("business_name", "").strip() or "My SME Business"
        existing = sb.table("users").select("id").eq("email", email).execute().data
        if existing:
            flash("An account with that email already exists.", "error")
            return redirect(url_for("signup"))
        created = sb.table("users").insert({
            "email": email,
            "password_hash": generate_password_hash(password),
            "business_name": biz_name,
            "is_guest": False,
        }).execute().data[0]
        session["user_id"] = created["id"]
        flash(f"Welcome, {biz_name}!", "success")
        return redirect(url_for("dashboard"))
    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("dashboard"))


# --- Main Pages ---

@app.route("/")
def dashboard():
    user = current_user()
    if not user:
        return render_template("landing.html")
    rows = sb.table("invoices").select("*").eq("user_id", user["id"]).order("created_at", desc=True).execute().data
    sales = [r for r in rows if r["kind"] == "sales"]
    purchases = [r for r in rows if r["kind"] == "purchase"]

    stats = {
        "receivable": sum(float(r["total_amount"]) - float(r["paid_amount"]) for r in sales),
        "collected": sum(float(r["paid_amount"]) for r in sales),
        "payable": sum(float(r["total_amount"]) - float(r["paid_amount"]) for r in purchases),
        "sales_count": len(sales),
        "purchase_count": len(purchases),
    }
    return render_template("dashboard.html", stats=stats, recent=rows[:6])


@app.route("/sales", methods=["GET", "POST"])
@login_required
def sales():
    user = current_user()
    if request.method == "POST":
        total = float(request.form["total_amount"])
        paid = total if request.form.get("paid_in_full") else min(total, max(0.0, float(request.form.get("paid_amount") or 0)))
        created = sb.table("invoices").insert({
            "user_id": user["id"],
            "kind": "sales",
            "party_name": request.form["party_name"].strip(),
            "description": request.form.get("description", "").strip(),
            "invoice_number": request.form.get("invoice_number", "").strip() or f"INV-{date.today().strftime('%m%d')}",
            "total_amount": total,
            "paid_amount": paid,
            "due_date": request.form.get("due_date") or None,
            "status": calc_status(total, paid),
        }).execute().data[0]
        if paid > 0:
            sb.table("payments").insert({
                "invoice_id": created["id"],
                "user_id": user["id"],
                "amount": paid,
                "method": request.form.get("method", "M-Pesa"),
            }).execute()
        flash("Sales record saved.", "success")
        return redirect(url_for("sales"))

    rows = sb.table("invoices").select("*").eq("user_id", user["id"]).eq("kind", "sales").order("created_at", desc=True).execute().data
    return render_template("sales.html", invoices=rows)


@app.route("/purchases", methods=["GET", "POST"])
@login_required
def purchases():
    user = current_user()
    if request.method == "POST":
        total = float(request.form["total_amount"])
        paid = min(total, max(0.0, float(request.form.get("paid_amount") or 0)))
        kind = request.form.get("kind", "purchase")
        if kind not in ("purchase", "sales"):
            kind = "purchase"
        try:
            extra = json.loads(request.form.get("extra_fields_json") or "{}")
            if not isinstance(extra, dict):
                extra = {}
        except Exception:
            extra = {}

        sb.table("invoices").insert({
            "user_id": user["id"],
            "kind": kind,
            "party_name": request.form["party_name"].strip(),
            "description": request.form.get("description", "").strip(),
            "invoice_number": request.form.get("invoice_number", "").strip(),
            "total_amount": total,
            "paid_amount": paid,
            "due_date": request.form.get("due_date") or None,
            "status": calc_status(total, paid),
            "ai_notes": request.form.get("ai_notes", "").strip(),
            "extra_fields": extra,
        }).execute()
        flash("Record saved to ledger.", "success")
        return redirect(url_for("sales" if kind == "sales" else "purchases"))

    rows = sb.table("invoices").select("*").eq("user_id", user["id"]).eq("kind", "purchase").order("created_at", desc=True).execute().data
    return render_template("purchases.html", bills=rows)


@app.route("/pay/<invoice_id>", methods=["POST"])
@login_required
def record_payment(invoice_id):
    user = current_user()
    inv = sb.table("invoices").select("*").eq("id", invoice_id).eq("user_id", user["id"]).single().execute().data
    amount = float(request.form["amount"])
    method = request.form.get("method", "M-Pesa")
    new_paid = min(float(inv["total_amount"]), float(inv["paid_amount"]) + amount)

    sb.table("payments").insert({
        "invoice_id": invoice_id,
        "user_id": user["id"],
        "amount": amount,
        "method": method,
        "reference": request.form.get("reference", "").strip(),
    }).execute()
    sb.table("invoices").update({
        "paid_amount": new_paid,
        "status": calc_status(float(inv["total_amount"]), new_paid),
    }).eq("id", invoice_id).execute()

    flash(f"Recorded KES {amount:,.0f} payment via {method}.", "success")
    return redirect(url_for("sales" if inv["kind"] == "sales" else "purchases"))


@app.route("/delete/<invoice_id>", methods=["POST"])
@login_required
def delete_invoice(invoice_id):
    user = current_user()
    kind = request.form.get("kind", "sales")
    sb.table("invoices").delete().eq("id", invoice_id).eq("user_id", user["id"]).execute()
    flash("Record deleted.", "success")
    return redirect(url_for("sales" if kind == "sales" else "purchases"))


# --- AI Endpoints (Amazon Bedrock) ---

def _read_doc_block(file):
    if not file or not file.filename:
        return None, "Please upload a PDF or image file."
    ext = file.filename.rsplit(".", 1)[-1].lower()
    raw = file.read()
    fmt = "jpeg" if ext == "jpg" else ext
    if fmt == "pdf":
        return {"document": {"format": "pdf", "name": "uploaded_doc", "source": {"bytes": raw}}}, None
    if fmt in {"png", "jpeg", "webp", "gif"}:
        return {"image": {"format": fmt, "source": {"bytes": raw}}}, None
    return None, "Unsupported file type. Use PDF, PNG, or JPG."


@app.route("/api/extract-bill", methods=["POST"])
@login_required
def extract_bill():
    user = current_user()
    doc_block, err = _read_doc_block(request.files.get("document"))
    if err:
        return jsonify({"error": err}), 400

    system = (
        f"You are an intelligent OCR & accounting reader for {user['business_name']} (currency KES). "
        "Read any company's invoice or receipt (PDF or photo). Compare seller and buyer names against "
        f"'{user['business_name']}' to decide if it is 'sales' (business is seller) or 'purchase' (business is buyer; default if unclear). "
        "Also detect if it is an unpaid 'invoice' or an already-paid 'receipt'. "
        "Return ONLY valid JSON with keys: "
        "suggested_kind ('purchase' or 'sales'), doc_type ('invoice' or 'receipt'), "
        "supplier_name (the other party name), invoice_number (string), "
        "description (short summary string), total_amount (number), "
        "paid_amount (number: equal to total_amount if receipt/paid, else 0), "
        "due_date (YYYY-MM-DD or null), math_ok (boolean), "
        "math_note (short string explaining calculation check or 'Totals verified'), "
        "extra_fields (flat JSON object of any other useful company-specific fields found, e.g. VAT, KRA PIN, M-Pesa Code, Vehicle Reg, Discount, Payment Method)."
    )
    try:
        reply = call_bedrock([doc_block, {"text": "Extract all invoice/receipt details as JSON."}], system)
        data = parse_json_block(reply)
    except Exception as exc:
        return jsonify({"error": f"AI extraction failed: {exc}"}), 500

    kind = data.get("suggested_kind") if data.get("suggested_kind") in ("sales", "purchase") else "purchase"
    existing = sb.table("invoices").select("party_name,invoice_number,total_amount").eq("user_id", user["id"]).eq("kind", kind).execute().data
    dup_msg = ""
    sup = (data.get("supplier_name") or "").strip().lower()
    inv_no = (data.get("invoice_number") or "").strip().lower()
    total = float(data.get("total_amount") or 0)

    for row in existing:
        if inv_no and row["invoice_number"].strip().lower() == inv_no:
            dup_msg = f"Possible duplicate: Invoice #{row['invoice_number']} from {row['party_name']} is already saved."
            break
        if sup and row["party_name"].strip().lower() == sup and abs(float(row["total_amount"]) - total) < 0.01:
            dup_msg = f"Possible duplicate: A bill from {row['party_name']} for KES {total:,.0f} already exists."
            break

    data["duplicate_warning"] = dup_msg
    return jsonify(data)


@app.route("/api/extract-batch", methods=["POST"])
@login_required
def extract_batch():
    user = current_user()
    doc_block, err = _read_doc_block(request.files.get("document"))
    if err:
        return jsonify({"error": err}), 400

    default_kind = request.form.get("default_kind", "sales")
    system = (
        f"You are an intelligent OCR bookkeeper for {user['business_name']} (currency KES). "
        "The user uploaded a photo or PDF of a handwritten ledger book page, receipt list, or multi-row invoice sheet. "
        "Extract EVERY individual customer or supplier entry into a JSON object: {\"records\": [...]}. "
        f"Each item must have: kind ('sales' or 'purchase', default '{default_kind}'), "
        "party_name (string), description (short items/notes string), invoice_number (string or ''), "
        "total_amount (number), paid_amount (number, 0 if unpaid), due_date (YYYY-MM-DD or null). "
        "Return ONLY valid JSON."
    )
    try:
        reply = call_bedrock([doc_block, {"text": "Extract all rows/entries from this page as JSON."}], system)
        data = parse_json_block(reply)
        return jsonify({"records": data.get("records", [])})
    except Exception as exc:
        return jsonify({"error": f"Batch scan failed: {exc}"}), 500


@app.route("/api/save-batch", methods=["POST"])
@login_required
def save_batch():
    user = current_user()
    records = (request.get_json() or {}).get("records", [])
    rows = []
    for r in records:
        total = float(r.get("total_amount") or 0)
        paid = min(total, max(0.0, float(r.get("paid_amount") or 0)))
        kind = r.get("kind") if r.get("kind") in ("sales", "purchase") else "sales"
        if not (r.get("party_name") or "").strip() or total <= 0:
            continue
        rows.append({
            "user_id": user["id"],
            "kind": kind,
            "party_name": r["party_name"].strip(),
            "description": (r.get("description") or "").strip(),
            "invoice_number": (r.get("invoice_number") or "").strip(),
            "total_amount": total,
            "paid_amount": paid,
            "due_date": r.get("due_date") or None,
            "status": calc_status(total, paid),
        })
    if not rows:
        return jsonify({"error": "No valid records to save."}), 400
    sb.table("invoices").insert(rows).execute()
    return jsonify({"saved": len(rows)})


@app.route("/api/chat", methods=["POST"])
@login_required
def ai_chat():
    user = current_user()
    question = (request.get_json() or {}).get("question", "").strip()
    if not question:
        return jsonify({"answer": "Ask me anything about your invoices, balances, or bills."})

    rows = sb.table("invoices").select("kind,party_name,description,total_amount,paid_amount,due_date,status,extra_fields").eq("user_id", user["id"]).execute().data
    context = json.dumps(rows, default=str)
    system = (
        f"You are a helpful financial assistant for {user['business_name']} in Kenya (currency: KES). "
        "Answer concisely and clearly using ONLY the saved invoice records provided. "
        "Format rules: do NOT use '#' headings. Use short sentences or brief '- ' bullet lines, "
        "write amounts as 'KES 10,000', and keep the total answer under 80 words. "
        "Sales invoices = money customers owe the business. Purchase bills = money the business owes suppliers."
    )
    prompt = f"Saved records:\n{context}\n\nOwner's question: {question}"
    try:
        answer = call_bedrock([{"text": prompt}], system)
    except Exception as exc:
        answer = f"AI assistant unavailable right now ({exc})."
    return jsonify({"answer": answer})


@app.route("/api/reminder/<invoice_id>", methods=["POST"])
@login_required
def draft_reminder(invoice_id):
    user = current_user()
    inv = sb.table("invoices").select("*").eq("id", invoice_id).eq("user_id", user["id"]).single().execute().data
    balance = float(inv["total_amount"]) - float(inv["paid_amount"])
    fallback = (
        f"Hello {inv['party_name']}, friendly reminder from {user['business_name']}: "
        f"your balance for {inv['description'] or inv['invoice_number']} is KES {balance:,.0f}. "
        "Kindly clear via M-Pesa when ready. Thank you!"
    )
    try:
        msg = call_bedrock(
            [{"text": f"Draft a short, polite WhatsApp payment reminder (max 45 words) for {inv['party_name']} owing KES {balance:,.0f} to {user['business_name']} for '{inv['description']}'."}],
            "Write warm, professional Kenyan SME payment reminders.",
        )
        return jsonify({"reminder": msg.strip()})
    except Exception:
        return jsonify({"reminder": fallback})


if __name__ == "__main__":
    app.run(debug=True)
