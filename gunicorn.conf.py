bind = "0.0.0.0:8080"
workers = 1
timeout = 120


def post_fork(server, worker):
    import threading

    import app as app_module

    t = threading.Thread(target=app_module.sync_loop, daemon=True)
    t.start()
