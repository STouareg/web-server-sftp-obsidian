# web-server-sftp-obsidian

Small Flask app in Docker: periodically pulls a Markdown file over **SFTP**, stores it on a volume, and serves it as **HTML**. Intended for homelab setups (for example **Portainer** on an **Orange Pi** or similar ARM board) with notes synced from a NAS or another host.

## What runs in the container

- **Dockerfile** is **multi-stage**: dependencies are installed into a **`/venv`** in a builder image (with `build-essential` and `-dev` packages), then only **`/venv`**, your app files, and runtime **`libssl3` / `libffi8`** are copied into the final image—no compiler or headers in the image you run.
- **Gunicorn** (one sync worker) serves the web app on port **8080** inside the container; `gunicorn.conf.py` starts the SFTP sync thread in `post_fork` so it runs with the worker process.
- A background thread runs an SFTP sync on a fixed interval (default **5 minutes**).
- The synced file is compared with a SHA-256 hash of the previous copy; the file on disk is only replaced when the content changes.

## Quick start (Docker Compose)

1. Copy the environment template and edit it:

   ```bash
   cp .env.example .env
   ```

2. On the host, ensure the data directory exists (adjust the path in `docker-compose.yml` if you like):

   ```bash
   sudo mkdir -p /opt/ks-web/data
   ```

3. Build and run:

   ```bash
   docker compose up -d --build
   ```

   Compose reads a **`.env`** file next to `docker-compose.yml` only for **substituting** `${...}` in the compose file; those values are then passed into the container via the `environment` section (you do not need `env_file`).

4. Open **http://\<host\>:8088** (host port `8088` is mapped to container port `8080` in the sample compose file).

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TZ` | No | `Europe/Kyiv` | IANA timezone for status timestamps |
| `SFTP_HOST` | Yes | — | SFTP server hostname or IP |
| `SFTP_PORT` | No | `22` | SFTP port |
| `SFTP_USER` | Yes | — | Username |
| `SFTP_PASSWORD` | Yes | — | Password |
| `SFTP_REMOTE_FILE` | Yes | — | Remote path to the `.md` file |
| `LOCAL_FILE` | No | `/data/note.md` | Path to the synced `.md` in the container; the **file name** is used in empty/not-found messages and (unless `PAGE_TITLE` is set) for the browser tab title |
| `PAGE_TITLE` | No | *(from `LOCAL_FILE`)* | Overrides the `<title>` text; if unset, the tab title is the basename of `LOCAL_FILE` without `.md`, with underscores replaced by spaces |
| `LOGO_URL` | No | [default SVG](https://cdn.prod.website-files.com/669e6ea2fe9a21fd38d7d4d1/669f8b8b68d5838eeaae1296_Group%206.svg) | Header logo and tab favicon. Set **`LOGO_URL=`** (empty) to hide both. |
| `LOGO_LINK_URL` | No | [skinia.com.ua](https://www.skinia.com.ua/) | URL the **logo image** opens (new tab). Set **`LOGO_LINK_URL=`** (empty) so the logo only reloads this app (`/`). |
| `LOGO_LINK_TEXT` | No | *(none)* | If set, adds a **second line** of text under the logo linking to the same `LOGO_LINK_URL`. Omit for **image-only** (clickable logo, no caption). |
| `PAGE_FOOTER` | No | `All rights reserved.` | Text at the bottom of **`/`**. If the variable is **set but empty**, the footer is **omitted**. Use any short line you like (© notice, etc.). |
| `CHECK_INTERVAL_SECONDS` | No | `300` | Seconds between SFTP sync attempts |

## HTTP routes

| Path | Purpose |
|------|---------|
| `/` | Markdown rendered as HTML; footer is `PAGE_FOOTER` (default **All rights reserved.**), not live sync text |
| `/raw` | Plain text of the synced file |
| `/status` | Last SFTP sync line (same text as written to `/data/status.txt`) |
| `/health` | Plain `OK` for health checks |

### Page rendering (Obsidian-friendly)

- **Light / dark**: use the **Тема** buttons at the top of the page (**Системна** / **Світла** / **Темна**). **Системна** follows the OS (`prefers-color-scheme`). The choice is stored in the browser (`localStorage` key `web-sftp-obsidian-theme`).
- **`==text==`** (Obsidian highlights) becomes `<mark>` with a soft yellow background (`pymdownx.mark`).
- **`#` / `##` / `###`** sections are wrapped in **`<details>`** in the browser: they start **expanded**; click the header bar to collapse or expand that section and everything under it until the next heading of the same or higher level. Headings **`####` and below** are left as normal static headings.

## Failures and improving error output

**Today:** sync problems are summarized in one line written to `/data/status.txt` and returned on **`/status`** (and printed to container **stdout** with a full **Python traceback** on errors). Open **container logs** in Portainer or `docker logs web-sftp-obsidian` for details. The main page **`/`** shows a small **footer** from **`PAGE_FOOTER`** (default *All rights reserved.*), not the live sync line.

