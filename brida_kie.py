"""Brida machine -> Kie.ai backup generator (stdlib only, uses kie.py and .env).

Usage:
    python3 brida_kie.py credits
    python3 brida_kie.py upload <local file>             # -> public URL (lives 24h)
    python3 brida_kie.py cost <job.json> [job.json ...]   # estimate only, spends nothing
    python3 brida_kie.py run  <job.json> [job.json ...]   # submit all, wait, download

Job file (one generation):
    {"kind": "image" | "video",
     "model": "nano_banana_2" | "nano_banana_2_1" | "nano_banana_pro" | "gpt_image_2_5"
            | "kling3_0" | "kling_o3" | "gemini_omni" | "gemini_omni_flash_1_1" | "gemini_omni_flash_1_2" | "veo3_1"
            | "seedance_2_0" | "seedance_2_5" | "seedance_2_5_fast",
     "prompt": "..." or "prompt_file": "path.txt",
     "refs": ["local.png" or "https://..."],      # image references, in role order
     "start": "...", "end": "...",                  # video start / end frame
     "duration": 5, "sound": false,
     "resolution": "2K" / "1080p" (optional), "mode": "pro" (kling), "tier": "veo3_fast" (veo),
     "aspect": "4:5" (optional, default 9:16),
     "out": "output/batch-450/H1A_K1"}            # file name without extension

Prints one JSON line per job: {"job", "ok", "taskId", "model", "kieModel", "url", "path", "credits", "error"}.
"""
import json
import math
import mimetypes
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import kie

HERE = Path(__file__).parent
UPLOAD_URL = "https://kieai.redpandaai.co/api/file-stream-upload"
USD_PER_CREDIT = 0.005


# ---------- reference upload ----------

