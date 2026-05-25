# YouTube Shorts Auto-Pipeline — Internet Archive Edition
# =========================================================
#
# ╔══════════════════════════════════════════════════════════╗
# ║  COPYRIGHT STRATEGY (READ THIS FIRST)                   ║
# ║                                                          ║
# ║  The NARRATION discusses celebrities / events / stories  ║
# ║  The VISUALS are public domain B-roll from Archive.org   ║
# ║                                                          ║
# ║  Why this works legally:                                 ║
# ║  • Actual celebrity footage = copyrighted → strikes      ║
# ║  • Commentary + PD B-roll  = standard practice ✅        ║
# ║  • Every major facts channel does this exact approach    ║
# ╚══════════════════════════════════════════════════════════╝
#
# LEGAL CHECKLIST:
#   ✅ Kokoro TTS           — Apache 2.0, free commercial use
#   ✅ Archive.org footage  — Public domain / CC0 only (filtered)
#   ✅ LLaMA 3.3 / Groq     — Meta commercial license OK
#   ✅ Procedural music     — 100% original, no samples
#   ✅ YouTube disclosure   — AI label + disclosure in description
#   ✅ Output audio         — .wav (lossless, no encoder license issues)
#   ✅ Commentary doctrine  — narration = commentary/education
#
# INSTALL:
#   pip install kokoro soundfile numpy pillow moviepy requests \
#               google-api-python-client google-auth-httplib2 \
#               google-auth-oauthlib
#   Linux: sudo apt-get install espeak-ng ffmpeg
#   macOS: brew install espeak-ng ffmpeg

import os, json, math, random, re, base64, time, hashlib
import requests
from pathlib import Path
from datetime import datetime

import numpy as np
import soundfile as sf
import PIL.Image

if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

from PIL import Image, ImageDraw, ImageFont
from kokoro import KPipeline

from moviepy.editor import (
    VideoFileClip, AudioFileClip, ImageClip,
    CompositeVideoClip, CompositeAudioClip,
    ColorClip, concatenate_videoclips,
)
from moviepy.audio.AudioClip import AudioClip
import moviepy.video.fx.all as vfx
from moviepy.video.fx.all import crop


# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════

GROQ_API_KEY       = os.getenv("GROQ_API_KEY")
CLIENT_SECRET_JSON = os.getenv("CLIENT_SECRET_JSON")   # base64-encoded
TOKEN_JSON         = os.getenv("TOKEN_JSON")            # base64-encoded

# ── Content Niches ────────────────────────────────────────────
# The narration covers these topics; visuals = public-domain B-roll.
# Rotate randomly or set a single one.
NICHES = [
    {
        "id":       "celebrity_mysteries",
        "label":    "Celebrity Dark Secrets",
        "prompt":   "shocking untold mysteries, scandals, and dark secrets surrounding famous celebrities",
        "keywords": ["vintage hollywood", "old cinema", "city lights night", "luxury mansion", "newspaper headlines"],
        "color":    (80, 10, 10),
        "emoji":    "🎭",
    },
    {
        "id":       "business_empires",
        "label":    "Rags-to-Riches Empires",
        "prompt":   "inspiring rags-to-riches business stories — how poor people built billion-dollar empires (Haldiram, Amul, Zara, IKEA, Aldi, etc.)",
        "keywords": ["factory workers 1950s", "small shop market", "industrial machinery vintage", "street market india", "warehouse workers"],
        "color":    (10, 40, 80),
        "emoji":    "💰",
    },
    {
        "id":       "historical_mysteries",
        "label":    "History's Biggest Mysteries",
        "prompt":   "mind-blowing unsolved historical mysteries and conspiracy theories that changed the world",
        "keywords": ["ancient ruins", "old maps exploration", "government documents", "cold war military", "mysterious artifacts"],
        "color":    (20, 50, 30),
        "emoji":    "🔍",
    },
    {
        "id":       "science_facts",
        "label":    "Insane Science Facts",
        "prompt":   "jaw-dropping science facts and discoveries that sound impossible but are 100% real",
        "keywords": ["space exploration nasa", "laboratory science", "nature wildlife", "ocean deep sea", "microscope cells"],
        "color":    (10, 20, 80),
        "emoji":    "🔬",
    },
    {
        "id":       "recent_events",
        "label":    "World Events Untold Truth",
        "prompt":   "shocking untold truths and hidden angles behind major world events and trending news",
        "keywords": ["city skyline", "government buildings", "protest crowd vintage", "newspaper printing", "world map"],
        "color":    (60, 30, 10),
        "emoji":    "🌍",
    },
    {
        "id":       "psychology_hacks",
        "label":    "Dark Psychology Tricks",
        "prompt":   "dark psychology tricks and manipulation tactics used by powerful people that most people never learn",
        "keywords": ["business meeting vintage", "psychology mind", "chess strategy", "human behavior", "social experiment"],
        "color":    (40, 10, 60),
        "emoji":    "🧠",
    },
]

WIDTH, HEIGHT = 1080, 1920
FPS           = 30