**Ways to improve output when something fails** (optional follow-ups for this repo or your fork):

- **Richer `/status`**: return last *N* lines, or JSON with fields such as `time`, `ok`, `message`, and `error_type` (configuration vs network vs authentication), without dumping secrets.
- **Clearer HTML on `/`**: when `LOCAL_FILE` is missing or sync never succeeded, show a dedicated panel (not only the generic “waiting” text) with a hint to check env vars and SFTP path, or surface the latest line from **`/status`** if you prefer.
- **Logging**: use the **`logging`** module with a structured format (timestamp, level, message) instead of only `print` / `traceback.print_exc`, or log to a file under `/data` for persistence across quick log rotations.
- **Health check**: optionally make **`/health`** reflect sync health (for example HTTP 503 if the last sync failed and there is no local file yet), so orchestrators mark the container unhealthy; keep a separate **`/health/live`** if you still want a trivial liveness probe.
- **User-facing messages**: map common Paramiko/socket errors to short explanations (timeout, refused connection, auth failed, path not found) so the footer is easier to read than raw exceptions.

## Portainer

- **“pull access denied for web-sftp-obsidian”**: Compose was trying to **pull** `web-sftp-obsidian:local` from Docker Hub, but that name is only meant as a **local tag after `docker compose build`**. This repo sets **`pull_policy: build`** so a normal **deploy / up** builds from the Git `Dockerfile` instead of pulling. If you still see pull errors, turn off **“Always pull latest image”** / **re-pull only** for this stack when the image is not on a registry, or run a one-time **Build** from Portainer before start.
- Add **environment variables on the stack** in Portainer using the **same names** as in the table below (`SFTP_HOST`, `SFTP_USER`, and so on). Compose substitutes `${VAR}` at deploy time and passes them into the container; **no changes to `app.py` are required** (it already uses `os.getenv`). **`TZ`** defaults to **`Europe/Kyiv`** if omitted. Optional display variables (`PAGE_FOOTER`, `LOGO_URL`, `LOGO_LINK_URL`, `LOGO_LINK_TEXT`) use **list-style** entries in `docker-compose.yml`: they are injected **only when** you define them in the stack or in a `.env` file next to the compose file—so they are not sent as empty strings and the app can keep its built-in defaults when you omit them.
- You do **not** need a `.env` file on the server when values come from Portainer.
- The sample compose binds **`/opt/ks-web/data:/data`**. Create that directory on the Orange Pi (or change the left-hand path to match your host).
- **ARM (Orange Pi PC Plus, armv7)**: The image uses **`python:3.12-slim-bookworm`** (Debian/glibc), not Alpine. On **32-bit ARM musl** (Alpine), `cryptography` often has no prebuilt wheel and tries to compile with Rust, which fails (as in Portainer logs: `arm-unknown-linux-musleabihf`). Debian slim gets normal manylinux **armv7l** wheels from PyPI instead. Some dependencies (for example **PyNaCl**) may still build **cffi** from source on armv7; the Dockerfile installs **`build-essential`** so the linker and C library headers (`stdlib.h`, `crti.o`, …) are present during `pip install`, then removes those packages to keep the final image smaller.

### Building on a Mac vs on the Orange Pi

For **linux/arm/v7** (32-bit Pi), a Mac build needs **`docker buildx build --platform linux/arm/v7`**, which usually runs under **QEMU emulation**. That is often **slower** than building **natively on the Pi**, especially for compiling extensions.

If your Mac is Apple Silicon (**arm64**), a default `docker build` produces an **arm64** image, which will **not** run on an **armv7** Orange Pi unless you always pass the correct `--platform` and accept emulation time (or use a remote ARM builder).

Practical options: fix the Dockerfile and **build on the Pi** in Portainer; or build on the Mac with **buildx + `--platform linux/arm/v7` + `--push`** to a registry, then on the Pi use **`image: your-registry/web-sftp-obsidian:tag`** and **remove the `build:` section** from compose so the Pi only pulls layers (no compile on the Pi).

## Local development (without Gunicorn)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

This starts the Flask development server on `0.0.0.0:8080` with the same SFTP background loop. Export the variables first (for example `set -a && source .env && set +a` in bash), because `app.py` does not load `.env` by itself.

## Security notes (short)

- Prefer SSH **keys** and a dedicated SFTP user on the server when you can; passwords in a local `.env` or in Portainer stack env are convenient but protect Portainer and shell access on the host.
- Markdown is rendered with Python-Markdown; **raw HTML in the `.md` file is passed through** to the browser. Only sync notes you trust, or add sanitization if the source is not fully trusted.
- Host SSH keys are not pinned in the current code; on a trusted LAN this is a common trade-off.

## License

Use and modify for your own deployment; add a license file if you publish the project.
