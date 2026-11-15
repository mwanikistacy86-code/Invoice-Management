// Toggle Floating AI Chat Drawer
function toggleChat() {
  const drawer = document.getElementById("chat-drawer");
  if (!drawer) return;
  drawer.classList.toggle("open");
  if (drawer.classList.contains("open")) {
    document.getElementById("chat-input")?.focus();
  }
}

// AI Financial Assistant Chat
async function sendChat(questionText) {
  const input = document.getElementById("chat-input");
  const box = document.getElementById("chat-box");
  const q = (questionText || input.value).trim();
  if (!q) return;

  box.innerHTML += `<div class="msg msg-user">${escapeHtml(q)}</div>`;
  if (!questionText) input.value = "";
  const loadingId = "loading-" + Date.now();
  box.innerHTML += `<div id="${loadingId}" class="msg msg-ai">Thinking...</div>`;
  box.scrollTop = box.scrollHeight;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
    });
    const data = await res.json();
    document.getElementById(loadingId).innerHTML = formatAiMessage(data.answer);
  } catch {
    document.getElementById(loadingId).textContent = "Could not reach AI assistant.";
  }
  box.scrollTop = box.scrollHeight;
}

function formatAiMessage(text) {
  const safe = escapeHtml(text || "");
  return safe
    .replace(/^#{1,3}\s+(.+)$/gm, "<strong>$1</strong>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^\s*[-•]\s+(.+)$/gm, '<div class="ai-bullet">• $1</div>')
    .replace(/\n{2,}/g, '<div class="ai-gap"></div>')
    .replace(/\n/g, "<br>");
}

// AI Purchase Bill / Receipt Extraction
function extractBill(fileInput) {
  const file = fileInput.files[0];
  if (file) extractFromFile(file);
}

async function extractFromFile(file) {
  const status = document.getElementById("extract-status");
  const alertBox = document.getElementById("ai-alerts");
  status.textContent = "Scanning document with AI...";
  alertBox.innerHTML = "";

  const form = new FormData();
  form.append("document", file);

  try {
    const res = await fetch("/api/extract-bill", { method: "POST", body: form });
    const data = await res.json();
    if (data.error) {
      status.textContent = "";
      alertBox.innerHTML = `<div class="alert alert-error">${escapeHtml(data.error)}</div>`;
      return;
    }

    document.getElementById("bill-kind").value = data.suggested_kind === "sales" ? "sales" : "purchase";
    document.getElementById("bill-supplier").value = data.supplier_name || "";
    document.getElementById("bill-number").value = data.invoice_number || "";
    document.getElementById("bill-desc").value = data.description || "";
    document.getElementById("bill-total").value = data.total_amount || "";
    document.getElementById("bill-paid").value = data.paid_amount ?? 0;
    document.getElementById("bill-due").value = data.due_date || "";
    document.getElementById("bill-notes").value = data.math_note || "";

    const extraList = document.getElementById("extra-fields-list");
    extraList.innerHTML = "";
    Object.entries(data.extra_fields || {}).forEach(([k, v]) => addExtraField(k, v));

    let alerts = "";
    if (data.doc_type) {
      alerts += `<div class="alert alert-success">🤖 Detected: <strong>${escapeHtml(data.doc_type)}</strong> → suggested <strong>${data.suggested_kind === "sales" ? "Sales (IN)" : "Purchase (OUT)"}</strong></div>`;
    }
    if (data.duplicate_warning) {
      alerts += `<div class="alert alert-warn">⚠️ ${escapeHtml(data.duplicate_warning)}</div>`;
    }
    if (data.math_ok === false) {
      alerts += `<div class="alert alert-warn">🧮 Math Check: ${escapeHtml(data.math_note)}</div>`;
    } else if (data.math_note) {
      alerts += `<div class="alert alert-success">✅ ${escapeHtml(data.math_note)}</div>`;
    }
    alertBox.innerHTML = alerts;
    status.textContent = "Extracted! Please review and confirm below before saving.";
  } catch {
    status.textContent = "Failed to extract document.";
  }
}

function addExtraField(key = "", val = "") {
  const list = document.getElementById("extra-fields-list");
  if (!list) return;
  const row = document.createElement("div");
  row.className = "extra-row";
  row.innerHTML = `
    <input type="text" class="extra-key" placeholder="Field (e.g. KRA PIN, VAT)" value="${escapeHtml(key)}">
    <input type="text" class="extra-val" placeholder="Value" value="${escapeHtml(val)}">
    <button type="button" class="btn btn-danger btn-sm" onclick="this.parentElement.remove()">✕</button>
  `;
  list.appendChild(row);
}

function serializeExtraFields() {
  const out = {};
  document.querySelectorAll("#extra-fields-list .extra-row").forEach((row) => {
    const k = row.querySelector(".extra-key").value.trim();
    const v = row.querySelector(".extra-val").value.trim();
    if (k && v) out[k] = v;
  });
  const hidden = document.getElementById("extra-fields-json");
  if (hidden) hidden.value = JSON.stringify(out);
}

// Live Camera Scanner (Google Lens style)
let camStream = null;
let camMode = "single";

async function openCamera(mode = "single") {
  camMode = mode;
  const box = document.getElementById("camera-box");
  const video = document.getElementById("camera-feed");
  try {
    camStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
    video.srcObject = camStream;
    box.classList.add("open");
  } catch (err) {
    const alertTarget = document.getElementById("ai-alerts") || document.getElementById("batch-status");
    if (alertTarget) alertTarget.innerHTML = `<div class="alert alert-error">Camera unavailable: ${escapeHtml(err.message)}. Use file upload instead.</div>`;
  }
}

function closeCamera() {
  if (camStream) {
    camStream.getTracks().forEach((t) => t.stop());
    camStream = null;
  }
  document.getElementById("camera-box")?.classList.remove("open");
}

function captureAndScan() {
  const video = document.getElementById("camera-feed");
  if (!video || !video.videoWidth) return;
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);
  closeCamera();
  canvas.toBlob((blob) => {
    if (!blob) return;
    const file = new File([blob], "camera_scan.jpg", { type: "image/jpeg" });
    if (camMode === "batch") extractBatchFromFile(file);
    else extractFromFile(file);
  }, "image/jpeg", 0.9);
}

