# Technical Architecture & Code Walkthrough

---

## 1. System Architecture Overview
The application follows a **server-rendered monolith** pattern powered by **Python + Flask**, connected to **Supabase (PostgreSQL)** for persistent data storage and **Amazon Bedrock (Claude Haiku 4.5)** for multimodal OCR and conversational AI.

```
[ Browser / Phone ]
   │  HTML / CSS / Vanilla JS (Camera API, Fetch, DOM)
   ▼
[ Flask Backend (app.py / Gunicorn) ]
   ├──► Supabase PostgreSQL (users, invoices, payments)
   └──► Amazon Bedrock Converse API (Claude Haiku 4.5)
           ├── Multimodal PDF / Image OCR + Classification
           ├── Financial Assistant Chat
           └── Polite Payment Reminder Drafting
```

---

## 2. Languages, Frameworks & Services Used
- **Python 3.12 + Flask (`flask==3.1.0`):** Handles routing, session-based authentication, business logic, and Jinja2 HTML rendering.
- **Gunicorn (`gunicorn==23.0.0`):** Production WSGI HTTP server for cloud deployment (e.g., Render).
- **HTML5 + Jinja2 Templates:** Server-rendered pages with a shared base layout (`templates/base.html`).
- **CSS3 (`static/style.css`):** Custom responsive design system (warm light-mode palette, CSS Grid/Flexbox, keyframe animations, mobile bottom navigation bar, and confirmation modal).
- **Vanilla JavaScript (`static/app.js`):** Handles asynchronous `fetch` requests to AI endpoints, live camera capture via `navigator.mediaDevices.getUserMedia` + `<canvas>`, dynamic extra-field serialization, markdown-to-HTML chat formatting, and modal confirmations.
- **Supabase (`supabase==2.13.0`):** Hosted PostgreSQL database accessed via the official Python client.
- **Amazon Bedrock (`boto3` / Bearer Token HTTPS):** Multimodal LLM (`us.anthropic.claude-haiku-4-5-20251001-v1:0`, configurable via `BEDROCK_MODEL_ID`) using the Converse API.
- **Werkzeug Security (`werkzeug.security`):** Password hashing (`generate_password_hash`, `check_password_hash`).

---

## 3. Project File Structure
- `app.py` — Core Flask application, routes, authentication, database queries, and Bedrock AI integration.
- `schema.sql` — PostgreSQL table definitions (`users`, `invoices`, `payments`).
- `requirements.txt` — Python dependencies.
- `.env` / `.env.example` — Environment variables (`FLASK_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION`, `BEDROCK_MODEL_ID`).
- `templates/`
  - `base.html` — Shared layout, navbar, mobile bottom navigation, floating AI chat drawer, and confirmation modal.
  - `landing.html` — Public landing page with typing headline and `static/hero.png` illustration.
  - `login.html` & `signup.html` — Separate authentication pages.
  - `dashboard.html` — Top action buttons, 3 KPI cards, and the columnar Recent Ledger table.
  - `sales.html` — Sales invoice creation, partial payment recording, and reminder copying.
  - `purchases.html` — Live camera scanner, file upload dropzone, AI review form with adjustable extra fields, and Purchase Bills list.
- `static/`
  - `style.css` — All styling and responsive mobile breakpoints (`@media (max-width: 768px)`).
  - `app.js` — Frontend interactivity.
  - `hero.png` — Landing page illustration.

---

## 4. Database Schema (`schema.sql`)
1. **`users`:** Stores `id` (UUID primary key), `email` (unique), `password_hash`, `business_name`, `is_guest`, and `created_at`.
2. **`invoices`:** Unified ledger table for both `sales` and `purchase` records:
   - `id`, `user_id` (foreign key to `users`), `kind` (`'sales'` or `'purchase'`), `party_name`, `description`, `invoice_number`, `total_amount`, `paid_amount`, `due_date`, `status` (`'unpaid'`, `'partial'`, `'paid'`), `ai_notes`, `extra_fields` (`jsonb`), and `created_at`.
   - Using `extra_fields (jsonb)` allows storing arbitrary company-specific key-value pairs (e.g., `KRA PIN`, `VAT`, `Vehicle Reg`, `M-Pesa Code`) without altering the table schema.
