from flask import Flask, Response
import markdown
import os
import time
import hashlib
import threading
import tempfile
import traceback
import paramiko
from html import escape
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

app = Flask(__name__)

SFTP_HOST = os.getenv("SFTP_HOST")
SFTP_PORT = int(os.getenv("SFTP_PORT", "22"))
SFTP_USER = os.getenv("SFTP_USER")
SFTP_PASSWORD = os.getenv("SFTP_PASSWORD")
SFTP_REMOTE_FILE = os.getenv("SFTP_REMOTE_FILE", "/note.md")
LOCAL_FILE = os.getenv("LOCAL_FILE", "/data/note.md")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))

_tz_name = os.getenv("TZ", "Europe/Kyiv")
try:
    APP_TZ = ZoneInfo(_tz_name)
except ZoneInfoNotFoundError:
    APP_TZ = ZoneInfo("Europe/Kyiv")

STATUS_FILE = "/data/status.txt"


def local_note_basename():
    return os.path.basename(LOCAL_FILE) or "note.md"


def page_title_text():
    custom = os.getenv("PAGE_TITLE", "").strip()
    if custom:
        return custom
    base = local_note_basename()
    if base.lower().endswith(".md"):
        base = base[:-3]
    base = base.replace("_", " ").strip()
    return base or "Notes"


def page_footer_html():
    """HTML fragment under the note. Unset env → default line; PAGE_FOOTER= (empty) → no footer."""
    if "PAGE_FOOTER" in os.environ:
        text = os.environ["PAGE_FOOTER"].strip()
        if not text:
            return ""
        return f'<div class="page-footer">{escape(text)}</div>'
    return '<div class="page-footer">All rights reserved.</div>'


_DEFAULT_LOGO_URL = (
    "https://cdn.prod.website-files.com/669e6ea2fe9a21fd38d7d4d1/"
    "669f8b8b68d5838eeaae1296_Group%206.svg"
)


def logo_url_resolved():
    """Return logo URL, or None to hide logo and favicon."""
    if "LOGO_URL" in os.environ:
        u = os.environ["LOGO_URL"].strip()
        return u or None
    return _DEFAULT_LOGO_URL


def logo_head_extras():
    u = logo_url_resolved()
    if not u:
        return ""
    safe = escape(u)
    return f'  <link rel="icon" href="{safe}" type="image/svg+xml" />'


def logo_body_html():
    u = logo_url_resolved()
    if not u:
        return ""
    safe = escape(u)
    return (
        f'<div class="site-logo"><a href="/" aria-label="Home">'
        f'<img src="{safe}" alt="" loading="lazy" decoding="async" /></a></div>'
    )