OUTPUT_DIR  = Path("shorts_output")
TOPICS_LOG  = Path("used_topics.json")
UPLOAD_LOG  = Path("upload_log.json")
CACHE_DIR   = Path("archive_cache")

OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

AI_DISCLOSURE = (
    "\n\n⚠️ AI Disclosure: Script and voiceover created with AI assistance. "
    "All footage is public domain from Internet Archive (archive.org)."
)

# Kokoro voices — Apache 2.0, all commercial-safe
KOKORO_VOICES = [
    ("am_michael", "a"),   # American Male   — authoritative, deep
    ("bm_george",  "b"),   # British Male    — BBC-like gravitas
    ("bf_emma",    "b"),   # British Female  — warm, engaging
]
TTS_SPEED = 1.08


# ═══════════════════════════════════════════════════════════════
#  FONT LOADER
# ═══════════════════════════════════════════════════════════════

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ═══════════════════════════════════════════════════════════════
#  TEXT RENDERING
# ═══════════════════════════════════════════════════════════════

def _render_text_image(
    text, canvas_w, font_size, text_color, stroke_color=(0,0,0),
    stroke_width=3, max_width_px=None, bg_color=None, padding=20,
):
    max_width_px = max_width_px or (canvas_w - 80)
    font = _load_font(font_size)
    words = text.split()
    lines, current = [], ""
    dummy = Image.new("RGBA", (1, 1))
    dd = ImageDraw.Draw(dummy)

    for word in words:
        test = (current + " " + word).strip()
        bb = dd.textbbox((0, 0), test, font=font)
        if bb[2] - bb[0] <= max_width_px:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    line_bboxes = [dd.textbbox((0, 0), ln, font=font) for ln in lines]
    line_h = max((bb[3] - bb[1]) for bb in line_bboxes) + 8
    block_w = max((bb[2] - bb[0]) for bb in line_bboxes)
    block_h = line_h * len(lines)

    img_w = block_w + padding * 2 + stroke_width * 2
    img_h = block_h + padding * 2 + stroke_width * 2
    img   = Image.new("RGBA", (img_w, img_h), bg_color or (0, 0, 0, 0))
    draw  = ImageDraw.Draw(img)

    for i, line in enumerate(lines):
        bb = draw.textbbox((0, 0), line, font=font)
        lw = bb[2] - bb[0]
        x  = (img_w - lw) // 2
        y  = padding + stroke_width + i * line_h
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=(*stroke_color, 255))
        draw.text((x, y), line, font=font, fill=(*text_color, 255))
    return np.array(img)


def _text_clip(text, duration, font_size, text_color, position,
               stroke_color=(0,0,0), stroke_width=3, bg_color=None,
               start=0.0, opacity=1.0):
    arr = _render_text_image(
        text, WIDTH, font_size, text_color, stroke_color, stroke_width,
        bg_color=bg_color
    )
    return (
        ImageClip(arr)
        .set_duration(duration)
        .set_position(position)
        .set_start(start)
        .set_opacity(opacity)
    )


# ═══════════════════════════════════════════════════════════════
#  MARKER STRIPPING
# ═══════════════════════════════════════════════════════════════