function shareWhatsApp(btn) {
  const d = btn.dataset;
  const lines = [
    `*${d.biz}* — Invoice ${d.ref || ""}`.trim(),
    `Customer: ${d.party}`,
    d.desc ? `Items: ${d.desc}` : "",
    `Total: KES ${d.total}`,
    `Paid: KES ${d.paid}`,
    d.bal === "0" ? `Status: PAID IN FULL` : `Balance Due: KES ${d.bal}${d.due ? ` (Due: ${d.due})` : ""}`,
  ].filter(Boolean).join("\n");
  window.open(`https://wa.me/?text=${encodeURIComponent(lines)}`, "_blank", "noopener");
}

function randomCustomer() {
  const input = document.getElementById("sales-customer");
  if (input) input.value = `Walk-in Customer #${Math.floor(1000 + Math.random() * 9000)}`;
}

// Batch Book Page Scanner (Multiple Records)
function scanBatchFile(input) {
  if (input.files[0]) extractBatchFromFile(input.files[0]);
}

async function extractBatchFromFile(file) {
  const status = document.getElementById("batch-status");
  const preview = document.getElementById("batch-preview");
  const tbody = document.getElementById("batch-rows");
  status.textContent = "Reading all entries on page with AI...";
  preview.style.display = "none";

  const form = new FormData();
  form.append("document", file);
  form.append("default_kind", "sales");

  try {
    const res = await fetch("/api/extract-batch", { method: "POST", body: form });
    const data = await res.json();
    if (data.error || !data.records?.length) {
      status.textContent = data.error || "No entries detected. Try a clearer photo.";
      return;
    }
    tbody.innerHTML = data.records.map((r) => `
      <tr>
        <td><input type="checkbox" class="b-check" checked style="width:18px;height:18px;"></td>
        <td>
          <select class="b-kind" style="min-width:95px;">
            <option value="sales" ${r.kind !== "purchase" ? "selected" : ""}>Sales IN</option>
            <option value="purchase" ${r.kind === "purchase" ? "selected" : ""}>Bill OUT</option>
          </select>
        </td>
        <td><input class="b-party" value="${escapeHtml(r.party_name || "")}"></td>
        <td><input class="b-desc" value="${escapeHtml(r.description || "")}"></td>
        <td><input class="b-total" type="number" step="0.01" value="${r.total_amount || 0}" style="min-width:90px;"></td>
        <td><input class="b-paid" type="number" step="0.01" value="${r.paid_amount || 0}" style="min-width:90px;"></td>
      </tr>
    `).join("");
    preview.style.display = "block";
    status.textContent = `Found ${data.records.length} entries! Review and click Save Selected Records.`;
  } catch {
    status.textContent = "Failed to scan page.";
  }
}

