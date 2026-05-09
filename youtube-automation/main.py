"""
╔══════════════════════════════════════════════════════════════════════╗
║   VIRAL DOCUMENTARY ENGINE  v9.0  —  main.py                       ║
║   Elite 20M-subscriber level content production system             ║
║                                                                      ║
║   PIPELINE:                                                          ║
║     1. Topic Viability Audit + Upgrade                              ║
║     2. Viral Title Engine       (10 CTR-ranked titles)             ║
║     3. Thumbnail Engine         (5 concepts with briefs)            ║
║     4. Best Angle Selector      (Rise/Fall, War, Betrayal etc)     ║
║     5. Full Documentary Structure (8-min OR 60-sec Shorts)         ║
║     6. Scene-by-Scene Visual Plan (every 2-5 seconds)              ║
║     7. Exact Asset Search Terms  (30+ Pexels/Pixabay queries)      ║
║     8. Hybrid Asset Router       (wiki/pexels/pixabay per scene)   ║
║     9. Voice Engine              (Christopher Neural +8% +10vol)   ║
║    10. Editing Engine            (zoom, cuts, SFX, retention)      ║
║    11. SEO Engine                (title, desc, 30 tags, chapters)  ║
║    12. Viral Scorecard           (CTR, retention, breakout est)    ║
║    13. Shorts Version            (45-sec reel from same topic)     ║
║    14. YouTube Upload                                               ║
║                                                                      ║
║   ENV KEYS:                                                         ║
║     GEMINI_API_KEY   PIXABAY_API_KEY   PEXELS_API_KEY              ║
║     NEWSAPI_KEY      YT_CLIENT_ID      YT_CLIENT_SECRET            ║
║     YT_REFRESH_TOKEN   CHANNEL_NAME                                 ║
║                                                                      ║
║   Run:   python main.py                                             ║
║   Deps:  pip install -r requirements.txt                            ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os, sys, re, json, random, asyncio, uuid, shutil, io, bisect, traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import PIL.Image as PilImage
import google.generativeai as genai

from moviepy.editor import (
    AudioFileClip, ColorClip, CompositeAudioClip,
    CompositeVideoClip, ImageClip, VideoClip,
    VideoFileClip, concatenate_audioclips,
)
from moviepy.video.fx import all as vfx
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if not hasattr(PilImage, "ANTIALIAS"):
    PilImage.ANTIALIAS = PilImage.LANCZOS

# ══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════
OUT_DIR    = "output"
SCENE_DIR  = "output/scenes"
CLIPS_DIR  = "output/clips"
MUS_DIR    = "output/music"
LOG_FILE   = "output/posted.log"

CW, CH     = 1080, 1920          # vertical short canvas
FPS        = 30
MIN_CLIP   = 2.0                 # minimum clip duration seconds

# ─── Voice: Christopher Neural — deep, cinematic, documentary ─────────
VOICE_NAME   = "en-US-ChristopherNeural"
VOICE_RATE   = "+8%"
VOICE_VOLUME = "+10%"

# ─── Caption colors ───────────────────────────────────────────────────
CAP_BOX  = (255, 214,   0, 248)   # yellow box active word
CAP_TXT  = (  0,   0,   0, 255)   # black text on yellow
CAP_WHT  = (255, 255, 255, 255)   # white surrounding words
CAP_BLK  = (  0,   0,   0, 210)   # outline

HDR = {"User-Agent": "ViralDocEngine/9.0 (research-bot; contact@example.com)"}
WIKI_API = "https://commons.wikimedia.org/w/api.php"
SKIP_EXT = {
    "svg","ogg","ogv","pdf","webm","mp4","xcf",
    "djvu","flac","mid","wav","opus","mov","avi","tif","tiff",
}

# Module-level state (reset each run)
USED_IDS:   set  = set()
WIKI_CACHE: dict = {}

# ─── Safe fallback Pixabay queries (NO people, NO haram) ─────────────
SAFE_FALLBACKS = [
    "money cash dollar bills finance",
    "corporate building exterior finance",
    "wall street stock exchange",
    "government building politics",
    "data server technology center",
    "city skyline architecture",
    "finance chart graph data",
    "gold coins money wealth",
    "bank building exterior",
    "technology circuit board",
    "newspaper headline breaking news",
    "document paper contract",
]


# ══════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════
def validate_env():
    must = ["GEMINI_API_KEY", "PIXABAY_API_KEY"]
    bad  = [k for k in must if not os.getenv(k)]
    if bad:
        for b in bad:
            print("MISSING: " + b + "  →  add to .env file")
        sys.exit(1)
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    pexels_ok = bool(os.getenv("PEXELS_API_KEY"))
    newsapi_ok = bool(os.getenv("NEWSAPI_KEY"))
    yt_ok = all([os.getenv("YT_CLIENT_ID"),
                 os.getenv("YT_CLIENT_SECRET"),
                 os.getenv("YT_REFRESH_TOKEN")])
    print("ENV OK. Pexels=" + str(pexels_ok) +
          "  NewsAPI=" + str(newsapi_ok) +
          "  YouTube=" + str(yt_ok))


def boot():
    global USED_IDS, WIKI_CACHE
    USED_IDS    = set()
    WIKI_CACHE  = {}
    for d in [OUT_DIR, SCENE_DIR, CLIPS_DIR, MUS_DIR, OUT_DIR + "/tmp"]:
        os.makedirs(d, exist_ok=True)
    print("Workspace clean.")


# ══════════════════════════════════════════════════════════════════════
# HTTP HELPERS
# ══════════════════════════════════════════════════════════════════════
def jget(url, params=None, extra_headers=None, timeout=14):
    try:
        h = dict(HDR)
        if extra_headers:
            h.update(extra_headers)
        r = requests.get(url, params=params, headers=h, timeout=timeout)
        if r.status_code != 200:
            return None
        t = r.text.strip()
        if not t or t[0] not in ("{", "["):
            return None
        return r.json()
    except Exception:
        return None


def dlb(url, timeout=45):
    try:
        r = requests.get(url, headers=HDR, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 512:
            return r.content
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════
# MODULE 1 — TREND DISCOVERY
# ══════════════════════════════════════════════════════════════════════
FALLBACK_TRENDS = [
    "Nvidia just became the most powerful gatekeeper in AI history and nobody voted for it",
    "Apple destroyed Meta's ad business with one privacy update and secretly built its own",
    "Amazon warehouse AI fires workers for being six seconds too slow with zero human review",
    "Sam Altman's Worldcoin scanned 5 million people's irises and created permanent biometric IDs",
    "BlackRock AI named Aladdin manages 21 trillion dollars and is buying residential property",
    "McDonald's real estate empire is worth 40 billion and the burgers are just a side business",
    "Uber deliberately lost 31 billion dollars to destroy every local taxi company on earth",
    "Boeing spent 43 billion on bonuses while 346 people died in preventable crashes",
    "Goldman Sachs sold toxic mortgage products to pension funds then bet against them internally",
    "Purdue Pharma paid 18000 doctors to call OxyContin safer than aspirin",
    "TikTok algorithm predicts pregnancy before the mother knows using hover-time to the millisecond",
    "Netflix algorithm detects when you want to cancel and surfaces content designed to stop you",
]


def get_trend():
    key = os.getenv("NEWSAPI_KEY")
    if key:
        try:
            d = jget(
                "https://newsapi.org/v2/top-headlines",
                params={"apiKey": key, "category": "business",
                        "country": "us", "pageSize": 20},
            )
            if d:
                kws = ["billion", "trillion", "ceo", "fraud", "fed", "bank",
                       "apple", "google", "amazon", "nvidia", "tesla", "meta",
                       "debt", "layoff", "antitrust", "lawsuit", "merger"]
                for art in d.get("articles", []):
                    c = (art.get("title", "") + " " +
                         art.get("description", "")).lower()
                    if any(k in c for k in kws):
                        hl   = art.get("title", "")
                        desc = art.get("description", "") or ""
                        full = hl + ". " + desc
                        print("TREND (NewsAPI): " + hl)
                        return full
        except Exception as e:
            print("NewsAPI err: " + str(e))
    t = random.choice(FALLBACK_TRENDS)
    print("TREND (fallback): " + t)
    return t


# ══════════════════════════════════════════════════════════════════════
# MODULE 2 — FULL GEMINI PRODUCTION ENGINE
# One call returns the ENTIRE production package:
#   - viral titles (10)
#   - thumbnail concepts (5)
#   - video angle
#   - full 8-min documentary structure
#   - scene-by-scene breakdown
#   - 30 exact asset search terms
#   - voiceover style notes
#   - SEO pack
#   - viral scorecard
#   - 45-sec shorts version
# ══════════════════════════════════════════════════════════════════════
PRODUCTION_SYSTEM = """
You are an elite YouTube documentary strategist combining MagnatesMedia, Johnny Harris, and James Jani.
You think like a 20M-subscriber media operator.