3. **`payments`:** Tracks individual installment payments (`invoice_id`, `user_id`, `amount`, `method`, `reference`, `paid_at`).

---

## 5. How the Code Works (Key Flows)

### A. Authentication & Route Protection (`app.py`)
- `current_user()` checks `session.get("user_id")` and fetches the user from `users`.
- The `@login_required` decorator protects `/sales`, `/purchases`, `/pay/<invoice_id>`, `/delete/<invoice_id>`, and all `/api/*` endpoints—redirecting unauthenticated browsers to `/login` or returning `401` JSON for API calls.
- `GET /` renders `landing.html` when logged out, or queries the user's `invoices` to compute `receivable`, `collected`, and `payable` KPIs and renders `dashboard.html` when logged in.
- `/signup` hashes the password with `generate_password_hash` and inserts a new user; `/login` verifies with `check_password_hash`; `/logout` clears `session["user_id"]`.

### B. Multimodal AI Integration (`call_bedrock` in `app.py`)
- `call_bedrock(content_blocks, system_text)` supports two authentication modes:
  1. **Bearer Token (`AWS_BEARER_TOKEN_BEDROCK`):** Base64-encodes binary document/image bytes via `_b64_encode()` and sends an HTTPS `POST` request to `https://bedrock-runtime.{region}.amazonaws.com/model/{BEDROCK_MODEL}/converse`.
  2. **IAM Keys (`boto3`):** Falls back to `bedrock.converse(...)` using standard AWS credentials.

### C. Live Camera Scan & OCR Extraction (`/api/extract-bill` & `static/app.js`)
1. On `/purchases`, clicking **Live Scan (Camera)** calls `openCamera()`, which requests `navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } })`.
2. Clicking **Capture & Scan** (`captureAndScan()`) draws the video frame onto an HTML5 `<canvas>`, converts it to a JPEG `File`, stops the camera, and calls `extractFromFile(file)`. (Uploading a PDF/image calls the same `extractFromFile(file)` function.)
3. `/api/extract-bill` sends the raw PDF or image bytes to `call_bedrock()`. The prompt instructs the AI to:
   - Compare seller/buyer names against `user['business_name']` to suggest `sales` or `purchase`.
   - Identify `doc_type` (`invoice` vs `receipt`) and set `paid_amount`.
   - Verify line-item math (`math_ok`, `math_note`).
   - Extract company-specific details into `extra_fields`.
4. The backend queries existing records for that `user_id` and `kind` to flag any matching `invoice_number` or matching `party_name` + `total_amount` as `duplicate_warning`.
5. `static/app.js` populates the form, renders editable key-value rows via `addExtraField()`, and serializes them into `extra_fields_json` on form submit (`serializeExtraFields()`).

### D. Partial Payments, Confirmations & Reminders
- `POST /pay/<invoice_id>` inserts a row into `payments`, caps `paid_amount` at `total_amount`, and recalculates `status` via `calc_status(total, paid)`.
- Forms with `data-confirm="..."` are intercepted by a global `submit` listener in `static/app.js`, which opens the `#confirm-modal` dialog before allowing deletion or full payment submission.
- `POST /api/reminder/<invoice_id>` asks Bedrock to draft a concise WhatsApp/SMS reminder (with a built-in template fallback), and `copyReminder()` copies it to the clipboard.

### E. AI Financial Assistant (`/api/chat`)
- Fetches the logged-in user's `invoices` (including `extra_fields`) from Supabase, passes them as JSON context to `call_bedrock()`, and returns a concise KES-formatted answer.
- `formatAiMessage()` in `static/app.js` escapes HTML to prevent XSS and converts `**bold**` and `- ` bullet lines into styled HTML inside `#chat-box`.
