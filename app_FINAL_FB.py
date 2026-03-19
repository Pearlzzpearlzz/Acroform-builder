from flask import Flask, request, send_file, abort, render_template_string, redirect, jsonify, url_for
from werkzeug.utils import secure_filename



from pathlib import Path

app = Flask(__name__)

@app.route('/')
def home():
    return redirect('/form-builder')

def get_source_pdf_relpath(form_name: str) -> str:
    from pathlib import Path

    raw = Path(form_name).name if form_name else ""
    if not raw:
        return ""

    source_hint = ""
    fname = raw
    if "|" in raw:
        source_hint, fname = raw.split("|", 1)
        source_hint = Path(source_hint).name.strip()
        fname = Path(fname).name.strip()
    else:
        fname = Path(raw).name.strip()

    source_map = {
        "EF": "EF_v2.2",
        "EF_v2.2": "EF_v2.2",
    }

    if source_hint in source_map:
        preferred = Path(source_map[source_hint]) / fname
        if preferred.exists():
            return preferred.as_posix()

    # Only the 2 real source folders, plus static/documents as a last fallback
    direct = [
        Path("EF_v2.2") / fname,
        Path("static/documents") / fname,
        Path("/mnt/chromeos/MyFiles/Essential_Forms v2.1") / fname,
    ]
    for c in direct:
        if c.exists():
            return c.as_posix()

    # Search only inside EF_v2.2 and Core-v2.1
    for base in [Path("EF_v2.2")]:
        if base.exists():
            hits = list(base.rglob(fname))
            if hits:
                return hits[0].as_posix()

    return ""

def get_source_pdf_url(form_name: str) -> str:
    from urllib.parse import quote
    return f"/source-pdf/{quote(form_name)}" if form_name else ""

def candidate_form_keys(form_name: str):
    from pathlib import Path as _Path
    import re as _re

    raw = _Path(form_name).name if form_name else ""
    if not raw:
        return []

    stem = _Path(raw).stem
    suffix = _Path(raw).suffix or ".pdf"
    variants = []

    def add(name):
        if name and name not in variants:
            variants.append(name)

    def add_swaps(name):
        add(name)
        add(name.replace("&", "AND"))
        add(name.replace("AND", "&"))

    add_swaps(raw)

    m = _re.match(r"^(\d+)(.*)$", stem)
    if m:
        num = m.group(1)
        rest = m.group(2)
        try:
            n = int(num)
            for width in (1, 2, 3):
                add_swaps(f"{n:0{width}d}{rest}{suffix}")
        except Exception:
            pass

    norm = stem
    norm = norm.replace("&", " AND ")
    norm = norm.replace("-", " ")
    norm = norm.replace("_", " ")
    norm = _re.sub(r"\s+", " ", norm).strip()

    add_swaps(norm.replace(" ", "_") + suffix)

    m2 = _re.match(r"^(\d+)(.*)$", norm)
    if m2:
        num = m2.group(1)
        rest = m2.group(2)
        rest_us = rest.replace(" ", "_")
        try:
            n = int(num)
            for width in (1, 2, 3):
                add_swaps(f"{n:0{width}d}{rest_us}{suffix}")
        except Exception:
            pass

    return variants

def resolve_layout_path(layout_dir, form_name: str):
    from pathlib import Path as _Path
    for key in candidate_form_keys(form_name):
        candidate = _Path(layout_dir) / f"{_Path(key).name}.json"
        if candidate.exists():
            return candidate
    return _Path(layout_dir) / f"{_Path(form_name).name}.json"

