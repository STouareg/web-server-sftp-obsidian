# Робота з репозиторієм

## Структура

- `app.py` — Flask-маршрути, SFTP-синхронізація, SHA-256 порівняння файлів,
  метрики Prometheus і HTML/CSS/JS у `PAGE_TEMPLATE`. Окремого frontend build немає.
- `gunicorn.conf.py` — порт 8080, один worker, запуск потоку синхронізації в `post_fork`.
- `Dockerfile` — багатостадійний образ Python 3.12; `requirements.txt` — залежності.
- `docker-compose.yml` — локальний сервіс, порти `8088:8080`, bind mount
  `/opt/ks-web/data:/data`; `.env.example` — шаблон конфігурації.

## Запуск і перевірки

Виконуй з кореня репозиторію. Створення середовища й встановлення залежностей:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

- Розробка: `python app.py`.
- Gunicorn: `python -m gunicorn -c gunicorn.conf.py app:app`.
- Обидва слухають `0.0.0.0:8080` і запускають SFTP-потік. Експортуй потрібні
  змінні перед запуском: застосунок сам не завантажує `.env`.
- Контейнерний запуск: `docker compose up -d --build`; підготовка тому й
  оточення описана в [README](README.md#quick-start-docker-compose).

Окремого набору тестів, лінтера й CI-конфігурації немає. Базові перевірки:

```sh
python -m pip check
python -m py_compile app.py gunicorn.conf.py
python -m gunicorn --check-config -c gunicorn.conf.py app:app
docker compose --env-file /dev/null config --quiet
```

Остання команда перевіряє структуру Compose без локального `.env`; попередження
про відсутні SFTP-змінні очікувані. За окремої інсталяції Compose використовуй
`docker-compose` замість `docker compose`.

Smoke-перевірка маршрутів і Markdown без мережі та запису в `/data`
(імпорт `app` не запускає синхронізацію):

```sh
python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import app
with TemporaryDirectory() as d:
    app.LOCAL_FILE = str(Path(d) / 'note.md')
    app.STATUS_FILE = str(Path(d) / 'status.txt')
    client = app.app.test_client()
    for route in ('/', '/raw', '/status', '/health', '/metrics'):
        assert client.get(route).status_code == 200, route
    assert client.get('/health').data == b'OK'
    Path(app.LOCAL_FILE).write_text('# Heading\n\n==highlight==', encoding='utf-8')
    assert b'<mark>highlight</mark>' in client.get('/').data
    assert client.get('/raw').data == b'# Heading\n\n==highlight=='
print('HTTP smoke checks passed')
PY
```

## Важливі обмеження

- Зберігай один worker: кожен `post_fork` створює власний sync-потік, а метрики
  зберігаються в пам'яті процесу. Масштабування потребує зміни цієї архітектури.
- Тимчасовий файл завантаження має бути поряд із `LOCAL_FILE`, щоб `os.replace`
  залишався атомарним у межах файлової системи. Незмінний вміст не перезаписується.
- `STATUS_FILE` фіксований як `/data/status.txt`; зміна `LOCAL_FILE` його не
  переносить. Помилки запису статусу приглушуються.
- `/health` — лише liveness (`OK`), не перевірка успішності SFTP. Для синхронізації
  використовуй `/metrics` і `/status`; до першої спроби метрика результату відсутня.
- SFTP використовує пароль і не перевіряє ключ хоста. Markdown допускає сирий HTML,
  маршрути не мають автентифікації: джерело нотаток має бути довіреним.
- У `PAGE_TEMPLATE` літеральні дужки CSS/JS подвоєні через `str.format`.
  Після змін інтерфейсу перевіряй також браузер: smoke-тест не виконує JavaScript.
- Відсутні та порожні `PAGE_FOOTER`/`LOGO_*` мають різну семантику; не підміняй
  перевірку `is None` перевіркою істинності. Основні SFTP-параметри читаються при імпорті.
- Не записуй паролі, вміст `.env` чи приватні нотатки в код, документацію та тести.
  Production deployment і маршрутизація сповіщень належать репозиторію `infrastructure`.

## Документація

- [Налаштування оточення](README.md#environment-variables)
- [HTTP-маршрути](README.md#http-routes)
- [Production deployment](README.md#production-deployment)
- [Обмеження безпеки](README.md#security-notes-short)