You optimize for: CTR, retention (70%+), emotional tension, bingeability.

VOICE: en-US-ChristopherNeural at +8% rate +10% volume.
All content must be safe for US audiences. No sensitive imagery suggestions.

When given a topic, output ONLY valid JSON (no markdown, no explanation):

{
  "topic_audit": {
    "type": "mass_market | niche | weak",
    "view_potential": "estimated range e.g. 500K-2M",
    "why_wins": "one sentence",
    "risk": "one sentence",
    "upgraded_angle": "stronger framing of the topic"
  },

  "viral_titles": [
    {"title": "...", "ctr_rank": 1, "why": "short reason"}
  ],
  "best_title_index": 0,

  "thumbnail_concepts": [
    {
      "concept": "visual description",
      "emotion_trigger": "shock|curiosity|betrayal|fear|power",
      "color_contrast": "e.g. red vs black",
      "text_overlay": "max 3 words or empty string",
      "ctr_score": 9
    }
  ],

  "video_angle": {
    "archetype": "Rise and Fall | Hidden War | Betrayal | Secret Strategy | Company Killed Industry | Man Who Built Rival",
    "one_liner": "The story in one sentence",
    "why_this_angle": "why this beats others"
  },

  "documentary_structure": {
    "sections": [
      {
        "id": 1,
        "timecode": "0:00-0:20",
        "label": "HOOK",
        "narration_summary": "what is said",
        "emotion_target": "shock",
        "retention_trick": "how you keep them watching",
        "cliffhanger": "line that creates curiosity gap"
      }
    ]
  },

  "scenes": [
    {
      "id": 1,
      "section": "HOOK",
      "duration_seconds": 12,
      "narration": "full voiceover text for this scene. Short punchy sentences. Max 10 words each.",
      "emotion": "hook | tension | rise | conflict | turning_point | cliffhanger",
      "visual_plan": ["what appears on screen every 2-4 seconds"],
      "clip_sources": ["wiki:Jensen Huang Nvidia CEO", "pix:corporate boardroom meeting"],
      "edit_style": "zoom-in | glitch | cinematic_pan | slow_motion | hard_cut",
      "retention_trigger": "curiosity gap line inserted at scene end",
      "pacing": "fast | medium | slow",
      "sfx_hit": true
    }
  ],

  "asset_search_terms": [
    {"query": "exact pixabay or pexels search term", "source": "pexels|pixabay|wikimedia", "scene_id": 1}
  ],

  "voiceover_guide": {
    "voice": "en-US-ChristopherNeural",
    "rate": "+8%",
    "volume": "+10%",
    "style_notes": "how to deliver each section",
    "emphasis_words": ["list of words to stress"]
  },

  "editing_blueprint": {
    "cut_frequency": "2-4 seconds",
    "zoom_rule": "zoom in 8% every scene transition",
    "music_arc": "dark tension → momentum → heavy suspense → epic unresolved",
    "sfx_moments": ["list of where to place whoosh/bass/glitch"],
    "pattern_interrupts": ["what changes every 15-20 seconds to re-hook viewer"]
  },

  "seo": {
    "final_title": "...",
    "alt_titles": ["alt1", "alt2"],
    "description": "full YouTube description with chapters",
    "tags": ["30 tags"],
    "hashtags": ["15 hashtags"],
    "chapters": ["0:00 Hook", "0:20 Background", "..."]
  },

  "viral_scorecard": {
    "ctr": 8,
    "retention": 7,
    "topic_size": 9,
    "competition": 6,
    "monetization": 8,
    "subscriber_conversion": 7,
    "verdict": "realistic estimate e.g. 300K-1M",
    "breakout_scenario": "what would make it hit 5M+"
  },

  "shorts_version": {
    "duration": "45 seconds",
    "hook_line": "first line stops the scroll",
    "script": "full 45-sec script",
    "clip_sources": ["list of 6 clips for the short"]
  },

  "channel_growth": {
    "upload_frequency": "e.g. daily",
    "next_10_topics": ["list of 10 related viral topics"],
    "binge_strategy": "one sentence"
  },

  "brutal_honest_advice": "What would actually kill this video. What would make it hit 1M+. Beginner mistakes to avoid."
}

