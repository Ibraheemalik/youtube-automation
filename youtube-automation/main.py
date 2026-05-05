#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║   DARK CONFESSIONS - YouTube Horror Automation Pipeline v3.0    ║
║   Target: 300K–600K views | 1.5–2 Lakh PKR per video           ║
║   Stack: Edge-TTS + Gemini + Pixabay + MoviePy + FFmpeg         ║
╚══════════════════════════════════════════════════════════════════╝

Usage:
  python main.py                        # Generate + schedule upload
  python main.py --run-now              # Generate + upload immediately
  python main.py --day sunday           # Override schedule day
  python main.py --topic "stalker"      # Custom topic input
  python main.py --skip-upload          # Generate video only, no upload
  python main.py --skip-video           # Script + thumbnail only
"""

import os
import sys
import re
import json
import time
import asyncio
import hashlib
import logging
import argparse
import tempfile
import textwrap
import subprocess
import unicodedata
import urllib.request
import urllib.parse
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

# ── Third-party ──────────────────────────────────────────────────
import yaml
import requests
import numpy as np
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import google.generativeai as genai

# ── Optional upload libs (graceful if missing) ───────────────────
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    import pickle
    UPLOAD_AVAILABLE = True
except ImportError:
    UPLOAD_AVAILABLE = False

# ── MoviePy ───────────────────────────────────────────────────────
try:
    from moviepy import VideoFileClip, AudioFileClip, ImageClip
    from moviepy import CompositeVideoClip, concatenate_videoclips
    from moviepy import CompositeAudioClip, concatenate_audioclips
    from moviepy.audio.fx import MultiplyVolume
    MOVIEPY_V2 = True
except ImportError:
    from moviepy.editor import (VideoFileClip, AudioFileClip, ImageClip,
                                 CompositeVideoClip, concatenate_videoclips,
                                 CompositeAudioClip, concatenate_audioclips)
    MOVIEPY_V2 = False

# ─────────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(), logging.FileHandler("pipeline.log")]
)
log = logging.getLogger("DarkConfessions")

# ─────────────────────────────────────────────────────────────────
#  CONFIG LOADER
# ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CFG_PATH  = BASE_DIR / "config.yml"
SCH_PATH  = BASE_DIR / "schedule.yml"

def load_config() -> Dict:
    with open(CFG_PATH, "r") as f:
        cfg = yaml.safe_load(f)
    os.makedirs(cfg["output"]["folder"], exist_ok=True)
    os.makedirs(f"{cfg['output']['folder']}/temp", exist_ok=True)
    return cfg

def load_schedule() -> Dict:
    with open(SCH_PATH, "r") as f:
        return yaml.safe_load(f)

CFG = load_config()
SCH = load_schedule()
TEMP_DIR  = Path(CFG["output"]["folder"]) / "temp"
OUT_DIR   = Path(CFG["output"]["folder"])
SCOPES    = ["https://www.googleapis.com/auth/youtube.upload"]

# ─────────────────────────────────────────────────────────────────
#  STEP 1 — GEMINI SCRIPT GENERATOR
# ─────────────────────────────────────────────────────────────────
def init_gemini() -> genai.GenerativeModel:
    key = CFG["api_keys"]["gemini_api_key"]
    if key == "YOUR_GEMINI_API_KEY_HERE":
        log.warning("⚠ Gemini key not set – using built-in fallback script")
        return None
    genai.configure(api_key=key)
    return genai.GenerativeModel("gemini-1.5-flash")

FALLBACK_STORIES = [
    {
        "title": "The Breathing Under My Bed",
        "tone_sequence": ["calm","tense","tense","whisper","reveal"],
        "lines": [
            ("calm",   "I was twelve when I first heard it."),
            ("calm",   "A slow... deliberate breathing."),
            ("calm",   "Coming from beneath my mattress."),
            ("tense",  "I told myself it was the house settling."),
            ("tense",  "Houses don't breathe."),
            ("tense",  "I know that now."),
            ("whisper","I reached down... and something grabbed my wrist."),
            ("whisper","Cold. Thin fingers. Unmistakably human."),
            ("reveal", "My brother had been missing for three days."),
            ("reveal", "The police found him the next morning."),
            ("calm",   "He never explained how he got under there."),
            ("calm",   "He never spoke again after that night."),
        ]
    },
    {
        "title": "My Neighbor Knew Things He Shouldn't",
        "tone_sequence": ["calm","calm","tense","tense","whisper","reveal"],
        "lines": [
            ("calm",   "He moved in on a Tuesday."),
            ("calm",   "Quiet man. Kept to himself."),
            ("tense",  "Then he started describing my dreams."),
            ("tense",  "In perfect detail. Over the fence. Like small talk."),
            ("tense",  "The red hallway. The door with no handle."),
            ("whisper","He said: 'I used to live there too. In that place.'"),
            ("whisper","'You should stop opening that door.'"),
            ("reveal", "I looked him up after he disappeared."),
            ("reveal", "He had died eleven years before we ever met."),
        ]
    },
    {
        "title": "The Gas Station at Mile 47",
        "tone_sequence": ["calm","tense","tense","whisper","reveal","calm"],
        "lines": [
            ("calm",   "I was driving through Nevada at two in the morning."),
            ("calm",   "Nowhere else to stop. So I pulled in."),
            ("tense",  "The attendant smiled the entire time I was there."),
            ("tense",  "Didn't blink once in twenty minutes."),
            ("tense",  "He pumped the gas. Cleaned the windshield."),
            ("whisper","Then he leaned in and said:"),
            ("whisper","'The last three people who stopped here never left.'"),
            ("whisper","'You're very lucky you're the fourth.'"),
            ("reveal", "I drove six hours without stopping."),
            ("reveal", "When I checked the map... Mile 47 doesn't exist."),
            ("calm",   "Never did."),
        ]
    },
    {
        "title": "The Woman in My Wedding Photos",
        "tone_sequence": ["calm","tense","whisper","reveal","reveal"],
        "lines": [
            ("calm",   "We got the wedding photos back three weeks later."),
            ("calm",   "Beautiful shots. Perfect day. Or so I thought."),
            ("tense",  "In seventeen different photos... there was a woman."),
            ("tense",  "Standing just behind the guests. Watching."),
            ("tense",  "We didn't recognize her. Nobody did."),
            ("whisper","My mother went pale when she finally saw them."),
            ("whisper","She said: 'That's impossible.'"),
            ("reveal", "It was my grandmother."),
            ("reveal", "She had died four months before the wedding."),
            ("calm",   "In every photo, she was smiling."),
        ]
    },
    {
        "title": "What My Son Drew",
        "tone_sequence": ["calm","calm","tense","tense","whisper","reveal"],
        "lines": [
            ("calm",   "My son is four years old."),
            ("calm",   "He loves to draw. Houses. Dogs. Suns."),
            ("tense",  "Last Tuesday he handed me a drawing before bed."),
            ("tense",  "A tall dark figure. Standing over a small figure sleeping."),
            ("tense",  "I asked him: 'Who is that?'"),
            ("whisper","He said: 'The man who watches me so you don't have to.'"),
            ("whisper","'He says not to turn on the lights.'"),
            ("reveal", "There were scratch marks on the inside of his closet door."),
            ("reveal", "The wood had been gouged from the inside."),
        ]
    },
    {
        "title": "The Last Voicemail",
        "tone_sequence": ["calm","tense","whisper","whisper","reveal"],
        "lines": [
            ("calm",   "My phone rang at 3:17 AM."),
            ("calm",   "I didn't answer. It went to voicemail."),
            ("tense",  "In the morning I listened to it."),
            ("tense",  "It was my own voice. Saying my own name."),
            ("whisper","Over and over. Getting slower. Getting quieter."),
            ("whisper","Then silence. Then one final whisper:"),
            ("whisper","'Don't go to work today.'"),
            ("reveal", "There was a gas explosion at my office building at 8 AM."),
            ("reveal", "Twelve people were hurt. My desk was destroyed."),
            ("calm",   "The phone number that called me... was my own."),
        ]
    },
]

SCRIPT_PROMPT = """You are a professional horror narration scriptwriter for a YouTube channel with 10M subscribers. 
Write a horror video script about: {topic}