def upload(path):
    path = Path(path)
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts = []
    for name, value in (("uploadPath", "brida"), ("fileName", f"{uuid.uuid4().hex[:8]}-{path.name}")):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                 f'Content-Type: {ctype}\r\n\r\n'.encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(UPLOAD_URL, data=b"".join(parts), method="POST", headers={
        "Authorization": f"Bearer {kie.API_KEY}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    if data.get("code") != 200:
        raise RuntimeError(f"upload failed {data.get('code')}: {data.get('msg')}")
    return data["data"]["downloadUrl"]


def as_url(ref, cache):
    if not ref:
        return None
    if ref.startswith(("http://", "https://")):
        return ref
    if ref not in cache:
        cache[ref] = upload(ref)
    return cache[ref]


# ---------- duration helpers ----------

def pick(duration, allowed):
    """Smallest allowed duration >= requested (or the longest one)."""
    d = math.ceil(float(duration or allowed[0]))
    for a in allowed:
        if a >= d:
            return a
    return allowed[-1]


def clamp(duration, lo, hi):
    return max(lo, min(hi, math.ceil(float(duration or lo))))


# ---------- model mapping: Brida key -> (kie model, input, estimated credits) ----------
# Prices from kie.ai/pricing (2026-10-15), credits; None = not listed, shown after the run.

def build(job, urls):
    m, p = job["model"], job["prompt"]
    refs, start, end = urls["refs"], urls["start"], urls["end"]
    sound = bool(job.get("sound", False))
    dur = job.get("duration")

    if m in ("nano_banana_2", "nano_banana_2_1"):
        res = job.get("resolution", "2K").upper()
        inp = {"prompt": p, "aspect_ratio": job.get("aspect", "9:16"), "resolution": res, "output_format": "png"}
        if refs:
            inp["image_input"] = refs[:10]
        price = {"1K": 8, "2K": 12, "4K": 18}[res] if m == "nano_banana_2" else None
        return ("nano-banana-2" if m == "nano_banana_2" else "nano-banana-2-1"), inp, price
    if m == "nano_banana_pro":
        res = job.get("resolution", "2K").upper()
        inp = {"prompt": p, "aspect_ratio": job.get("aspect", "9:16"), "resolution": res, "output_format": "png"}
        if refs:
            inp["image_input"] = refs[:8]
        return "nano-banana-pro", inp, (24 if res == "4K" else 18)
    if m == "gpt_image_2_5":
        res = job.get("resolution", "2K").upper()
        inp = {"prompt": p, "aspect_ratio": job.get("aspect", "9:16"), "resolution": res}
        if refs:
            inp["input_urls"] = refs[:16]
            return "gpt-image-2-5-flare-image-to-image", inp, None
        return "gpt-image-2-5-flare-text-to-image", inp, None

    frames = [u for u in (start, end) if u]
    if m == "kling3_0":
        mode = job.get("mode", "pro")
        d = clamp(dur, 3, 15)
        inp = {"prompt": p, "image_urls": frames, "sound": sound, "duration": str(d),
               "aspect_ratio": job.get("aspect", "9:16"), "mode": mode, "multi_shots": False}
        per = {"std": (14, 20), "pro": (18, 27), "4K": (67, 67)}[mode][sound]
        return "kling-3.0/video", inp, per * d
    if m == "kling_o3":
        res = job.get("resolution", "1080p")
        d = clamp(dur, 3, 15)
        inp = {"prompt": p, "image_urls": frames, "duration": d, "resolution": res,
               "aspect_ratio": "auto", "audio": sound}
        per = {"720p": (14, 18), "1080p": (18, 23), "4k": (67, 67)}[res][sound]
        return "kling-3.0-omni/image-to-video", inp, per * d
    if m in ("gemini_omni", "gemini_omni_flash_1_1"):
        d = pick(dur, [4, 6, 8, 10])
        inp = {"prompt": p, "duration": str(d), "aspect_ratio": job.get("aspect", "9:16"),
               "resolution": job.get("resolution", "720p")}
        if m == "gemini_omni" and not end:
            if start:
                inp["image_urls"] = [start]
            return "gemini-omni-video", inp, None
        # Kie's gemini-omni-video has no start/end frames: keyframe scenes go through Flash 1.1
        if start:
            inp["first_frame_url"] = start
        if end:
            inp["last_frame_url"] = end
        return "google/gemini-omni-flash-1-1", inp, None
    if m == "gemini_omni_flash_1_2":
        # Kie google/gemini-omni-flash-1-2: integer duration 3-15 (3-10 with a last frame), first/last frame, no audio field
        res = job.get("resolution", "1080p")
        d = clamp(dur, 3, 10 if end else 15)
        inp = {"prompt": p, "duration": d, "aspect_ratio": job.get("aspect", "9:16"), "resolution": res}
        if start:
            inp["first_frame_url"] = start
            if end:
                inp["last_frame_url"] = end
        elif refs:
            inp["image_urls"] = refs[:6]
        per = {"360p": 4, "720p": 9, "1080p": 10, "4k": 22}[res]
        return "google/gemini-omni-flash-1-2", inp, per * d
    if m == "veo3_1":
        tier = job.get("tier", "veo3_fast")
        res = job.get("resolution", "1080p")
        d = pick(dur, [4, 6, 8])
        inp = {"prompt": p, "model": tier, "aspect_ratio": job.get("aspect", "9:16"), "resolution": res, "duration": d}
        if frames:
            inp["image_urls"] = frames
            inp["generation_type"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"
        price = {"veo3_fast": {"720p": 60, "1080p": 65, "4k": 180},
                 "veo3_lite": {"720p": 30, "1080p": 35, "4k": 150},
                 "veo3": {"720p": 250, "1080p": 255, "4k": 370}}[tier][res]
        return "veo-3-1", inp, price
    if m in ("seedance_2_0", "seedance_2_5", "seedance_2_5_fast"):
        draft = m == "seedance_2_5_fast"
        res = "480p" if draft else job.get("resolution", "720p")
        d = clamp(dur, 4, 15)
        inp = {"prompt": p, "aspect_ratio": job.get("aspect", "9:16"), "resolution": res, "duration": d,
               "generate_audio": sound}
        if start:
            inp["first_frame_url"] = start
        if end:
            inp["last_frame_url"] = end
        if m == "seedance_2_0":
            return "bytedance/seedance-2", inp, None
        if draft:
            inp["draft"] = True
            return "bytedance/seedance-2-5", inp, None
        return "bytedance/seedance-2-5", inp, {"720p": 63, "1080p": 158}.get(res, 63) * d
    raise ValueError(f"unknown model key: {m}")


# ---------- running ----------

def load_job(path):
    job = json.loads(Path(path).read_text())
    if "prompt_file" in job:
        job["prompt"] = (Path(path).parent / job["prompt_file"]).read_text()
    job.setdefault("out", str(kie.PERSONAL / "output" / Path(path).stem))
    return job


def result_url(task):
    res = json.loads(task.get("resultJson") or "{}")
    urls = res.get("resultUrls") or (res.get("data") or {}).get("result_urls") \
        or (res.get("data") or {}).get("origin_urls") or res.get("result_urls") or []
    return urls[0] if urls else None


def save(url, out):
    ext = Path(url.split("?")[0]).suffix or ".bin"
    path = Path(out).with_suffix(ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, path)
    return str(path)


def cmd_cost(paths):
    total, unknown = 0, []
    for p in paths:
        job = load_job(p)
        fake = {"refs": ["x"] * len(job.get("refs", [])), "start": job.get("start"), "end": job.get("end")}
        kmodel, _, price = build(job, fake)
        print(f"{Path(p).name}: {job['model']} -> {kmodel}: " + (f"{price} cr (~${price * USD_PER_CREDIT:.2f})" if price else "price not listed"))
        if price:
            total += price
        else:
            unknown.append(Path(p).name)
    print(f"TOTAL ~{total} credits (~${total * USD_PER_CREDIT:.2f})" + (f" + unlisted: {', '.join(unknown)}" if unknown else ""))
    print(f"Balance: {kie.get_credits()} credits")


def cmd_run(paths):
    cache, live = {}, []
    for p in paths:
        job = load_job(p)
        try:
            urls = {"refs": [as_url(r, cache) for r in job.get("refs", [])],
                    "start": as_url(job.get("start"), cache), "end": as_url(job.get("end"), cache)}
            kmodel, inp, _ = build(job, urls)
            tid = kie.create_task(kmodel, inp)
            live.append({"job": p, "model": job["model"], "kieModel": kmodel, "taskId": tid, "out": job["out"]})
        except Exception as e:
            msg = str(e)
            if "402" in msg:
                msg = "Kie: not enough credits (402). " + msg
            print(json.dumps({"job": p, "ok": False, "error": msg}, ensure_ascii=False), flush=True)
    deadline = time.time() + 20 * 60
    while live and time.time() < deadline:
        time.sleep(5)
        for j in list(live):
            try:
                task = kie.get_task(j["taskId"])
            except Exception:
                continue
            state = task.get("state")
            if state not in ("success", "fail"):
                continue
            live.remove(j)
            out = {k: j[k] for k in ("job", "model", "kieModel", "taskId")}
            out["credits"] = task.get("creditsConsumed")
            if state == "success" and result_url(task):
                out["url"] = result_url(task)
                out["path"] = save(out["url"], j["out"])
                out["ok"] = True
            else:
                out["ok"] = False
                out["error"] = f"{task.get('failCode')}: {task.get('failMsg')}"
            print(json.dumps(out, ensure_ascii=False), flush=True)
    for j in live:
        print(json.dumps({"job": j["job"], "taskId": j["taskId"], "ok": False,
                          "error": "still running after 20 min; check later with: python3 kie.py status " + j["taskId"]}), flush=True)


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "credits":
        print(kie.get_credits())
    elif a[0] == "upload":
        print(upload(a[1]))
    elif a[0] == "cost":
        cmd_cost(a[1:])
    elif a[0] == "run":
        cmd_run(a[1:])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
