# Brida Machine

A Claude skill for ad production: turns a brief (screenshots, requirements, video references) into a storyboard, generates frames and clips in Higgsfield (Kie.ai as a backup), and records voice-over in ElevenLabs.

## 1. Add the skill to Claude

1. Download `brida-machine.zip` from this repository (don't unzip it).
2. In Claude: **Settings → Capabilities** → turn on **Code execution and file creation**.
3. Go to **Customize → Skills → + → Upload skill** and choose `brida-machine.zip`.

## 2. Set up your Mac (for Kie.ai, ElevenLabs and video tools)

1. Download this repository: green **Code** button → **Download ZIP**, then unzip it anywhere.
2. Open the Claude desktop app → **Code** tab → open the unzipped folder and say:
   **"run the brida machine setup"** (it runs `setup.sh`).
3. The installer downloads the tools it needs and asks for your **Kie.ai** and **ElevenLabs** API keys.
   Paste keys **into the installer window only, never into the chat**.

## What's inside

- `skill/SKILL.md` — the skill itself (instructions for Claude)
- `kie.py`, `brida_kie.py` — Kie.ai image/video generation
- `brida_voice.py` — ElevenLabs voice-over
- `setup.sh` — one-time setup on a Mac
- `tools/audio2mp4.swift` — wraps voice-over audio into mp4

## Good to know

- You need your own accounts and API keys for Higgsfield, Kie.ai and ElevenLabs.
- Keys are stored only on your Mac in `~/.brida/.env` and are never uploaded anywhere.
- Links to the storyboard board and style guide inside the skill belong to the original team and won't open for you.