STRICT RULES:
- 6 disturbing Reddit-style TRUE stories, ordered from least to most terrifying
- Each story: 8-14 lines of narration
- Each line gets a [TONE] tag: [calm] [tense] [whisper] [reveal] [hook]
- NO mention of real people, NO sexual content, NO graphic gore
- 100% faceless descriptions — no character faces described
- Build dread through IMPLICATION, not description
- Humanoid pauses: use "..." for dramatic pause, "—" for sudden stop
- Lines must feel like a real person remembering trauma, not AI writing
- Natural sentence rhythm — short punchy lines mixed with longer ones

FORMAT (strict JSON):
{{
  "video_title": "CLICKBAIT SCARY TITLE WITH EMOJIS",
  "hook_lines": ["line1", "line2", "line3"],
  "subscribe_plug": "one line subscription reminder",
  "stories": [
    {{
      "title": "Story Title",
      "reddit_intro": "one line intro mentioning reddit/user post",
      "lines": [["tone", "narration line"], ...],
      "transition_line": "single bridge line to next story"
    }}
  ],
  "outro_lines": ["line1", "line2", "line3"],
  "youtube_title": "Full SEO title with emojis",
  "description": "Full 300-word YouTube description with chapters",
  "tags": ["tag1","tag2",...20 tags]
}}"""

def generate_script(topic: str, model) -> Dict:
    if model is None:
        log.info("Using built-in fallback script (no Gemini key)")
        return _build_fallback_script(topic)
    log.info(f"🤖 Generating script via Gemini — topic: {topic}")
    try:
        prompt = SCRIPT_PROMPT.format(topic=topic)
        resp = model.generate_content(prompt)
        raw = resp.text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        log.info("✅ Gemini script generated successfully")
        return data
    except Exception as e:
        log.warning(f"Gemini failed ({e}) — using fallback script")
        return _build_fallback_script(topic)

def _build_fallback_script(topic: str) -> Dict:
    stories = FALLBACK_STORIES
    chapters = "\n".join([
        f"0:00 – Hook & Intro",
        f"0:40 – Subscribe",
    ] + [f"{i*150//60}:{i*150%60:02d} – {s['title']}" for i,s in enumerate(stories,1)])
    return {
        "video_title": "😱 6 Disturbing Reddit Stories That Will Keep You Up ALL Night",
        "hook_lines": [
            "These are real accounts. Posted by real people.",
            "Stories that were... never fully explained.",
            "You might want to check your room before we begin."
        ],
        "subscribe_plug": "Hit subscribe — we post the darkest stories every single week.",
        "stories": [
            {
                "title": s["title"],
                "reddit_intro": f"This story comes from a Reddit user who posted this at 3 AM and deleted it by morning.",
                "lines": s["lines"],
                "transition_line": "But that story... is nothing compared to what comes next."
            }
            for s in stories
        ],
        "outro_lines": [
            "These stories were submitted anonymously.",
            "Some accounts were deleted. Some users were never heard from again.",
            "Sleep well."
        ],
        "youtube_title": "😱 6 Disturbing Reddit Stories That Will Keep You Up ALL Night | Dark Confessions",
        "description": f"""These are 6 of the most disturbing true stories ever posted on Reddit. 
Horror narration. Dark atmosphere. Real accounts from real people.

Chapters:
{chapters}

🔔 Subscribe for weekly horror narration every Sunday at 10 AM ET.

#horrorstoies #reddit #nosleep #scarystories #truehorrror #darkconfessions""",
        "tags": ["reddit horror stories","disturbing reddit","nosleep","scary stories",
                 "true horror","horror narration","dark confessions","creepy reddit",
                 "horror 2024","reddit nosleep","scary narration","horror stories",
                 "true scary stories","reddit creepy stories","let me not sleep"]
    }

# ─────────────────────────────────────────────────────────────────
#  STEP 2 — EDGE-TTS VOICE GENERATION WITH TONE CHANGES
# ─────────────────────────────────────────────────────────────────
async def _synthesize_ssml(ssml_text: str, voice: str, output_path: str):
    """Synthesize using Edge-TTS with SSML prosody control."""
    communicate = edge_tts.Communicate(ssml_text, voice)
    await communicate.save(output_path)

def build_ssml_line(text: str, tone: str, cfg: Dict) -> str:
    """Wrap a line in SSML prosody tags matching the tone."""
    tones = cfg["tts"]["tones"]
    t = tones.get(tone, tones["calm"])
    rate   = t["rate"]
    pitch  = t["pitch"]
    # Add humanoid pause markers
    text = text.replace("...", '<break time="700ms"/>')
    text = text.replace("—",  '<break time="400ms"/>')
    # Add micro-pause between sentences naturally
    return (
        f'<prosody rate="{rate}" pitch="{pitch}">'
        f'{text}'
        f'</prosody>'
        f'<break time="350ms"/>'
    )

def build_full_ssml(lines: List[Tuple[str,str]], cfg: Dict) -> str:
    """Build complete SSML document for full story."""
    inner = ""
    prev_tone = None
    for tone, text in lines:
        # Add longer pause on tone change (humanoid rhythm)
        if prev_tone and prev_tone != tone:
            inner += '<break time="500ms"/>'
        inner += build_ssml_line(text, tone, cfg)
        prev_tone = tone
    return (
        '<speak xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="http://www.w3.org/2001/mstts" '
        f'xml:lang="en-US">'
        f'<voice name="{cfg["tts"]["voice"]}">'
        f'{inner}'
        f'</voice>'
        f'</speak>'
    )