async function saveBatchRecords() {
  const records = [];
  document.querySelectorAll("#batch-rows tr").forEach((tr) => {
    if (!tr.querySelector(".b-check")?.checked) return;
    records.push({
      kind: tr.querySelector(".b-kind").value,
      party_name: tr.querySelector(".b-party").value,
      description: tr.querySelector(".b-desc").value,
      total_amount: tr.querySelector(".b-total").value,
      paid_amount: tr.querySelector(".b-paid").value,
    });
  });
  const res = await fetch("/api/save-batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ records }),
  });
  if (res.ok) location.reload();
}

// Draft & Copy Payment Reminder
async function copyReminder(invoiceId, btn) {
  const original = btn.textContent;
  btn.textContent = "Drafting...";
  try {
    const res = await fetch(`/api/reminder/${invoiceId}`, { method: "POST" });
    const data = await res.json();
    await navigator.clipboard.writeText(data.reminder);
    btn.textContent = "Copied!";
    setTimeout(() => (btn.textContent = original), 2000);
  } catch {
    btn.textContent = original;
  }
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Confirmation Modal for Delete & Mark Paid forms
let pendingForm = null;

function closeConfirm() {
  document.getElementById("confirm-modal")?.classList.remove("open");
  pendingForm = null;
}

document.addEventListener("submit", (e) => {
  const form = e.target;
  const msg = form.getAttribute("data-confirm");
  if (!msg) return;
  e.preventDefault();
  pendingForm = form;
  document.getElementById("confirm-message").textContent = msg;
  const okBtn = document.getElementById("confirm-ok");
  okBtn.className = msg.toLowerCase().includes("delete") ? "btn btn-danger" : "btn btn-primary";
  okBtn.textContent = msg.toLowerCase().includes("delete") ? "Delete" : "Yes, Confirm";
  document.getElementById("confirm-modal").classList.add("open");
});

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("confirm-ok")?.addEventListener("click", () => {
    if (!pendingForm) return;
    const form = pendingForm;
    form.removeAttribute("data-confirm");
    closeConfirm();
    form.submit();
  });

  // Landing Page Typing Animation
  const typedEl = document.getElementById("typed-headline");
  if (typedEl) {
    const phrases = [
      "Track every invoice, scan any receipt.",
      "Record M-Pesa payments in seconds.",
      "Ask AI about your business cashflow.",
    ];
    let pIdx = 0, cIdx = phrases[0].length, deleting = true;
    const step = () => {
      const current = phrases[pIdx];
      typedEl.textContent = current.slice(0, cIdx);
      if (!deleting && cIdx === current.length) {
        deleting = true;
        return setTimeout(step, 1800);
      }
      if (deleting && cIdx === 0) {
        deleting = false;
        pIdx = (pIdx + 1) % phrases.length;
        return setTimeout(step, 350);
      }
      cIdx += deleting ? -1 : 1;
      setTimeout(step, deleting ? 32 : 55);
    };
    setTimeout(step, 1600);
  }
});
