# ============================================================
# AUTONOMOUS YOUTUBE SHORTS ENGINE
# ============================================================
#
# FEATURES
# --------
# ✓ Infinite AI-generated documentary ideas
# ✓ Semantic visual matching
# ✓ Dynamic visual direction
# ✓ Mobile-safe vertical rendering
# ✓ Micro-cut editing system
# ✓ Procedural music randomization
# ✓ Cinematic pacing engine
# ✓ Pexels integration
# ✓ Kokoro TTS
# ✓ Groq/LLaMA script generation
# ✓ Fully automated Shorts pipeline
#
# ============================================================

import os
import json
import time
import math
import random
import hashlib
import requests
import numpy as np
import soundfile as sf

from pathlib import Path
from datetime import datetime
from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips,
    ColorClip,
    ImageClip,
)

import moviepy.video.fx.all as vfx

from PIL import Image, ImageDraw, ImageFont
from kokoro import KPipeline

# ============================================================
# CONFIG
# ============================================================

WIDTH = 1080
HEIGHT = 1920
FPS = 30

OUTPUT_DIR = Path("output")
CACHE_DIR = Path("cache")

OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

# ============================================================
# KOKORO
# ============================================================

pipeline = KPipeline(lang_code="a")

# ============================================================
# FONT
# ============================================================

def get_font(size):
    fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]

    for f in fonts:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)

    return ImageFont.load_default()

# ============================================================
# SCRIPT GENERATION
# ============================================================

def generate_script(topic="business empire"):
    prompt = f"""
You are writing a viral YouTube Shorts documentary.

Topic category:
{topic}

Return ONLY valid JSON.

Format:
{{
  "title": "...",
  "segments": [
    {{
      "line": "...",
      "visual": "specific footage search term"
    }}
  ]
}}

IMPORTANT:
- Every visual must describe what should literally appear on screen.
- Use documentary style visuals.
- Use emotional visual matching.
- Do NOT use generic terms.

BAD:
"business success"

GOOD:
"crowded indian street food market"
"old spice shop india"
"factory workers preparing snacks"
"newspaper printing press"

8-10 segments.
Short punchy narration.
"""

    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
        },
        timeout=60,
    )

    raw = r.json()["choices"][0]["message"]["content"]

    if raw.startswith("```"):
        raw = raw.split("```", 1)[1]
        raw = raw.replace("json", "")
        raw = raw.strip("`")

    return json.loads(raw)

# ============================================================
# TTS
# ============================================================

def generate_voiceover(segments, out_path):
    audio_chunks = []
    timings = []

    current = 0.0
    sr = 24000

    opening = np.zeros(int(sr * 0.3), dtype=np.float32)
    audio_chunks.append(opening)
    current += 0.3

    for idx, seg in enumerate(segments):
        text = seg["line"]

        sentence_audio = []

        for _, _, audio in pipeline(text, voice="am_michael", speed=0.96 if idx == 0 else 1.0):
            if audio is not None:
                sentence_audio.append(np.array(audio))

        sentence_audio = np.concatenate(sentence_audio).astype(np.float32)

        start = current

        audio_chunks.append(sentence_audio)

        duration = len(sentence_audio) / sr
        current += duration

        timings.append({
            "text": text,
            "visual": seg["visual"],
            "start": start,
            "end": current,
            "duration": duration,
        })

        pause = np.zeros(int(sr * 0.45), dtype=np.float32)
        audio_chunks.append(pause)
        current += 0.45

    final_audio = np.concatenate(audio_chunks)

    peak = np.max(np.abs(final_audio))
    if peak > 0:
        final_audio = final_audio / peak * 0.92

    sf.write(out_path, final_audio, sr)

    return timings

# ============================================================
# VIDEO SEARCH
# ============================================================

def search_pexels_video(query):
    headers = {
        "Authorization": PEXELS_API_KEY
    }

    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers=headers,
        params={
            "query": query,
            "per_page": 10,
        },
        timeout=30,
    )

    data = r.json()

    videos = data.get("videos", [])

    if not videos:
        return None

    random.shuffle(videos)

    for vid in videos:
        files = vid.get("video_files", [])

        mp4s = [f for f in files if f.get("file_type") == "video/mp4"]

        if mp4s:
            mp4s.sort(key=lambda x: x.get("width", 0))
            return mp4s[-1]["link"]

    return None

# ============================================================
# DOWNLOAD
# ============================================================

def download_video(url):
    key = hashlib.md5(url.encode()).hexdigest()[:12]
    path = CACHE_DIR / f"{key}.mp4"

    if path.exists():
        return str(path)

    r = requests.get(url, stream=True)

    with open(path, "wb") as f:
        for chunk in r.iter_content(65536):
            f.write(chunk)

    return str(path)

# ============================================================
# VERTICAL FIT FIX
# ============================================================

def fit_vertical(clip):
    bg = (
        clip
        .resize(height=HEIGHT)
        .resize((WIDTH, HEIGHT))
        .fx(vfx.gaussian_blur, 35)
        .set_opacity(0.75)
    )

    fg = clip.resize(height=HEIGHT)

    if fg.w > WIDTH:
        fg = fg.resize(width=WIDTH)

    return CompositeVideoClip(
        [
            bg,
            fg.set_position("center")
        ],
        size=(WIDTH, HEIGHT)
    )

# ============================================================
# MICRO CUT SYSTEM
# ============================================================