def generate_audio_segments(script: Dict, cfg: Dict) -> List[Dict]:
    """Generate audio for hook, each story, and outro. Returns list of segments."""
    voice = cfg["tts"]["voice"]
    segments = []
    out_dir  = TEMP_DIR

    # ── Hook ──────────────────────────────────────────────────────
    hook_lines = [("hook", l) for l in script["hook_lines"]]
    hook_ssml  = build_full_ssml(hook_lines, cfg)
    hook_path  = str(out_dir / "seg_hook.mp3")
    asyncio.run(_synthesize_ssml(hook_ssml, voice, hook_path))
    segments.append({"type":"hook", "path":hook_path, "lines":hook_lines})
    log.info("✅ Hook audio generated")

    # ── Subscribe plug ────────────────────────────────────────────
    sub_lines  = [("calm", script["subscribe_plug"])]
    sub_ssml   = build_full_ssml(sub_lines, cfg)
    sub_path   = str(out_dir / "seg_subscribe.mp3")
    asyncio.run(_synthesize_ssml(sub_ssml, voice, sub_path))
    segments.append({"type":"subscribe", "path":sub_path, "lines":sub_lines})
    log.info("✅ Subscribe audio generated")

    # ── Stories ───────────────────────────────────────────────────
    for i, story in enumerate(script["stories"]):
        all_lines = []
        # Intro line
        all_lines.append(("calm", story["reddit_intro"]))
        # Story lines
        for tone, text in story["lines"]:
            all_lines.append((tone, text))
        # Transition
        if story.get("transition_line"):
            all_lines.append(("tense", story["transition_line"]))
        ssml  = build_full_ssml(all_lines, cfg)
        path  = str(out_dir / f"seg_story_{i:02d}.mp3")
        asyncio.run(_synthesize_ssml(ssml, voice, path))
        segments.append({
            "type":  "story",
            "index": i,
            "title": story["title"],
            "path":  path,
            "lines": all_lines
        })
        log.info(f"✅ Story {i+1}/{len(script['stories'])} audio: {story['title']}")

    # ── Outro ─────────────────────────────────────────────────────
    outro_lines = [("whisper", l) for l in script["outro_lines"]]
    outro_ssml  = build_full_ssml(outro_lines, cfg)
    outro_path  = str(out_dir / "seg_outro.mp3")
    asyncio.run(_synthesize_ssml(outro_ssml, voice, outro_path))
    segments.append({"type":"outro", "path":outro_path, "lines":outro_lines})
    log.info("✅ Outro audio generated")

    return segments

# ─────────────────────────────────────────────────────────────────
#  STEP 3 — PIXABAY VIDEO FETCHER
# ─────────────────────────────────────────────────────────────────
HORROR_QUERIES = [
    "dark forest night", "empty hallway", "foggy street night",
    "abandoned house interior", "dark bedroom night", "storm lightning",
    "old attic dark", "rain window night", "dark corridor",
    "shadows wall", "candle flame dark", "empty road fog",
    "dark staircase", "night sky stars", "forest mist",
    "old door creaky", "basement dark", "night city empty",
    "moonlight shadow", "dark field night"
]

def fetch_pixabay_clips(cfg: Dict, count: int = 80) -> List[str]:
    """Download horror B-roll clips from Pixabay. Returns list of local paths."""
    api_key = cfg["api_keys"]["pixabay_api_key"]
    if api_key == "YOUR_PIXABAY_API_KEY_HERE":
        log.warning("⚠ Pixabay key not set — generating solid-color placeholder clips")
        return _generate_placeholder_clips(count, cfg)
    
    clips_dir = TEMP_DIR / "clips"
    clips_dir.mkdir(exist_ok=True)
    downloaded = []
    
    per_query = max(4, count // len(HORROR_QUERIES))
    for query in HORROR_QUERIES:
        if len(downloaded) >= count:
            break
        try:
            url = (f"https://pixabay.com/api/videos/"
                   f"?key={api_key}&q={urllib.parse.quote(query)}"
                   f"&per_page={per_query}&min_width=1280&video_type=film")
            resp = requests.get(url, timeout=15)
            data = resp.json()
            for hit in data.get("hits", []):
                if len(downloaded) >= count:
                    break
                # Prefer medium quality (720p) for speed
                video_url = (hit.get("videos",{}).get("medium",{}).get("url") or
                             hit.get("videos",{}).get("small",{}).get("url"))
                if not video_url:
                    continue
                vid_id   = hit["id"]
                out_path = clips_dir / f"clip_{vid_id}.mp4"
                if out_path.exists():
                    downloaded.append(str(out_path))
                    continue
                r = requests.get(video_url, timeout=30, stream=True)
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
                downloaded.append(str(out_path))
        except Exception as e:
            log.warning(f"Pixabay fetch error for '{query}': {e}")
    
    if not downloaded:
        log.warning("No Pixabay clips downloaded — using placeholders")
        return _generate_placeholder_clips(count, cfg)
    
    log.info(f"✅ Fetched {len(downloaded)} B-roll clips from Pixabay")
    return downloaded

def _generate_placeholder_clips(count: int, cfg: Dict) -> List[str]:
    """Generate dark atmospheric placeholder clips using FFmpeg."""
    clips_dir = TEMP_DIR / "clips"
    clips_dir.mkdir(exist_ok=True)
    paths     = []
    colors    = ["#020408", "#030a0f", "#040610", "#050510", "#030810"]
    W, H      = cfg["video"]["resolution"]
    
    for i in range(min(count, 20)):
        c    = colors[i % len(colors)]
        path = str(clips_dir / f"placeholder_{i:03d}.mp4")
        if not os.path.exists(path):
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c={c}:size={W}x{H}:rate=30",
                "-t", "8", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", path
            ]
            subprocess.run(cmd, capture_output=True)
        paths.append(path)
    return paths

# ─────────────────────────────────────────────────────────────────
#  STEP 4 — ADVANCED FFmpeg CLIP PROCESSOR
# ─────────────────────────────────────────────────────────────────
def apply_cinematic_grade(input_path: str, output_path: str, cfg: Dict,
                           clip_idx: int = 0) -> str:
    """Apply full cinematic color grade + grain + vignette + Ken Burns zoom."""
    vg   = cfg["video"]
    cgr  = vg["color_grade"]
    W, H = vg["resolution"]

    # Ken Burns: alternate zoom in/out for visual variety
    zoom_dir = 1 if clip_idx % 2 == 0 else -1
    spd      = vg["effects"]["slow_zoom_speed"]
    z_start  = 1.0
    z_end    = 1.0 + zoom_dir * spd * 30 * 8  # over 8-sec clip

    # Teal-orange LUT simulation via curves
    # Teal shadows: lift blue/green in shadows; Orange highlights: push red/yellow
    grade_filter = (
        f"curves=r='0/0 0.5/{0.5+0.04} 1/{1.0}':"   # slight red boost highlights
        f"g='0/0 0.3/{0.3+0.02} 1/1':"               # green mid tweak
        f"b='0/{0.04} 0.3/{0.3+0.08} 1/0.95',"       # teal lift in shadows
        f"eq=contrast={cgr['contrast_boost']}"
        f":brightness={cgr['brightness']}"
        f":saturation={cgr['saturation']},"
        # Film grain
        f"noise=alls={cgr['grain_strength']}:allf=t+u,"
        # Vignette
        f"vignette=angle=PI/4:mode=backward:eval=frame"
    )

    # Chromatic aberration via scale+overlay trick
    ca_px = cgr.get("chromatic_aberration", 3)
    chroma_filter = (
        f"[in]split=3[r][g][b];"
        f"[r]lutrgb=g=0:b=0,scale={W+ca_px*2}:{H+ca_px*2},"
        f"crop={W}:{H}:{ca_px}:{ca_px}[rv];"
        f"[g]lutrgb=r=0:b=0[gv];"
        f"[b]lutrgb=r=0:g=0,scale={W-ca_px*2}:{H-ca_px*2},"
        f"pad={W}:{H}:{ca_px}:{ca_px}[bv];"
        f"[rv][gv]blend=all_mode=addition[rg];"
        f"[rg][bv]blend=all_mode=addition[out]"
    )

    # Ken Burns zoom using zoompan
    zoom_filter = (
        f"scale={W*2}:{H*2},"
        f"zoompan=z='if(lte(on\\,1)\\,{z_start}\\,min(zoom+{spd}\\,{max(z_start,z_end)}))':"
        f"d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps=30"
    )

    full_filter = f"{zoom_filter},{grade_filter}"

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", full_filter,
        "-t", "8",
        "-r", "30",
        "-c:v", "libx264", "-preset", "fast",
        "-crf", "20", "-pix_fmt", "yuv420p",
        "-an",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning(f"Grade filter failed for {input_path}, using simpler grade")
        # Fallback simple grade
        cmd2 = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"eq=contrast=1.1:brightness=-0.05:saturation=0.85,"
                   f"noise=alls=18:allf=t",
            "-t", "8", "-r", "30", "-c:v", "libx264", "-preset", "fast",
            "-crf", "22", "-pix_fmt", "yuv420p", "-an", output_path
        ]
        subprocess.run(cmd2, capture_output=True)
    return output_path

