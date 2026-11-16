"""Minimal KIE API client (stdlib only).

Usage:
    python3 kie.py credits
    python3 kie.py image "a cat astronaut, digital art" [--ratio 16:9]
    python3 kie.py run <model> '<input json>'
    python3 kie.py status <taskId>
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BASE_URL = "https://api.kie.ai/api/v1"
# personal things (keys, binaries, downloads) live in ~/.brida on each Mac; the shared folder holds only code
PERSONAL = Path.home() / ".brida"
OUTPUT_DIR = PERSONAL / "output"


def load_api_key():
    for env_file in (PERSONAL / ".env", Path(__file__).parent / ".env"):
        if not env_file.exists():
            continue
        for line in env_file.read_text().splitlines():
            if line.startswith("KIE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"\'')
    key = os.environ.get("KIE_API_KEY")
    if not key:
        sys.exit("KIE_API_KEY not found in .env or environment")
    return key


API_KEY = load_api_key()


def request(method, path, body=None):
    req = urllib.request.Request(
        BASE_URL + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    # KIE returns HTTP 200 even on errors, so the real status is in "code"
    if data.get("code") != 200:
        raise RuntimeError(f"KIE error {data.get('code')}: {data.get('msg')}")
    return data["data"]


def get_credits():
    return request("GET", "/chat/credit")


def create_task(model, input_params, callback_url=None):
    body = {"model": model, "input": input_params}
    if callback_url:
        body["callBackUrl"] = callback_url
    return request("POST", "/jobs/createTask", body)["taskId"]


def get_task(task_id):
    return request("GET", f"/jobs/recordInfo?taskId={task_id}")


def wait_for_task(task_id, interval=3, timeout=600):
    start = time.time()
    while time.time() - start < timeout:
        task = get_task(task_id)
        state = task["state"]
        print(f"  [{int(time.time() - start)}s] {state}")
        if state == "success":
            return json.loads(task["resultJson"])
        if state == "fail":
            raise RuntimeError(f"Task failed ({task.get('failCode')}): {task.get('failMsg')}")
        time.sleep(interval)
    raise TimeoutError(f"Task {task_id} not finished after {timeout}s")


def download(urls):
    OUTPUT_DIR.mkdir(exist_ok=True)
    paths = []
    for url in urls:
        name = url.split("?")[0].rsplit("/", 1)[-1]
        path = OUTPUT_DIR / name
        urllib.request.urlretrieve(url, path)
        paths.append(path)
    return paths


def run(model, input_params):
    task_id = create_task(model, input_params)
    print(f"Task created: {task_id}")
    result = wait_for_task(task_id)
    urls = result.get("resultUrls", [])
    for path in download(urls):
        print(f"Saved: {path}")
    return result


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    cmd = args[0]
    if cmd == "credits":
        print(f"Credits: {get_credits()}")
    elif cmd == "image":
        ratio = args[args.index("--ratio") + 1] if "--ratio" in args else "1:1"
        run("google/nano-banana", {"prompt": args[1], "aspect_ratio": ratio, "output_format": "png"})
    elif cmd == "run":
        run(args[1], json.loads(args[2]))
    elif cmd == "status":
        print(json.dumps(get_task(args[1]), indent=2, ensure_ascii=False))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
