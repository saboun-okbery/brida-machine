#!/bin/zsh
# Brida machine — setup on a team member's Mac. Run it from the shared brida-machine folder:
#   zsh "<path to brida-machine>/setup.sh"
# Safe to run again: it only adds what is missing, updates tools and re-checks everything.
# Shared folder (this one, synced for the team): scripts, setup, instructions — code only.
# Personal folder ~/.brida (this Mac only, never shared): API keys, ffmpeg, audio2mp4, ffmpeg-skill, outputs.
set -u
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"; P="$HOME/.brida"
ok(){ print -P "%F{green}✓%f $1"; }; warn(){ print -P "%F{yellow}!%f $1"; }; fail(){ print -P "%F{red}✗%f $1"; }

print "Brida machine setup\n  shared folder:   $HERE\n  personal folder: $P"
mkdir -p "$P/bin" "$P/tools" "$P/output"; chmod 700 "$P"
print -r -- "$HERE" > "$P/home"          # the skill finds the shared folder through this file
ARCH="$(uname -m)"; ok "Mac: $ARCH"

# 1. Python
if command -v python3 >/dev/null; then
  ok "Python $(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
  python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)' || warn "Python 3.10+ recommended (python.org); 3.9 still works for now."
else fail "python3 not found — run this script again after step 2 installs Command Line Tools."; fi

# 2. Apple Command Line Tools (python3, git, swiftc)
if ! xcode-select -p >/dev/null 2>&1; then
  warn "Installing Apple Command Line Tools — a system window opens; finish it, then run this script again."
  xcode-select --install; exit 1
fi
ok "Command Line Tools"

# 3. audio2mp4 — wraps voice-over takes into mp4 (the board stores media as video), built for this Mac
if [[ ! -x "$P/bin/audio2mp4" || tools/audio2mp4.swift -nt "$P/bin/audio2mp4" ]]; then
  swiftc -O tools/audio2mp4.swift -o "$P/bin/audio2mp4" 2>/dev/null && ok "audio2mp4 built" || fail "audio2mp4 build failed"
else ok "audio2mp4"; fi

# 4. ffmpeg + ffprobe — static builds from ffmpeg.martin-riedl.de (listed on ffmpeg.org)
if [[ ! -x "$P/bin/ffmpeg" || ! -x "$P/bin/ffprobe" ]]; then
  if [[ "$ARCH" == "arm64" ]]; then CH="arm64/snapshot"; else CH="amd64/release"; fi
  for t in ffmpeg ffprobe; do
    print "Downloading $t ($CH)…"
    curl -fsSL -o "$P/bin/$t.zip" "https://ffmpeg.martin-riedl.de/redirect/latest/macos/$CH/$t.zip" \
      && unzip -oq "$P/bin/$t.zip" -d "$P/bin" && rm -f "$P/bin/$t.zip" && chmod +x "$P/bin/$t"
    xattr -d com.apple.quarantine "$P/bin/$t" 2>/dev/null
  done
fi
if "$P/bin/ffmpeg" -hide_banner -version >/dev/null 2>&1; then
  ok "$("$P/bin/ffmpeg" -hide_banner -version | head -1 | cut -c1-40)"
  "$P/bin/ffmpeg" -hide_banner -filters 2>/dev/null | grep -q " subtitles " && ok "ffmpeg can burn captions" || warn "this ffmpeg build cannot burn captions"
else fail "ffmpeg not working"; fi

# 5. ffmpeg-skill (rough-cut tools, MIT, github.com/kajisho5/ffmpeg-skill)
if [[ -d "$P/tools/ffmpeg-skill/.git" ]]; then
  git -C "$P/tools/ffmpeg-skill" pull -q --ff-only && ok "ffmpeg-skill up to date" || warn "ffmpeg-skill update skipped"
else
  git clone -q --depth 1 https://github.com/kajisho5/ffmpeg-skill "$P/tools/ffmpeg-skill" && ok "ffmpeg-skill installed" || fail "ffmpeg-skill download failed"
fi

# 6. API keys — typed hidden, saved only in ~/.brida/.env on this Mac. Never paste keys into chat.
touch "$P/.env"; chmod 600 "$P/.env"
ask_key(){ # VAR, label
  if grep -q "^$1=." "$P/.env"; then ok "$2 key present"; return; fi
  print -n "Paste the $2 API key (hidden, Enter to skip): "; read -rs k; print
  if [[ -n "$k" ]]; then [[ -s "$P/.env" && -n "$(tail -c1 "$P/.env")" ]] && print >> "$P/.env"; print -r -- "$1=$k" >> "$P/.env"; ok "$2 key saved"
  else warn "$2 key skipped — run setup again to add it"; fi
}
ask_key KIE_API_KEY "Kie.ai"
ask_key ELEVENLABS_API_KEY "ElevenLabs"

# 7. Checks
export PATH="$P/bin:$PATH"
if grep -q "^KIE_API_KEY=." "$P/.env"; then c=$(python3 brida_kie.py credits 2>&1 | tail -1); [[ "$c" == [0-9]* ]] && ok "Kie credits: $c" || fail "Kie: $c"; fi
if grep -q "^ELEVENLABS_API_KEY=." "$P/.env"; then c=$(python3 brida_voice.py credits 2>&1 | tail -1); [[ "$c" == [0-9]* ]] && ok "ElevenLabs: $c" || fail "ElevenLabs: $c"; fi
if [[ -d "$P/tools/ffmpeg-skill" ]]; then
  python3 "$P/tools/ffmpeg-skill/scripts/_contract.py" doctor >/dev/null 2>&1 && ok "ffmpeg-skill doctor: ok" || warn "ffmpeg-skill doctor: python3 ~/.brida/tools/ffmpeg-skill/scripts/_contract.py doctor"
fi
print "\nDone. In the Claude desktop app (Code tab) say: «запусти брида машину»."
