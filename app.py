from flask import Flask, Response
import markdown
from markdown.extensions.toc import TocExtension
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
    """Footer under the note. Key omitted → default; empty string → no footer."""
    raw = os.environ.get("PAGE_FOOTER")
    if raw is None:
        return '<div class="page-footer">All rights reserved.</div>'
    text = raw.strip()
    if not text:
        return ""
    return f'<div class="page-footer">{escape(text)}</div>'


_DEFAULT_LOGO_URL = (
    "https://cdn.prod.website-files.com/669e6ea2fe9a21fd38d7d4d1/"
    "669f8b8b68d5838eeaae1296_Group%206.svg"
)
_DEFAULT_LOGO_LINK_URL = "https://www.skinia.com.ua/"


def logo_url_resolved():
    """Return logo URL, or None to hide. Key omitted → built-in default."""
    v = os.environ.get("LOGO_URL")
    if v is None:
        return _DEFAULT_LOGO_URL
    v = v.strip()
    return v or None


def logo_link_url_resolved():
    v = os.environ.get("LOGO_LINK_URL")
    if v is None:
        return _DEFAULT_LOGO_LINK_URL
    v = v.strip()
    return v or None


def logo_link_text_resolved():
    """Optional second line under the logo; None → image-only (image still links to LOGO_LINK_URL)."""
    v = os.environ.get("LOGO_LINK_TEXT")
    if v is None:
        return None
    t = v.strip()
    return t or None


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
    safe_img = escape(u)
    link_u = logo_link_url_resolved()
    label = logo_link_text_resolved()

    if link_u:
        safe_link = escape(link_u)
        href = safe_link
        target = ' target="_blank" rel="noopener noreferrer"'
        aria = escape(label) if label else "Відкрити сайт церкви (нова вкладка)"
    else:
        href = "/"
        target = ""
        aria = "Головна"

    parts = [
        f'<div class="site-logo-mark"><a href="{href}" aria-label="{aria}"{target}>'
        f'<img src="{safe_img}" alt="" loading="lazy" decoding="async" /></a></div>'
    ]
    if link_u and label:
        safe_l = escape(label)
        parts.append(
            f'<div class="site-logo-sub">'
            f'<a class="site-logo-link" href="{escape(link_u)}" target="_blank" rel="noopener noreferrer">'
            f"{safe_l}</a></div>"
        )
    return f'<div class="site-logo">{"".join(parts)}</div>'


