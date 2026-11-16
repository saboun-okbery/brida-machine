"""Brida machine -> ElevenLabs voice-over (stdlib only, key ELEVENLABS_API_KEY in .env).

Usage:
    python3 brida_voice.py credits                       # characters left this period
    python3 brida_voice.py voices [search words]          # voice name | id | labels
    python3 brida_voice.py cost <job.json> [...]          # characters each job will use
    python3 brida_voice.py say  <job.json> [...]          # generate, save mp3 + word timings

Job file (one line of VO):
    {"voice": "<voice_id or exact voice name>",
     "text": "..." or "text_file": "line.txt",
     "model": "eleven_v4" | "eleven_v4_turbo" | "eleven_v3" (tags like [excited] [faster]) | "eleven_multilingual_v2" | "eleven_turbo_v2_5" | "eleven_flash_v2_5",
     "stability": 0.5, "similarity": 0.75, "style": 0.0, "speed": 1.0, "boost": true   (all optional; only these are sent),
     "language": "en",
     "out": "output/vo/batch-450/H1A"}               # file name without extension

Writes <out>.mp3 and <out>.words.json ([{"word", "start", "end"}] in seconds).
Prints one JSON line per job: {"job", "ok", "path", "words", "duration", "chars", "error"}.
"""
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
PERSONAL = Path.home() / ".brida"   # keys, binaries, outputs — per Mac, never in the shared folder
API = "https://api.elevenlabs.io"
# credits per character (ElevenLabs pricing): v3 / multilingual = 1, flash / turbo = 0.5
RATE = {"eleven_v4": 1.0, "eleven_v4_turbo": 0.5, "eleven_v3": 1.0, "eleven_multilingual_v2": 1.0, "eleven_flash_v2_5": 0.5, "eleven_turbo_v2_5": 0.5}


def load_key():
    for env in (PERSONAL / ".env", HERE / ".env"):
        if not env.exists():
            continue
        for line in env.read_text().splitlines():
            if line.startswith("ELEVENLABS_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"\'')
    sys.exit("ELEVENLABS_API_KEY not found in .env")


KEY = load_key()


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"xi-api-key": KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        raise RuntimeError(f"ElevenLabs {e.code}: {detail}") from None


def credits():
    s = call("GET", "/v1/user/subscription")
    return s["character_limit"] - s["character_count"], s["character_limit"], s.get("tier")


def all_voices(search=None):
    out, token = [], None
    while True:
        q = {"page_size": 100}
        if search:
            q["search"] = search
        if token:
            q["next_page_token"] = token
        d = call("GET", "/v2/voices?" + urllib.parse.urlencode(q))
        out += d["voices"]
        token = d.get("next_page_token")
        if not d.get("has_more") or not token:
            return out


def resolve_voice(v, cache={}):
    if len(v) == 20 and v.isalnum():
        return v
    if not cache:
        for x in all_voices():
            cache.setdefault(x["name"].strip().lower(), []).append(x["voice_id"])
    ids = cache.get(v.strip().lower(), [])
    if not ids:
        raise ValueError(f"voice not found: {v}")
    if len(ids) > 1:
        raise ValueError(f"several voices are named '{v}': {', '.join(ids)}; put the voice_id in the job")
    return ids[0]


def load_job(path):
    job = json.loads(Path(path).read_text())
    if "text_file" in job:
        job["text"] = (Path(path).parent / job["text_file"]).read_text().strip()
    job.setdefault("model", "eleven_v4")
    job.setdefault("out", str(PERSONAL / "output" / "vo" / Path(path).stem))
    return job


def words_from(alignment):
    """Character timings -> word timings."""
    chars = alignment["characters"]
    starts, ends = alignment["character_start_times_seconds"], alignment["character_end_times_seconds"]
    words, cur, t0, t1 = [], "", None, None
    for c, s, e in zip(chars, starts, ends):
        if c.isspace():
            if cur:
                words.append({"word": cur, "start": round(t0, 3), "end": round(t1, 3)})
            cur, t0 = "", None
            continue
        if t0 is None:
            t0 = s
        cur, t1 = cur + c, e
    if cur:
        words.append({"word": cur, "start": round(t0, 3), "end": round(t1, 3)})
    return words