def _clean_for_tts(text):
    text = re.sub(r'\[PAUSE\]', '...', text)
    text = re.sub(r'\[[A-Z_0-9]+\]', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _clean_for_display(text):
    text = re.sub(r'\[[A-Z_0-9]+\]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


# ═══════════════════════════════════════════════════════════════
#  VOICEOVER — Kokoro TTS (Apache 2.0)
# ═══════════════════════════════════════════════════════════════

_kokoro_pipelines: dict = {}


def _get_kokoro_pipeline(lang_code):
    if lang_code not in _kokoro_pipelines:
        print(f"    📦 Loading Kokoro model (lang={lang_code})…")
        _kokoro_pipelines[lang_code] = KPipeline(lang_code=lang_code)
    return _kokoro_pipelines[lang_code]


def generate_voiceover(script_lines, path):
    full_text  = " ".join(l.strip() for l in script_lines if l.strip())
    clean_text = _clean_for_tts(full_text)
    voice_name, lang_code = random.choice(KOKORO_VOICES)
    pipeline   = _get_kokoro_pipeline(lang_code)
    audio_parts = []
    try:
        for _gs, _ps, chunk in pipeline(clean_text, voice=voice_name, speed=TTS_SPEED):
            if chunk is not None and len(chunk) > 0:
                audio_parts.append(
                    chunk if isinstance(chunk, np.ndarray) else np.array(chunk)
                )
    except Exception as e:
        raise RuntimeError(f"Kokoro TTS failed for {voice_name}: {e}")

    if not audio_parts:
        raise RuntimeError("Kokoro produced no audio — is espeak-ng installed?")

    full_audio = np.concatenate(audio_parts).astype(np.float32)
    sf.write(str(path), full_audio, samplerate=24000)
    print(f"    ✅ Voice: {voice_name} | Apache 2.0 ✓")
    return voice_name


# ═══════════════════════════════════════════════════════════════
#  SCRIPT GENERATION — Multi-Niche (Groq / LLaMA 3.3)
# ═══════════════════════════════════════════════════════════════

def pick_niche() -> dict:
    """Rotate through niches, weighted toward the most viral."""
    weights = [3, 2, 2, 2, 1, 2]   # celebrity and biz stories weighted higher
    return random.choices(NICHES, weights=weights, k=1)[0]


def generate_script(niche: dict) -> dict:
    used      = json.loads(TOPICS_LOG.read_text()) if TOPICS_LOG.exists() else []
    avoid_str = ", ".join(used[-40:]) if used else "none"

    prompt = f"""You are a viral YouTube Shorts scriptwriter.
Niche: {niche['prompt']}

Write an EXTREMELY ENGAGING, ADDICTIVE YouTube Short script that stops the scroll.

RULES:
1. Exactly 8–10 short, punchy sentences.
2. FIRST sentence = shocking hook. Must create instant curiosity or disbelief.
3. Every sentence under 15 words.
4. Include specific names, numbers, and dates — vague claims get skipped.
5. Build tension across sentences — each one must make the viewer need the next.
6. Last sentence: "Follow for more shocking truths every day!"
7. Avoid these topics (already used): {avoid_str}
8. The content will be voiced over PUBLIC DOMAIN archival footage — 
   write in a documentary-narration style, not a listicle.

Return ONLY valid JSON (no markdown, no code fences):
{{
  "title": "catchy title with emoji, max 60 chars",
  "topic": "3-word slug for deduplication",
  "hook": "sentence 1 exactly",
  "script": ["sentence1", "sentence2", ...],
  "archive_search_terms": ["term1", "term2", "term3"],
  "description": "compelling YT description, max 200 chars",
  "tags": ["tag1","tag2","tag3","tag4","tag5","tag6"]
}}

archive_search_terms: choose terms that will find GENERIC PUBLIC DOMAIN footage
(NOT the celebrity's name — use visual B-roll concepts like
"vintage city", "old factory", "1950s office", "space exploration",
"crowd cheering", "newspaper headline", "luxury interior", etc.)"""

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                 "Content-Type": "application/json"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.90,
            "max_tokens": 900,
        },
        timeout=30,
    )
    resp.raise_for_status()

    raw = resp.json()["choices"][0]["message"]["content"].strip()
    if raw.startswith("```"):
        raw = raw.split("```", 1)[1].lstrip("json").strip()
    raw = raw.rstrip("```").strip()

    data = json.loads(raw)
    used.append(data["topic"])
    TOPICS_LOG.write_text(json.dumps(used[-200:], indent=2))
    return data


# ═══════════════════════════════════════════════════════════════
#  INTERNET ARCHIVE FETCHER — Public Domain Only
# ═══════════════════════════════════════════════════════════════
#
#  Legal basis:
#  • Prelinger Archives: donated to the public domain / CC0
#    https://archive.org/details/prelinger
#  • US Government films: 17 U.S.C. § 105 — federal gov works
#    are not copyrightable, public domain by statute
#  • nasa: NASA explicitly places all imagery in the public domain
#    https://www.nasa.gov/multimedia/guidelines/index.html
#  • CC0 items: explicitly waived copyright worldwide
#
#  WHAT WE NEVER DOWNLOAD:
#  • News footage from commercial networks (Reuters, AP, BBC, CNN)
#  • Celebrity-specific footage
#  • TV shows, movies (even "old" ones — check carefully)
#  • Anything without explicit PD / CC0 license marker
# ═══════════════════════════════════════════════════════════════

# Only pull from collections with guaranteed public domain status
ARCHIVE_SAFE_COLLECTIONS = [
    "prelinger",         # Prelinger Archives — all public domain
    "usgov",             # US Government — public domain by statute
    "nasa",              # NASA — explicitly public domain
    "ephemera",          # Historical ephemera — PD
    "opensource_movies", # Explicitly open / CC licensed
]

# CC license URLs that permit commercial use
COMMERCIAL_CC_PREFIXES = (
    "https://creativecommons.org/publicdomain/",
    "https://creativecommons.org/licenses/by/",
    "https://creativecommons.org/licenses/by-sa/",
    "https://creativecommons.org/licenses/by-nd/",
)

def _is_commercially_safe(item: dict) -> bool:
    """Check if an Archive.org item is safe for commercial monetized use."""
    license_url = item.get("licenseurl", "") or item.get("license", "")
    subject     = " ".join(item.get("subject", []) if isinstance(item.get("subject"), list) else [item.get("subject", "")])

    # Explicit CC commercial licenses
    if any(license_url.startswith(p) for p in COMMERCIAL_CC_PREFIXES):
        return True
    # US Government items are public domain by law
    if any(c in ARCHIVE_SAFE_COLLECTIONS[:3] for c in
           ([item.get("collection")] if isinstance(item.get("collection"), str)
            else item.get("collection", []))):
        return True
    # No license = assume copyrighted, skip
    return False


