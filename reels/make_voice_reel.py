"""TheScrollStroll - Voice Reel lane (relatable everyday life).

Builds a vertical (1080x1920) Reel with:
  * a scroll-stopping HOOK spoken and shown from the very first frame
  * a voiceover (Gemini TTS, then edge-tts, then silent as last resort)
  * big word-by-word captions that pop in time with the voice
  * a looping Pixabay video behind it, dimmed so the text is readable
  * a series label at the top so people recognise the format

Writes the SAME files the Make scenario already reads, so Make needs no change:
  reels/out/reel.mp4   reels/out/reel.json   (+ reels/out/history.json to avoid repeats)

Secrets (all optional - each missing one just triggers a fallback):
  GEMINI_API_KEY   script writing + voiceover
  PIXABAY_API_KEY  moving video background
"""
import asyncio
import base64
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
OUT_DIR = Path("reels/out")
TMP_DIR = Path("reels/tmp")
HISTORY_FILE = OUT_DIR / "history.json"
MUSIC_DIR = Path("reels/audio")        # your music library (add as many tracks as you like)
MUSIC_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
HANDLE = "@TheScrollStroll"
REPO_RAW = os.environ.get(
    "REPO_RAW_BASE",
    "https://raw.githubusercontent.com/aakarshmodiuk-hub/thescrollstroll-bot/main",
)

TEXT_MODELS = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
TTS_MODELS = ["gemini-3.8-flash-lite-tts", "gemini-3.8-flash-tts"]
VOICE_NAME = os.environ.get("VOICE_NAME", "Kore")              # Gemini voice
EDGE_VOICE = os.environ.get("EDGE_VOICE", "en-US-AriaNeural")  # fallback voice

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf",
    "/usr/share/fonts/truetype/google-fonts/ofl/montserrat/Montserrat[wght].ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

# Repeatable formats = a reason to follow for the next one
SERIES = [
    "Things nobody tells you about adulthood",
    "Relatable thoughts at 2am",
    "Signs you're officially an adult now",
    "Things only people who cook at home understand",
    "Signs you've been on your phone too long",
    "Monday morning, explained",
    "The group chat knows exactly what I mean",
    "Small things that make a day better",
    "Pets are basically tiny roommates",
    "Things we all do when nobody is watching",
    "Shopping with a plan vs shopping for real",
    "Sunday night feelings, explained",
    "Meetings that could have been an email",
    "Things every office has, whether you like it or not",
    "Signs you're the work friend everyone relies on",
    "Work-from-home habits nobody admits to",
]

# Fallback only: words to look for in track file names, per series
SERIES_MOOD_HINTS = {
    SERIES[0]: ["soft", "piano", "warm", "acoustic"],
    SERIES[1]: ["night", "ambient", "rain", "lofi"],
    SERIES[2]: ["quirky", "upbeat", "acoustic", "warm"],
    SERIES[3]: ["warm", "acoustic", "soft"],
    SERIES[4]: ["lofi", "chill", "focus"],
    SERIES[5]: ["upbeat", "quirky", "chill"],
    SERIES[6]: ["quirky", "upbeat"],
    SERIES[7]: ["warm", "acoustic", "soft", "upbeat"],
    SERIES[8]: ["quirky", "upbeat", "warm"],
    SERIES[9]: ["quirky", "lofi", "chill"],
    SERIES[10]: ["upbeat", "quirky"],
    SERIES[11]: ["lofi", "chill", "peaceful", "rain"],
    SERIES[12]: ["quirky", "upbeat"],
    SERIES[13]: ["quirky", "upbeat", "chill"],
    SERIES[14]: ["warm", "acoustic", "upbeat"],
    SERIES[15]: ["lofi", "chill", "quirky"],
}

CORE_TAGS = ["#relatable", "#everydaylife", "#dailythoughts", "#relatablecontent", "#realtalk"]
BANNED_TAGS = {"#fyp", "#foryou", "#foryoupage", "#viral", "#explore", "#trending", "#follow",
               "#followme", "#like4like", "#instagood", "#love", "#instagram"}
MAX_HASHTAGS = 10
MAX_CAPTION_CHARS = 2000

CTAS = [
    "Follow {h} for a daily dose of relatable.",
    "Send this to the friend who gets it. More daily on {h}.",
    "Save this for the next bad day. Follow {h}.",
]