def process_clips_for_segment(raw_clips: List[str], duration_sec: float,
                               cfg: Dict, seg_name: str) -> str:
    """Process + grade enough clips to cover duration_sec. Returns concat video path."""
    W, H          = cfg["video"]["resolution"]
    interval      = cfg["video"]["clip_change_interval"]  # 1.5 sec
    clips_needed  = int(duration_sec / interval) + 2
    graded_dir    = TEMP_DIR / "graded"
    graded_dir.mkdir(exist_ok=True)

    # Cycle through available raw clips
    graded_paths  = []
    for i in range(clips_needed):
        raw = raw_clips[i % len(raw_clips)]
        out = str(graded_dir / f"{seg_name}_clip_{i:03d}.mp4")
        if not os.path.exists(out):
            apply_cinematic_grade(raw, out, cfg, clip_idx=i)
        graded_paths.append(out)

    # Build concat list
    concat_list = TEMP_DIR / f"concat_{seg_name}.txt"
    with open(concat_list, "w") as f:
        for p in graded_paths:
            f.write(f"file '{p}'\n")
            f.write(f"duration {interval}\n")

    concat_out = str(TEMP_DIR / f"concat_{seg_name}.mp4")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-t", str(duration_sec + 0.5),
        concat_out
    ]
    subprocess.run(cmd, capture_output=True)
    return concat_out

# ─────────────────────────────────────────────────────────────────
#  STEP 5 — TEXT OVERLAY (Word-by-Word Animation)
# ─────────────────────────────────────────────────────────────────
def get_font(size: int) -> ImageFont.FreeTypeFont:
    """Try multiple font paths for robustness."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/fonts-uralic/Uralic.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def render_subtitle_frame(text: str, W: int, H: int,
                           cfg: Dict, progress: float = 1.0) -> np.ndarray:
    """Render a single subtitle frame with glow + shadow. progress 0->1 for fade-in."""
    tc   = cfg["video"]["text"]
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_size = int(tc["size"] * (0.7 + 0.3 * progress))  # scale animation
    font = get_font(font_size)

    # Word wrap
    lines     = textwrap.wrap(text, width=38)
    line_h    = font_size + 10
    total_h   = len(lines) * line_h
    y_start   = H - total_h - 80

    for li, line in enumerate(lines):
        bbox  = draw.textbbox((0, 0), line, font=font)
        tw    = bbox[2] - bbox[0]
        x     = (W - tw) // 2
        y     = y_start + li * line_h

        alpha = int(255 * progress)

        # Glow layer (blurred white)
        glow_img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd        = ImageDraw.Draw(glow_img)
        for dx in range(-tc["glow_radius"]//2, tc["glow_radius"]//2 + 1, 2):
            for dy in range(-tc["glow_radius"]//2, tc["glow_radius"]//2 + 1, 2):
                gd.text((x+dx, y+dy), line, font=font, fill=(255,255,255, alpha//4))
        glow_blur = glow_img.filter(ImageFilter.GaussianBlur(tc["glow_radius"]//2))
        img = Image.alpha_composite(img, glow_blur)
        draw = ImageDraw.Draw(img)

        # Drop shadow
        sx, sy = tc["shadow_offset"]
        draw.text((x+sx, y+sy), line, font=font, fill=(0,0,0,int(alpha*0.8)))

        # Main text
        draw.text((x, y), line, font=font, fill=(255,255,255,alpha))

    return np.array(img)

def create_subtitle_video(lines: List[Tuple[str,str]], total_duration: float,
                          cfg: Dict, seg_name: str) -> Optional[str]:
    """Create subtitle overlay video (RGBA) synced to narration."""
    W, H     = cfg["video"]["resolution"]
    fps      = cfg["video"]["fps"]
    wd       = cfg["video"]["text"]["word_duration"]
    out_path = str(TEMP_DIR / f"subs_{seg_name}.mp4")

    total_frames = int(total_duration * fps)
    all_frames   = []

    # Build timeline of what text shows at each second
    timeline: List[Tuple[float,float,str]] = []
    t = 0.0
    for _, text in lines:
        words   = text.split()
        for wi, word in enumerate(words):
            # Show growing phrase (word by word)
            phrase = " ".join(words[:wi+1])
            timeline.append((t, t + wd, phrase))
            t += wd
        t += 0.3  # pause between lines

    # Render frames
    for fi in range(total_frames):
        sec       = fi / fps
        frame_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        # Find active subtitle
        for (start, end, phrase) in timeline:
            if start <= sec < end:
                progress = min(1.0, (sec - start) / 0.12)  # 0.12s fade-in
                sub_arr  = render_subtitle_frame(phrase, W, H, cfg, progress)
                sub_img  = Image.fromarray(sub_arr, "RGBA")
                frame_img = Image.alpha_composite(frame_img, sub_img)
                break
        all_frames.append(np.array(frame_img)[:,:,:3])  # drop alpha for video

    if not all_frames:
        return None

    # Write frames via FFmpeg pipe
    pipe_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{W}x{H}", "-pix_fmt", "rgb24",
        "-r", str(fps), "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", out_path
    ]
    proc = subprocess.Popen(pipe_cmd, stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for frame in all_frames:
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()
    log.info(f"✅ Subtitles rendered: {seg_name} ({len(all_frames)} frames)")
    return out_path

# ─────────────────────────────────────────────────────────────────
#  STEP 6 — AUDIO MIXER (Narration + BG Music + SFX)
# ─────────────────────────────────────────────────────────────────
def get_audio_duration(path: str) -> float:
    """Get duration of audio file using FFprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", path
    ]
    try:
        out = subprocess.check_output(cmd).decode()
        data = json.loads(out)
        for stream in data.get("streams", []):
            if "duration" in stream:
                return float(stream["duration"])
    except Exception:
        pass
    return 10.0

def generate_bg_music(duration: float, cfg: Dict) -> str:
    """Generate atmospheric dark ambient music using FFmpeg sine waves."""
    out_path = str(TEMP_DIR / "bg_music.mp3")
    if os.path.exists(out_path):
        return out_path
    
    vol  = cfg["video"]["audio"]["background_music_volume"]
    # Dark ambient: low drone frequencies layered
    layers = [
        f"sine=frequency=55:duration={duration}",   # Deep bass drone
        f"sine=frequency=82:duration={duration}",   # Low tension
        f"sine=frequency=110:duration={duration}",  # Mid drone
        f"sine=frequency=165:duration={duration}",  # Atmospheric
    ]
    # Mix all layers
    filter_parts = [f"[{i}]volume=0.25[a{i}]" for i in range(len(layers))]
    mix_inputs   = "".join(f"[a{i}]" for i in range(len(layers)))
    amix         = f"{mix_inputs}amix=inputs={len(layers)},volume={vol}"

    inputs = []
    for layer in layers:
        inputs += ["-f", "lavfi", "-i", layer]

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex",
        ";".join(filter_parts) + ";" + amix,
        "-ar", "44100", "-ac", "2",
        "-codec:a", "libmp3lame", "-b:a", "128k",
        out_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        # Ultra-simple fallback
        cmd2 = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"sine=frequency=60:duration={duration}",
            "-af", f"volume={vol}",
            "-ar", "44100", out_path
        ]
        subprocess.run(cmd2, capture_output=True)
    log.info("✅ Background music generated")
    return out_path