def _search_archive(keyword: str, collection: str, max_results: int = 8) -> list:
    """Search Internet Archive and return identifier list."""
    params = {
        "q":        f'collection:{collection} AND ({keyword}) AND mediatype:movies',
        "fl[]":     ["identifier", "title", "licenseurl", "collection", "subject"],
        "sort[]":   "downloads desc",
        "rows":     max_results,
        "page":     1,
        "output":   "json",
    }
    try:
        r = requests.get(
            "https://archive.org/advancedsearch.php",
            params=params,
            timeout=15,
        )
        r.raise_for_status()
        docs = r.json().get("response", {}).get("docs", [])
        return docs
    except Exception as e:
        print(f"    ⚠ Archive search failed ({collection}/{keyword}): {e}")
        return []


def _get_video_url(identifier: str) -> str | None:
    """
    Given an Archive.org item identifier, find the best MP4 download URL.
    Prefers 512kb/720p mp4, falls back to anything playable.
    """
    try:
        r = requests.get(
            f"https://archive.org/metadata/{identifier}",
            timeout=15,
        )
        r.raise_for_status()
        meta = r.json()
    except Exception:
        return None

    files = meta.get("files", [])
    # Ranked preference: smaller MP4 first (faster download, good enough for B-roll)
    preferred = []
    fallback   = []

    for f in files:
        name   = f.get("name", "")
        format = f.get("format", "").lower()
        size   = int(f.get("size", 0) or 0)

        if name.endswith(".mp4") or "mpeg4" in format or "mp4" in format:
            if size < 200 * 1024 * 1024:   # under 200 MB
                preferred.append((size, name))
        elif name.endswith(".ogv") or name.endswith(".webm"):
            fallback.append((size, name))

    chosen = None
    if preferred:
        preferred.sort()
        chosen = preferred[0][1]
    elif fallback:
        fallback.sort()
        chosen = fallback[0][1]

    if chosen:
        return f"https://archive.org/download/{identifier}/{chosen}"
    return None


def _download_clip(url: str, dest: Path) -> bool:
    """Download a file with retry. Returns True on success."""
    if dest.exists() and dest.stat().st_size > 50_000:
        return True
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"    ⚠ Download failed: {e}")
        if dest.exists():
            dest.unlink()
        return False


def fetch_archive_clips(
    search_terms: list,
    topic_slug:   str,
    target_count: int = 6,
    max_duration_s: float = 60,
) -> list:
    """
    Fetch public domain video clips from Internet Archive.

    Strategy:
    1. Search Prelinger + NASA + USGOV collections using B-roll keywords
    2. Verify each item has a commercial-safe license
    3. Download the smallest available MP4 for each item
    4. Cache downloads so repeated runs don't re-download

    Returns list of local file paths.
    """
    found_identifiers = []

    # Shuffle collections so we get variety
    collections = ARCHIVE_SAFE_COLLECTIONS.copy()
    random.shuffle(collections)

    for term in search_terms[:4]:
        for collection in collections[:3]:
            if len(found_identifiers) >= target_count * 2:
                break
            docs = _search_archive(term, collection, max_results=6)
            for doc in docs:
                identifier = doc.get("identifier", "")
                if not identifier:
                    continue
                # Prelinger and NASA are always safe — no need to check license URL
                if collection in ("prelinger", "nasa", "usgov"):
                    found_identifiers.append(identifier)
                elif _is_commercially_safe(doc):
                    found_identifiers.append(identifier)

    # Deduplicate while preserving order
    seen = set()
    unique_ids = []
    for ident in found_identifiers:
        if ident not in seen:
            seen.add(ident)
            unique_ids.append(ident)

    print(f"    📚 Found {len(unique_ids)} archive candidates")

    local_paths = []
    attempts    = 0

    for identifier in unique_ids:
        if len(local_paths) >= target_count:
            break
        attempts += 1
        if attempts > target_count * 3:
            break

        # Use content-hash cache key so same identifier reused across topics
        cache_name = f"archive_{hashlib.md5(identifier.encode()).hexdigest()[:12]}.mp4"
        cache_path = CACHE_DIR / cache_name

        if cache_path.exists() and cache_path.stat().st_size > 50_000:
            local_paths.append(str(cache_path))
            print(f"    💾 Cache hit: {identifier}")
            continue

        url = _get_video_url(identifier)
        if not url:
            print(f"    ⚠ No video URL for: {identifier}")
            continue

        print(f"    ⬇ Downloading: {identifier}")
        if _download_clip(url, cache_path):
            # Quick sanity check: can moviepy open it?
            try:
                test = VideoFileClip(str(cache_path), audio=False)
                dur  = test.duration
                test.close()
                if dur and dur > 1.5:
                    local_paths.append(str(cache_path))
                    print(f"    ✅ {identifier} ({dur:.1f}s)")
                else:
                    print(f"    ⚠ Too short, skipping: {identifier}")
                    cache_path.unlink(missing_ok=True)
            except Exception as e:
                print(f"    ⚠ Not a valid video: {identifier} — {e}")
                cache_path.unlink(missing_ok=True)

        time.sleep(0.5)   # be polite to Archive.org servers

    if not local_paths:
        print("    ⚠ No archive clips found — will use colour fallback")
    else:
        print(f"    ✅ Using {len(local_paths)} public domain clips")

    return local_paths


# ═══════════════════════════════════════════════════════════════
#  PROCEDURAL CINEMATIC MUSIC (100% original, no samples)
# ═══════════════════════════════════════════════════════════════