PAGE_TEMPLATE = """
<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta http-equiv="refresh" content="60">
  <title>{page_title}</title>
  <script>
  (function () {{
    try {{
      var k = "web-sftp-obsidian-theme";
      var v = localStorage.getItem(k);
      if (v === "light")
        document.documentElement.setAttribute("data-theme", "light");
      else
        document.documentElement.setAttribute("data-theme", "dark");
    }} catch (e) {{}}
  }})();
  </script>
  {head_extras}
  <style>
    :root {{
      color-scheme: dark;
      --bg-body: #121212;
      --bg-card: #1e1e1e;
      --text: #e8e8e8;
      --text-secondary: #b0b0b0;
      --text-muted: #9a9a9a;
      --border: #404040;
      --border-soft: #333333;
      --code-bg: #2d2d2d;
      --mark-bg: #5c4f12;
      --mark-text: #f5e6a8;
      --link: #7eb8ff;
      --details-border: #3d3d3d;
      --details-bg: #252525;
      --summary-bg: #2c2c2c;
      --shadow: rgba(0, 0, 0, 0.4);
      --scrollbar-track: #333333;
      --scrollbar-thumb: #666666;
      --scrollbar-thumb-hover: #888888;
    }}
    :root[data-theme="light"] {{
      color-scheme: light;
      --bg-body: #fafafa;
      --bg-card: #ffffff;
      --text: #222222;
      --text-secondary: #555555;
      --text-muted: #666666;
      --border: #dddddd;
      --border-soft: #eeeeee;
      --code-bg: #f2f2f2;
      --mark-bg: #fff3bf;
      --mark-text: inherit;
      --link: #1a5fb4;
      --details-border: #e8e8e8;
      --details-bg: #fcfcfc;
      --summary-bg: #f4f4f4;
      --shadow: rgba(0, 0, 0, 0.08);
      --scrollbar-track: #ececec;
      --scrollbar-thumb: #a8a8a8;
      --scrollbar-thumb-hover: #888888;
    }}
    html {{
      min-height: 100%;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      max-width: 900px;
      margin: 28px auto 32px;
      padding: 0 20px;
      box-sizing: border-box;
      line-height: 1.6;
      color: var(--text);
      background: var(--bg-body);
      min-height: 100%;
    }}
    main {{
      background: var(--bg-card);
      color: var(--text);
      padding: 28px;
      border-radius: 14px;
      box-shadow: 0 2px 12px var(--shadow);
      overflow-x: hidden;
    }}
    article.md-body a {{
      color: var(--link);
    }}
    article.md-body a:visited {{
      color: var(--link);
      opacity: 0.88;
    }}
    article.md-body hr {{
      border: none;
      border-top: 1px solid var(--border-soft);
      margin: 1.25em 0;
    }}
    @media (min-width: 769px) {{
      html {{
        height: 100%;
      }}
      main {{
        max-height: calc(100dvh - 5.5rem);
        max-height: calc(100vh - 5.5rem);
        overflow-y: auto;
        -webkit-overflow-scrolling: touch;
        scrollbar-gutter: stable;
        scrollbar-width: auto;
        scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track);
      }}
      main::-webkit-scrollbar {{
        width: 24px;
      }}
      main::-webkit-scrollbar-track {{
        background: var(--scrollbar-track);
        border-radius: 14px;
      }}
      main::-webkit-scrollbar-thumb {{
        background: var(--scrollbar-thumb);
        border-radius: 14px;
        border: 4px solid var(--scrollbar-track);
      }}
      main::-webkit-scrollbar-thumb:hover {{
        background: var(--scrollbar-thumb-hover);
      }}
    }}
    @media (max-width: 768px) {{
      body {{
        margin: 16px auto 24px;
        padding: 0 14px;
      }}
      main {{
        padding: 20px;
      }}
    }}
    .page-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px 16px;
      margin: 0 0 1.25rem;
      flex-wrap: wrap;
    }}
    .page-top-logo {{
      flex: 1;
      min-width: 0;
    }}
    .site-logo {{
      margin: 0;
      text-align: left;
    }}
    .site-logo-mark a {{
      display: inline-block;
      line-height: 0;
    }}
    .site-logo-mark img {{
      max-height: 48px;
      width: auto;
      height: auto;
      vertical-align: middle;
    }}
    .site-logo-sub {{
      margin-top: 0.45rem;
      line-height: 1.35;
    }}
    .site-logo-link {{
      font-size: 0.95rem;
      color: var(--link);
      text-decoration: none;
    }}
    .site-logo-link:hover {{
      text-decoration: underline;
    }}
    h1, h2, h3 {{
      line-height: 1.25;
      color: var(--text);
    }}
    code {{
      background: var(--code-bg);
      padding: 2px 5px;
      border-radius: 4px;
    }}
    pre {{
      background: var(--code-bg);
      padding: 12px;
      overflow-x: auto;
      border-radius: 8px;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
    }}
    th, td {{
      border: 1px solid var(--border);
      padding: 8px;
    }}
    blockquote {{
      border-left: 4px solid var(--border);
      margin-left: 0;
      padding-left: 16px;
      color: var(--text-secondary);
    }}
    mark {{
      background-color: var(--mark-bg);
      color: var(--mark-text);
      padding: 0.05em 0.25em;
      border-radius: 4px;
    }}
    article.md-body details.section-collapse {{
      border: 1px solid var(--details-border);
      border-radius: 10px;
      margin: 0.75em 0;
      padding: 0 12px 10px;
      background: var(--details-bg);
    }}
    article.md-body details.section-collapse > summary {{
      cursor: pointer;
      list-style: none;
      margin: 0 -12px;
      padding: 10px 14px;
      border-radius: 10px 10px 0 0;
      background: var(--summary-bg);
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
      color: var(--text-muted);
      font-size: 13px;
      margin-top: 30px;
      border-top: 1px solid var(--border-soft);
      padding-top: 12px;
    }}
    .theme-switcher {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: flex-end;
      gap: 6px;
      margin: 0;
      flex-shrink: 0;
    }}
    .theme-switcher button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      line-height: 0;
      padding: 9px;
      min-width: 40px;
      min-height: 40px;
      box-sizing: border-box;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--bg-body);
      color: var(--text-secondary);
      cursor: pointer;
    }}
    .theme-switcher button svg {{
      flex-shrink: 0;
    }}
    .theme-switcher button:hover {{
      border-color: var(--text-muted);
      color: var(--text);
    }}
    .theme-switcher button[aria-pressed="true"] {{
      border-color: var(--link);
      color: var(--text);
      background: var(--details-bg);
    }}
    details.md-outline-collapse {{
      margin: 0 0 1.25rem;
      border: 1px solid var(--details-border);
      border-radius: 10px;
      background: var(--details-bg);
      font-size: 0.95rem;
    }}
    details.md-outline-collapse > summary {{
      cursor: pointer;
      list-style: none;
      margin: 0;
      padding: 10px 14px;
      border-radius: 10px;
      background: var(--summary-bg);
      color: var(--text);
      font-weight: 600;
    }}
    details.md-outline-collapse > summary::-webkit-details-marker {{
      display: none;
    }}
    details.md-outline-collapse > summary::marker {{
      content: '';
    }}
    details.md-outline-collapse[open] > summary {{
      border-radius: 10px 10px 0 0;
    }}
    nav.md-outline {{
      margin: 0;
      padding: 8px 14px 12px;
    }}
    nav.md-outline > .toc {{
      margin: 0;
    }}
    nav.md-outline .toc ul {{
      margin: 0.35em 0 0;
      padding-left: 1.15rem;
      list-style: disc;
    }}
    nav.md-outline .toc > ul {{
      margin: 0;
      padding-left: 1.1rem;
    }}
    nav.md-outline .toc li {{
      margin: 0.2em 0;
    }}
    nav.md-outline .toc a {{
      color: var(--link);
      text-decoration: none;
    }}
    nav.md-outline .toc a:hover {{
      text-decoration: underline;
    }}
    .scroll-to-top {{
      position: fixed;
      right: max(20px, env(safe-area-inset-right));
      bottom: max(20px, env(safe-area-inset-bottom));
      z-index: 20;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      line-height: 0;
      padding: 11px;
      min-width: 44px;
      min-height: 44px;
      box-sizing: border-box;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--bg-card);
      color: var(--text-secondary);
      box-shadow: 0 2px 12px var(--shadow);
      cursor: pointer;
      opacity: 0;
      visibility: hidden;
      transform: translateY(8px);
      transition: opacity 0.2s ease, transform 0.2s ease, visibility 0.2s ease,
        border-color 0.15s ease, color 0.15s ease;
    }}
    .scroll-to-top.is-visible {{
      opacity: 1;
      visibility: visible;
      transform: translateY(0);
    }}
    .scroll-to-top:hover {{
      border-color: var(--text-muted);
      color: var(--text);
    }}
    .scroll-to-top svg {{
      flex-shrink: 0;
    }}
  </style>
</head>
<body>
  <main>
    <div class="page-top">
      <div class="page-top-logo">{logo}</div>
      <div class="theme-switcher" role="group" aria-label="Тема оформлення">
        <button type="button" data-theme-value="light" aria-pressed="false" aria-label="Світла тема" title="Світла">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32l1.41 1.41M2 12h2m16 0h2M6.34 17.66l-1.41 1.41m13.02-13.02l-1.41 1.41"/></svg>
        </button>
        <button type="button" data-theme-value="dark" aria-pressed="false" aria-label="Темна тема" title="Темна">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        </button>
      </div>
    </div>
    {toc}
    {content}
    {footer}
  </main>
  <button type="button" class="scroll-to-top" aria-label="На початок" title="На початок" hidden>
    <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>
  </button>
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
      if (h.id) inner.id = h.id;
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
  (function () {{
    var key = "web-sftp-obsidian-theme";
    var buttons = document.querySelectorAll(".theme-switcher button[data-theme-value]");
    function current() {{
      var t = document.documentElement.getAttribute("data-theme");
      if (t === "light") return "light";
      return "dark";
    }}
    function syncButtons() {{
      var c = current();
      for (var i = 0; i < buttons.length; i++) {{
        var b = buttons[i];
        b.setAttribute("aria-pressed", b.getAttribute("data-theme-value") === c ? "true" : "false");
      }}
    }}
    function apply(mode) {{
      if (mode !== "light") mode = "dark";
      document.documentElement.setAttribute("data-theme", mode);
      try {{ localStorage.setItem(key, mode); }} catch (e) {{}}
      syncButtons();
    }}
    for (var i = 0; i < buttons.length; i++)
      buttons[i].addEventListener("click", function () {{
        apply(this.getAttribute("data-theme-value"));
      }});
    syncButtons();
  }})();
  (function () {{
    var btn = document.querySelector(".scroll-to-top");
    var main = document.querySelector("main");
    if (!btn) return;
    function scrollRoot() {{
      var mq = window.matchMedia("(min-width: 769px)");
      if (mq.matches && main) return main;
      return null;
    }}
    function scrollTop() {{
      var root = scrollRoot();
      if (root) root.scrollTo({{ top: 0, behavior: "smooth" }});
      else window.scrollTo({{ top: 0, behavior: "smooth" }});
    }}
    function scrolled() {{
      var root = scrollRoot();
      if (root) return root.scrollTop > 200;
      return window.scrollY > 200;
    }}
    function update() {{
      var show = scrolled();
      btn.hidden = !show;
      btn.classList.toggle("is-visible", show);
    }}
    btn.addEventListener("click", scrollTop);
    if (main) main.addEventListener("scroll", update, {{ passive: true }});
    window.addEventListener("scroll", update, {{ passive: true }});
    window.addEventListener("resize", update, {{ passive: true }});
    update();
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


_MD_EXTENSIONS = [
    "tables",
    "fenced_code",
    TocExtension(toc_depth="1-3"),
    "pymdownx.mark",
]


def _outline_nav_html(toc_fragment):
    """Wrap non-empty TOC in a collapsed-by-default <details> (h1–h3 only)."""
    if not toc_fragment or 'href="#' not in toc_fragment:
        return ""
    return (
        '<details class="md-outline-collapse">'
        '<summary id="md-outline-summary">☰ Зміст </summary>'
        '<nav class="md-outline" aria-labelledby="md-outline-summary">'
        f"{toc_fragment}"
        "</nav></details>"
    )


@app.route("/")
def index():
    note = escape(local_note_basename())
    toc = ""
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
            md = markdown.Markdown(extensions=_MD_EXTENSIONS)
            html = md.convert(md_text)
            toc = _outline_nav_html(md.toc)
            content = f'<article class="md-body">{html}</article>'

    return Response(
        PAGE_TEMPLATE.format(
            toc=toc,
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