def create_micro_clips(path, duration):
    source = VideoFileClip(path, audio=False)

    source = fit_vertical(source)

    clips = []

    remaining = duration

    while remaining > 0:
        piece = random.uniform(0.8, 1.8)
        piece = min(piece, remaining)

        max_start = max(0, source.duration - piece)

        start = random.uniform(0, max_start) if max_start > 0 else 0

        clip = source.subclip(start, start + piece)

        motion = random.choice([
            "zoom_in",
            "zoom_out",
            "pan"
        ])

        if motion == "zoom_in":
            clip = clip.resize(lambda t: 1.0 + 0.06 * t)

        elif motion == "zoom_out":
            clip = clip.resize(lambda t: 1.08 - 0.05 * t)

        else:
            clip = clip.set_position(
                lambda t: (
                    int(math.sin(t * 0.5) * 20),
                    int(math.cos(t * 0.5) * 15)
                )
            )

        clip = clip.fx(vfx.fadein, 0.1)
        clip = clip.fx(vfx.fadeout, 0.1)

        clips.append(clip.set_duration(piece))

        remaining -= piece

    return concatenate_videoclips(clips, method="compose")

# ============================================================
# CAPTIONS
# ============================================================

def render_caption(text, size=70):
    font = get_font(size)

    img = Image.new("RGBA", (1000, 300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    wrapped = []
    words = text.split()

    line = ""

    for w in words:
        test = f"{line} {w}".strip()

        bbox = draw.textbbox((0, 0), test, font=font)

        if bbox[2] < 850:
            line = test
        else:
            wrapped.append(line)
            line = w

    wrapped.append(line)

    y = 40

    for ln in wrapped:
        bbox = draw.textbbox((0, 0), ln, font=font)
        w = bbox[2]

        x = (1000 - w) // 2

        for dx in range(-3, 4):
            for dy in range(-3, 4):
                draw.text(
                    (x + dx, y + dy),
                    ln,
                    font=font,
                    fill=(0, 0, 0, 255)
                )

        draw.text(
            (x, y),
            ln,
            font=font,
            fill=(255, 255, 255, 255)
        )

        y += 85

    return np.array(img)

# ============================================================
# MUSIC PROFILES
# ============================================================

MUSIC_PROFILES = [
    {
        "name": "ambient",
        "bpm": 70,
        "bass": True,
        "drums": False,
    },
    {
        "name": "dramatic",
        "bpm": 90,
        "bass": True,
        "drums": True,
    },
    {
        "name": "tense",
        "bpm": 120,
        "bass": True,
        "drums": True,
    },
    {
        "name": "documentary",
        "bpm": 82,
        "bass": False,
        "drums": True,
    },
]

# ============================================================
# SIMPLE MUSIC ENGINE
# ============================================================

def generate_music(duration):
    from moviepy.audio.AudioClip import AudioClip

    profile = random.choice(MUSIC_PROFILES)

    sr = 44100
    total = int(sr * duration)

    audio = np.zeros(total, dtype=np.float32)

    bpm = profile["bpm"]
    beat = 60 / bpm

    freqs = [110, 130, 146, 164]

    for i in range(int(duration / beat) + 2):
        idx = int(i * beat * sr)

        if profile["bass"]:
            length = int(sr * 0.4)
            t = np.arange(length) / sr

            freq = random.choice(freqs)

            wave = np.sin(2 * np.pi * freq * t)
            env = np.exp(-t * 5)

            end = min(total, idx + length)

            audio[idx:end] += (wave[:end-idx] * env[:end-idx] * 0.12)

        if profile["drums"] and i % 2 == 0:
            length = int(sr * 0.08)
            t = np.arange(length) / sr

            noise = np.random.randn(length) * np.exp(-t * 40)

            end = min(total, idx + length)

            audio[idx:end] += noise[:end-idx] * 0.05

    peak = np.max(np.abs(audio))

    if peak > 0:
        audio = audio / peak * 0.25

    stereo = np.column_stack([audio, audio])

    def frame(t):
        idx = np.clip((np.array(t) * sr).astype(int), 0, total - 1)
        return stereo[idx]

    return AudioClip(frame, duration=duration, fps=sr)

# ============================================================
# BUILD VIDEO
# ============================================================

def build_video(timings, audio_path, out_path):
    visual_layers = []
    caption_layers = []

    for idx, seg in enumerate(timings):
        print(f"Searching visuals: {seg['visual']}")

        url = search_pexels_video(seg["visual"])

        if not url:
            fallback = ColorClip(
                (WIDTH, HEIGHT),
                color=(20, 20, 20)
            ).set_duration(seg["duration"])

            visual_layers.append(fallback.set_start(seg["start"]))
            continue

        path = download_video(url)

        clip = create_micro_clips(path, seg["duration"])

        clip = clip.set_start(seg["start"])

        visual_layers.append(clip)

        caption = ImageClip(
            render_caption(seg["text"])
        )

        caption = (
            caption
            .set_duration(seg["duration"])
            .set_start(seg["start"])
            .set_position((40, HEIGHT - 700))
            .fx(vfx.fadein, 0.08)
            .fx(vfx.fadeout, 0.08)
        )

        caption_layers.append(caption)

    narration = AudioFileClip(audio_path)

    music = generate_music(narration.duration)

    final_audio = CompositeAudioClip([
        narration.volumex(1.0),
        music.volumex(0.35)
    ])

    final = CompositeVideoClip(
        visual_layers + caption_layers,
        size=(WIDTH, HEIGHT)
    )

    final = final.set_audio(final_audio)

    final.write_videofile(
        out_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        threads=4,
    )

# ============================================================
# MAIN
# ============================================================

def run_pipeline():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    script = generate_script("Indian business empire")

    audio_path = OUTPUT_DIR / f"voice_{ts}.wav"
    video_path = OUTPUT_DIR / f"short_{ts}.mp4"

    timings = generate_voiceover(
        script["segments"],
        str(audio_path)
    )

    build_video(
        timings,
        str(audio_path),
        str(video_path)
    )

    print("DONE")
    print(video_path)

# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    run_pipeline()