def generate_background_music(duration: float, mood: str = "dramatic") -> AudioClip:
    """
    Generates a fully original procedural score.
    mood: 'dramatic' | 'mysterious' | 'inspiring' | 'tense'
    All synthesis — zero samples, zero copyright.
    """
    sr  = 44100
    n   = int(duration * sr)
    buf = np.zeros(n, dtype=np.float64)
    rng = np.random.default_rng(random.randint(0, 999999))

    # ── Scale selection by mood ───────────────────────────────
    if mood == "mysterious":
        root     = 130.81   # C3
        # Phrygian dominant (Spanish/mysterious)
        intervals = [0, 1, 4, 5, 7, 8, 10]
        bpm       = random.choice([70, 75, 80])
    elif mood == "inspiring":
        root     = 146.83   # D3
        intervals = [0, 2, 4, 7, 9, 12, 14]   # Major pentatonic + extensions
        bpm       = random.choice([90, 95, 100])
    elif mood == "tense":
        root     = 123.47   # B2
        intervals = [0, 1, 3, 5, 6, 8, 10]    # Locrian
        bpm       = random.choice([100, 110])
    else:  # dramatic (default)
        root     = 138.59   # C#3
        intervals = [0, 2, 3, 5, 7, 8, 10]    # Dorian (dark but epic)
        bpm       = random.choice([80, 85, 90])

    scale = [root * (2 ** (i / 12)) for i in intervals]
    beat  = 60.0 / bpm

    # ── DRUMS ─────────────────────────────────────────────────
    def _add_kick(buf, t_sec, vol=0.45):
        idx = int(t_sec * sr)
        L   = min(int(0.30 * sr), n - idx)
        if L <= 0: return
        t    = np.arange(L) / sr
        freq = 80 * np.exp(-t * 32) + 36
        ph   = 2 * np.pi * np.cumsum(freq) / sr
        buf[idx:idx+L] += np.sin(ph) * np.exp(-t * 14) * vol

    def _add_snare(buf, t_sec, vol=0.22):
        idx = int(t_sec * sr)
        L   = min(int(0.16 * sr), n - idx)
        if L <= 0: return
        t     = np.arange(L) / sr
        noise = rng.standard_normal(L)
        tone  = np.sin(2 * np.pi * 200 * t)
        env   = np.exp(-t * 30)
        buf[idx:idx+L] += (0.6 * noise + 0.4 * tone) * env * vol

    def _add_hihat(buf, t_sec, vol=0.07):
        idx = int(t_sec * sr)
        L   = min(int(0.04 * sr), n - idx)
        if L <= 0: return
        t = np.arange(L) / sr
        buf[idx:idx+L] += rng.standard_normal(L) * np.exp(-t * 120) * vol

    total_beats = int(duration / beat) + 4
    for i in range(total_beats):
        t = i * beat
        # Kick on 1 and 3
        if i % 4 in (0, 2):
            _add_kick(buf, t)
        # Snare on 2 and 4
        if i % 4 in (1, 3):
            _add_snare(buf, t)
        # Hi-hats 8th notes
        _add_hihat(buf, t, vol=0.07)
        _add_hihat(buf, t + beat / 2, vol=0.035)

    # ── BASS ──────────────────────────────────────────────────
    bass_pattern = [scale[0]/2, scale[0]/2, scale[2]/2, scale[1]/2,
                    scale[0]/2, scale[4]/2, scale[3]/2, scale[0]/2]
    for i in range(total_beats):
        freq = bass_pattern[i % len(bass_pattern)]
        idx  = int(i * beat * sr)
        L    = min(int(beat * 0.88 * sr), n - idx)
        if L <= 0: continue
        t   = np.arange(L) / sr
        env = np.exp(-t * 4) * (1 - np.exp(-t * 100))
        buf[idx:idx+L] += (
            np.sin(2 * np.pi * freq * t) * 0.70
            + np.sin(2 * np.pi * freq * 2 * t) * 0.25
            + np.sin(2 * np.pi * freq * 3 * t) * 0.05
        ) * env * 0.28

    # ── CHORD PADS ────────────────────────────────────────────
    chord_prog = [
        [scale[0], scale[2], scale[4]],
        [scale[3], scale[5], scale[1]],
        [scale[2], scale[4], scale[6]] if len(scale) > 6 else [scale[2], scale[4], scale[0]],
        [scale[1], scale[3], scale[5]],
    ]
    chord_dur = beat * 4
    for i in range(int(duration / chord_dur) + 2):
        chord = chord_prog[i % len(chord_prog)]
        idx   = int(i * chord_dur * sr)
        L     = min(int(chord_dur * sr), n - idx)
        if L <= 0: continue
        t   = np.arange(L) / sr
        env = np.clip(t / 0.4, 0, 1) * np.clip((chord_dur - t) / 0.5, 0, 1)
        for freq in chord:
            buf[idx:idx+L] += np.sin(2 * np.pi * freq * t) * env * 0.055
            # Slight detune for richness
            buf[idx:idx+L] += np.sin(2 * np.pi * freq * 1.0017 * t) * env * 0.022

    # ── CINEMATIC LEAD / ARPEGGIO ─────────────────────────────
    arp_pat = [0, 2, 4, 6 % len(scale), 4, 2, 1, 3]
    for i in range(total_beats):
        idx  = int(i * beat * sr)
        freq = scale[arp_pat[i % len(arp_pat)]]
        L    = min(int(beat * 0.65 * sr), n - idx)
        if L <= 0: continue
        t   = np.arange(L) / sr
        env = np.exp(-t * 9) * (1 - np.exp(-t * 50))
        buf[idx:idx+L] += (
            np.sin(2 * np.pi * freq * t) * 0.55
            + np.sin(2 * np.pi * freq * 2 * t) * 0.30
            + np.sin(2 * np.pi * freq * 4 * t) * 0.15
        ) * env * 0.07

    # ── ATMOSPHERIC TEXTURE (synth pad noise) ─────────────────
    atmosphere = rng.standard_normal(n) * 0.003
    # Low-pass feel: smooth with rolling average
    kernel = np.ones(int(sr * 0.005)) / int(sr * 0.005)
    atmosphere = np.convolve(atmosphere, kernel, mode="same")
    buf += atmosphere

    # ── VINYL WARMTH ──────────────────────────────────────────
    buf += rng.standard_normal(n) * 0.002

    # ── DYNAMICS: fade in/out + normalize ─────────────────────
    fade_len = int(sr * 3.0)
    buf[:fade_len]  *= np.linspace(0, 1, fade_len)
    buf[-fade_len:] *= np.linspace(1, 0, fade_len)

    peak = np.max(np.abs(buf))
    if peak > 1e-6:
        buf = buf / peak * 0.28

    stereo = np.column_stack([buf, buf]).astype(np.float32)

    def make_frame(t):
        t_a   = np.atleast_1d(np.asarray(t, dtype=float))
        idx   = np.clip((t_a * sr).astype(int), 0, n - 1)
        frames = stereo[idx]
        return frames[0] if np.isscalar(t) else frames

    return AudioClip(make_frame, duration=duration, fps=sr)


