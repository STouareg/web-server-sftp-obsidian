# web-server-sftp-obsidian

Small Flask app in Docker: periodically pulls a Markdown file over **SFTP**, stores it on a volume, and serves it as **HTML**. Intended for homelab setups (for example **Portainer** on an **Orange Pi** or similar ARM board) with notes synced from a NAS or another host.

## What runs in the container

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
| `SFTP_HOST` | Yes | — | SFTP server hostname or IP |
| `SFTP_PORT` | No | `22` | SFTP port |
| `SFTP_USER` | Yes | — | Username |
| `SFTP_PASSWORD` | Yes | — | Password |
| `SFTP_REMOTE_FILE` | Yes | — | Remote path to the `.md` file |
| `LOCAL_FILE` | No | `/data/KS_actual.md` | Where the file is stored in the container (should live under `/data` with the sample volume) |
| `CHECK_INTERVAL_SECONDS` | No | `300` | Seconds between SFTP sync attempts |

## HTTP routes

| Path | Purpose |
|------|---------|
| `/` | Markdown rendered as HTML |
| `/raw` | Plain text of the synced file |
| `/status` | Last sync line (same footer as on `/`) |
| `/health` | Plain `OK` for health checks |

## Failures and improving error output

**Today:** sync problems are summarized in one line written to `/data/status.txt` and shown on **`/`** (footer) and **`/status`**. The same failure is printed to the container **stdout** with a full **Python traceback** (open **container logs** in Portainer or `docker logs ks-web`).

**Ways to improve output when something fails** (optional follow-ups for this repo or your fork):

- **Richer `/status`**: return last *N* lines, or JSON with fields such as `time`, `ok`, `message`, and `error_type` (configuration vs network vs authentication), without dumping secrets.
- **Clearer HTML on `/`**: when `LOCAL_FILE` is missing or sync never succeeded, show a dedicated panel (not only the generic “waiting” text) with the latest status line and a hint to check env vars and SFTP path.
- **Logging**: use the **`logging`** module with a structured format (timestamp, level, message) instead of only `print` / `traceback.print_exc`, or log to a file under `/data` for persistence across quick log rotations.
- **Health check**: optionally make **`/health`** reflect sync health (for example HTTP 503 if the last sync failed and there is no local file yet), so orchestrators mark the container unhealthy; keep a separate **`/health/live`** if you still want a trivial liveness probe.
- **User-facing messages**: map common Paramiko/socket errors to short explanations (timeout, refused connection, auth failed, path not found) so the footer is easier to read than raw exceptions.

## Portainer

- Use **Stacks** with the repository `docker-compose.yml`, or paste the compose YAML.
- Add **environment variables on the stack** in Portainer using the **same names** as in the table below (`SFTP_HOST`, `SFTP_USER`, and so on). Compose substitutes `${VAR}` at deploy time and passes them into the container; **no changes to `app.py` are required** (it already uses `os.getenv`).
- You do **not** need a `.env` file on the server when values come from Portainer.
- The sample compose binds **`/opt/ks-web/data:/data`**. Create that directory on the Orange Pi (or change the left-hand path to match your host).
- **ARM (Orange Pi PC Plus, armv7)**: The image uses **`python:3.12-slim-bookworm`** (Debian/glibc), not Alpine. On **32-bit ARM musl** (Alpine), `cryptography` often has no prebuilt wheel and tries to compile with Rust, which fails (as in Portainer logs: `arm-unknown-linux-musleabihf`). Debian slim gets normal manylinux **armv7l** wheels from PyPI instead. Some dependencies (for example **PyNaCl**) may still build **cffi** from source on armv7; the Dockerfile installs **`build-essential`** so the linker and C library headers (`stdlib.h`, `crti.o`, …) are present during `pip install`, then removes those packages to keep the final image smaller.

### Building on a Mac vs on the Orange Pi

For **linux/arm/v7** (32-bit Pi), a Mac build needs **`docker buildx build --platform linux/arm/v7`**, which usually runs under **QEMU emulation**. That is often **slower** than building **natively on the Pi**, especially for compiling extensions.

If your Mac is Apple Silicon (**arm64**), a default `docker build` produces an **arm64** image, which will **not** run on an **armv7** Orange Pi unless you always pass the correct `--platform` and accept emulation time (or use a remote ARM builder).

Practical options: fix the Dockerfile and **build on the Pi** in Portainer; or build on the Mac with **buildx + `--platform linux/arm/v7` + `--push`** to a registry, then on the Pi use **`image: your-registry/ks-web:tag`** and **remove the `build:` section** from compose so the Pi only pulls layers (no compile on the Pi).

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