RULES:
- All scene narration: short punchy sentences, max 10 words each
- Re-hook every 15 seconds (insert retention trigger)
- Never fully explain in the same sentence you introduce
- Use specific names, numbers, dates — not generic claims
- Every scene must add new narrative value
- clip_sources: "wiki:X" for named people/companies, "pix:X" for concepts
- No haram content — no alcohol, gambling, inappropriate imagery
- All Pixabay searches must be safe for US general audiences
- Generate 6-9 scenes total for a 60-90 second output
"""


def run_production_engine(raw_trend):
    print("\n[GEMINI] Generating full production package...")
    try:
        model  = genai.GenerativeModel("gemini-1.5-pro")
        prompt = (
            "TRENDING TOPIC:\n" + raw_trend + "\n\n"
            "Generate the complete viral documentary production package. "
            "Use real CEO names, real dollar amounts, real percentages. "
            "Make every claim specific and verifiable. "
            "Target US audience aged 18-45 who care about money, power, and corporate deception. "
            "Script total = 70-100 words across all scenes (60-90 second video). "
            "Each scene narration = 12-20 words max. Short. Punchy. Urgent."
        )
        resp = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.85),
            system_instruction=PRODUCTION_SYSTEM,
        )
        text = resp.text.strip()
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        data = json.loads(text)
        _print_production_summary(data)
        return data
    except Exception as e:
        print("Gemini err: " + str(e))
        return None


def _print_production_summary(data):
    audit  = data.get("topic_audit", {})
    titles = data.get("viral_titles", [])
    bi     = data.get("best_title_index", 0)
    score  = data.get("viral_scorecard", {})
    scenes = data.get("scenes", [])

    print("\n" + "=" * 60)
    print("  VIRAL DOCUMENTARY PRODUCTION PACKAGE")
    print("=" * 60)
    print("TOPIC TYPE:   " + audit.get("type", "?"))
    print("VIEW POTENTIAL: " + audit.get("view_potential", "?"))
    print("BEST ANGLE:   " + data.get("video_angle", {}).get("one_liner", "?"))
    print("")
    print("TOP 3 TITLES:")
    for i, t in enumerate(titles[:3]):
        star = " ← SELECTED" if i == bi else ""
        print("  [" + str(i + 1) + "] " + t.get("title", "") + star)
    print("")
    print("VIRAL SCORE:")
    print("  CTR:       " + str(score.get("ctr", "?")) + "/10")
    print("  Retention: " + str(score.get("retention", "?")) + "/10")
    print("  Topic:     " + str(score.get("topic_size", "?")) + "/10")
    print("  Verdict:   " + score.get("verdict", "?"))
    print("")
    print("SCENES: " + str(len(scenes)))
    for s in scenes:
        print("  [" + str(s.get("id", "?")) + "] " +
              s.get("emotion", "?").upper() + " — " +
              s.get("narration", "")[:55] + "...")
    thumb = data.get("thumbnail_concepts", [{}])[0]
    print("")
    print("THUMBNAIL:")
    print("  " + thumb.get("concept", ""))
    print("  TEXT: " + thumb.get("text_overlay", ""))
    print("")
    print("BRUTAL TRUTH:")
    print("  " + data.get("brutal_honest_advice", ""))
    print("=" * 60 + "\n")


def fallback_production(raw_trend):
    """Used only when Gemini completely fails."""
    return {
        "topic_audit": {
            "type": "mass_market",
            "view_potential": "300K-1.5M",
            "why_wins": "Corporate expose with named entity and specific dollar amount",
            "risk": "Topic may be partially known — needs fresh angle",
            "upgraded_angle": "The secret they buried for years",
        },
        "viral_titles": [
            {"title": "The Corporate Secret Nobody Is Talking About", "ctr_rank": 1, "why": "mystery + power"},
        ],
        "best_title_index": 0,
        "thumbnail_concepts": [
            {"concept": "Dark corporate logo cracked", "emotion_trigger": "shock",
             "color_contrast": "red vs black", "text_overlay": "THEY KNEW.", "ctr_score": 8}
        ],
        "video_angle": {
            "archetype": "Hidden War",
            "one_liner": "How a corporation manipulated millions and paid nothing",
            "why_this_angle": "conflict drives watch time",
        },
        "scenes": [
            {"id": 1, "section": "HOOK", "duration_seconds": 12,
             "narration": "What they did is fully legal. That is the terrifying part.",
             "emotion": "hook",
             "clip_sources": ["pix:corporate boardroom dark", "pix:money cash finance"],
             "edit_style": "zoom-in", "retention_trigger": "And it gets worse.",
             "pacing": "fast", "sfx_hit": True},
            {"id": 2, "section": "CONFLICT", "duration_seconds": 30,
             "narration": raw_trend[:100] + ".",
             "emotion": "conflict",
             "clip_sources": ["pix:wall street finance", "pix:government building"],
             "edit_style": "cinematic_pan", "retention_trigger": "Nobody stopped them.",
             "pacing": "medium", "sfx_hit": False},
            {"id": 3, "section": "CLIFFHANGER", "duration_seconds": 18,
             "narration": "This is still happening. Right now. And you are paying for it.",
             "emotion": "cliffhanger",
             "clip_sources": ["pix:money loss finance", "pix:corporate profit chart"],
             "edit_style": "slow_motion", "retention_trigger": "Follow for what comes next.",
             "pacing": "slow", "sfx_hit": False},
        ],
        "asset_search_terms": [
            {"query": "corporate boardroom meeting", "source": "pixabay", "scene_id": 1},
            {"query": "money cash finance", "source": "pixabay", "scene_id": 2},
        ],
        "seo": {
            "final_title": "The Corporate Secret Nobody Is Talking About",
            "alt_titles": ["What They Hid From You", "The Truth They Buried"],
            "description": "The truth they hoped you would never find. Every claim documented.\n\n#FinanceSecrets #CorporateExpose",
            "tags": ["finance", "expose", "corporate", "secrets", "usa", "2026"],
            "hashtags": ["#FinanceSecrets", "#CorporateExpose", "#WallStreet"],
            "chapters": ["0:00 Hook", "0:12 The Truth", "0:42 What This Means For You"],
        },
        "viral_scorecard": {
            "ctr": 7, "retention": 7, "topic_size": 8,
            "competition": 6, "monetization": 8, "subscriber_conversion": 7,
            "verdict": "300K-800K realistic",
            "breakout_scenario": "Thumbnail with one shocking number + trending news timing",
        },
        "shorts_version": {
            "duration": "45 seconds",
            "hook_line": "What they did is legal. That is the terrifying part.",
            "script": "What they did is fully legal. Nobody warned you. " + raw_trend[:80] + " And this is still happening today.",
            "clip_sources": ["pix:corporate boardroom", "pix:money finance", "pix:government building"],
        },
        "channel_growth": {
            "upload_frequency": "1 per day",
            "next_10_topics": [
                "How McDonald's Makes Money Without Selling Food",
                "The Visa Tax Nobody Talks About",
                "Why Your Credit Score Rewards Debt",
                "How Netflix Decides What You Watch Next",
                "The Amazon AI That Fires Workers Automatically",
                "Why Uber Lost $31 Billion On Purpose",
                "The Sugar Lobby That Rewrote Nutrition Science",
                "How Ticketmaster Owns Every Major Venue",
                "The BlackRock AI Managing More Than the US Economy",
                "Why Warren Buffett Is Holding Record Cash",
            ],
            "binge_strategy": "End each video with a teaser of the next expose",
        },
        "brutal_honest_advice": "Thumbnail is 70% of success. No thumbnail = no views. Specific numbers outperform vague claims every time.",
        "editing_blueprint": {
            "cut_frequency": "2-4 seconds",
            "zoom_rule": "zoom in 8% every scene",
            "music_arc": "dark tension → momentum → heavy suspense → unresolved",
            "sfx_moments": ["bass hit at hook", "whoosh at each cut"],
            "pattern_interrupts": ["new visual every 3 seconds", "caption color shift"],
        },
        "voiceover_guide": {
            "voice": "en-US-ChristopherNeural",
            "rate": "+8%", "volume": "+10%",
            "style_notes": "Slow start, accelerate into conflict, quiet before punchline",
            "emphasis_words": ["legal", "right now", "paying", "zero"],
        },
    }


# ══════════════════════════════════════════════════════════════════════
# MODULE 3 — VOICE ENGINE
# Christopher Neural — deep, cinematic, documentary tone
# Per-scene MP3 files for modular re-renders
# WordBoundary for ms-accurate caption sync
# ══════════════════════════════════════════════════════════════════════
async def generate_scene_voice(text, scene_id, out_dir):
    out_path = os.path.join(out_dir, "s" + str(scene_id) + "_voice.mp3")
    timings  = []
    com      = edge_tts.Communicate(
        text, VOICE_NAME,
        rate=VOICE_RATE,
        volume=VOICE_VOLUME,
    )
    with open(out_path, "wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                w = chunk.get("text", "").strip()
                if not w or all(c in ".,;:!?-—'" for c in w):
                    continue
                s = chunk["offset"]   / 1e7
                d = chunk["duration"] / 1e7
                timings.append({"word": w, "start": s, "end": s + d, "duration": d})

    # Even-split fallback
    if not timings:
        ac    = AudioFileClip(out_path)
        dur   = ac.duration
        ac.close()
        words = [w for w in text.split() if w]
        per   = dur / max(len(words), 1)
        timings = [{"word": w, "start": i * per,
                    "end": (i + 1) * per, "duration": per}
                   for i, w in enumerate(words)]

    ac    = AudioFileClip(out_path)
    total = ac.duration
    ac.close()
    return out_path, timings, total


async def build_all_voices(scenes, out_dir):
    results = []
    for scene in scenes:
        sid  = scene.get("id", len(results) + 1)
        # Narration + retention trigger spoken together
        narr  = scene.get("narration", "")
        rt    = scene.get("retention_trigger", "")
        text  = narr + " " + rt if rt else narr
        path, timings, dur = await generate_scene_voice(text, sid, out_dir)
        results.append({
            "scene":   scene,
            "voice":   path,
            "timings": timings,
            "duration": dur,
        })
        print("  Voice s" + str(sid) + ": " + str(round(dur, 1)) + "s — " + text[:50] + "...")
    return results


# ══════════════════════════════════════════════════════════════════════
# MODULE 4 — VISUAL ASSET ENGINE
# Priority (Viral Doc rules):
#   1. Human emotion clips (CEOs, faces, reactions)
#   2. Real-world business/tech footage
#   3. Symbolic visuals (war, chess, storms, shadow/light)
#   4. Abstract (charts, data, maps)
# NEVER: repeated office screens, generic coding
# Wikimedia: named people / company HQs / specific products
# Pexels: human-facing, emotional contextual clips
# Pixabay: abstract, symbolic, financial (safesearch=true)
# ══════════════════════════════════════════════════════════════════════

# ── Image grading pipeline ────────────────────────────────────────────
def grade_and_save(img):
    """Cinematic grade: desaturate + darken + contrast + vignette."""
    img = img.convert("RGB")
    img = ImageEnhance.Color(img).enhance(0.78)
    img = ImageEnhance.Brightness(img).enhance(0.84)
    img = ImageEnhance.Contrast(img).enhance(1.18)

    # Vignette
    w, h = img.size
    mask = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(mask)
    for i in range(55):
        v = int(255 * (i / 55) ** 1.7)
        draw.rectangle([i, i, w - i, h - i], outline=v)
    mask  = mask.filter(ImageFilter.GaussianBlur(radius=w // 5))
    black = Image.new("RGB", (w, h), (0, 0, 0))
    img   = Image.composite(img, black, mask)
    return img


def cover_crop_img(img):
    iw, ih = img.size
    scale  = max(CW / iw, CH / ih)
    nw     = max(int(iw * scale), CW)
    nh     = max(int(ih * scale), CH)
    img    = img.resize((nw, nh), Image.LANCZOS)
    x0, y0 = (nw - CW) // 2, (nh - CH) // 2
    return img.crop((x0, y0, x0 + CW, y0 + CH))


def save_clip_image(img):
    dest = os.path.join(CLIPS_DIR, "img_" + uuid.uuid4().hex[:7] + ".jpg")
    img.save(dest, "JPEG", quality=92)
    return dest


# ── Wikimedia ─────────────────────────────────────────────────────────
def _wiki_pages(q, limit=20):
    d = jget(WIKI_API, {
        "action": "query", "format": "json",
        "generator": "search",
        "gsrsearch": "filetype:bitmap " + q,
        "gsrlimit": limit, "prop": "imageinfo",
        "iiprop": "url|mime|size", "iilimit": 1, "gsrnamespace": 6,
    })
    if not d:
        return []
    return list(d.get("query", {}).get("pages", {}).values())


def _pick_url(pages):
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        url  = info.get("url", "")
        mime = info.get("mime", "")
        ext  = url.rsplit(".", 1)[-1].lower().split("?")[0]
        if ext in SKIP_EXT:
            continue
        if mime and not mime.startswith("image"):
            continue
        if info.get("size", 9999999) < 2000:
            continue
        return url
    return None


def get_wiki_image(query):
    if query in WIKI_CACHE:
        return WIKI_CACHE[query]
    attempts = [query, query + " portrait photo", query + " official"]
    seen, unique = set(), []
    for a in attempts:
        a = a.strip()
        if a and a not in seen:
            seen.add(a); unique.append(a)
    for attempt in unique:
        pages = _wiki_pages(attempt)
        url   = _pick_url(pages)
        if not url:
            continue
        raw = dlb(url)
        if not raw:
            continue
        try:
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            if img.width < 80 or img.height < 80:
                continue
            img  = cover_crop_img(img)
            img  = grade_and_save(img)
            dest = save_clip_image(img)
            WIKI_CACHE[query] = dest
            print("  Wiki: " + query)
            return dest
        except Exception as e:
            print("  Wiki err (" + attempt + "): " + str(e))
    WIKI_CACHE[query] = None
    print("  Wiki miss: " + query)
    return None


def wiki_clip(path, dur, edit_style="zoom-in"):
    c = ImageClip(path).set_duration(dur)
    if edit_style in ("zoom-in", "cinematic_pan"):
        c = c.fx(vfx.resize, lambda t: 1.0 + 0.09 * (t / max(dur, 0.001)))
    elif edit_style == "slow_motion":
        c = c.fx(vfx.resize, lambda t: 1.0 + 0.04 * (t / max(dur, 0.001)))
    return c.set_position("center")


# ── Pexels ────────────────────────────────────────────────────────────
def get_pexels_clip(query, dur):
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": 20,
                    "orientation": "portrait", "size": "medium"},
            headers={"Authorization": key},
            timeout=14,
        )
        if r.status_code != 200:
            return None
        hits = r.json().get("videos", [])
        if not hits:
            return None
        random.shuffle(hits)
        for hit in hits:
            vid_id = hit.get("id")
            if vid_id and vid_id in USED_IDS:
                continue
            files = sorted(
                hit.get("video_files", []),
                key=lambda x: x.get("height", 0), reverse=True
            )
            for vf in files:
                if vf.get("quality") in ("hd", "sd") and vf.get("link"):
                    raw = dlb(vf["link"])
                    if not raw:
                        continue
                    dest = os.path.join(CLIPS_DIR, "pex_" + uuid.uuid4().hex[:7] + ".mp4")
                    with open(dest, "wb") as f:
                        f.write(raw)
                    vc  = VideoFileClip(dest).without_audio()
                    if vc.duration < 0.5:
                        vc.close(); continue
                    sub = vc.subclip(0, min(dur, vc.duration - 0.05))
                    rv, rc = sub.w / sub.h, CW / CH
                    if rv > rc:
                        sub = sub.resize(height=CH).crop(x_center=sub.w / 2, width=CW)
                    else:
                        sub = sub.resize(width=CW).crop(y_center=sub.h / 2, height=CH)
                    USED_IDS.add(vid_id)
                    print("  Pexels: " + query)
                    return sub
    except Exception as e:
        print("  Pexels err (" + query + "): " + str(e))
    return None


# ── Pixabay (safesearch=true always) ─────────────────────────────────
def get_pixabay_clip(query, dur):
    key = os.getenv("PIXABAY_API_KEY")
    if not key:
        return None
    d = jget("https://pixabay.com/api/videos/", {
        "key": key, "q": query, "per_page": 30,
        "orientation": "vertical", "safesearch": "true", "min_duration": 3,
    })
    if not d:
        return None
    hits = d.get("hits", [])
    if not hits:
        return None
    random.shuffle(hits)
    for hit in hits:
        hid  = hit.get("id")
        if hid and hid in USED_IDS:
            continue
        vs   = hit.get("videos", {})
        info = vs.get("medium") or vs.get("small") or vs.get("large") or vs.get("tiny")
        if not info or not info.get("url"):
            continue
        try:
            raw = dlb(info["url"])
            if not raw:
                continue
            dest = os.path.join(CLIPS_DIR, "pix_" + uuid.uuid4().hex[:7] + ".mp4")
            with open(dest, "wb") as f:
                f.write(raw)
            vc  = VideoFileClip(dest).without_audio()
            if vc.duration < 0.5:
                vc.close(); continue
            sub = vc.subclip(0, min(dur, vc.duration - 0.05))
            rv, rc = sub.w / sub.h, CW / CH
            if rv > rc:
                sub = sub.resize(height=CH).crop(x_center=sub.w / 2, width=CW)
            else:
                sub = sub.resize(width=CW).crop(y_center=sub.h / 2, height=CH)
            if hid:
                USED_IDS.add(hid)
            print("  Pixabay: " + query)
            return sub
        except Exception as e:
            print("  Pixabay err (" + query + "): " + str(e))
    return None


def get_any_clip(query, dur):
    """Hybrid router: Pexels → Pixabay → safe fallbacks → dark frame."""
    vc = get_pexels_clip(query, dur)
    if vc:
        return vc
    vc = get_pixabay_clip(query, dur)
    if vc:
        return vc
    for fb in SAFE_FALLBACKS:
        vc = get_pixabay_clip(fb, dur)
        if vc:
            return vc
    return ColorClip(size=(CW, CH), color=(8, 8, 22)).set_duration(dur)


# ── Scene visual builder ──────────────────────────────────────────────
def build_scene_visuals(scene, voice_dur):
    """
    Builds one scene's visual sequence.
    Cuts every 2-4s (editing engine rule).
    Uses clip_sources in order, cycling if needed.
    Applies edit_style motion to each clip.
    """
    clip_sources = scene.get("clip_sources", [])
    edit_style   = scene.get("edit_style", "zoom-in")
    pacing       = scene.get("pacing", "medium")

    # Cut timing based on pacing
    cut_min = {"fast": 1.8, "medium": 2.5, "slow": 3.5}.get(pacing, 2.5)
    cut_max = {"fast": 2.8, "medium": 3.8, "slow": 5.0}.get(pacing, 3.8)

    if not clip_sources:
        clip_sources = ["pix:corporate finance money dark"]

    all_clips  = []
    base       = ColorClip(size=(CW, CH), color=(0, 0, 0)).set_duration(voice_dur)
    layers     = [base]
    t          = 0.0
    src_idx    = 0

    while t < voice_dur:
        remain   = voice_dur - t
        clip_dur = min(random.uniform(cut_min, cut_max), remain)
        if clip_dur < 0.15:
            break

        src_str  = clip_sources[src_idx % len(clip_sources)]
        src_idx += 1

        if ":" in src_str:
            src_type, src_q = src_str.split(":", 1)
        else:
            src_type, src_q = "pix", src_str
        src_type = src_type.strip().lower()
        src_q    = src_q.strip()

        clip_obj = None

        # Wiki: exact named entity with zoom
        if src_type == "wiki":
            path = get_wiki_image(src_q)
            if path:
                try:
                    clip_obj = wiki_clip(path, clip_dur, edit_style)
                except Exception as e:
                    print("  Wiki clip err: " + str(e))

        # Pex/Pix: contextual video
        if clip_obj is None:
            clip_obj = get_any_clip(src_q, clip_dur)

        # Apply zoom motion to video clips (editing engine rule)
        if clip_obj is not None and edit_style == "zoom-in":
            try:
                clip_obj = clip_obj.fx(
                    vfx.resize,
                    lambda tt, d=clip_dur: 1.0 + 0.06 * (tt / max(d, 0.001))
                )
            except Exception:
                pass

        # Clamp to segment duration
        try:
            if clip_obj.duration > clip_dur + 0.1:
                clip_obj = clip_obj.subclip(0, clip_dur)
        except Exception:
            pass

        layers.append(clip_obj.set_start(t))
        t += clip_dur

    return CompositeVideoClip(layers, size=(CW, CH)).set_duration(voice_dur)


# ══════════════════════════════════════════════════════════════════════
# MODULE 5 — CAPTION ENGINE
# 3-word sliding window. Yellow box on active word.
# Previous + next = white with black outline.
# PIL pre-renders all frames → VideoClip + alpha mask.
# Synced to exact WordBoundary ms timestamps.
# ══════════════════════════════════════════════════════════════════════
def _load_font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


FA = _load_font(88)
FO = _load_font(68)


def _meas(draw, text, font):
    try:
        bb = draw.textbbox((0, 0), text, font=font)
        return bb[2] - bb[0], bb[3] - bb[1]
    except AttributeError:
        return draw.textsize(text, font=font)


def _stroke(draw, x, y, text, font, thick=3):
    for dx in range(-thick, thick + 1):
        for dy in range(-thick, thick + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=CAP_BLK)


def render_caption(prev_w, curr_w, next_w):
    SW, SH       = 1080, 210
    PAD_X, PAD_Y = 20, 10
    RADIUS, GAP  = 14, 22
    img  = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    items = []
    if prev_w:
        items.append(("o", prev_w.upper()))
    items.append(("a", curr_w.upper()))
    if next_w:
        items.append(("o", next_w.upper()))
    fonts   = [FA if r == "a" else FO for r, _ in items]
    widths  = [_meas(draw, t, f)[0] for (_, t), f in zip(items, fonts)]
    heights = [_meas(draw, t, f)[1] for (_, t), f in zip(items, fonts)]
    bx      = PAD_X * 2 if any(r == "a" for r, _ in items) else 0
    total_w = sum(widths) + GAP * max(0, len(widths) - 1) + bx
    cx      = max(0, (SW - total_w) // 2)
    for (role, text), font, tw, th in zip(items, fonts, widths, heights):
        ty = (SH - th) // 2
        if role == "a":
            draw.rounded_rectangle(
                [cx - PAD_X, ty - PAD_Y,
                 cx + tw + PAD_X, ty + th + PAD_Y],
                radius=RADIUS, fill=CAP_BOX,
            )
            draw.text((cx, ty), text, font=font, fill=CAP_TXT)
            cx += tw + PAD_X * 2 + GAP
        else:
            _stroke(draw, cx, ty, text, font)
            draw.text((cx, ty), text, font=font, fill=CAP_WHT)
            cx += tw + GAP
    return np.array(img)


def build_caption_layer(timings, total):
    if not timings:
        return None
    CAP_Y, CAP_H = 1360, 210
    words  = [t["word"]  for t in timings]
    starts = [t["start"] for t in timings]
    ends   = [t["end"]   for t in timings]
    print("  Pre-rendering " + str(len(timings)) + " caption frames...")
    frames = [
        render_caption(
            words[i - 1] if i > 0             else None,
            words[i],
            words[i + 1] if i < len(words) - 1 else None,
        )
        for i in range(len(timings))
    ]
    blank_rgb  = np.zeros((CH, CW, 3), dtype=np.uint8)
    blank_mask = np.zeros((CH, CW),    dtype=float)

    def active(t):
        idx = bisect.bisect_right(starts, t) - 1
        if idx < 0:
            return None
        return idx if t <= ends[idx] + 0.07 else None

    def make_rgb(t):
        idx = active(t)
        if idx is None:
            return blank_rgb
        out = blank_rgb.copy()
        out[CAP_Y:CAP_Y + CAP_H, :, :] = frames[idx][:, :, :3]
        return out

    def make_mask(t):
        idx = active(t)
        if idx is None:
            return blank_mask
        m = blank_mask.copy()
        m[CAP_Y:CAP_Y + CAP_H, :] = frames[idx][:, :, 3] / 255.0
        return m

    vc = VideoClip(make_rgb,  duration=total).set_fps(FPS)
    mc = VideoClip(make_mask, duration=total, ismask=True).set_fps(FPS)
    return vc.set_mask(mc)


# ══════════════════════════════════════════════════════════════════════
# MODULE 6 — AUDIO ENGINE
# Music arc: dark tension → momentum → heavy suspense → unresolved
# SFX: bass hit at hook, whoosh at each cut, glitch on conflict
# ══════════════════════════════════════════════════════════════════════
def get_music(q, total):
    key = os.getenv("PIXABAY_API_KEY")
    if not key:
        return None
    queries = [q, "dark corporate investigation",
               "suspense cinematic thriller", "tension mystery dark background"]
    for mq in queries:
        try:
            r = requests.get(
                "https://pixabay.com/api/music/",
                params={"key": key, "q": mq, "per_page": 10},
                headers=HDR, timeout=14,
            )
            if r.status_code != 200:
                continue
            hits = r.json().get("hits", [])
            if not hits:
                continue
            random.shuffle(hits)
            for track in hits[:5]:
                url = None
                for field in ["audio", "audioURL", "url", "previewURL", "download"]:
                    url = track.get(field)
                    if url:
                        break
                if not url:
                    continue
                raw = dlb(url)
                if not raw:
                    continue
                dest = os.path.join(MUS_DIR, "bg_" + uuid.uuid4().hex[:6] + ".mp3")
                with open(dest, "wb") as f:
                    f.write(raw)
                c = AudioFileClip(dest)
                if c.duration < 2.0:
                    c.close(); continue
                loops  = int(total / c.duration) + 2
                looped = concatenate_audioclips([c] * loops)
                music  = looped.subclip(0, total).volumex(0.055)
                print("Music: " + str(round(music.duration, 1)) + "s")
                return music
        except Exception as e:
            print("Music err: " + str(e))
    return None


def get_sfx(q):
    key = os.getenv("PIXABAY_API_KEY")
    if not key:
        return None
    for sq in [q, "dramatic impact bass hit", "whoosh transition", "cinematic sting"]:
        try:
            r = requests.get(
                "https://pixabay.com/api/sounds/",
                params={"key": key, "q": sq, "per_page": 10},
                headers=HDR, timeout=12,
            )
            if r.status_code != 200:
                continue
            hits = r.json().get("hits", [])
            if not hits:
                continue
            info = random.choice(hits)
            url  = None
            for field in ["audio", "audioURL", "url", "previewURL", "download"]:
                url = info.get(field)
                if url:
                    break
            if not url:
                continue
            raw = dlb(url)
            if not raw:
                continue
            dest = os.path.join(MUS_DIR, "sfx_" + uuid.uuid4().hex[:6] + ".mp3")
            with open(dest, "wb") as f:
                f.write(raw)
            print("SFX: " + sq)
            return dest
        except Exception as e:
            print("SFX err: " + str(e))
    return None


# ══════════════════════════════════════════════════════════════════════
# MODULE 7 — BRAND WATERMARK
# ══════════════════════════════════════════════════════════════════════
def make_brand_watermark(channel_name, total):
    W, H  = 440, 76
    img   = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw  = ImageDraw.Draw(img)
    font  = None
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]:
        if os.path.exists(p):
            try:
                font = ImageFont.truetype(p, 34); break
            except Exception:
                continue
    if not font:
        font = ImageFont.load_default()
    draw.ellipse([12, 20, 44, 52], fill=(210, 25, 25, 230))
    draw.text((56, 18), channel_name.upper(), font=font, fill=(255, 255, 255, 185))
    dest = os.path.join(CLIPS_DIR, "brand.png")
    img.save(dest, "PNG")
    return (ImageClip(dest)
            .set_duration(total)
            .set_position((CW - W - 18, 46))
            .set_opacity(0.80))


# ══════════════════════════════════════════════════════════════════════
# MODULE 8 — YOUTUBE UPLOAD
# ══════════════════════════════════════════════════════════════════════
def upload_youtube(path, seo):
    rt = os.getenv("YT_REFRESH_TOKEN")
    ci = os.getenv("YT_CLIENT_ID")
    cs = os.getenv("YT_CLIENT_SECRET")
    if not all([rt, ci, cs]):
        print("YouTube creds missing — saved at: " + path)
        return
    print("Uploading: " + seo["final_title"])
    try:
        creds = Credentials(
            token=None, refresh_token=rt,
            client_id=ci, client_secret=cs,
            token_uri="https://oauth2.googleapis.com/token",
        )
        yt   = build("youtube", "v3", credentials=creds)
        body = {
            "snippet": {
                "title":       seo["final_title"],
                "description": seo["description"],
                "categoryId":  "27",
                "tags":        seo.get("tags", [])[:30],
            },
            "status": {
                "privacyStatus":           "public",
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(path, chunksize=-1, resumable=True)
        res   = yt.videos().insert(
            part="snippet,status", body=body, media_body=media
        ).execute()
        print("LIVE: https://youtube.com/shorts/" + res.get("id", "?"))
        alt = seo.get("alt_titles", [])
        if alt:
            print("A/B TEST THESE TITLES:")
            for t in alt:
                print("  > " + t)
    except Exception as e:
        print("Upload err: " + str(e))


# ══════════════════════════════════════════════════════════════════════
# POSTED LOG
# ══════════════════════════════════════════════════════════════════════
def was_posted(title):
    if not os.path.exists(LOG_FILE):
        return False
    with open(LOG_FILE) as f:
        return title in f.read()


def mark_posted(title):
    with open(LOG_FILE, "a") as f:
        f.write(datetime.now().isoformat() + " | " + title + "\n")


# ══════════════════════════════════════════════════════════════════════
# CHANNEL GROWTH PRINTER
# ══════════════════════════════════════════════════════════════════════
def print_growth_guide(data):
    cg = data.get("channel_growth", {})
    sc = data.get("viral_scorecard", {})
    shorts = data.get("shorts_version", {})
    edit   = data.get("editing_blueprint", {})

    print("\n" + "=" * 60)
    print("  CHANNEL GROWTH ENGINE")
    print("=" * 60)
    print("UPLOAD FREQUENCY: " + cg.get("upload_frequency", "1/day"))
    print("BINGE STRATEGY:   " + cg.get("binge_strategy", ""))
    print("")
    print("NEXT 10 TOPICS TO PRODUCE:")
    for i, t in enumerate(cg.get("next_10_topics", [])[:10], 1):
        print("  " + str(i) + ". " + t)
    print("")
    print("EDITING BLUEPRINT:")
    print("  Cut every:       " + edit.get("cut_frequency", "2-4 seconds"))
    print("  Zoom rule:       " + edit.get("zoom_rule", ""))
    print("  Music arc:       " + edit.get("music_arc", ""))
    print("")
    print("SHORTS VERSION (45s):")
    print("  Hook: " + shorts.get("hook_line", ""))
    print("")
    print("VIRAL SCORECARD:")
    print("  CTR:       " + str(sc.get("ctr", "?")) + "/10")
    print("  Retention: " + str(sc.get("retention", "?")) + "/10")
    print("  Size:      " + str(sc.get("topic_size", "?")) + "/10")
    print("  Verdict:   " + sc.get("verdict", ""))
    print("  Breakout:  " + sc.get("breakout_scenario", ""))
    print("")
    print("BRUTAL TRUTH: " + data.get("brutal_honest_advice", ""))
    print("=" * 60 + "\n")


# ══════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════
async def run():
    print("\n" + "=" * 60)
    print("  VIRAL DOCUMENTARY ENGINE  v9.0")
    print("  Voice: " + VOICE_NAME + "  Rate: " + VOICE_RATE + "  Vol: " + VOICE_VOLUME)
    print("=" * 60 + "\n")

    validate_env()
    boot()

    # ── 1. Trend ────────────────────────────────────────────────────
    raw_trend = get_trend()

    # ── 2. Full production package from Gemini ──────────────────────
    prod = run_production_engine(raw_trend)
    if prod is None:
        print("Gemini failed — using fallback production package.")
        prod = fallback_production(raw_trend)

    scenes = prod.get("scenes", [])
    if not scenes:
        print("No scenes generated. Exiting.")
        sys.exit(1)

    seo       = prod.get("seo", {})
    final_title = seo.get("final_title", "Financial Expose")

    # Check duplicate
    if was_posted(final_title):
        print("Already posted: " + final_title + " — getting new trend.")
        raw_trend   = get_trend()
        prod        = run_production_engine(raw_trend) or fallback_production(raw_trend)
        scenes      = prod.get("scenes", [])
        seo         = prod.get("seo", {})
        final_title = seo.get("final_title", "Financial Expose")

    # ── 3. Print growth guide (channel strategy) ────────────────────
    print_growth_guide(prod)

    # ── 4. Generate per-scene voices (Christopher Neural +8% +10%) ──
    print("[VOICE ENGINE] Christopher Neural +8% +10%")
    voice_results = await build_all_voices(scenes, SCENE_DIR)
    total_dur     = sum(vr["duration"] for vr in voice_results)
    print("Total audio: " + str(round(total_dur, 1)) + "s\n")

    # ── 5. Download audio assets ────────────────────────────────────
    print("[AUDIO ENGINE]")
    music_q = prod.get("voiceover_guide", {}).get("voice", "dark corporate suspense")
    bgm     = get_music("dark corporate suspense", total_dur)
    sfx_p   = get_sfx("dramatic bass impact sting")
    sfx_c   = None
    if sfx_p:
        try:
            sfx_c = AudioFileClip(sfx_p).set_start(0.15).volumex(0.30)
        except Exception as e:
            print("SFX load err: " + str(e))

    # ── 6. Build word-synced visuals per scene ──────────────────────
    print("\n[VISUAL ENGINE] Building word-synced scene visuals...")
    scene_clips        = []
    global_timings     = []
    time_offset        = 0.0

    for vr in voice_results:
        scene   = vr["scene"]
        timings = vr["timings"]
        dur     = vr["duration"]
        sid     = scene.get("id", "?")

        print("\n  SCENE " + str(sid) + " [" + scene.get("emotion", "?").upper() +
              "] " + str(round(dur, 1)) + "s")
        print("  Edit: " + scene.get("edit_style", "zoom-in") +
              "  Pacing: " + scene.get("pacing", "medium"))

        vis = build_scene_visuals(scene, dur)
        scene_clips.append(vis.set_start(time_offset))

        for t in timings:
            global_timings.append({
                "word":     t["word"],
                "start":    t["start"] + time_offset,
                "end":      t["end"]   + time_offset,
                "duration": t["duration"],
            })

        time_offset += dur

    # ── 7. Concatenate all scene audio ──────────────────────────────
    print("\n[AUDIO STITCH]")
    voice_clips  = [AudioFileClip(vr["voice"]) for vr in voice_results]
    final_voice  = concatenate_audioclips(voice_clips)
    audio_layers = [final_voice]
    if bgm:
        audio_layers.append(bgm)
    if sfx_c:
        audio_layers.append(sfx_c)
    final_audio  = (CompositeAudioClip(audio_layers)
                    if len(audio_layers) > 1 else final_voice)

    # ── 8. Caption layer (global, ms-accurate) ──────────────────────
    print("\n[CAPTION ENGINE]")
    cap_layer = build_caption_layer(global_timings, total_dur)

    # ── 9. Brand watermark ──────────────────────────────────────────
    channel = os.getenv("CHANNEL_NAME", "THE EXPOSE")
    brand   = make_brand_watermark(channel, total_dur)

    # ── 10. Composite ───────────────────────────────────────────────
    print("\n[COMPOSITE]")
    base   = ColorClip(size=(CW, CH), color=(0, 0, 0)).set_duration(total_dur)
    layers = [base] + scene_clips
    if cap_layer is not None:
        layers.append(cap_layer)
    layers.append(brand)

    final_video = (
        CompositeVideoClip(layers, size=(CW, CH))
        .set_duration(total_dur)
        .set_audio(final_audio)
    )

    # ── 11. Render ──────────────────────────────────────────────────
    out_path = os.path.join(OUT_DIR, "final_reel.mp4")
    print("\n[RENDER] " + str(round(total_dur, 1)) + "s @ " + str(FPS) + "fps")
    final_video.write_videofile(
        out_path, fps=FPS, codec="libx264",
        audio_codec="aac", threads=4, preset="fast",
    )
    mb = os.path.getsize(out_path) / (1024 * 1024)
    print("FILE: " + out_path + " (" + str(round(mb, 1)) + " MB)")

    # ── 12. Mark + upload ───────────────────────────────────────────
    mark_posted(final_title)
    upload_youtube(out_path, seo)

    # ── 13. Final production summary ────────────────────────────────
    print("\n" + "=" * 60)
    print("  PRODUCTION COMPLETE")
    print("=" * 60)
    print("TITLE:     " + final_title)
    print("DURATION:  " + str(round(total_dur, 1)) + "s")
    print("SCENES:    " + str(len(scenes)))
    print("FILE:      " + out_path)
    print("")
    alt = seo.get("alt_titles", [])
    if alt:
        print("A/B TEST TITLES:")
        for a in alt:
            print("  > " + a)
    print("")
    thumb = (prod.get("thumbnail_concepts") or [{}])[0]
    print("THUMBNAIL BRIEF:")
    print("  CONCEPT: " + thumb.get("concept", ""))
    print("  TEXT:    " + thumb.get("text_overlay", ""))
    print("  EMOTION: " + thumb.get("emotion_trigger", ""))
    print("")
    print("SEO CHAPTERS:")
    for ch in seo.get("chapters", [])[:6]:
        print("  " + ch)
    print("=" * 60 + "\n")

    return out_path


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception:
        traceback.print_exc()
        sys.exit(1)