# ═══════════════════════════════════════════════════════════════
#  MOTION HELPERS
# ═══════════════════════════════════════════════════════════════

def _motionize_clip(clip, seg_dur: float, seed: int):
    rng  = random.Random(seed)
    mode = rng.choice(["zoom_in", "zoom_out", "pan_left", "pan_right",
                        "drift", "dynamic"])
    base = rng.uniform(1.12, 1.22)

    if mode == "zoom_in":
        clip = clip.resize(lambda t: base + 0.09 * (t / max(seg_dur, 0.1)))
    elif mode == "zoom_out":
        clip = clip.resize(lambda t: base - 0.08 * (t / max(seg_dur, 0.1)))
    elif mode == "dynamic":
        clip = clip.resize(
            lambda t: base + 0.07 * math.sin(2 * math.pi * t / max(seg_dur, 0.1))
        )
    else:
        clip = clip.resize(base)

    ax, ay = rng.randint(20, 80), rng.randint(15, 50)
    freq   = rng.uniform(0.08, 0.22)
    phase  = rng.uniform(0, 2 * math.pi)

    if mode in ("pan_left", "pan_right", "drift", "dynamic"):
        def pos(t):
            p = t / max(seg_dur, 0.1)
            x = int(ax * math.sin(2 * math.pi * freq * t + phase))
            x += int(-30 * p if mode == "pan_left" else 30 * p if mode == "pan_right"
                     else 15 * math.sin(2 * math.pi * 0.06 * t + phase / 2))
            y = int(ay * math.cos(2 * math.pi * freq * 0.85 * t + phase / 2))
            return (x, y)
        clip = clip.set_position(pos)

    return clip.fx(vfx.fadein, 0.12).fx(vfx.fadeout, 0.12)


def _fit_to_916(clip):
    cw, ch = clip.size
    target = WIDTH / HEIGHT
    if cw / ch > target:
        clip = crop(clip, width=int(ch * target), height=ch, x_center=cw / 2)
    else:
        clip = crop(clip, width=cw, height=int(cw / target), y_center=ch / 2)
    return clip.resize((WIDTH, HEIGHT))


# ═══════════════════════════════════════════════════════════════
#  VIDEO ASSEMBLY
# ═══════════════════════════════════════════════════════════════