BG_TERMS = ["coffee morning", "city walk", "rain window", "train window", "night city",
            "laptop desk", "kitchen", "sunset street", "cozy room", "road trip"]

# Original scripts, used only if Gemini is unavailable
FALLBACK_SCRIPTS = [
    {"series": SERIES[0], "hook": "Nobody warns you adulthood is this tiring.",
     "lines": ["You call bills a personality.", "Nine p.m. is your new bedtime."],
     "payoff": "We're all just winging it.",
     "comment": "Which one is you?", "tags": ["#adultlife"], "visual": "coffee morning"},
    {"series": SERIES[1], "hook": "2 a.m. and your brain remembered everything.",
     "lines": ["That awkward thing from 2016.", "Whether you left the oven on."],
     "payoff": "Sleep is optional, apparently.",
     "comment": "What keeps you up?", "tags": ["#overthinking"], "visual": "night city"},
    {"series": SERIES[3], "hook": "If you cook at home, you know this feeling.",
     "lines": ["Fresh herbs, one leaf used.", "'Quick recipe' lied again."],
     "payoff": "Dinner is a small daily win.",
     "comment": "What do you always overcook?", "tags": ["#homecooking"], "visual": "kitchen"},
    {"series": SERIES[5], "hook": "Monday mornings have their own sadness.",
     "lines": ["Alarm negotiates five more minutes.", "Coffee becomes your personality."],
     "payoff": "Weekend feels like a rumour.",
     "comment": "How's your Monday?", "tags": ["#mondayvibes"], "visual": "city walk"},
    {"series": SERIES[8], "hook": "Your pet has decided who's in charge.",
     "lines": ["They wait by the door like you're late.", "They sleep on your laptop."],
     "payoff": "We pay the bills, they run the house.",
     "comment": "Who runs your home?", "tags": ["#petlife"], "visual": "cozy room"},
    {"series": SERIES[11], "hook": "Remember when weekends meant plans?",
     "lines": ["Now it's a nap and zero obligations.", "Cancelled plans feel like a win."],
     "payoff": "Growing up is getting good at staying in.",
     "comment": "Be honest, who agrees?", "tags": ["#introvert"], "visual": "cozy room"},
    {"series": SERIES[12], "hook": "Some meetings could have been one sentence.",
     "lines": ["Twenty slides to say we need time.", "'Quick sync' lasts an hour."],
     "payoff": "The best part is the follow-up email.",
     "comment": "Which meeting ruined your afternoon?", "tags": ["#worklife"], "visual": "laptop desk"},
    {"series": SERIES[14], "hook": "Every office has one person who knows everything.",
     "lines": ["Nobody remembers when that started.", "They still answer with a smile."],
     "payoff": "Buy that person a coffee today.",
     "comment": "Who's your office hero?", "tags": ["#officelife"], "visual": "office window"},
]


# ------------------------------------------------------------------ helpers ----
def clean_text(text):
    """Plain ASCII-ish text the caption font can always draw."""
    text = (str(text).replace("\u2018", "'").replace("\u2019", "'")
            .replace("\u201c", '"').replace("\u201d", '"')
            .replace("\u2014", ", ").replace("\u2013", ", ").replace("\u2026", "..."))
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"[^\x20-\x7E]", "", text)
    return re.sub(r"\s+", " ", text).strip().strip('"')


def end_punct(text):
    return text if re.search(r"[.!?]$", text) else text + "."


def clean_tag(tag):
    body = re.sub(r"[^a-z0-9]", "", str(tag).lower().lstrip("#"))
    return f"#{body}" if 3 <= len(body) <= 30 else None


def clean_search_word(text):
    words = re.sub(r"[^a-zA-Z ]", " ", str(text)).split()
    return " ".join(words[:2]).lower() if words else None


def post_json(url, body, headers=None, timeout=60):
    hdr = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, headers=hdr, data=json.dumps(body).encode())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post_with_retry(url, body, headers, attempts=2, timeout=60, label="CALL"):
    """Retry on timeouts / 5xx / 429; a 4xx (bad model name) fails straight away."""
    last = None
    for n in range(1, attempts + 1):
        try:
            return post_json(url, body, headers, timeout)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise
            last = exc
        except Exception as exc:  # noqa: BLE001
            last = exc
        print(f"{label}: attempt {n}/{attempts} failed ({last})")
        time.sleep(3)
    raise last