def mix_audio_segment(narration_path: str, bg_music_path: str,
                      seg_start: float, duration: float, cfg: Dict,
                      has_reveal: bool = False) -> str:
    """Mix narration + BG music for one segment. Returns mixed audio path."""
    seg_name    = Path(narration_path).stem
    out_path    = str(TEMP_DIR / f"mixed_{seg_name}.mp3")
    nav_vol     = cfg["video"]["audio"]["narration_volume"]
    bg_vol      = cfg["video"]["audio"]["background_music_volume"]

    # Optional reverb on reveal moments
    reverb_filter = ""
    if has_reveal and cfg["video"]["audio"]["reverb_on_reveal"]:
        reverb_filter = ",aecho=0.8:0.9:500:0.3"

    cmd = [
        "ffmpeg", "-y",
        "-i", narration_path,
        "-ss", str(seg_start), "-i", bg_music_path,
        "-filter_complex",
        f"[0:a]volume={nav_vol}{reverb_filter}[nav];"
        f"[1:a]volume={bg_vol}[bg];"
        f"[nav][bg]amix=inputs=2:duration=first:dropout_transition=2[out]",
        "-map", "[out]",
        "-t", str(duration),
        "-ar", "44100", "-ac", "2",
        "-codec:a", "libmp3lame", "-b:a", "192k",
        out_path
    ]
    subprocess.run(cmd, capture_output=True)
    return out_path