PAGE_TEMPLATE = """
<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>{page_title}</title>
  {head_extras}
  <style>
    html {{
      height: 100%;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      max-width: 900px;
      margin: 28px auto 32px;
      padding: 0 20px;
      box-sizing: border-box;
      line-height: 1.6;
      color: #222;
      background: #fafafa;
    }}
    main {{
      background: white;
      padding: 28px;
      border-radius: 14px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
      max-height: calc(100vh - 5.5rem);
      max-height: calc(100dvh - 5.5rem);
      overflow-y: auto;
      overflow-x: hidden;
      scrollbar-gutter: stable;
      scrollbar-width: thin;
      scrollbar-color: #bdbdbd #f0f0f0;
    }}
    main::-webkit-scrollbar {{
      width: 10px;
    }}
    main::-webkit-scrollbar-track {{
      background: #f0f0f0;
      border-radius: 10px;
    }}
    main::-webkit-scrollbar-thumb {{
      background: #bdbdbd;
      border-radius: 10px;
      border: 2px solid #f0f0f0;
    }}
    main::-webkit-scrollbar-thumb:hover {{
      background: #9e9e9e;
    }}
    .site-logo {{
      margin: 0 0 1.25rem;
      text-align: center;
    }}
    .site-logo a {{
      display: inline-block;
      line-height: 0;
    }}
    .site-logo img {{
      max-height: 64px;
      width: auto;
      height: auto;
      vertical-align: middle;
    }}
    h1, h2, h3 {{
      line-height: 1.25;
    }}
    code {{
      background: #f2f2f2;
      padding: 2px 5px;
      border-radius: 4px;
    }}
    pre {{
      background: #f2f2f2;
      padding: 12px;
      overflow-x: auto;
      border-radius: 8px;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
    }}
    th, td {{
      border: 1px solid #ddd;
      padding: 8px;
    }}
    blockquote {{
      border-left: 4px solid #ddd;
      margin-left: 0;
      padding-left: 16px;
      color: #555;
    }}
    mark {{
      background-color: #fff3bf;
      color: inherit;
      padding: 0.05em 0.25em;
      border-radius: 4px;
    }}
    article.md-body details.section-collapse {{
      border: 1px solid #e8e8e8;
      border-radius: 10px;
      margin: 0.75em 0;
      padding: 0 12px 10px;
      background: #fcfcfc;
    }}
    article.md-body details.section-collapse > summary {{
      cursor: pointer;
      list-style: none;
      margin: 0 -12px;
      padding: 10px 14px;
      border-radius: 10px 10px 0 0;
      background: #f4f4f4;
    }}
    article.md-body details.section-collapse > summary::-webkit-details-marker {{
      display: none;
    }}
    article.md-body details.section-collapse > summary::marker {{
      content: '';
    }}
    article.md-body details.section-collapse > summary > h1,
    article.md-body details.section-collapse > summary > h2,
    article.md-body details.section-collapse > summary > h3 {{
      display: inline;
      margin: 0;
      font-size: inherit;
      line-height: inherit;
      font-weight: inherit;
    }}
    article.md-body details.section-collapse > summary > h1 {{
      font-size: 1.35em;
      font-weight: 700;
    }}
    article.md-body details.section-collapse > summary > h2 {{
      font-size: 1.2em;
      font-weight: 600;
    }}
    article.md-body details.section-collapse > summary > h3 {{
      font-size: 1.08em;
      font-weight: 600;
    }}
    .page-footer {{
      color: #666;
      font-size: 13px;
      margin-top: 30px;
      border-top: 1px solid #eee;
      padding-top: 12px;
    }}
  </style>
</head>
<body>
  <main>
    {logo}
    {content}
    {footer}
  </main>
  <script>
  (function () {{
    function level(tag) {{
      if (tag === "H1") return 1;
      if (tag === "H2") return 2;
      if (tag === "H3") return 3;
      return 99;
    }}
    function wrapHeader(h) {{
      var L = level(h.tagName);
      var details = document.createElement("details");
      details.className = "section-collapse";
      details.open = true;
      var summary = document.createElement("summary");
      var inner = document.createElement(h.tagName.toLowerCase());
      inner.innerHTML = h.innerHTML;
      summary.appendChild(inner);
      details.appendChild(summary);
      h.replaceWith(details);
      var el = details.nextElementSibling;
      while (el) {{
        var tag = el.tagName;
        if (["H1", "H2", "H3"].indexOf(tag) !== -1 && level(tag) <= L) break;
        var next = el.nextElementSibling;
        details.appendChild(el);
        el = next;
      }}
    }}
    function runCollapsibles() {{
      var root = document.querySelector("article.md-body");
      if (!root) return;
      for (var L = 3; L >= 1; L--) {{
        var headers = Array.prototype.slice.call(root.querySelectorAll("h1, h2, h3"));
        for (var i = 0; i < headers.length; i++) {{
          var h = headers[i];
          if (!document.body.contains(h)) continue;
          if (level(h.tagName) !== L) continue;
          if (h.closest("details.section-collapse > summary")) continue;
          wrapHeader(h);
        }}
      }}
    }}
    if (document.readyState === "loading")
      document.addEventListener("DOMContentLoaded", runCollapsibles);
    else
      runCollapsibles();
  }})();
  </script>
</body>
</html>
"""