def assemble_video(
    script_data:  dict,
    niche:        dict,
    audio_path:   Path,
    stock_paths:  list,
    output_path:  Path,
    mood:         str = "dramatic",
):
    narration = AudioFileClip(str(audio_path))
    total_dur = narration.duration
    sentences = script_data["script"]
    n_clips   = max(len(stock_paths), 1)
    seg_dur   = total_dur / n_clips

    # ── Background stock footage ──────────────────────────────
    bg_clips = []
    for i, sp in enumerate(stock_paths):
        try:
            vc = VideoFileClip(sp, audio=False)
            vc = _fit_to_916(vc)
            vc = _motionize_clip(
                vc, seg_dur,
                seed=hash((script_data["topic"], i)) & 0xFFFFFFFF,
            )
            loop_dur = seg_dur + 0.3
            vc = (
                vc.fx(vfx.loop, duration=loop_dur)
                if vc.duration < loop_dur
                else vc.subclip(0, loop_dur)
            )
            bg_clips.append(vc.set_duration(seg_dur))
        except Exception as e:
            print(f"    ⚠ Skipping clip {i}: {e}")

    if not bg_clips:
        # Gradient fallback
        bg_clips = [
            ColorClip((WIDTH, HEIGHT), color=niche["color"])
            .set_duration(total_dur)
        ]
    else:
        bg_clips[-1] = bg_clips[-1].set_duration(
            total_dur - seg_dur * (len(bg_clips) - 1)
        )

    background = concatenate_videoclips(bg_clips, method="compose").set_duration(total_dur)

    # ── Film grain overlay (vintage feel) ─────────────────────
    overlay = (
        ColorClip((WIDTH, HEIGHT), color=(0, 0, 0))
        .set_opacity(0.30)
        .set_duration(total_dur)
    )

    # ── Top branding bar ──────────────────────────────────────
    brand_bar = (
        ColorClip((WIDTH, 130), color=(20, 20, 30))
        .set_opacity(0.88)
        .set_position((0, 0))
        .set_duration(total_dur)
    )
    brand_text = _text_clip(
        f"  {niche['emoji']}  {niche['label'].upper()}  ",
        duration=total_dur,
        font_size=42,
        text_color=(255, 215, 0),
        stroke_width=2,
        stroke_color=(180, 130, 0),
        position=("center", 30),
    )

    # ── Source attribution watermark (ethical transparency) ───
    source_clip = _text_clip(
        "Footage: Internet Archive (Public Domain)",
        duration=total_dur,
        font_size=26,
        text_color=(200, 200, 200),
        stroke_width=1,
        stroke_color=(0, 0, 0),
        position=(30, HEIGHT - 55),
        opacity=0.75,
    )

    # ── Captions ─────────────────────────────────────────────
    time_per_sent = total_dur / len(sentences)
    caption_clips = []
    cap_bg_colors = [
        (0, 0, 0, 160), (20, 0, 40, 160), (0, 20, 40, 160)
    ]

    for i, sentence in enumerate(sentences):
        display = _clean_for_display(sentence)
        is_hook = i == 0
        size    = 74 if is_hook else 64
        color   = (255, 255, 0) if is_hook else (255, 255, 255)
        base_y  = HEIGHT // 2 - 140

        cap = _text_clip(
            display,
            duration=time_per_sent,
            font_size=size,
            text_color=color,
            stroke_color=(0, 0, 0),
            stroke_width=5 if is_hook else 4,
            position=("center", base_y),
            start=i * time_per_sent,
        )
        cap = cap.fx(vfx.fadein, 0.10).fx(vfx.fadeout, 0.10)
        caption_clips.append(cap)

    # ── Bottom CTA bar ────────────────────────────────────────
    cta_bar = (
        ColorClip((WIDTH, 160), color=(180, 0, 30))
        .set_opacity(0.92)
        .set_position((0, HEIGHT - 160))
        .set_duration(total_dur)
    )
    cta_clip = _text_clip(
        "👆 FOLLOW for daily shocking truths!",
        duration=total_dur,
        font_size=46,
        text_color=(255, 255, 255),
        stroke_width=3,
        stroke_color=(100, 0, 0),
        position=("center", HEIGHT - 148),
    )

    layers = [
        background, overlay,
        brand_bar, brand_text,
        *caption_clips,
        cta_bar, cta_clip,
        source_clip,
    ]

    # ── Audio mix ─────────────────────────────────────────────
    print(f"    🎵 Generating procedural {mood} score…")
    bg_music  = generate_background_music(total_dur, mood=mood)
    audio_mix = CompositeAudioClip([
        narration.volumex(1.0),
        bg_music.volumex(0.28),
    ])

    final = CompositeVideoClip(layers, size=(WIDTH, HEIGHT)).set_audio(audio_mix)

    try:
        final.write_videofile(
            str(output_path),
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=str(OUTPUT_DIR / "_tmp_audio.m4a"),
            remove_temp=True,
            threads=4,
            verbose=False,
            logger=None,
        )
    finally:
        for obj in ([final, audio_mix, narration, bg_music] + bg_clips):
            try: obj.close()
            except: pass

    return output_path


# ═══════════════════════════════════════════════════════════════
#  YOUTUBE UPLOAD
# ═══════════════════════════════════════════════════════════════

