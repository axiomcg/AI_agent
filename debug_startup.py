import threading
import time

import httpx
import uvicorn

from src.webui.interface import create_ui

ui = create_ui()
config = uvicorn.Config(ui.app, host="127.0.0.1", port=7788, log_level="info")
server = uvicorn.Server(config)

def run_server():
    server.run()

thread = threading.Thread(target=run_server, daemon=True)
thread.start()

for _ in range(40):
    if server.started:
        break
    time.sleep(0.25)

time.sleep(1)
resp = httpx.get("http://127.0.0.1:7788/gradio_api/startup-events")
print("status", resp.status_code, "headers", resp.headers, "body", resp.text)
server.should_exit = True
thread.join()