def load_history():
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return {"hooks": list(data.get("hooks", []))[-30:], "last_series": data.get("last_series", ""),
                "last_track": data.get("last_track", ""),
                "recent_series": list(data.get("recent_series", []))[-(len(SERIES) - 1):]}
    except Exception:  # noqa: BLE001
        return {"hooks": [], "last_series": "", "last_track": "", "recent_series": []}


def save_history(history, hook, series, track_name=""):
    history["hooks"] = (history["hooks"] + [hook])[-30:]
    history["last_series"] = series
    history["recent_series"] = (history.get("recent_series", []) + [series])[-(len(SERIES) - 1):]
    history["last_track"] = track_name
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------- script ----
def ask_gemini_script(series, recent_hooks, track_names):
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        print("SCRIPT: GEMINI_API_KEY missing -> built-in script.")
        return None
    avoid = "\n".join(f"- {h}" for h in recent_hooks[-12:]) or "(none yet)"
    prompt = (
        f"You write 20-second Instagram Reel scripts for the page {HANDLE}.\n"
        f'Series title (shown on screen): "{series}".\n'
        "Audience: 18-40 year olds. Topic: relatable everyday life (food, phones, friends, family, "
        "pets, shopping, commuting, weekends, sleep, office and work life, small daily moments). "
        "Total spoken script must be under 25 words. Short, fast, punchy. "
        "Work jokes must be funny and specific (meetings, emails, colleagues, video calls), never "
        "preachy or motivational. Tone: spoken, conversational, funny-because-true, "
        "a little self-deprecating, never preachy. Use contractions. No emojis.\n"
        "Return ONLY a JSON object with these keys:\n"
        '  "hook": one scroll-stopping opening line, max 8 words, speaks directly to "you";\n'
        '  "lines": array of exactly 2 very short spoken lines, max 7 words each, each a different '
        "relatable observation that fits the series title;\n"
        '  "payoff": a punchline, max 7 words, a funny twist people want to share;\n'
        '  "comment": a short question (max 10 words) that makes viewers comment;\n'
        '  "hashtags": 4 to 6 lowercase hashtags specific to THIS script (no #fyp or #viral);\n'
        '  "visual": 1 or 2 plain words for a calm background video that fits the mood'
        + (';\n  "music": the ONE track from the list below whose mood best fits this script, '
           'copied exactly.\n' if track_names else ".\n")
        + (f"Available music tracks: {', '.join(track_names)}\n" if track_names else "")
        + f"Do NOT reuse or closely copy these recent hooks:\n{avoid}"
    )
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    for model in TEXT_MODELS:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            data = post_with_retry(url, body, {"x-goog-api-key": key}, label="SCRIPT")
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
            obj = json.loads(text)
            hook = end_punct(clean_text(obj.get("hook", "")))
            lines = [end_punct(clean_text(x)) for x in obj.get("lines", []) if clean_text(x)]
            payoff = end_punct(clean_text(obj.get("payoff", "")))
            comment = clean_text(obj.get("comment", ""))
            words = len(" ".join([hook, *lines, payoff]).split())
            if not (3 <= len(hook) <= 80 and len(lines) == 2 and len(payoff) >= 3 and 12 <= words <= 30):
                print(f"SCRIPT: {model} answer didn't fit the format ({words} words), trying next.")
                continue
            tags = [t for t in (clean_tag(x) for x in obj.get("hashtags", [])) if t and t not in BANNED_TAGS]
            print(f"SCRIPT: written by Gemini ({model})")
            return {"series": series, "hook": hook, "lines": lines, "payoff": payoff,
                    "comment": comment if 3 <= len(comment) <= 90 else "", "tags": tags,
                    "visual": clean_search_word(obj.get("visual", "")),
                    "music": str(obj.get("music", "")).strip()}
        except Exception as exc:  # noqa: BLE001
            print(f"SCRIPT: {model} failed ({exc}), trying next.")
    print("SCRIPT: Gemini unavailable -> built-in script.")
    return None