@app.route("/source-pdf/<path:form_name>")
def source_pdf(form_name):
    from urllib.parse import unquote
    raw_name = form_name
    fixed_name = raw_name.replace(" & ", " and ").replace("&", " and ")
    safe_name = Path(unquote(fixed_name)).name

    rel = get_source_pdf_relpath(safe_name)
    if rel and Path(rel).exists():
        return send_file(rel, mimetype="application/pdf")

    uploaded = (Path.cwd() / "static/uploads/documents" / safe_name).resolve()
    if uploaded.exists():
        return send_file(uploaded, mimetype="application/pdf")

    abort(404)

    rel = get_source_pdf_relpath(raw_name)
    if not rel:
        for key in candidate_form_keys(raw_name):
            rel = get_source_pdf_relpath(key)
            if rel:
                break

    if not rel:
        abort(404)

    return send_file(rel, mimetype="application/pdf")


@app.route("/form-builder", methods=["GET", "POST"])
def form_builder():
    import json
    import re
    from pathlib import Path
    from urllib.parse import quote
    from urllib.parse import quote

    session_id = request.args.get("session_id") or "public_builder"

    image_dir = Path("static/uploads/images")
    doc_dir = Path(app.static_folder) / "uploads" / "documents"

    image_dir.mkdir(parents=True, exist_ok=True)
    doc_dir.mkdir(parents=True, exist_ok=True)

    layout_dir = Path("form_builder_layouts")
    layout_dir.mkdir(parents=True, exist_ok=True)

    if request.method == "POST":
        f = request.files.get("form_image")
        if not f or not f.filename:
            return redirect("/form-builder")

        safe_name = secure_filename(Path(f.filename).name)
        ext = Path(safe_name).suffix.lower()

        allowed = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}
        if ext not in allowed:
            return redirect("/form-builder")

        save_path = doc_dir / safe_name
        f.save(save_path)
        return redirect(f"/form-builder?pdf={safe_name}")

    current_doc_value = request.args.get("pdf", "").strip()
    current_source = ""
    current_image = ""
    if current_doc_value:
        if "|" in current_doc_value:
            current_source, current_image = current_doc_value.split("|", 1)
            current_source = Path(current_source).name.strip()
            current_image = Path(current_image).name.strip()
            current_doc_value = f"{current_source}|{current_image}"
        else:
            current_image = Path(current_doc_value).name
            current_doc_value = current_image

    source_pdf_url = get_source_pdf_url(current_doc_value) if current_doc_value else ""
    uploaded_doc_url = url_for("static", filename=f"uploads/documents/{current_image}") if current_image else ""
    current_path = None
    current_image_url = uploaded_doc_url or source_pdf_url
    ext_name = current_image or current_doc_value or ""
    current_ext = Path(ext_name).suffix.lower() if ext_name else ""
    current_is_image = False
    current_is_pdf = current_ext == ".pdf"

    initial_fields = []
    if current_image:
        layout_path = resolve_layout_path(layout_dir, current_image)
        if layout_path.exists():
            try:
                initial_fields = json.loads(layout_path.read_text())
            except Exception:
                initial_fields = []

        
    def pretty_label(filename: str) -> str:
        import re as _re
        name = Path(filename).stem
        name = _re.sub(r"[\ud800-\udfff]", "", name)
        name = "".join(ch for ch in name if ch.isprintable())
        name = name.replace("_", " ").replace("-", " ")
        name = _re.sub(r"^\d+[ ._-]*", "", name)
        name = _re.sub(r"\bv\d+(?:\.\d+)?\b", "", name, flags=_re.I)
        name = _re.sub(r"\s+", " ", name).strip()
        return name or "Unnamed Form"
    form_options = []

    return render_template_string("""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Custom Form App</title>
        <style>
          * { box-sizing: border-box; }
          body { margin: 0; font-family: Arial, sans-serif; background: #f4f6f8; color: #111; }
          .wrap { max-width: 1180px; margin: 0 auto; padding: 20px; }
          .card { background: #fff; border: 2px solid #111; border-radius: 18px; padding: 18px; margin-bottom: 16px; }
          .toolbar { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
          .toolbtn, .btn {
            display: inline-block;
            text-decoration: none;
            border: 2px solid #111;
            background: #fff;
            color: #111;
            padding: 10px 14px;
            border-radius: 12px;
            font-weight: 700;
            cursor: pointer;
          }
          .toolbtn.active, .btn.primary { background: #111; color: #fff; }
          .note { font-size: 14px; color: #444; margin: 8px 0 0 0; }
          .stage-wrap {
            background: #fff;
            border: 2px solid #111;
            border-radius: 18px;
            padding: 14px;
            overflow: auto;
          }
          .stage {
            position: relative;
            display: inline-block;
            max-width: 100%;
            border: 1px solid #ccc;
            background: #fafafa;
            min-height: 300px;
          }
          .stage img {
            display: block;
            max-width: 100%;
            height: auto;
          }
          .placeholder {
            width: 800px;
            max-width: 100%;
            min-height: 500px;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 30px;
            text-align: center;
            color: #666;
          }
          .pdf-pages {
            width: 100%;
            max-width: 1000px;
            margin: 0 auto;
          }
          .pdf-page-wrap {
            position: relative;
            width: fit-content;
            margin: 0 auto 22px auto;
            background: #fff;
            box-shadow: 0 2px 10px rgba(0,0,0,.08);
          }
          .pdf-page-wrap.active-tool {
            outline: 3px solid #111;
            outline-offset: 4px;
            cursor: crosshair;
          }
          .pdf-page-label {
            font-size: 13px;
            font-weight: 700;
            color: #333;
            margin: 0 0 6px 0;
          }
          .pdf-canvas {
            display: block;
            max-width: 100%;
            height: auto;
            background: #fff;
          }
          .marker {
            position: absolute;
            transform: translate(-50%, -50%);
            background: rgba(255,255,255,.92);
            border: 2px solid #111;
            border-radius: 10px;
            padding: 4px 8px;
            font-size: 13px;
            font-weight: 700;
            white-space: nowrap;
            cursor: pointer;
            z-index: 20;
          }
          .marker small {
            font-size: 11px;
            font-weight: 700;
            color: #444;
            margin-left: 6px;
          }
          .row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
          input[type=file] { padding: 10px; border: 2px solid #111; border-radius: 12px; background: #fff; }
          .status { margin-top: 10px; font-size: 14px; font-weight: 700; }
        </style>
      </head>
      <body>
        <div class="wrap">
          <div class="card">
            <h1 style="margin:0 0 8px 0;">Turn Any PDF Into a Fillable Form</h1>
            <p style="margin:0 0 10px 0;">Upload your PDF, choose a tool, click where you want it placed, then download your finished file.</p>

<div style="margin:12px 0;">
  
</div>

<script>
const d = document.getElementById("doc-selector");
if (d) {
  d.addEventListener("change", () => {
    if (d.value) {
      window.location = "/form-builder?pdf=" + encodeURIComponent(d.value);
    }
  });
}
</script>

            <form method="POST" enctype="multipart/form-data" class="row">
              <input id="uploadInput" type="file" name="form_image" accept=".png,.jpg,.jpeg,.webp,.pdf" style="display:none;">
              <button class="btn primary" type="button" id="uploadBtn">Upload PDF</button>
              
            </form>
<script>
const uploadBtn = document.getElementById("uploadBtn");
const uploadInput = document.getElementById("uploadInput");
if (uploadBtn && uploadInput) {
  uploadBtn.addEventListener("click", () => uploadInput.click());
  uploadInput.addEventListener("change", () => {
    if (uploadInput.files && uploadInput.files.length) {
      uploadInput.form.submit();
    }
  });
}
</script>

            <div class="toolbar">
              <button type="button" class="toolbtn" data-tool="name">Text</button>
              <button type="button" class="toolbtn" data-tool="checkbox">Checkmark</button>
              <button type="button" class="toolbtn" data-tool="realcheckbox">Checkbox</button>
                            <button type="button" class="toolbtn" data-tool="date">Date</button>
              <button type="button" class="toolbtn" data-tool="signature">Signature</button>
              <button type="button" class="toolbtn" id="snapToggle">Snap: OFF</button>
              <button type="button" class="toolbtn" id="clearLast">Delete Last</button>
              <button type="button" class="btn primary" id="saveLayout">Save Layout</button>
              <button type="button" class="btn primary" id="downloadPdf">Download PDF</button>
              
            </div>

            <p class="note">Images place directly on the builder. PDFs now render page-by-page inside the app so fields can save with the correct page number. Only images and PDFs are supported. PDFs render page-by-page for accurate field placement.</p>
            <div class="status" id="status"></div>
          </div>

          <div class="stage-wrap">
            <div class="stage" id="stage">
              {% if current_image_url and current_is_image %}
                <img id="docImage" src="{{ current_image_url }}" alt="Uploaded form page">
              {% elif current_image_url and current_is_pdf %}
                <div id="pdfPages" class="pdf-pages"></div>
              {% elif current_image_url %}
                <div class="placeholder" id="docImage">Unsupported file type. Please upload a PNG, JPG, WEBP, or PDF.</div>
              {% else %}
                <div class="placeholder" id="docImage">Upload your PDF first, then add text, checkmarks, dates, or a signature.</div>
              {% endif %}
            </div>
          </div>
        </div>

        {% if current_is_pdf and current_image_url %}
        <script src="https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js"></script>
<script>
          const pdfjsLib = window.pdfjsLib;
          window.addEventListener("error", (e) => {
            const statusEl = document.getElementById("status");
            if (statusEl) statusEl.textContent = "JS error: " + (e.message || "unknown error");
          });
          if (!pdfjsLib) {
            const statusEl = document.getElementById("status");
            if (statusEl) statusEl.textContent = "PDF.js failed to load.";
            throw new Error("PDF.js failed to load");
          }

          pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js";

          const stage = document.getElementById("stage");
          const pdfPages = document.getElementById("pdfPages");
          const statusEl = document.getElementById("status");
          const toolButtons = document.querySelectorAll(".toolbtn[data-tool]");
          const clearLastBtn = document.getElementById("clearLast");
          const saveBtn = document.getElementById("saveLayout");
          const downloadBtn = document.getElementById("downloadPdf");



          let selectedTool = "";
          let snapEnabled = false;
          let fields = {{ initial_fields|tojson }};
          const pdfUrl = {{ current_image_url|tojson }};

          function markerText(type) {
            if (type === "name" || type === "text") return "Text";
            if (type === "email") return "Email";
            if (type === "phone") return "Phone";
            if (type === "address") return "Address";
            if (type === "checkbox") return "✓";
            if (type === "date") return "Date";
            if (type === "signature") return "Signature";
            return type;
          }

          function setStatus(msg) {
            statusEl.textContent = msg || "";
          }

          function renderFields() {
            document.querySelectorAll(".marker").forEach(el => el.remove());

            fields.forEach((field, index) => {
              const wrap = document.querySelector('.pdf-page-wrap[data-page="' + field.page + '"]');
              if (!wrap) return;

              const el = document.createElement("div");
              el.className = "marker";
              el.style.left = (field.x * 100) + "%";
              el.style.top = (field.y * 100) + "%";
              if (field.type === "checkbox") {
                el.style.width = "auto";
                el.style.minWidth = "0";
                el.style.padding = "0";
                el.style.border = "none";
                el.style.background = "transparent";
                el.style.fontSize = "18px";
                el.innerHTML = "✓";
              } else if (field.type === "realcheckbox") {
                el.style.width = "18px";
                el.style.height = "18px";
                el.style.minWidth = "18px";
                el.style.padding = "0";
                el.style.borderRadius = "3px";
                el.style.fontSize = "0";
                el.style.lineHeight = "18px";
                el.style.background = "#fff";
                el.innerHTML = "";
              } else if (field.type === "checkmark") {
    el.style.width = "auto";
    el.style.minWidth = "0";
    el.style.padding = "0";
    el.style.border = "none";
    el.style.background = "transparent";
    el.style.fontSize = "18px";
    el.innerHTML = "✓";
} else {
                el.style.width = ((field.width || 0.18) * 100) + "%";
                el.innerHTML = markerText(field.type) + '<small>P' + field.page + '</small>';
              }
              el.title = "Double-click to delete";
              el.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
              };
              el.ondblclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                fields.splice(index, 1);
                renderFields();
                setStatus("Field removed.");
              };
              wrap.appendChild(el);
            });
          }

          function syncActiveToolView() {
            document.querySelectorAll(".pdf-page-wrap").forEach(el => {
              if (selectedTool) el.classList.add("active-tool");
              else el.classList.remove("active-tool");
            });
          }

          async function renderPdf() {
            pdfPages.innerHTML = "";
            setStatus("Rendering PDF pages...");

            const loadingTask = pdfjsLib.getDocument(pdfUrl);
            const pdf = await loadingTask.promise;

            for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
              const page = await pdf.getPage(pageNum);
              const viewport = page.getViewport({ scale: 1.35 });

              const wrap = document.createElement("div");
              wrap.className = "pdf-page-wrap";
              wrap.dataset.page = String(pageNum);

              const label = document.createElement("div");
              label.className = "pdf-page-label";
              label.textContent = "Page " + pageNum + " of " + pdf.numPages;

              const canvas = document.createElement("canvas");
              canvas.className = "pdf-canvas";
              canvas.width = viewport.width;
              canvas.height = viewport.height;
              canvas.dataset.page = String(pageNum);

              wrap.appendChild(label);
              wrap.appendChild(canvas);
              pdfPages.appendChild(wrap);

              await page.render({
                canvasContext: canvas.getContext("2d"),
                viewport
              }).promise;

              let clickLocked = false;
let toolTimeout = null;

              wrap.addEventListener("click", (e) => {
                if (clickLocked) return;
                clickLocked = true;

                // 1 second click delay
                setTimeout(() => { clickLocked = false; }, 1000);

                // reset 5-second tool auto-off timer
                if (toolTimeout) clearTimeout(toolTimeout);
                toolTimeout = setTimeout(() => {
                  selectedTool = "";
                  toolButtons.forEach(b => b.classList.remove("active"));
                  syncActiveToolView();
                  setStatus("Tool auto-turned off.");
                }, 5000);
                if (!selectedTool) {
                  setStatus("Choose Checkbox, Date, or Signature first.");
                  return;
                }

                const rect = canvas.getBoundingClientRect();
                if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) {
                  return;
                }

                let x = (e.clientX - rect.left) / rect.width;
                let y = (e.clientY - rect.top) / rect.height;

                if (selectedTool === "checkbox") {
                  x = x - 0.005;
                  y = y + 0.010;

                  // snap to consistent rows
                  if (snapEnabled) {
                  y = Math.round(y * 28) / 28;
                }
                }

                const defaultFieldName =
                  selectedTool === "name" ? "legal_name" :
                  selectedTool === "date" ? "signature_date" :
                  selectedTool === "signature" ? "signature_data" :
                  selectedTool === "checkbox" ? "signature_ack" :
                  selectedTool;

                const defaultWidth =
                  selectedTool === "signature" ? 0.55 :
                  selectedTool === "name" ? 0.45 :
                  selectedTool === "date" ? 0.28 :
                  selectedTool === "checkbox" ? 0.08 :
                  0.30;

                fields.push({
                  page: pageNum,
                  type: selectedTool,
                  field_name: defaultFieldName + "_" + fields.length,
                  x: Number(x.toFixed(6)),
                  y: Number(y.toFixed(6)),
                  width: Number(defaultWidth.toFixed(6))
                });

                renderFields();
                selectedTool = "";
                toolButtons.forEach(b => b.classList.remove("active"));
                syncActiveToolView();
                setStatus("Field placed on page " + pageNum + ".");
              });
            }

            renderFields();
            syncActiveToolView();
            setStatus("PDF ready. Choose a tool, then click the correct page.");
          }

          
          const snapBtn = document.getElementById("snapToggle");
          if (snapBtn) {
            snapBtn.addEventListener("click", () => {
              snapEnabled = !snapEnabled;
              snapBtn.textContent = snapEnabled ? "Snap: ON" : "Snap: OFF";
              setStatus("Snap " + (snapEnabled ? "enabled." : "disabled."));
            });
          }
toolButtons.forEach(btn => {
            btn.addEventListener("click", () => {
              selectedTool = btn.dataset.tool;
              toolButtons.forEach(b => b.classList.remove("active"));
              btn.classList.add("active");
              syncActiveToolView();
              setStatus(selectedTool + " selected. Click the correct PDF page.");
            });
          });

          clearLastBtn.addEventListener("click", () => {
            if (!fields.length) {
              setStatus("No fields to remove.");
              return;
            }
            fields.pop();
            renderFields();
            setStatus("Last field removed.");
          });

          saveBtn.addEventListener("click", async () => {
            const img = {{ current_image|tojson }} || "";
            if (!img) {
              setStatus("Upload a page, PDF, or document first.");
              return;
            }

            const res = await fetch("/form-builder/save", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ img, fields })
            });

            const data = await res.json().catch(() => ({}));
            if (res.ok) {
              setStatus(data.message || "Layout saved.");

              // AUTO LOAD NEXT FORM
              const selector = document.getElementById("doc-selector");
              if (selector && selector.selectedIndex >= 0) {
                const nextIndex = selector.selectedIndex + 1;
                if (nextIndex < selector.options.length) {
                  const nextValue = selector.options[nextIndex].value;
                  if (nextValue) {
                    setTimeout(() => {
                      window.location = "/form-builder?pdf=" + encodeURIComponent(nextValue);
                    }, 600);
                  }
                } else {
                  setStatus("All forms completed.");
                }
              }

            } else {
              setStatus(data.error || "Save failed.");
            }
          });

          if (downloadBtn) {
            downloadBtn.addEventListener("click", async () => {
              const img = {{ current_image|tojson }} || "";
              if (!img) {
                setStatus("Upload a PDF first.");
                return;
              }

              if (!fields.length) {
                setStatus("Add at least one field first.");
                return;
              }

              try {
                setStatus("Building fillable PDF...");
                const res = await fetch("/form-builder/download", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ img, fields })
                });

                if (!res.ok) {
                  let msg = "Download failed.";
                  try {
                    const data = await res.json();
                    msg = data.error || msg;
                  } catch (_) {}
                  setStatus(msg);
                  return;
                }

                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = (img.replace(/\.pdf$/i, "") || "filled_form") + "_fillable.pdf";
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                setStatus("Download ready.");
              } catch (err) {
                setStatus("Download failed: " + (err && err.message ? err.message : String(err)));
              }
            });
          }

          renderPdf().catch(err => {
            console.error(err);
            setStatus("PDF render failed: " + (err && err.message ? err.message : String(err)));
          });
        </script>
        {% else %}
        <script>
          const stage = document.getElementById("stage");
          const docImage = document.getElementById("docImage");
          const statusEl = document.getElementById("status");
          const toolButtons = document.querySelectorAll(".toolbtn[data-tool]");
          const clearLastBtn = document.getElementById("clearLast");
          const saveBtn = document.getElementById("saveLayout");

          let selectedTool = "";
          let snapEnabled = false;
          let fields = {{ initial_fields|tojson }};

          function markerText(type) {
            if (type === "name" || type === "text") return "Text";
            if (type === "email") return "Email";
            if (type === "phone") return "Phone";
            if (type === "address") return "Address";
            if (type === "checkbox") return "✓";
            if (type === "date") return "Date";
            if (type === "signature") return "Signature";
            return type;
          }

          function setStatus(msg) {
            statusEl.textContent = msg || "";
          }

          function renderFields() {
            document.querySelectorAll(".marker").forEach(el => el.remove());

            fields.forEach((field, index) => {
              const el = document.createElement("div");
              el.className = "marker";
              el.style.left = (field.x * 100) + "%";
              el.style.top = (field.y * 100) + "%";
              el.textContent = markerText(field.type);
              el.title = "Double-click to delete";
              el.ondblclick = () => {
                fields.splice(index, 1);
                renderFields();
                setStatus("Field removed.");
              };
              stage.appendChild(el);
            });
          }

          
          const snapBtn = document.getElementById("snapToggle");
          if (snapBtn) {
            snapBtn.addEventListener("click", () => {
              snapEnabled = !snapEnabled;
              snapBtn.textContent = snapEnabled ? "Snap: ON" : "Snap: OFF";
              setStatus("Snap " + (snapEnabled ? "enabled." : "disabled."));
            });
          }
toolButtons.forEach(btn => {
            btn.addEventListener("click", () => {
              selectedTool = btn.dataset.tool;
              toolButtons.forEach(b => b.classList.remove("active"));
              btn.classList.add("active");
              setStatus(selectedTool + " selected. Now click the page.");
            });
          });

          clearLastBtn.addEventListener("click", () => {
            if (!fields.length) {
              setStatus("No fields to remove.");
              return;
            }
            fields.pop();
            renderFields();
            setStatus("Last field removed.");
          });

          


          saveBtn.addEventListener("click", async () => {
            const img = {{ current_image|tojson }} || "";
            if (!img) {
              setStatus("Upload a page, PDF, or document first.");
              return;
            }

            const res = await fetch("/form-builder/save", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ img, fields })
            });

            const data = await res.json().catch(() => ({}));
            if (res.ok) {
              setStatus(data.message || "Layout saved.");
            } else {
              setStatus(data.error || "Save failed.");
            }
          });

          renderFields();
        </script>
        {% endif %}
      </body>
    </html>
    """, current_image=current_image, current_doc_value=current_doc_value, current_image_url=current_image_url, current_is_image=current_is_image, current_is_pdf=current_is_pdf, initial_fields=initial_fields, form_options=form_options)


