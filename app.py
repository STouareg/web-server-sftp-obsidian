from flask import Flask, Response
import markdown
import os
import time
import hashlib
import threading
import tempfile
import traceback
import paramiko
from datetime import datetime

app = Flask(__name__)

SFTP_HOST = os.getenv("SFTP_HOST")
SFTP_PORT = int(os.getenv("SFTP_PORT", "22"))
SFTP_USER = os.getenv("SFTP_USER")
SFTP_PASSWORD = os.getenv("SFTP_PASSWORD")
SFTP_REMOTE_FILE = os.getenv("SFTP_REMOTE_FILE", "/KS_actual.md")
LOCAL_FILE = os.getenv("LOCAL_FILE", "/data/KS_actual.md")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))

STATUS_FILE = "/data/status.txt"

PAGE_TEMPLATE = """
<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>KS Actual</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      max-width: 900px;
      margin: 40px auto;
      padding: 0 20px;
      line-height: 1.6;
      color: #222;
      background: #fafafa;
    }}
    main {{
      background: white;
      padding: 28px;
      border-radius: 14px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
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
    .meta {{
      color: #777;
      font-size: 14px;
      margin-bottom: 20px;
    }}
    .status {{
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
    <div class="meta">Source file: KS_actual.md</div>
    {content}
    <div class="status">{status}</div>
  </main>
</body>
</html>
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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

    os.makedirs(os.path.dirname(LOCAL_FILE), exist_ok=True)

    old_hash = file_hash(LOCAL_FILE)

    fd, tmp_path = tempfile.mkstemp(prefix="ks_", suffix=".md")
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
    if not os.path.exists(LOCAL_FILE):
        content = "<h1>KS_actual.md not found</h1><p>Waiting for first SFTP sync...</p>"
    else:
        with open(LOCAL_FILE, "r", encoding="utf-8") as f:
            md_text = f.read()

        if not md_text.strip():
            content = "<h1>KS_actual.md is empty</h1>"
        else:
            content = markdown.markdown(
                md_text,
                extensions=["tables", "fenced_code", "toc"],
            )

    return Response(
        PAGE_TEMPLATE.format(
            content=content,
            status=read_status(),
        ),
        mimetype="text/html",
    )


@app.route("/raw")
def raw():
    if not os.path.exists(LOCAL_FILE):
        return Response("KS_actual.md not found", mimetype="text/plain")

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