def pick_script(history, track_names):
    # cycle through every series before any repeats: avoid the last len(SERIES)-1 used
    recent = history.get("recent_series", [])
    options = [x for x in SERIES if x not in recent] or [x for x in SERIES if x != history["last_series"]] or SERIES
    series = random.choice(options)
    script = ask_gemini_script(series, history["hooks"], track_names)
    if script:
        return script
    recent = history.get("recent_series", [])
    fresh = [f for f in FALLBACK_SCRIPTS if f["series"] not in recent and f["hook"] not in history["hooks"]]
    pool = fresh or [f for f in FALLBACK_SCRIPTS if f["hook"] not in history["hooks"]] or FALLBACK_SCRIPTS
    return dict(random.choice(pool))


# -------------------------------------------------------------------- voice ----
def wav_duration(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def write_wav(path, pcm, rate):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def trim_and_normalise(src, dst):
    """Cut silence at both ends (so the hook starts at 0s), then level the volume.
    Two separate ffmpeg passes: one combined filter chain can stall on audio with no silence."""
    cut = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.04"
    trimmed = TMP_DIR / "voice_trimmed.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                    "-af", f"{cut},areverse,{cut},areverse", str(trimmed)], check=True, timeout=120)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(trimmed),
                    "-af", "atempo=1.2,loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "1", str(dst)],
                   check=True, timeout=120)


def estimate_word_times(text, duration):
    """Spread the words over the audio by length + punctuation pauses (no timestamps needed)."""
    tokens = text.split()
    weights = []
    for t in tokens:
        w = len(re.sub(r"\W", "", t)) + 2
        if re.search(r"[,;:]$", t):
            w += 3
        if re.search(r"[.!?]$", t):
            w += 7
        weights.append(w)
    total = float(sum(weights)) or 1.0
    out, t0 = [], 0.0
    for tok, w in zip(tokens, weights):
        span = duration * w / total
        out.append((tok, t0, t0 + span))
        t0 += span
    return out