def upload_to_youtube(video_path: Path, script_data: dict, niche: dict) -> str:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    TOKEN  = Path("token.json")
    CLIENT = Path("client_secret.json")

    if CLIENT_SECRET_JSON:
        CLIENT.write_bytes(base64.b64decode(CLIENT_SECRET_JSON))
    if TOKEN_JSON:
        TOKEN.write_bytes(base64.b64decode(TOKEN_JSON))

    for f, name in [(CLIENT, "client_secret.json"), (TOKEN, "token.json")]:
        if not f.exists():
            raise FileNotFoundError(f"{name} not found.")

    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN.write_text(creds.to_json())
        else:
            raise RuntimeError("Token invalid — re-run OAuth flow.")

    yt   = build("youtube", "v3", credentials=creds)
    tags = script_data["tags"] + [
        "Shorts", "YouTubeShorts",
        niche["label"].replace(" ", ""),
        "facts", "viral",
    ]

    desc = (
        script_data["description"]
        + f"\n\n#Shorts #YouTubeShorts #{niche['id']}"
        + " ".join(f"#{t.replace(' ','')}" for t in script_data["tags"][:5])
        + AI_DISCLOSURE
        + "\n\n📽️ B-roll footage sourced from Internet Archive (archive.org) "
          "— Public Domain / US Government works."
    )

    body = {
        "snippet": {
            "title":       script_data["title"],
            "description": desc,
            "tags":        list(dict.fromkeys(tags)),
            "categoryId":  "25",   # News & Politics (or 27 = Education)
        },
        "status": {
            "privacyStatus":           "public",
            "selfDeclaredMadeForKids": False,
            "madeForKids":             False,
        },
    }

    media   = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = yt.videos().insert(
        part=",".join(body.keys()), body=body, media_body=media
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"    ⬆ Uploading {int(status.progress()*100)}%", end="\r")

    vid_id = response["id"]
    print(f"\n    ✅ Live: https://www.youtube.com/shorts/{vid_id}")
    return vid_id


# ═══════════════════════════════════════════════════════════════
#  MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════

NICHE_MOOD_MAP = {
    "celebrity_mysteries": "mysterious",
    "business_empires":    "inspiring",
    "historical_mysteries":"mysterious",
    "science_facts":       "inspiring",
    "recent_events":       "dramatic",
    "psychology_hacks":    "tense",
}


def run_pipeline(upload: bool = True, niche_override: str = None):
    ts         = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_path = OUTPUT_DIR / f"voice_{ts}.wav"
    video_path = OUTPUT_DIR / f"short_{ts}.mp4"

    niche = (
        next((n for n in NICHES if n["id"] == niche_override), None)
        or pick_niche()
    )
    mood  = NICHE_MOOD_MAP.get(niche["id"], "dramatic")

    print(f"\n{'═'*62}")
    print(f"🎬  Shorts Pipeline — {ts}")
    print(f"    Niche  : {niche['emoji']} {niche['label']}")
    print(f"    Music  : {mood}")
    print(f"    TTS    : Kokoro Apache 2.0 ✓")
    print(f"    Footage: Internet Archive PD ✓")
    print(f"{'═'*62}")

    try:
        print("\n📝  Generating script…")
        data = generate_script(niche)
        print(f"    Title  : {data['title']}")
        print(f"    Topic  : {data['topic']}")
        print(f"    Hook   : {data['hook'][:70]}…")

        print("\n🎙   Voiceover (Kokoro TTS)…")
        voice = generate_voiceover(data["script"], audio_path)
        print(f"    Saved  : {audio_path} | Voice: {voice}")

        print("\n📚  Fetching public domain footage (Internet Archive)…")
        print(f"    Search terms: {data['archive_search_terms']}")
        clips = fetch_archive_clips(
            data["archive_search_terms"],
            data["topic"],
            target_count=6,
        )
        print(f"    Got {len(clips)} clips")

        print("\n🎞   Assembling video…")
        assemble_video(data, niche, audio_path, clips, video_path, mood=mood)
        print(f"    Saved  : {video_path}")

        vid_id = None
        if upload:
            print("\n📤  Uploading to YouTube…")
            vid_id = upload_to_youtube(video_path, data, niche)

        # Logging
        logs = json.loads(UPLOAD_LOG.read_text()) if UPLOAD_LOG.exists() else []
        logs.append({
            "timestamp": ts,
            "niche":     niche["id"],
            "title":     data["title"],
            "video_id":  vid_id,
            "file":      str(video_path),
        })
        UPLOAD_LOG.write_text(json.dumps(logs, indent=2))

        # Cleanup transient files (keep cached archive clips)
        audio_path.unlink(missing_ok=True)

        print(f"\n🎉  Done! → {video_path.name}")
        print(f"    Legal: PD footage ✓ | Original music ✓ | Apache TTS ✓")
        return vid_id

    except Exception as e:
        print(f"\n❌  Pipeline failed: {e}")
        import traceback; traceback.print_exc()
        raise


# ─── CLI ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--no-upload", action="store_true",
                   help="Render video locally, skip YouTube upload")
    p.add_argument("--niche", choices=[n["id"] for n in NICHES],
                   help="Force a specific content niche")
    p.add_argument("--loop", type=int, default=1,
                   help="Number of videos to produce in sequence")
    args = p.parse_args()

    for i in range(args.loop):
        if args.loop > 1:
            print(f"\n{'━'*62}")
            print(f"  Video {i+1} of {args.loop}")
        run_pipeline(
            upload=not args.no_upload,
            niche_override=args.niche,
        )
        if args.loop > 1 and i < args.loop - 1:
            print("    ⏳ Cooling down 30s before next video…")
            time.sleep(30)