# ─────────────────────────────────────────────────────────────────
#  STEP 7 — RED BOX GLITCH EFFECT (Big Reveal Moments)
# ─────────────────────────────────────────────────────────────────
def create_red_box_reveal(text: str, duration: float, cfg: Dict,
                           seg_name: str) -> str:
    """Create red text + glitch box overlay for story reveals."""
    W, H     = cfg["video"]["resolution"]
    fps      = cfg["video"]["fps"]
    out_path = str(TEMP_DIR / f"redbox_{seg_name}.mp4")
    n_frames = int(duration * fps)
    
    frames   = []
    font     = get_font(72)
    
    for fi in range(n_frames):
        t         = fi / fps
        img       = Image.new("RGBA", (W, H), (0,0,0,0))
        draw      = ImageDraw.Draw(img)
        progress  = min(1.0, t / 0.3)
        # Glitch offset
        glitch_x  = int(np.random.uniform(-8, 8) * max(0, 1.0 - t*3))
        
        # Red box border
        box_alpha = int(200 * progress)
        box_w     = int(W * 0.7)
        box_h     = 120
        bx        = (W - box_w) // 2 + glitch_x
        by        = H // 2 - box_h // 2
        draw.rectangle([bx, by, bx+box_w, by+box_h],
                        outline=(200,20,20,box_alpha), width=4)
        # Red glow fill
        draw.rectangle([bx+2, by+2, bx+box_w-2, by+box_h-2],
                        fill=(200,20,20,int(30*progress)))
        # Red text
        bbox = draw.textbbox((0,0), text, font=font)
        tw   = bbox[2] - bbox[0]
        tx   = (W - tw) // 2 + glitch_x
        ty   = by + (box_h - (bbox[3]-bbox[1])) // 2
        draw.text((tx+2, ty+2), text, font=font, fill=(0,0,0,box_alpha))
        draw.text((tx, ty), text, font=font, fill=(255,50,50,box_alpha))
        frames.append(np.array(img)[:,:,:3])
    
    pipe_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{W}x{H}", "-pix_fmt", "rgb24",
        "-r", str(fps), "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", out_path
    ]
    proc = subprocess.Popen(pipe_cmd, stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for frame in frames:
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()
    return out_path

# ─────────────────────────────────────────────────────────────────
#  STEP 8 — FREEZE FRAME EFFECT
# ─────────────────────────────────────────────────────────────────
def apply_freeze_frame(input_path: str, freeze_at: float,
                        freeze_duration: float, cfg: Dict,
                        seg_name: str) -> str:
    """Freeze a frame at a dramatic moment, then continue."""
    out_path  = str(TEMP_DIR / f"freeze_{seg_name}.mp4")
    W, H      = cfg["video"]["resolution"]
    fps       = cfg["video"]["fps"]

    # Extract freeze frame as image
    freeze_img = str(TEMP_DIR / f"freeze_frame_{seg_name}.png")
    cmd_extract = [
        "ffmpeg", "-y", "-ss", str(freeze_at),
        "-i", input_path, "-frames:v", "1", freeze_img
    ]
    subprocess.run(cmd_extract, capture_output=True)

    # Build: before freeze | freeze still | after freeze
    duration = get_audio_duration(input_path) if os.path.exists(input_path) else 10
    after_start = freeze_at + freeze_duration

    part1 = str(TEMP_DIR / f"freeze_p1_{seg_name}.mp4")
    part2 = str(TEMP_DIR / f"freeze_p2_{seg_name}.mp4")
    part3 = str(TEMP_DIR / f"freeze_p3_{seg_name}.mp4")

    # Part 1: before freeze
    cmd1 = ["ffmpeg","-y","-i",input_path,"-t",str(freeze_at),
             "-c:v","libx264","-preset","fast","-an",part1]
    subprocess.run(cmd1, capture_output=True)
    # Part 2: freeze still (with slight desaturation)
    cmd2 = ["ffmpeg","-y","-loop","1","-i",freeze_img,
             "-vf",f"eq=saturation=0.3:contrast=1.2,scale={W}:{H}",
             "-t",str(freeze_duration),"-r",str(fps),
             "-c:v","libx264","-preset","fast","-pix_fmt","yuv420p","-an",part2]
    subprocess.run(cmd2, capture_output=True)
    # Part 3: after freeze
    cmd3 = ["ffmpeg","-y","-ss",str(after_start),"-i",input_path,
             "-c:v","libx264","-preset","fast","-an",part3]
    subprocess.run(cmd3, capture_output=True)

    # Concat
    concat_txt = str(TEMP_DIR / f"freeze_concat_{seg_name}.txt")
    with open(concat_txt,"w") as f:
        for p in [part1, part2, part3]:
            if os.path.exists(p) and os.path.getsize(p) > 0:
                f.write(f"file '{p}'\n")
    cmd4 = ["ffmpeg","-y","-f","concat","-safe","0",
             "-i",concat_txt,"-c:v","libx264","-preset","fast",
             "-crf","20","-pix_fmt","yuv420p",out_path]
    subprocess.run(cmd4, capture_output=True)
    return out_path if os.path.exists(out_path) else input_path

# ─────────────────────────────────────────────────────────────────
#  STEP 9 — COMPOSITE ASSEMBLER
# ─────────────────────────────────────────────────────────────────
def assemble_segment(seg: Dict, raw_clips: List[str],
                     bg_music_path: str, bg_music_offset: float,
                     cfg: Dict) -> Tuple[str, float]:
    """
    Assemble one video segment:
    visuals + subtitle overlay + mixed audio
    Returns (final_segment_path, duration)
    """
    seg_name  = seg.get("type","seg") + "_" + str(seg.get("index","0"))
    audio_dur = get_audio_duration(seg["path"])
    lines     = seg.get("lines", [])
    W, H      = cfg["video"]["resolution"]
    fps       = cfg["video"]["fps"]

    # 1. Process B-roll clips to cover duration
    log.info(f"  Processing B-roll for segment: {seg_name} ({audio_dur:.1f}s)")
    visual_path = process_clips_for_segment(raw_clips, audio_dur, cfg, seg_name)

    # 2. Apply freeze frame on reveal moments
    has_reveal = any(t == "reveal" for t, _ in lines)
    if has_reveal:
        visual_path = apply_freeze_frame(visual_path, audio_dur * 0.6,
                                          1.2, cfg, seg_name)

    # 3. Generate subtitle overlay
    sub_path = create_subtitle_video(lines, audio_dur, cfg, seg_name)

    # 4. Create red box overlay for reveal lines
    reveal_lines = [text for tone, text in lines if tone == "reveal"]
    redbox_path  = None
    if reveal_lines and has_reveal:
        key_reveal = reveal_lines[0][:40]
        redbox_path = create_red_box_reveal(key_reveal, 2.5, cfg, seg_name)

    # 5. Mix audio
    mixed_audio = mix_audio_segment(
        seg["path"], bg_music_path, bg_music_offset,
        audio_dur, cfg, has_reveal
    )

    # 6. Composite: visual + subtitles + redbox
    final_vis = str(TEMP_DIR / f"final_vis_{seg_name}.mp4")
    
    filter_chain = f"[0:v][1:v]overlay=0:0[base]"
    inputs       = ["-i", visual_path, "-i", sub_path]
    
    if redbox_path and os.path.exists(redbox_path):
        # Place red box at 60% through the segment
        rb_start = audio_dur * 0.58
        filter_chain += f";[base][2:v]overlay=0:0:enable='between(t,{rb_start:.1f},{rb_start+2.5:.1f})'[out]"
        inputs += ["-i", redbox_path]
        map_arg  = "[out]"
    else:
        map_arg  = "[base]"

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_chain,
        "-map", map_arg,
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-t", str(audio_dur),
        final_vis
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning(f"Composite failed for {seg_name}, using raw visual")
        final_vis = visual_path

    # 7. Mux video + mixed audio
    muxed = str(TEMP_DIR / f"muxed_{seg_name}.mp4")
    cmd2  = [
        "ffmpeg", "-y",
        "-i", final_vis,
        "-i", mixed_audio,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", muxed
    ]
    subprocess.run(cmd2, capture_output=True)
    final = muxed if os.path.exists(muxed) else final_vis
    log.info(f"  ✅ Segment assembled: {seg_name}")
    return final, audio_dur

def add_transition(seg_a: str, seg_b: str, cfg: Dict, idx: int) -> str:
    """Add cinematic transition between segments (crossfade + glitch flash)."""
    W, H     = cfg["video"]["resolution"]
    out_path = str(TEMP_DIR / f"transition_{idx:02d}.mp4")
    dur_a    = get_audio_duration(seg_a)
    # 0.8-second crossfade with glitch distortion at cut point
    cmd = [
        "ffmpeg", "-y",
        "-i", seg_a, "-i", seg_b,
        "-filter_complex",
        f"[0:v]trim=start={max(0,dur_a-0.4)}:duration=0.8,setpts=PTS-STARTPTS,"
        f"noise=alls=60:allf=t+u[a_end];"
        f"[1:v]trim=start=0:duration=0.8,setpts=PTS-STARTPTS[b_start];"
        f"[a_end][b_start]xfade=transition=fade:duration=0.5:offset=0.3[trans]",
        "-map", "[trans]",
        "-c:v", "libx264", "-preset", "fast",
        "-crf", "20", "-pix_fmt", "yuv420p",
        "-t", "0.8",
        out_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return out_path if (result.returncode == 0 and os.path.exists(out_path)) else None

def concat_all_segments(segment_paths: List[str], transitions: List[Optional[str]],
                         cfg: Dict) -> str:
    """Final concatenation of all segments with transitions."""
    W, H     = cfg["video"]["resolution"]
    out_path = str(OUT_DIR / f"{CFG['output']['video_filename_prefix']}{_datestamp()}.mp4")
    
    # Build interleaved list: seg0, trans01, seg1, trans12, seg2, ...
    concat_items = []
    for i, seg_path in enumerate(segment_paths):
        concat_items.append(seg_path)
        if i < len(transitions) and transitions[i]:
            concat_items.append(transitions[i])
    
    # Write concat list
    concat_txt = str(TEMP_DIR / "final_concat.txt")
    with open(concat_txt, "w") as f:
        for item in concat_items:
            if item and os.path.exists(item) and os.path.getsize(item) > 0:
                f.write(f"file '{item}'\n")
    
    # Re-encode to ensure uniform stream
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_txt,
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        out_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"Final concat error: {result.stderr[-500:]}")
        # Last resort: just concat the main segments without transitions
        simple_txt = str(TEMP_DIR / "simple_concat.txt")
        with open(simple_txt, "w") as f:
            for seg in segment_paths:
                if seg and os.path.exists(seg) and os.path.getsize(seg) > 0:
                    f.write(f"file '{seg}'\n")
        cmd2 = ["ffmpeg","-y","-f","concat","-safe","0",
                 "-i",simple_txt,"-c","copy",out_path]
        subprocess.run(cmd2, capture_output=True)

    log.info(f"✅ Final video assembled: {out_path}")
    return out_path

# ─────────────────────────────────────────────────────────────────
#  STEP 10 — THUMBNAIL GENERATOR
# ─────────────────────────────────────────────────────────────────
def generate_thumbnail(script: Dict, cfg: Dict) -> str:
    """Generate YouTube thumbnail with dark cinematic style."""
    tc       = cfg["thumbnail"]
    W, H     = tc["width"], tc["height"]
    out_path = str(OUT_DIR / f"thumbnail_{_datestamp()}.jpg")

    # Base: near-black background with teal atmospheric gradient
    img  = Image.new("RGB", (W, H), tuple(tc["background_color"]))
    draw = ImageDraw.Draw(img)

    # Gradient overlay (teal top-left to dark)
    for y in range(H):
        alpha = 1.0 - (y / H) * 0.7
        teal  = tuple(tc["accent_color"])
        draw.line([(0,y),(W,y)],
                  fill=(int(teal[0]*alpha*0.15),
                        int(teal[1]*alpha*0.15),
                        int(teal[2]*alpha*0.18)))

    # Silhouette figure (abstract dark shape)
    # Dark figure standing in foreground (right side)
    fig_x, fig_y = W//2 + 180, H//4
    fig_h        = H - fig_y - 20
    fig_w        = 100
    # Body
    draw.ellipse([fig_x-35, fig_y-50, fig_x+35, fig_y+10],
                  fill=(8,8,12))  # head
    draw.rectangle([fig_x-45, fig_y+10, fig_x+45, fig_y+fig_h],
                    fill=(5,5,10))  # body
    # Rim glow (teal edge light)
    for offset in range(1, 8):
        a = int(60 - offset*7)
        draw.rectangle([fig_x-45-offset, fig_y+10-offset,
                         fig_x+45+offset, fig_y+fig_h+offset],
                         outline=(0, 180+offset*5, 180+offset*5, a))

    # Vignette overlay
    vig = Image.new("L", (W, H), 0)
    vd  = ImageDraw.Draw(vig)
    for r in range(min(W,H)//2, 0, -5):
        darkness = int(255 * (1 - (r / (min(W,H)/2))) * 0.65)
        vd.ellipse([W//2-r, H//2-r, W//2+r, H//2+r], fill=255-darkness)
    vig_rgb = Image.merge("RGB", [vig,vig,vig])
    img     = Image.blend(img, Image.new("RGB",(W,H),(0,0,0)), 0.0)
    img     = ImageEnhance.Brightness(img).enhance(0.85)

    # Apply film grain
    arr  = np.array(img).astype(np.float32)
    grain = np.random.normal(0, 12, arr.shape)
    arr   = np.clip(arr + grain, 0, 255).astype(np.uint8)
    img   = Image.fromarray(arr)
    draw  = ImageDraw.Draw(img)

    # ── Text Layout ───────────────────────────────────────────────
    title_text = script.get("video_title","DISTURBING REDDIT STORIES").upper()
    title_text = re.sub(r'[^\w\s!?]','', title_text)[:50]

    top_label  = "DISTURBING REDDIT STORIES"
    sub_label  = "THAT ACTUALLY HAPPENED"

    font_big   = get_font(tc["font_main_size"])
    font_med   = get_font(tc["font_sub_size"])
    font_small = get_font(36)

    # Top red label
    tb   = draw.textbbox((0,0), top_label, font=font_med)
    tw   = tb[2]-tb[0]
    draw.text((40+2, 42), top_label, font=font_med, fill=(0,0,0))
    draw.text((40, 40), top_label, font=font_med, fill=tuple(tc["danger_color"]))

    # Main white title (word wrapped)
    words  = title_text.split()
    line1  = " ".join(words[:4])
    line2  = " ".join(words[4:8]) if len(words) > 4 else ""
    for i, ln in enumerate([line1, line2]):
        if not ln: continue
        lb  = draw.textbbox((0,0), ln, font=font_big)
        lw  = lb[2]-lb[0]
        lx  = 40
        ly  = 110 + i * (tc["font_main_size"] + 8)
        # Glow
        for dx in range(-4,5,2):
            for dy in range(-4,5,2):
                draw.text((lx+dx,ly+dy), ln, font=font_big,
                           fill=(255,255,255,40))
        draw.text((lx+3,ly+3), ln, font=font_big, fill=(0,0,0))
        draw.text((lx,ly), ln, font=font_big,
                   fill=tuple(tc["text_color"]))

    # Sub label (teal)
    slb = draw.textbbox((0,0), sub_label, font=font_small)
    draw.text((40, H-80), sub_label, font=font_small,
               fill=tuple(tc["accent_color"]))

    # Teal accent bar
    draw.rectangle([0, H-10, W, H], fill=tuple(tc["accent_color"]))

    img.save(out_path, "JPEG", quality=95)
    log.info(f"✅ Thumbnail saved: {out_path}")
    return out_path

# ─────────────────────────────────────────────────────────────────
#  STEP 11 — YOUTUBE UPLOAD
# ─────────────────────────────────────────────────────────────────
def get_youtube_service(cfg: Dict):
    """Authenticate and return YouTube API service."""
    if not UPLOAD_AVAILABLE:
        log.error("YouTube upload libraries not installed")
        return None
    creds     = None
    token_file = "youtube_token.pickle"
    secrets   = cfg["api_keys"]["youtube_client_secrets"]
    if not os.path.exists(secrets):
        log.warning(f"⚠ YouTube OAuth file not found: {secrets} — skipping upload")
        return None
    if os.path.exists(token_file):
        with open(token_file, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(secrets, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "wb") as f:
            pickle.dump(creds, f)
    return build("youtube","v3", credentials=creds)

def upload_to_youtube(video_path: str, thumbnail_path: str,
                       script: Dict, cfg: Dict,
                       publish_now: bool = False) -> Optional[str]:
    """Upload video to YouTube with full SEO metadata."""
    svc = get_youtube_service(cfg)
    if svc is None:
        log.warning("⚠ YouTube upload skipped (no credentials)")
        return None

    privacy   = "public" if publish_now else cfg["youtube_seo"]["default_privacy"]
    tags      = (script.get("tags") or []) + cfg["youtube_seo"]["default_tags"]
    tags      = list(dict.fromkeys(tags))[:50]  # dedupe + limit

    body = {
        "snippet": {
            "title":       script.get("youtube_title", script.get("video_title","Horror Stories"))[:100],
            "description": script.get("description","")[:5000],
            "tags":        tags,
            "categoryId":  cfg["youtube_seo"]["default_category"],
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "madeForKids":   cfg["youtube_seo"]["made_for_kids"],
            "selfDeclaredMadeForKids": cfg["youtube_seo"]["made_for_kids"],
        }
    }

    log.info(f"📤 Uploading to YouTube as {privacy}...")
    media  = MediaFileUpload(video_path, mimetype="video/mp4",
                              resumable=True, chunksize=5*1024*1024)
    req    = svc.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
    resp   = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            log.info(f"  Upload progress: {int(status.progress()*100)}%")

    video_id = resp["id"]
    log.info(f"✅ Uploaded! Video ID: {video_id}")
    log.info(f"   https://www.youtube.com/watch?v={video_id}")

    # Set thumbnail
    try:
        svc.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
        ).execute()
        log.info("✅ Thumbnail uploaded")
    except Exception as e:
        log.warning(f"Thumbnail upload failed: {e}")

    return video_id

# ─────────────────────────────────────────────────────────────────
#  STEP 12 — SCHEDULER
# ─────────────────────────────────────────────────────────────────
def get_next_upload_time(day_override: Optional[str] = None) -> Optional[datetime]:
    """Calculate next scheduled upload time in US Eastern."""
    try:
        import pytz
        tz = pytz.timezone(SCH["schedule"]["timezone"])
    except ImportError:
        log.warning("pytz not installed — using UTC offset -5 for ET")
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=-5))

    now    = datetime.now(tz)
    weekly = SCH["schedule"]["weekly"]
    
    if day_override:
        day_key = day_override.lower()
        if day_key not in weekly:
            log.error(f"Unknown day: {day_override}")
            return None
        slot = weekly[day_key]
        h, m = map(int, slot["upload_time"].split(":"))
        days_ahead = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,
                       "friday":4,"saturday":5,"sunday":6}
        target_wd  = days_ahead[day_key]
        current_wd = now.weekday()
        diff = (target_wd - current_wd) % 7
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        target += timedelta(days=diff)
        if target < now:
            target += timedelta(days=7)
        return target

    # Auto: find next upcoming slot
    days_map   = {0:"monday",1:"tuesday",2:"wednesday",3:"thursday",
                   4:"friday",5:"saturday",6:"sunday"}
    candidates = []
    for offset in range(8):
        target_dt = now + timedelta(days=offset)
        day_name  = days_map[target_dt.weekday()]
        if day_name not in weekly:
            continue
        slot  = weekly[day_name]
        h, m  = map(int, slot["upload_time"].split(":"))
        sched = target_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        if sched > now:
            candidates.append((sched, day_name, slot))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        sched_time, day_name, slot = candidates[0]
        log.info(f"⏰ Next upload: {day_name.title()} {slot['upload_time']} ET "
                 f"({slot['label']}) — {sched_time.strftime('%Y-%m-%d %H:%M')}")
        return sched_time
    return None

def wait_for_upload_time(target: datetime):
    """Sleep until upload time."""
    try:
        import pytz
        tz  = pytz.timezone(SCH["schedule"]["timezone"])
        now = datetime.now(tz)
    except:
        now = datetime.utcnow()
    wait_sec = max(0, (target - now).total_seconds())
    if wait_sec > 0:
        log.info(f"⏳ Waiting {wait_sec/3600:.1f}h until scheduled upload time...")
        time.sleep(wait_sec)

# ─────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────
def _datestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def cleanup_temp(cfg: Dict):
    if not cfg["output"]["keep_temp_files"]:
        import shutil
        shutil.rmtree(str(TEMP_DIR), ignore_errors=True)
        TEMP_DIR.mkdir(exist_ok=True)
        log.info("🧹 Temp files cleaned")

def print_banner():
    print("""
╔══════════════════════════════════════════════════════════════════╗
║   DARK CONFESSIONS - Horror Automation Pipeline v3.0            ║
║   Target: 300K–600K views | 1.5–2 Lakh PKR per video           ║
║   US Audience Optimized | EdgeTTS + Gemini + Pixabay            ║
╚══════════════════════════════════════════════════════════════════╝
""")

def print_seo_report(script: Dict, video_path: str, thumb_path: str):
    print("\n" + "═"*60)
    print("  📊 SEO PRODUCTION REPORT")
    print("═"*60)
    print(f"  📹 Video   : {video_path}")
    print(f"  🖼  Thumb   : {thumb_path}")
    print(f"  📌 Title   : {script.get('youtube_title','')[:70]}")
    print(f"  🏷  Tags    : {len(script.get('tags',[]))} tags")
    print(f"  📝 Desc    : {len(script.get('description',''))} chars")
    print("\n  🎯 UPLOAD SCHEDULE (US Eastern):")
    for day, info in SCH["schedule"]["weekly"].items():
        print(f"     {day.title():<12} {info['upload_time']} ET  — {info['label']}")
    print("═"*60 + "\n")

# ─────────────────────────────────────────────────────────────────
#  MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────
def run_pipeline(topic: str, run_now: bool = False,
                 day_override: Optional[str] = None,
                 skip_upload: bool = False,
                 skip_video:  bool = False) -> Dict:
    """Master pipeline: script → audio → visuals → edit → thumbnail → upload."""
    print_banner()
    result = {}

    # ── 1. Script ─────────────────────────────────────────────────
    log.info("━━━ STEP 1: Generating Script ━━━")
    gemini = init_gemini()
    script = generate_script(topic, gemini)
    result["script"] = script

    # ── 2. Audio ──────────────────────────────────────────────────
    log.info("━━━ STEP 2: Generating Voice Audio ━━━")
    segments = generate_audio_segments(script, CFG)
    result["segments"] = segments

    # ── 3. Thumbnail (quick — do before video) ───────────────────
    log.info("━━━ STEP 3: Generating Thumbnail ━━━")
    thumb_path = generate_thumbnail(script, CFG)
    result["thumbnail"] = thumb_path

    if skip_video:
        print_seo_report(script, "(skipped)", thumb_path)
        return result

    # ── 4. Fetch B-roll ───────────────────────────────────────────
    log.info("━━━ STEP 4: Fetching B-Roll Clips ━━━")
    raw_clips = fetch_pixabay_clips(CFG, count=60)

    # ── 5. Generate BG Music ──────────────────────────────────────
    log.info("━━━ STEP 5: Generating Background Music ━━━")
    total_approx = sum(get_audio_duration(s["path"]) for s in segments)
    bg_music     = generate_bg_music(total_approx + 60, CFG)

    # ── 6. Assemble Segments ──────────────────────────────────────
    log.info("━━━ STEP 6: Assembling Video Segments ━━━")
    assembled    = []
    bg_offset    = 0.0
    for seg in segments:
        seg_path, dur = assemble_segment(seg, raw_clips, bg_music,
                                          bg_offset, CFG)
        assembled.append(seg_path)
        bg_offset += dur

    # ── 7. Transitions ────────────────────────────────────────────
    log.info("━━━ STEP 7: Adding Cinematic Transitions ━━━")
    transitions = []
    for i in range(len(assembled)-1):
        t = add_transition(assembled[i], assembled[i+1], CFG, i)
        transitions.append(t)

    # ── 8. Final Concat ───────────────────────────────────────────
    log.info("━━━ STEP 8: Final Assembly ━━━")
    video_path = concat_all_segments(assembled, transitions, CFG)
    result["video"] = video_path

    print_seo_report(script, video_path, thumb_path)

    if skip_upload:
        log.info("⏭ Upload skipped (--skip-upload)")
        return result

    # ── 9. Upload ─────────────────────────────────────────────────
    log.info("━━━ STEP 9: YouTube Upload ━━━")
    if run_now:
        vid_id = upload_to_youtube(video_path, thumb_path, script, CFG,
                                    publish_now=True)
    else:
        upload_time = get_next_upload_time(day_override)
        if upload_time and SCH["schedule"].get("enabled", True):
            wait_for_upload_time(upload_time)
            vid_id = upload_to_youtube(video_path, thumb_path, script, CFG,
                                        publish_now=True)
        else:
            vid_id = upload_to_youtube(video_path, thumb_path, script, CFG,
                                        publish_now=False)
    result["youtube_id"] = vid_id

    # ── 10. Cleanup ───────────────────────────────────────────────
    cleanup_temp(CFG)
    log.info("🎉 PIPELINE COMPLETE!")
    if vid_id:
        log.info(f"   Watch: https://www.youtube.com/watch?v={vid_id}")
    return result

# ─────────────────────────────────────────────────────────────────
#  CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Dark Confessions – Horror YouTube Automation Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python main.py                             Run with auto schedule
          python main.py --run-now                   Generate + upload immediately
          python main.py --day sunday                Override upload to Sunday slot
          python main.py --topic "stalker stories"  Custom horror topic
          python main.py --skip-upload              Generate video only
          python main.py --skip-video               Script + thumbnail only
        """)
    )
    parser.add_argument("--run-now",     action="store_true",
                         help="Generate and upload immediately (ignore schedule)")
    parser.add_argument("--day",         type=str, default=None,
                         help="Override upload day (monday/tuesday/.../sunday)")
    parser.add_argument("--topic",       type=str, default=None,
                         help="Custom horror topic for script generation")
    parser.add_argument("--skip-upload", action="store_true",
                         help="Generate video but don't upload")
    parser.add_argument("--skip-video",  action="store_true",
                         help="Only generate script + thumbnail")
    args = parser.parse_args()

    # Choose topic
    default_topics = [
        "strangers who came back",
        "things found in the dark",
        "someone was already in the house",
        "wrong place wrong time",
        "they were never alone",
        "messages from the missing",
    ]
    topic = args.topic or default_topics[datetime.now().weekday() % len(default_topics)]
    log.info(f"🎬 Topic: {topic}")

    run_pipeline(
        topic      = topic,
        run_now    = args.run_now,
        day_override = args.day,
        skip_upload = args.skip_upload,
        skip_video  = args.skip_video,
    )

if __name__ == "__main__":
    main()