def synth_gemini(text):
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        return None
    body = {"contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE_NAME}}}}}
    for model in TTS_MODELS:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            data = post_with_retry(url, body, {"x-goog-api-key": key}, timeout=90, label="VOICE")
            part = data["candidates"][0]["content"]["parts"][0]
            inline = part.get("inlineData") or part.get("inline_data")
            mime = inline.get("mimeType") or inline.get("mime_type") or ""
            pcm = base64.b64decode(inline["data"])
            m = re.search(r"rate=(\d+)", mime)
            rate = int(m.group(1)) if m else 24000
            raw = TMP_DIR / "voice_raw.wav"
            write_wav(raw, pcm, rate)
            clean = TMP_DIR / "voice.wav"
            trim_and_normalise(raw, clean)
            dur = wav_duration(clean)
            if dur < 3:
                print(f"VOICE: {model} audio too short ({dur:.1f}s), trying next.")
                continue
            print(f"VOICE: Gemini TTS ({model}, voice {VOICE_NAME}), {dur:.1f}s")
            return clean, dur, estimate_word_times(text, dur)
        except Exception as exc:  # noqa: BLE001
            print(f"VOICE: {model} failed ({exc}), trying next.")
    return None


def synth_edge(text):
    try:
        import edge_tts  # optional dependency
    except Exception:  # noqa: BLE001
        print("VOICE: edge-tts not installed, skipping.")
        return None

    async def run():
        try:
            comm = edge_tts.Communicate(text, EDGE_VOICE, rate="+12%", boundary="WordBoundary")
        except TypeError:
            comm = edge_tts.Communicate(text, EDGE_VOICE, rate="+12%")
        audio, words = bytearray(), []
        async for ch in comm.stream():
            if ch["type"] == "audio":
                audio.extend(ch["data"])
            elif ch["type"] == "WordBoundary":
                s = ch["offset"] / 1e7
                words.append((ch["text"], s, s + ch["duration"] / 1e7))
        return bytes(audio), words

    try:
        audio, words = asyncio.run(run())
        mp3 = TMP_DIR / "voice_edge.mp3"
        mp3.write_bytes(audio)
        wav = TMP_DIR / "voice.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "1", str(wav)], check=True, timeout=120)
        dur = wav_duration(wav)
        if dur < 3:
            return None
        if len(words) < 5:
            words = estimate_word_times(text, dur)
        print(f"VOICE: edge-tts fallback ({EDGE_VOICE}), {dur:.1f}s")
        return wav, dur, words
    except Exception as exc:  # noqa: BLE001
        print(f"VOICE: edge-tts failed ({exc}).")
        return None


def make_voice(text):
    result = synth_gemini(text) or synth_edge(text)
    if result:
        return result
    dur = max(10.0, len(text.split()) * 0.40 + 1.0)
    print(f"VOICE: all voice options failed -> SILENT Reel ({dur:.0f}s). Check the VOICE lines above.")
    return None, dur, estimate_word_times(text, dur)


# -------------------------------------------------------------------- music ----
def list_tracks():
    """All audio files in reels/audio (README and other files are ignored)."""
    if not MUSIC_DIR.exists():
        return []
    return sorted(p for p in MUSIC_DIR.iterdir() if p.is_file() and p.suffix.lower() in MUSIC_EXTS)


def norm(name):
    """Lowercase, no extension, letters and digits only: 'Quirky Upbeat.MP3' == 'quirky-upbeat'."""
    return re.sub(r"[^a-z0-9]", "", Path(str(name)).stem.lower())


def pick_music(tracks, script, last_track):
    """Gemini's mood pick -> keyword match for the series -> random. Avoids repeating the last track."""
    print(f"MUSIC: found {len(tracks)} track(s) in {MUSIC_DIR}: " + (", ".join(t.name for t in tracks) or "none"))
    if not tracks:
        print("MUSIC: no audio files in reels/audio -> no music.")
        return None
    pool = [t for t in tracks if t.name != last_track] or tracks
    wanted = norm(script.get("music") or "")
    if wanted:
        for t in pool:
            if wanted == norm(t.name):
                print(f"MUSIC: Gemini matched the mood -> {t.name}")
                return t
        print(f"MUSIC: Gemini suggested '{script.get('music')}', which isn't in the list above -> using mood keywords.")
    hints = SERIES_MOOD_HINTS.get(script.get("series"), [])
    scored = sorted(((sum(h in t.stem.lower() for h in hints), random.random(), t) for t in pool), reverse=True)
    if scored and scored[0][0] > 0:
        print(f"MUSIC: keyword match for '{script.get('series')}' -> {scored[0][2].name}")
        return scored[0][2]
    choice = random.choice(pool)
    print(f"MUSIC: random pick -> {choice.name}")
    return choice


def mix_music(voice, total, track, out_path):
    """Voice + quiet looping music. Music dips automatically whenever the voice speaks."""
    voice_in = ["-i", str(voice)] if voice else ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=44100:cl=mono"]
    fade_out_at = max(0.0, total - 1.5)
    graph = (
        f"[1:a]atrim=0:{total:.2f},asetpts=PTS-STARTPTS,loudnorm=I=-21:TP=-3:LRA=7,"
        f"afade=t=in:st=0:d=0.8,afade=t=out:st={fade_out_at:.2f}:d=1.5,aformat=sample_rates=44100:channel_layouts=mono[m];"
        f"[0:a]apad=whole_dur={total:.2f},aformat=sample_rates=44100:channel_layouts=mono,asplit[v][sc];"
        "[m][sc]sidechaincompress=threshold=0.05:ratio=3:attack=20:release=500[duck];"
        "[v][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]"
    )
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *voice_in,
                    "-stream_loop", "-1", "-i", str(track),
                    "-filter_complex", graph, "-map", "[a]", "-t", f"{total:.2f}",
                    "-ar", "44100", "-ac", "1", str(out_path)], check=True, timeout=120)
    print(f"MUSIC: mixed in {track.name}")
    return out_path


# --------------------------------------------------------------- background ----
def download_background(search_words):
    key = (os.environ.get("PIXABAY_API_KEY") or "").strip()
    if not key:
        print("BACKGROUND: PIXABAY_API_KEY empty or missing -> gradient used.")
        return None
    for term in search_words + ["nature", ""]:
        try:
            q = urllib.parse.quote(term)
            url = f"https://pixabay.com/api/videos/?key={key}&q={q}&per_page=30&safesearch=true"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            hits = [h for h in data.get("hits", []) if 4 <= h.get("duration", 0) <= 60]
            print(f"BACKGROUND: search '{term}' -> {len(data.get('hits', []))} hits, {len(hits)} usable")
            if not hits:
                continue
            vids = random.choice(hits)["videos"]
            for size in ("medium", "large", "small", "tiny"):
                link = (vids.get(size) or {}).get("url")
                if not link:
                    continue
                dest = TMP_DIR / "bg.mp4"
                req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=90) as r, open(dest, "wb") as f:
                    f.write(r.read())
                if dest.stat().st_size > 50_000:
                    print(f"BACKGROUND: using Pixabay video ({size}, {dest.stat().st_size / 1e6:.1f} MB)")
                    return dest
        except Exception as exc:  # noqa: BLE001
            print(f"BACKGROUND: search '{term}' failed: {exc}")
    print("BACKGROUND: all Pixabay attempts failed -> gradient used.")
    return None