@app.route("/form-builder/save", methods=["POST"])
def form_builder_save():
    import json
    from pathlib import Path

    session_id = request.args.get("session_id") or "public_builder"

    payload = request.get_json(silent=True) or {}
    img = (payload.get("img") or "").strip()
    fields = payload.get("fields") or []

    if not img:
        return {"error": "Missing image name."}, 400

    if not isinstance(fields, list):
        return {"error": "Fields must be a list."}, 400

    clean_fields = []
    for f in fields:
        try:
            clean_fields.append({
                "page": int(f.get("page", 1)),
                "type": str(f.get("type", "")).strip(),
                "field_name": str(f.get("field_name", "")).strip(),
                "x": float(f.get("x", 0)),
                "y": float(f.get("y", 0)),
                "width": float(f.get("width", 0.18)),
            })
        except Exception:
            continue

    layout_dir = Path("form_builder_layouts")
    layout_dir.mkdir(parents=True, exist_ok=True)

    clean_name = Path(img).name
    out = layout_dir / f"{clean_name}.json"
    out.write_text(json.dumps(clean_fields, indent=2))
    return {"ok": True, "message": f"Layout saved to {out.name}."}


@app.route("/form-builder/download", methods=["POST"])
def form_builder_download():
    from io import BytesIO
    from pathlib import Path
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        NameObject,
        DictionaryObject,
        ArrayObject,
        FloatObject,
        NumberObject,
        TextStringObject,
        BooleanObject,
    )

    payload = request.get_json(silent=True) or {}
    img = (payload.get("img") or "").strip()
    fields = payload.get("fields") or []

    if not img:
        return {"error": "Missing PDF name."}, 400

    if not isinstance(fields, list):
        return {"error": "Fields must be a list."}, 400

    pdf_path = Path(app.static_folder) / "uploads" / "documents" / Path(img).name
    if not pdf_path.exists():
        return {"error": f"PDF not found: {pdf_path.name}"}, 404

    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)

    acro_fields = ArrayObject()

    for i, raw in enumerate(fields):
        try:
            page_num = max(1, int(raw.get("page", 1)))
            page_index = page_num - 1
            if page_index < 0 or page_index >= len(reader.pages):
                continue

            src_page = reader.pages[page_index]
            dst_page = writer.pages[page_index]

            media = src_page.mediabox
            page_w = float(media.right) - float(media.left)
            page_h = float(media.top) - float(media.bottom)

            x = float(raw.get("x", 0))
            y = float(raw.get("y", 0))
            width_pct = float(raw.get("width", 0.18))
            field_type = str(raw.get("type", "")).strip().lower()
            field_name = str(raw.get("field_name", "")).strip() or f"field_{i}"

            rect_x1 = page_w * x
            rect_y2 = page_h * y
            rect_w = page_w * width_pct

            if field_type in ("checkbox", "realcheckbox"):
                rect_h = 16
                rect_w = 16
                ft = NameObject("/Btn")
                ff = NumberObject(0)
                value = NameObject("/Off")
            else:
                rect_h = 22
                ft = NameObject("/Tx")
                ff = NumberObject(0)
                value = TextStringObject("")

            rect_y1 = rect_y2 - rect_h
            rect_x2 = rect_x1 + rect_w

            annot = DictionaryObject()
            annot.update({
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/FT"): ft,
                NameObject("/T"): TextStringObject(field_name),
                NameObject("/F"): NumberObject(4),
                NameObject("/Ff"): ff,
                NameObject("/Rect"): ArrayObject([
                    FloatObject(rect_x1),
                    FloatObject(rect_y1),
                    FloatObject(rect_x2),
                    FloatObject(rect_y2),
                ]),
                NameObject("/DA"): TextStringObject("/Helv 10 Tf 0 g"),
                NameObject("/Required"): BooleanObject(False),
                NameObject("/P"): dst_page.indirect_reference,
            })

            if field_type in ("checkbox", "realcheckbox"):
                annot.update({
                    NameObject("/V"): NameObject("/Off"),
                    NameObject("/AS"): NameObject("/Off"),
                })
            else:
                annot.update({
                    NameObject("/V"): value,
                    NameObject("/DV"): TextStringObject(""),
                })

            annot_ref = writer._add_object(annot)

            if "/Annots" in dst_page:
                dst_page[NameObject("/Annots")].append(annot_ref)
            else:
                dst_page[NameObject("/Annots")] = ArrayObject([annot_ref])

            acro_fields.append(annot_ref)

        except Exception:
            continue

    if acro_fields:
        font_dict = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Name"): NameObject("/Helv"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        })
        font_ref = writer._add_object(font_dict)

        dr_dict = DictionaryObject({
            NameObject("/Font"): DictionaryObject({
                NameObject("/Helv"): font_ref
            })
        })

        acroform = DictionaryObject()
        acroform.update({
            NameObject("/Fields"): acro_fields,
            NameObject("/NeedAppearances"): BooleanObject(True),
            NameObject("/DR"): dr_dict,
            NameObject("/DA"): TextStringObject("/Helv 10 Tf 0 g"),
        })
        writer._root_object.update({
            NameObject("/AcroForm"): writer._add_object(acroform)
        })

    buf = BytesIO()
    writer.write(buf)
    buf.seek(0)

    out_name = Path(img).stem + "_fillable.pdf"
    return send_file(buf, as_attachment=True, download_name=out_name, mimetype="application/pdf")



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