def say(path):
    job = load_job(path)
    try:
        vid = resolve_voice(job["voice"])
        # send only the settings the job carries (the board puts in only what the chosen generator takes:
        # v4/v4 turbo: stability, similarity; v3: stability 0/0.5/1, language; multilingual v2: speed, stability,
        # similarity, style, boost; turbo/flash v2.5: speed, stability, similarity)
        vs = {k2: job[k1] for k1, k2 in (("stability", "stability"), ("similarity", "similarity_boost"),
                                          ("style", "style"), ("speed", "speed"), ("boost", "use_speaker_boost"))
              if job.get(k1) is not None}
        body = {"text": job["text"], "model_id": job["model"]}
        if vs:
            body["voice_settings"] = vs
        if job.get("language"):
            body["language_code"] = job["language"]
        d = call("POST", f"/v1/text-to-speech/{vid}/with-timestamps?output_format=mp3_44100_128", body)
        out = Path(job["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        mp3 = out.with_suffix(".mp3")
        mp3.write_bytes(base64.b64decode(d["audio_base64"]))
        al = d.get("normalized_alignment") or d.get("alignment")
        words = words_from(al) if al else []
        out.with_suffix(".words.json").write_text(json.dumps(words, ensure_ascii=False, indent=1))
        # the board stores media only as video: wrap the take into a tiny mp4 (audio2mp4, built from audio2mp4.swift)
        mp4, duration = None, words[-1]["end"] if words else None
        conv = PERSONAL / "bin" / "audio2mp4"
        if conv.exists():
            import subprocess
            res = subprocess.run([str(conv), str(mp3), str(out.with_suffix(".mp4"))], capture_output=True, text=True)
            if res.returncode == 0:
                mp4 = str(out.with_suffix(".mp4"))
                try:
                    duration = round(float(res.stdout.strip().splitlines()[-1]), 2)
                except Exception:
                    pass
        return {"job": path, "ok": True, "path": str(mp3), "mp4": mp4, "words": str(out.with_suffix(".words.json")),
                "duration": duration, "voiceId": vid, "chars": len(job["text"])}
    except Exception as e:
        return {"job": path, "ok": False, "error": str(e)}


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "credits":
        left, limit, tier = credits()
        print(f"{left} characters left of {limit} ({tier})")
    elif a[0] == "voices":
        for v in all_voices(" ".join(a[1:]) or None):
            l = v.get("labels") or {}
            print(f"{v['category']} | {v['name']} | {v['voice_id']} | " +
                  ", ".join(str(l[k]) for k in ("gender", "age", "accent", "use_case") if l.get(k)))
    elif a[0] == "catalog":
        # catalog <out_dir>: voices.json (board catalog rows) + previews/<voice_id>.mp3
        out = Path(a[1]); (out / "previews").mkdir(parents=True, exist_ok=True)
        rows = []
        for v in all_voices():
            l = v.get("labels") or {}
            row = {"id": v["voice_id"], "name": v["name"].strip(), "category": v.get("category", ""),
                   "gender": l.get("gender", ""), "age": l.get("age", ""), "accent": l.get("accent", ""),
                   "use_case": l.get("use_case", ""), "descriptive": l.get("descriptive", ""),
                   "language": l.get("language", ""), "description": (v.get("description") or "")[:300]}
            p = out / "previews" / f"{v['voice_id']}.mp3"
            if v.get("preview_url") and not p.exists():
                try:
                    urllib.request.urlretrieve(v["preview_url"], p)
                except Exception:
                    pass
            rows.append(row)
        (out / "voices.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        print(f"{len(rows)} voices -> {out}")
    elif a[0] == "cost":
        total = 0
        for p in a[1:]:
            j = load_job(p)
            c = len(j["text"]) * RATE.get(j["model"], 1.0)
            total += c
            print(f"{Path(p).name}: {j['model']} {len(j['text'])} chars -> {c:g} credits")
        left, _, _ = credits()
        print(f"TOTAL {total:g} credits; left {left}")
    elif a[0] == "say":
        with ThreadPoolExecutor(3) as ex:
            for r in ex.map(say, a[1:]):
                print(json.dumps(r, ensure_ascii=False), flush=True)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