# ----------------------------------------------------------------- captions ----
def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                try:
                    font.set_variation_by_name("Bold")
                except Exception:  # noqa: BLE001
                    pass
                return font
            except OSError:
                continue
    return ImageFont.load_default()


def wrap_to_width(draw, text, font, max_width):
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def make_chunks(words, hook_word_count):
    """Group words into 1-3 word caption chunks. Returns [(text, start, end, is_hook)]."""
    groups, cur = [], []
    for i, (t, s, e) in enumerate(words):
        cur.append((i, t, s, e))
        text = " ".join(x[1] for x in cur)
        if (len(cur) >= 3 or len(text) >= 20 or (len(cur) >= 2 and len(text) >= 14)
                or re.search(r"[.!?,;:]$", t)):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    chunks = []
    for g in groups:
        text = " ".join(x[1] for x in g).upper()
        text = re.sub(r"[,;:.]+$", "", text)
        chunks.append([text, g[0][2], None, g[0][0] < hook_word_count])
    for k, ch in enumerate(chunks):
        ch[2] = chunks[k + 1][1] if k + 1 < len(chunks) else None
    chunks[0][1] = 0.0  # the hook is on screen from the very first frame
    return chunks


def render_chunk_png(text, color, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    max_w = 920
    chosen = None
    for size in range(150, 63, -4):
        font = load_font(size)
        lines = wrap_to_width(draw, text, font, max_w)
        line_h = int(size * 1.15)
        if len(lines) <= 2 and all(draw.textlength(l, font=font) <= max_w for l in lines):
            chosen = (font, lines, line_h, size)
            break
    if chosen is None:
        font = load_font(64)
        lines = wrap_to_width(draw, text, font, max_w)
        chosen = (font, lines, int(64 * 1.15), 64)
    font, lines, line_h, size = chosen
    total_h = len(lines) * line_h
    y = 900 - total_h // 2
    for line in lines:
        x = (W - draw.textlength(line, font=font)) / 2
        draw.text((x, y), line, font=font, fill=color, stroke_width=max(4, int(size * 0.08)),
                  stroke_fill=(0, 0, 0, 255))
        y += line_h
    img.save(path)


def render_static_png(series, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    label = series.upper()
    size = 40
    font = load_font(size)
    while draw.textlength(label, font=font) > W - 220 and size > 24:
        size -= 2
        font = load_font(size)
    tw = draw.textlength(label, font=font)
    pad_x, pad_y = 36, 22
    x0, y0 = (W - tw) / 2 - pad_x, 300
    draw.rounded_rectangle([x0, y0, x0 + tw + 2 * pad_x, y0 + size + 2 * pad_y], radius=44, fill=(0, 0, 0, 150))
    draw.text(((W - tw) / 2, y0 + pad_y - 4), label, font=font, fill=(255, 255, 255, 255))
    small = load_font(40)
    hw = draw.textlength(HANDLE, font=small)
    draw.text(((W - hw) / 2, 1500), HANDLE, font=small, fill=(255, 255, 255, 210),
              stroke_width=3, stroke_fill=(0, 0, 0, 200))
    img.save(path)


# -------------------------------------------------------------------- video ----
def build_video(bg, audio, total, chunk_files, chunks, static_png, out_path):
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if bg:
        cmd += ["-stream_loop", "-1", "-i", str(bg)]
        base = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
                "fps=30,eq=brightness=-0.30:saturation=1.05[b]")
    else:
        cmd += ["-f", "lavfi", "-i",
                f"gradients=s={W}x{H}:c0=0x1f1c2c:c1=0x928dab:x0=0:y0=0:x1={W}:y1={H}:speed=0.015:d={total:.2f}"]
        base = "[0:v]fps=30,setsar=1[b]"
    cmd += ["-loop", "1", "-framerate", "30", "-t", f"{total:.2f}", "-i", str(static_png)]
    for f in chunk_files:
        cmd += ["-loop", "1", "-framerate", "30", "-t", f"{total:.2f}", "-i", str(f)]
    if audio:
        cmd += ["-i", str(audio)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=44100:cl=mono"]
    audio_idx = 2 + len(chunk_files)

    graph = [base, "[b][1:v]overlay=0:0[v1]"]
    prev = "v1"
    for k, (ch, _f) in enumerate(zip(chunks, chunk_files)):
        start = ch[1]
        end = ch[2] if ch[2] is not None else total
        nxt = f"v{k + 2}"
        graph.append(f"[{prev}][{k + 2}:v]overlay=0:0:enable='between(t,{start:.2f},{end:.2f})'[{nxt}]")
        prev = nxt
    graph.append(f"[{prev}]format=yuv420p[v]")
    cmd += ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", f"{audio_idx}:a",
            "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-movflags", "+faststart", str(out_path)]
    subprocess.run(cmd, check=True, timeout=900)


# ------------------------------------------------------------------ caption ----
def build_caption(script):
    tags = []
    for t in script["tags"][:4] + CORE_TAGS + ["#reels"]:
        if t not in tags and t not in BANNED_TAGS:
            tags.append(t)
    tags = tags[:MAX_HASHTAGS]
    parts = [script["hook"]]
    if script["comment"]:
        parts.append(script["comment"])
    parts.append(random.choice(CTAS).format(h=HANDLE))
    parts.append(" ".join(tags))
    caption = "\n\n".join(parts)
    if len(caption) > MAX_CAPTION_CHARS:
        caption = caption[:MAX_CAPTION_CHARS].rsplit(" ", 1)[0]
    return caption, tags


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    history = load_history()
    tracks = list_tracks()
    script = pick_script(history, [t.stem for t in tracks])
    spoken = " ".join([script["hook"], *script["lines"], script["payoff"]])
    print(f"SERIES: {script['series']}\nHOOK: {script['hook']}\nSPOKEN: {spoken}")

    audio, voice_dur, words = make_voice(spoken)
    chunks = make_chunks(words, len(script["hook"].split()))
    total = round(voice_dur + 0.3, 2)  # short hold at the end

    voice_ok = audio is not None
    track = pick_music(tracks, script, history.get("last_track", ""))
    if track:
        try:
            audio = mix_music(audio, total, track, TMP_DIR / "final_audio.wav")
        except Exception as exc:  # noqa: BLE001
            print(f"MUSIC: mixing failed ({exc}) -> continuing without music.")
            track = None

    static_png = TMP_DIR / "static.png"
    render_static_png(script["series"], static_png)
    chunk_files = []
    for k, ch in enumerate(chunks):
        color = (255, 222, 23, 255) if ch[3] else (255, 255, 255, 255)  # hook in yellow
        f = TMP_DIR / f"chunk_{k:02d}.png"
        render_chunk_png(ch[0], color, f)
        chunk_files.append(f)
    print(f"CAPTIONS: {len(chunks)} word groups over {total:.1f}s")

    terms = ([script["visual"]] if script.get("visual") else []) + random.sample(BG_TERMS, 3)
    bg = download_background(terms)

    out_mp4 = OUT_DIR / "reel.mp4"
    build_video(bg, audio, total, chunk_files, chunks, static_png, out_mp4)

    caption, tags = build_caption(script)
    print("TAGS:", " ".join(tags))
    stamp = int(time.time())
    meta = {
        "category": script["series"],
        "quote": spoken,
        "caption": caption,
        "hashtags": tags,
        "video_url": f"{REPO_RAW}/reels/out/reel.mp4?v={stamp}",
        "duration_seconds": total,
        "generated_at": stamp,
        "voice": "voiceover" if voice_ok else "silent",
        "music": track.name if track else "none",
    }
    (OUT_DIR / "reel.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    save_history(history, script["hook"], script["series"], track.name if track else "")
    print("DONE:", out_mp4, f"({out_mp4.stat().st_size / 1e6:.1f} MB, {total:.1f}s)")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print("FFmpeg failed:", exc, file=sys.stderr)
        sys.exit(1)