def now():
    return datetime.now(APP_TZ).strftime("%Y-%m-%d %H:%M:%S")


def write_status(message):
    text = f"[{now()}] {message}"
    print(text, flush=True)

    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def file_hash(path):
    if not os.path.exists(path):
        return None

    h = hashlib.sha256()

    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)

    return h.hexdigest()


def validate_config():
    missing = []

    for name, value in {
        "SFTP_HOST": SFTP_HOST,
        "SFTP_USER": SFTP_USER,
        "SFTP_PASSWORD": SFTP_PASSWORD,
        "SFTP_REMOTE_FILE": SFTP_REMOTE_FILE,
    }.items():
        if not value:
            missing.append(name)

    if missing:
        write_status(f"Missing required environment variables: {', '.join(missing)}")
        return False

    return True


def download_from_sftp():
    if not validate_config():
        return

    dest_dir = os.path.dirname(os.path.abspath(LOCAL_FILE))
    if not dest_dir:
        dest_dir = "."
    os.makedirs(dest_dir, exist_ok=True)

    old_hash = file_hash(LOCAL_FILE)

    # Same dir as LOCAL_FILE: os.replace cannot cross filesystems (/tmp vs volume).
    fd, tmp_path = tempfile.mkstemp(prefix="sync_", suffix=".md", dir=dest_dir)
    os.close(fd)

    transport = None
    sftp = None

    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(
            username=SFTP_USER,
            password=SFTP_PASSWORD,
        )

        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.get(SFTP_REMOTE_FILE, tmp_path)

        new_hash = file_hash(tmp_path)

        if new_hash != old_hash:
            os.replace(tmp_path, LOCAL_FILE)
            write_status("File updated from SFTP")
        else:
            os.remove(tmp_path)
            write_status("No changes detected")

    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

        write_status(f"SFTP sync failed: {e}")
        traceback.print_exc()

    finally:
        try:
            if sftp:
                sftp.close()
        except Exception:
            pass

        try:
            if transport:
                transport.close()
        except Exception:
            pass


def sync_loop():
    write_status("SFTP sync loop started")

    while True:
        download_from_sftp()
        time.sleep(CHECK_INTERVAL_SECONDS)


def read_status():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return f.read()

    return "No sync status yet"


@app.route("/")
def index():
    note = escape(local_note_basename())
    if not os.path.exists(LOCAL_FILE):
        content = (
            f'<article class="md-body"><h1>{note} not found</h1>'
            "<p>Waiting for first SFTP sync...</p></article>"
        )
    else:
        with open(LOCAL_FILE, "r", encoding="utf-8") as f:
            md_text = f.read()

        if not md_text.strip():
            content = f'<article class="md-body"><h1>{note} is empty</h1></article>'
        else:
            html = markdown.markdown(
                md_text,
                extensions=[
                    "tables",
                    "fenced_code",
                    "toc",
                    "pymdownx.mark",
                ],
            )
            content = f'<article class="md-body">{html}</article>'

    return Response(
        PAGE_TEMPLATE.format(
            content=content,
            footer=page_footer_html(),
            page_title=escape(page_title_text()),
            head_extras=logo_head_extras(),
            logo=logo_body_html(),
        ),
        mimetype="text/html",
    )


@app.route("/raw")
def raw():
    if not os.path.exists(LOCAL_FILE):
        return Response(f"{local_note_basename()} not found", mimetype="text/plain")

    with open(LOCAL_FILE, "r", encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/plain")


@app.route("/status")
def status():
    return Response(read_status(), mimetype="text/plain")


@app.route("/health")
def health():
    return Response("OK", mimetype="text/plain")


if __name__ == "__main__":
    thread = threading.Thread(target=sync_loop, daemon=True)
    thread.start()

    app.run(host="0.0.0.0", port=8080)
