"""
╔══════════════════════════════════════════════════════════════════════╗
║  VIRAL FINANCIAL EXPOSE ENGINE — main.py  v8.0                     ║
║  Full cinematic documentary pipeline                                ║
║                                                                      ║
║  PIPELINE:                                                           ║
║    1. Viral Topic Engine    → 3 title rewrites                      ║
║    2. Thumbnail Engine      → concept + text overlay                ║
║    3. Story Engine          → scene-by-scene with retention arcs    ║
║    4. Voice Engine          → per-scene MP3 files (WordBoundary)    ║
║    5. Visual Engine         → Pexels + Pixabay + Wikimedia          ║
║    6. Editing Engine        → zoom, transitions, SFX every cut      ║
║    7. SEO Engine            → 3 titles, description, 15 hashtags    ║
║    8. Upload                → YouTube Shorts                        ║
║                                                                      ║
║  ENV:                                                                ║
║    GEMINI_API_KEY, PIXABAY_API_KEY, PEXELS_API_KEY                 ║
║    NEWSAPI_KEY, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN   ║
║    CHANNEL_NAME  (default: "THE EXPOSE")                            ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os, sys, re, json, random, asyncio, uuid, shutil, io, bisect
import traceback, math, time
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
    VideoFileClip, concatenate_audioclips, concatenate_videoclips,
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
# CONFIG
# ══════════════════════════════════════════════════════════════════════
OUT      = "output"
SCENE_D  = "output/scenes"      # per-scene voice + video files
CLIPS_D  = "output/clips"
MUS_D    = "output/music"
LOG_F    = "output/posted.log"

CW, CH   = 1080, 1920
FPS      = 30
VOICE_M  = "en-US-ChristopherNeural"   # deep documentary tone
VOICE_R  = "+4%"
MIN_CLIP = 1.8        # minimum clip duration seconds

# Caption palette
CAP_BOX  = (255, 214,   0, 248)
CAP_TXT  = (  0,   0,   0, 255)
CAP_WHT  = (255, 255, 255, 255)
CAP_BLK  = (  0,   0,   0, 210)

HDR      = {"User-Agent": "ViralEngine/8.0 (research-bot; contact@example.com)"}
WIKI_URL = "https://commons.wikimedia.org/w/api.php"
SKIP_EXT = {
    "svg","ogg","ogv","pdf","webm","mp4","xcf",
    "djvu","flac","mid","wav","opus","mov","avi","tif","tiff",
}

USED_CLIP_IDS: set = set()
WIKI_CACHE:   dict = {}


# ══════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════
def validate_env():
    must = ["GEMINI_API_KEY", "PIXABAY_API_KEY"]
    bad  = [k for k in must if not os.getenv(k)]
    if bad:
        for b in bad:
            print("MISSING KEY: " + b)
        sys.exit(1)
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    print("ENV OK.")


def boot():
    global USED_CLIP_IDS, WIKI_CACHE
    USED_CLIP_IDS = set()
    WIKI_CACHE    = {}
    for d in [OUT, SCENE_D, CLIPS_D, MUS_D, OUT + "/tmp"]:
        os.makedirs(d, exist_ok=True)
    print("Workspace ready.")


# ══════════════════════════════════════════════════════════════════════
# HTTP HELPERS
# ══════════════════════════════════════════════════════════════════════
def jget(url, params=None, headers=None, timeout=14):
    try:
        h = dict(HDR)
        if headers:
            h.update(headers)
        r = requests.get(url, params=params, headers=h, timeout=timeout)
        if r.status_code != 200:
            return None
        t = r.text.strip()
        if not t or t[0] not in ("{", "["):
            return None
        return r.json()
    except Exception:
        return None


def dlb(url, timeout=40):
    try:
        r = requests.get(url, headers=HDR, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 512:
            return r.content
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════
# MODULE 1 — TRENDING TOPIC DISCOVERY
# ══════════════════════════════════════════════════════════════════════
FALLBACK_TRENDS = [
    "Nvidia just filed a patent that gives AI systems the ability to override human decisions without approval",
    "The Federal Reserve quietly changed reserve requirements while nobody was watching",
    "Apple's privacy update destroyed Meta's ad business while Apple's own ad revenue grew 238 percent",
    "Amazon warehouse AI fires workers automatically for being six seconds too slow",
    "Sam Altman's Worldcoin has now scanned the irises of five million people and nobody asked why",
    "BlackRock AI named Aladdin now manages 21 trillion dollars more than the US GDP",
    "TikTok algorithm internally called Targeting Accuracy predicts pregnancy before the mother knows",
    "Goldman Sachs internal emails called the mortgages they sold your pension fund a bad deal",
    "Boeing stock buybacks totaling 43 billion dollars happened same years 346 people died in crashes",
    "Purdue Pharma paid 18000 doctors to prescribe OxyContin as safer than aspirin",
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
                kws = ["billion", "trillion", "ceo", "fraud", "reserve",
                       "apple", "google", "amazon", "nvidia", "tesla",
                       "bank", "crypto", "debt", "layoff", "antitrust"]
                for art in d.get("articles", []):
                    combo = (art.get("title", "") + " " +
                             art.get("description", "")).lower()
                    if any(k in combo for k in kws):
                        headline = art.get("title", "")
                        desc     = art.get("description", "") or ""
                        print("TREND: " + headline)
                        return headline + ". " + desc
        except Exception as e:
            print("NewsAPI err: " + str(e))

    trend = random.choice(FALLBACK_TRENDS)
    print("FALLBACK TREND: " + trend)
    return trend


# ══════════════════════════════════════════════════════════════════════
# MODULE 2 — VIRAL TOPIC ENGINE
# Converts raw trend into 3 viral title options + selects the best.
# Rules: conflict, power, transformation, unanswered curiosity.
# ══════════════════════════════════════════════════════════════════════
VIRAL_TITLE_PROMPT = """
You are a viral YouTube title engineer. Your titles average 8%+ CTR.

Given a trending financial/tech topic, generate 3 viral title options.
Rules for each title:
- Must include conflict, power, OR transformation
- Must create unanswered curiosity (viewer MUST click to find out)
- Must include a named entity (CEO name, company, dollar amount)
- Max 60 characters
- Never neutral language — every word must carry weight
- Formats that work: "The X That Y", "How X Secretly Y", "X Just Y And Nobody Noticed"

Also generate:
- thumbnail_concept: one sentence describing the visual contrast (e.g. "JPMorgan logo cracking vs citizen running")
- thumbnail_text: 3-5 word overlay text (e.g. "THEY KNEW." or "$47 BILLION MISSING")
- hook: single sentence (max 12 words) that is the first thing spoken — must create immediate paranoia or shock
- best_title_index: 0, 1, or 2 — which title is most viral

Output ONLY valid JSON, no markdown:
{
  "titles": ["title1", "title2", "title3"],
  "best_title_index": 0,
  "thumbnail_concept": "...",
  "thumbnail_text": "...",
  "hook": "..."
}
"""


def run_viral_topic_engine(raw_trend):
    try:
        model  = genai.GenerativeModel("gemini-1.5-pro")
        prompt = "TRENDING TOPIC:\n" + raw_trend + "\n\nGenerate viral titles for this."
        resp   = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.9),
            system_instruction=VIRAL_TITLE_PROMPT,
        )
        text = re.sub(r"^```[a-z]*\n?", "", resp.text.strip())
        text = re.sub(r"\n?```$", "", text)
        data = json.loads(text)
        print("\n--- VIRAL TITLE OPTIONS ---")
        for i, t in enumerate(data.get("titles", [])):
            star = " ← SELECTED" if i == data.get("best_title_index", 0) else ""
            print("  [" + str(i) + "] " + t + star)
        print("  HOOK: " + data.get("hook", ""))
        print("  THUMBNAIL: " + data.get("thumbnail_text", ""))
        print("---------------------------\n")
        return data
    except Exception as e:
        print("Viral title engine err: " + str(e))
        return {
            "titles": [raw_trend[:60]],
            "best_title_index": 0,
            "thumbnail_concept": "Dark corporate logo vs broken chain",
            "thumbnail_text": "THEY LIED.",
            "hook": "What they did next will make your blood run cold.",
        }


# ══════════════════════════════════════════════════════════════════════
# MODULE 3 — STORY ENGINE
# Generates scene-by-scene breakdown with retention psychology:
#   - Curiosity gap every 10-15s
#   - Retention trigger line in each scene
#   - Delayed payoff — never explain immediately
#   - Story arc: Hook → Setup → Rise → Conflict → Turn → Cliffhanger
# ══════════════════════════════════════════════════════════════════════
STORY_PROMPT = """
You are an elite viral documentary scriptwriter. Your videos average 72% retention.

STORY STRUCTURE (MANDATORY):
- Scene 1 (0-10s):  SHOCK HOOK — no explanation. Drop a bombshell claim.
- Scene 2 (10-40s): IDENTITY + SETUP — who, what, name the enemy
- Scene 3 (40-90s): RISE — how big/powerful they became
- Scene 4 (90-180s): CONFLICT — what they did wrong. Specific. Named. Numbered.
- Scene 5 (180-240s): TURNING POINT — exposure, consequences, stakes
- Scene 6 (240-end): CLIFFHANGER — unanswered question. "And it gets worse."

RETENTION RULES (NON-NEGOTIABLE):
- Every scene must end with an UNRESOLVED statement or question
- Every 10-15 seconds insert a curiosity gap phrase
- NEVER fully explain something in the same sentence you introduce it
- Use DELAY: "But here is the part they don't want you to know..."
- Keep viewer off-balance. Alternate shock → pause → bigger shock.
- Short sentences. Max 10 words. Punchy. No filler.

SCENE FORMAT: Each scene needs:
- narration: the voiceover text (short punchy sentences, pause-friendly)
- emotion: hook / setup / rise / conflict / turning_point / cliffhanger
- visual_keywords: list of 3 specific search terms (human faces first, then real-world, then symbolic)
- clip_sources: list of "wiki:X" or "pix:X" for each visual keyword
- edit_style: zoom-in / glitch / cinematic_pan / slow_motion / hard_cut
- retention_trigger: the line that creates the curiosity gap (spoken at scene end)
- pacing: fast / medium / slow

OUTPUT ONLY valid JSON, no markdown:
{
  "scenes": [
    {
      "id": 1,
      "duration_hint": "0:00-0:10",
      "narration": "...",
      "emotion": "hook",
      "visual_keywords": ["keyword1", "keyword2", "keyword3"],
      "clip_sources": ["wiki:query", "pix:query", "pix:query"],
      "edit_style": "zoom-in",
      "retention_trigger": "...",
      "pacing": "fast"
    }
  ],
  "yt_tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "description_hook": "Two sentence description that teases without revealing"
}
"""


def run_story_engine(raw_trend, viral_data):
    title = viral_data["titles"][viral_data["best_title_index"]]
    hook  = viral_data["hook"]
    try:
        model  = genai.GenerativeModel("gemini-1.5-pro")
        prompt = (
            "TITLE: " + title + "\n"
            + "HOOK: " + hook + "\n"
            + "TOPIC: " + raw_trend + "\n\n"
            + "Generate the full scene breakdown for this viral documentary short (60-90 seconds total). "
            + "Use 6-8 scenes. Each scene narration: 15-25 words. "
            + "Include specific CEO names, dollar amounts, percentages — real data makes it credible. "
            + "Inject retention triggers that make the viewer feel they cannot leave."
        )
        resp = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.85),
            system_instruction=STORY_PROMPT,
        )
        text = re.sub(r"^```[a-z]*\n?", "", resp.text.strip())
        text = re.sub(r"\n?```$", "", text)
        data = json.loads(text)
        scenes = data.get("scenes", [])
        print("Story engine: " + str(len(scenes)) + " scenes generated.")
        for s in scenes:
            print("  Scene " + str(s["id"]) + " [" + s["emotion"] + "]: " + s["narration"][:60] + "...")
        return data
    except Exception as e:
        print("Story engine err: " + str(e))
        # Minimal fallback
        return {
            "scenes": [
                {
                    "id": 1,
                    "duration_hint": "0:00-0:12",
                    "narration": hook + " And almost no one noticed.",
                    "emotion": "hook",
                    "visual_keywords": ["corporate CEO", "money cash", "dark office"],
                    "clip_sources": ["pix:corporate CEO portrait", "pix:money cash finance", "pix:dark office corporate"],
                    "edit_style": "zoom-in",
                    "retention_trigger": "But this is only the beginning.",
                    "pacing": "fast",
                },
                {
                    "id": 2,
                    "duration_hint": "0:12-0:35",
                    "narration": raw_trend[:120] + ".",
                    "emotion": "conflict",
                    "visual_keywords": ["wall street", "data server", "government building"],
                    "clip_sources": ["pix:wall street finance", "pix:data server technology", "pix:government building politics"],
                    "edit_style": "cinematic_pan",
                    "retention_trigger": "And it gets worse.",
                    "pacing": "medium",
                },
                {
                    "id": 3,
                    "duration_hint": "0:35-0:60",
                    "narration": "This affects every single American. Every single day. And they are counting on you not knowing.",
                    "emotion": "cliffhanger",
                    "visual_keywords": ["american family", "money disappearing", "corporate profit"],
                    "clip_sources": ["pix:american street people", "pix:money loss finance", "pix:corporate profit chart"],
                    "edit_style": "slow_motion",
                    "retention_trigger": "Follow for what happens next.",
                    "pacing": "slow",
                },
            ],
            "yt_tags": ["finance", "expose", "secrets", "corporate", "usa"],
            "description_hook": "What they did is fully legal. That is the terrifying part.",
        }


# ══════════════════════════════════════════════════════════════════════
# MODULE 4 — VOICE ENGINE (PER-SCENE)
# Each scene = separate MP3 + WordBoundary timings.
# Scene-based voice allows perfect clip sync and re-renders.
# ══════════════════════════════════════════════════════════════════════
async def generate_scene_voice(scene_text, scene_id, out_dir):
    out_path = os.path.join(out_dir, "scene_" + str(scene_id) + "_voice.mp3")
    timings  = []
    com      = edge_tts.Communicate(scene_text, VOICE_M, rate=VOICE_R)

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
                timings.append({"word": w, "start": s,
                                 "end": s + d, "duration": d})

    # Even-split fallback
    if not timings:
        ac   = AudioFileClip(out_path)
        dur  = ac.duration
        ac.close()
        words = [w for w in scene_text.split() if w]
        per   = dur / max(len(words), 1)
        timings = [
            {"word": w, "start": i * per, "end": (i + 1) * per, "duration": per}
            for i, w in enumerate(words)
        ]

    ac    = AudioFileClip(out_path)
    total = ac.duration
    ac.close()
    return out_path, timings, total


async def generate_all_voices(scenes, out_dir):
    results = []
    for scene in scenes:
        sid  = scene["id"]
        text = scene["narration"] + " " + scene.get("retention_trigger", "")
        path, timings, dur = await generate_scene_voice(text, sid, out_dir)
        results.append({
            "scene":   scene,
            "voice":   path,
            "timings": timings,
            "duration": dur,
        })
        print("Voice scene " + str(sid) + ": " + str(round(dur, 1)) + "s")
    return results


# ══════════════════════════════════════════════════════════════════════
# MODULE 5 — VISUAL ENGINE
# Priority: human emotion > real-world business > symbolic > abstract
# Wikimedia for exact named entities (CEO faces, HQs, products)
# Pixabay/Pexels for relatable contextual clips
# ══════════════════════════════════════════════════════════════════════

# ── Wikimedia ─────────────────────────────────────────────────────────
def _wiki_search(q, limit=25):
    d = jget(WIKI_URL, {
        "action": "query", "format": "json",
        "generator": "search",
        "gsrsearch": "filetype:bitmap " + q,
        "gsrlimit": limit, "prop": "imageinfo",
        "iiprop": "url|mime|size", "iilimit": 1, "gsrnamespace": 6,
    })
    if not d:
        return []
    return list(d.get("query", {}).get("pages", {}).values())


def _pick_wiki_url(pages):
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


def grade_image(img):
    """Cinematic color grade: desaturate, darken, boost contrast."""
    img = img.convert("RGB")
    img = ImageEnhance.Color(img).enhance(0.80)
    img = ImageEnhance.Brightness(img).enhance(0.85)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    return img


def add_vignette(img):
    w, h = img.size
    mask = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(mask)
    for i in range(50):
        v = int(255 * (i / 50) ** 1.6)
        draw.rectangle([i, i, w - i, h - i], outline=v)
    mask  = mask.filter(ImageFilter.GaussianBlur(radius=w // 5))
    black = Image.new("RGB", (w, h), (0, 0, 0))
    img   = img.convert("RGB")
    return Image.composite(img, black, mask)


def cover_crop(img):
    iw, ih = img.size
    scale  = max(CW / iw, CH / ih)
    nw     = max(int(iw * scale), CW)
    nh     = max(int(ih * scale), CH)
    img    = img.resize((nw, nh), Image.LANCZOS)
    x0, y0 = (nw - CW) // 2, (nh - CH) // 2
    return img.crop((x0, y0, x0 + CW, y0 + CH))


def get_wiki_image(query):
    if query in WIKI_CACHE:
        return WIKI_CACHE[query]

    attempts = [query, query + " photo", query + " portrait"]
    seen, unique = set(), []
    for a in attempts:
        a = a.strip()
        if a and a not in seen:
            seen.add(a); unique.append(a)

    for attempt in unique:
        pages = _wiki_search(attempt)
        url   = _pick_wiki_url(pages)
        if not url:
            continue
        raw = dlb(url)
        if not raw:
            continue
        try:
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            if img.width < 80 or img.height < 80:
                continue
            img  = cover_crop(img)
            img  = grade_image(img)
            img  = add_vignette(img)
            dest = os.path.join(CLIPS_D, "wiki_" + uuid.uuid4().hex[:7] + ".jpg")
            img.save(dest, "JPEG", quality=92)
            WIKI_CACHE[query] = dest
            print("  Wiki OK: " + query)
            return dest
        except Exception as e:
            print("  Wiki err (" + attempt + "): " + str(e))

    WIKI_CACHE[query] = None
    print("  Wiki miss: " + query)
    return None


def wiki_to_clip(path, dur, edit_style="zoom-in"):
    """Convert a Wikimedia image to a MoviePy clip with motion."""
    c = ImageClip(path).set_duration(dur)
    if edit_style == "zoom-in":
        c = c.fx(vfx.resize, lambda t: 1.0 + 0.09 * (t / max(dur, 0.001)))
    elif edit_style == "slow_motion":
        c = c.fx(vfx.resize, lambda t: 1.0 + 0.04 * (t / max(dur, 0.001)))
    c = c.set_position("center")
    return c


# ── Pexels ────────────────────────────────────────────────────────────
def get_pexels_video(query, dur):
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
            if vid_id and vid_id in USED_CLIP_IDS:
                continue
            files = hit.get("video_files", [])
            # Prefer HD portrait
            files = sorted(files, key=lambda x: x.get("height", 0), reverse=True)
            for vf in files:
                if vf.get("quality") in ("hd", "sd") and vf.get("link"):
                    raw = dlb(vf["link"])
                    if not raw:
                        continue
                    dest = os.path.join(CLIPS_D, "pex_" + uuid.uuid4().hex[:7] + ".mp4")
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
                    USED_CLIP_IDS.add(vid_id)
                    print("  Pexels OK: " + query)
                    return sub
    except Exception as e:
        print("  Pexels err (" + query + "): " + str(e))
    return None


# ── Pixabay ───────────────────────────────────────────────────────────
SAFE_FALLBACKS = [
    "money cash dollar bills",
    "corporate building exterior finance",
    "wall street stock exchange",
    "government politics building",
    "data server technology",
    "city skyline architecture",
    "finance chart graph",
    "gold money wealth",
    "bank building exterior",
]


def get_pixabay_video(query, dur):
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
        if hid and hid in USED_CLIP_IDS:
            continue
        vs   = hit.get("videos", {})
        info = vs.get("medium") or vs.get("small") or vs.get("large") or vs.get("tiny")
        if not info or not info.get("url"):
            continue
        try:
            raw = dlb(info["url"])
            if not raw:
                continue
            dest = os.path.join(CLIPS_D, "pix_" + uuid.uuid4().hex[:7] + ".mp4")
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
                USED_CLIP_IDS.add(hid)
            print("  Pixabay OK: " + query)
            return sub
        except Exception as e:
            print("  Pixabay err (" + query + "): " + str(e))
    return None


def get_any_video(query, dur):
    """Priority: Pexels → Pixabay → Pixabay fallbacks → dark frame."""
    vc = get_pexels_video(query, dur)
    if vc:
        return vc
    vc = get_pixabay_video(query, dur)
    if vc:
        return vc
    for fb in SAFE_FALLBACKS:
        vc = get_pixabay_video(fb, dur)
        if vc:
            return vc
    return ColorClip(size=(CW, CH), color=(8, 8, 22)).set_duration(dur)


# ── Per-scene visual builder ──────────────────────────────────────────
def build_scene_visuals(scene, voice_dur):
    """
    Build the visual clip sequence for one scene.
    Uses clip_sources from Gemini output.
    Falls back to visual_keywords if clip_sources fails.
    Each sub-clip is MIN_CLIP to 4s, rotating through sources.
    Returns a single composite clip for this scene.
    """
    clip_sources = scene.get("clip_sources", [])
    visual_kws   = scene.get("visual_keywords", [])
    edit_style   = scene.get("edit_style", "zoom-in")

    # Merge sources: clip_sources first, then visual_keywords as pix
    all_sources = list(clip_sources)
    for kw in visual_kws:
        src = "pix:" + kw
        if src not in all_sources:
            all_sources.append(src)

    if not all_sources:
        all_sources = ["pix:corporate finance money"]

    # Black base
    base     = ColorClip(size=(CW, CH), color=(0, 0, 0)).set_duration(voice_dur)
    layers   = [base]
    t        = 0.0
    src_idx  = 0

    while t < voice_dur:
        remain   = voice_dur - t
        clip_dur = min(max(MIN_CLIP, random.uniform(2.0, 3.5)), remain)
        if clip_dur < 0.2:
            break

        src_str = all_sources[src_idx % len(all_sources)]
        src_idx += 1

        if ":" in src_str:
            src_type, src_q = src_str.split(":", 1)
        else:
            src_type, src_q = "pix", src_str
        src_type = src_type.strip().lower()
        src_q    = src_q.strip()

        clip_obj = None

        if src_type == "wiki":
            path = get_wiki_image(src_q)
            if path:
                try:
                    clip_obj = wiki_to_clip(path, clip_dur, edit_style)
                except Exception as e:
                    print("  Wiki clip err: " + str(e))

        if clip_obj is None:
            clip_obj = get_any_video(src_q, clip_dur)

        if clip_obj is not None:
            # Apply edit style motion to video clips too
            if edit_style == "zoom-in" and hasattr(clip_obj, "resize"):
                try:
                    clip_obj = clip_obj.fx(
                        vfx.resize,
                        lambda tt, d=clip_dur: 1.0 + 0.06 * (tt / max(d, 0.001))
                    )
                except Exception:
                    pass

            # Clamp to clip_dur
            try:
                if clip_obj.duration > clip_dur + 0.1:
                    clip_obj = clip_obj.subclip(0, clip_dur)
            except Exception:
                pass

            layers.append(clip_obj.set_start(t))

        t += clip_dur

    return CompositeVideoClip(layers, size=(CW, CH)).set_duration(voice_dur)


# ══════════════════════════════════════════════════════════════════════
# MODULE 6 — CAPTION ENGINE (per-scene, word-level sync)
# Yellow box on active word. 3-word sliding window.
# PIL pre-renders → VideoClip + alpha mask.
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


def render_cap(prev_w, curr_w, next_w):
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
                [cx - PAD_X, ty - PAD_Y, cx + tw + PAD_X, ty + th + PAD_Y],
                radius=RADIUS, fill=CAP_BOX,
            )
            draw.text((cx, ty), text, font=font, fill=CAP_TXT)
            cx += tw + PAD_X * 2 + GAP
        else:
            _stroke(draw, cx, ty, text, font, thick=3)
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
    frames = [
        render_cap(
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
# MODULE 7 — AUDIO ENGINE
# Background music + per-scene SFX whoosh on transitions
# ══════════════════════════════════════════════════════════════════════
def get_music(q, total):
    key = os.getenv("PIXABAY_API_KEY")
    if not key:
        return None
    queries = [q, "dark corporate investigation",
               "suspense cinematic thriller", "tension mystery"]
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
                dest = os.path.join(MUS_D, "bg_" + uuid.uuid4().hex[:6] + ".mp3")
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
    for sq in [q, "dramatic impact", "whoosh transition", "cinematic sting"]:
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
            dest = os.path.join(MUS_D, "sfx_" + uuid.uuid4().hex[:6] + ".mp3")
            with open(dest, "wb") as f:
                f.write(raw)
            print("SFX: " + sq)
            return dest
        except Exception as e:
            print("SFX err: " + str(e))
    return None


def get_whoosh():
    """Short whoosh SFX for scene transitions."""
    return get_sfx("whoosh transition short")


# ══════════════════════════════════════════════════════════════════════
# MODULE 8 — BRAND WATERMARK
# Channel name top-right. Subtle but persistent.
# ══════════════════════════════════════════════════════════════════════
def make_brand_watermark(channel_name, total):
    W, H  = 440, 78
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
                font = ImageFont.truetype(p, 34)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()
    # Red dot + name
    draw.ellipse([12, 20, 44, 52], fill=(210, 25, 25, 230))
    draw.text((56, 18), channel_name.upper(), font=font, fill=(255, 255, 255, 190))
    dest = os.path.join(CLIPS_D, "brand.png")
    img.save(dest, "PNG")
    return (ImageClip(dest)
            .set_duration(total)
            .set_position((CW - W - 18, 46))
            .set_opacity(0.82))


# ══════════════════════════════════════════════════════════════════════
# MODULE 9 — SEO ENGINE
# 3 CTR-optimised titles + description + 15 hashtags + keyword cluster
# ══════════════════════════════════════════════════════════════════════
SEO_HASHTAGS = [
    "#FinancialFreedom", "#WealthMindset", "#CorporateSecrets",
    "#ConsumerAwareness", "#MoneyHacks2026", "#WallStreetSecrets",
    "#InflationAlert", "#EconomicReality", "#HiddenTruths",
    "#SmartInvesting", "#AmericanEconomy", "#BillionaireMindset",
    "#FinancialLiteracy", "#TruthSeeker", "#ShortsFeed",
]


def build_seo_pack(viral_data, story_data, raw_trend):
    titles     = viral_data.get("titles", ["Financial Expose"])
    best_idx   = viral_data.get("best_title_index", 0)
    best_title = titles[best_idx]
    desc_hook  = story_data.get("description_hook", "The truth they hoped you would never find.")
    yt_tags    = story_data.get("yt_tags", [])

    description = (
        best_title + "\n\n"
        + desc_hook + "\n\n"
        + "Every claim in this video is documented. Every number is real. "
        + "This is what they are counting on you not knowing.\n\n"
        + "Follow for daily financial exposes.\n\n"
        + " ".join(SEO_HASHTAGS)
    )

    print("\n--- SEO PACK ---")
    print("BEST TITLE:  " + best_title)
    print("ALT TITLE 1: " + (titles[1] if len(titles) > 1 else "n/a"))
    print("ALT TITLE 2: " + (titles[2] if len(titles) > 2 else "n/a"))
    print("TAGS: " + ", ".join(yt_tags[:5]))
    print("----------------\n")

    return {
        "title":       best_title,
        "alt_titles":  [t for i, t in enumerate(titles) if i != best_idx],
        "description": description,
        "tags":        ["finance", "expose", "secrets", "2026", "usa"] + yt_tags,
        "hashtags":    SEO_HASHTAGS,
    }


# ══════════════════════════════════════════════════════════════════════
# MODULE 10 — THUMBNAIL CONCEPT PRINTER
# (Can't auto-generate images without image gen API,
#  but prints exact Canva/Photoshop instructions)
# ══════════════════════════════════════════════════════════════════════
def print_thumbnail_brief(viral_data):
    concept = viral_data.get("thumbnail_concept", "Dark corporate logo, cracked, on black background")
    text    = viral_data.get("thumbnail_text", "THEY KNEW.")
    print("\n" + "=" * 55)
    print("  THUMBNAIL BRIEF")
    print("=" * 55)
    print("CONCEPT: " + concept)
    print("TEXT OVERLAY: " + text)
    print("RULES:")
    print("  - Dark or black background (contrast = click)")
    print("  - ONE face OR one logo, not both")
    print("  - Text: Impact font, yellow or red, 3 words max")
    print("  - No smiling faces — shock or stern expression only")
    print("  - Add red outline/circle on the subject (fake urgency)")
    print("=" * 55 + "\n")


# ══════════════════════════════════════════════════════════════════════
# MODULE 11 — YOUTUBE UPLOAD
# ══════════════════════════════════════════════════════════════════════
def upload_to_youtube(path, seo):
    rt = os.getenv("YT_REFRESH_TOKEN")
    ci = os.getenv("YT_CLIENT_ID")
    cs = os.getenv("YT_CLIENT_SECRET")
    if not all([rt, ci, cs]):
        print("YouTube creds missing — saved at: " + path)
        return
    print("Uploading: " + seo["title"])
    try:
        creds = Credentials(
            token=None, refresh_token=rt,
            client_id=ci, client_secret=cs,
            token_uri="https://oauth2.googleapis.com/token",
        )
        yt   = build("youtube", "v3", credentials=creds)
        body = {
            "snippet": {
                "title":       seo["title"],
                "description": seo["description"],
                "categoryId":  "27",
                "tags":        seo["tags"],
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
        print("ALT TITLES TO A/B TEST:")
        for alt in seo.get("alt_titles", []):
            print("  > " + alt)
    except Exception as e:
        print("Upload err: " + str(e))


# ══════════════════════════════════════════════════════════════════════
# POSTED LOG
# ══════════════════════════════════════════════════════════════════════
def was_posted(title):
    if not os.path.exists(LOG_F):
        return False
    with open(LOG_F) as f:
        return title in f.read()


def mark_posted(title):
    with open(LOG_F, "a") as f:
        f.write(datetime.now().isoformat() + " | " + title + "\n")


# ══════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════
async def run():
    print("\n" + "=" * 55)
    print("  VIRAL FINANCIAL EXPOSE ENGINE v8.0")
    print("=" * 55 + "\n")

    validate_env()
    boot()

    # ── 1. Trend discovery ──────────────────────────────────────────
    raw_trend = get_trend()

    # ── 2. Viral title engine ───────────────────────────────────────
    viral_data = run_viral_topic_engine(raw_trend)
    print_thumbnail_brief(viral_data)

    # ── 3. Story engine → scenes ────────────────────────────────────
    story_data = run_story_engine(raw_trend, viral_data)
    scenes     = story_data.get("scenes", [])

    if not scenes:
        print("Story engine returned no scenes. Exiting.")
        sys.exit(1)

    # ── 4. SEO pack ─────────────────────────────────────────────────
    seo = build_seo_pack(viral_data, story_data, raw_trend)

    if was_posted(seo["title"]):
        print("Already posted this title. Running again for new topic.")
        raw_trend  = get_trend()
        viral_data = run_viral_topic_engine(raw_trend)
        story_data = run_story_engine(raw_trend, viral_data)
        scenes     = story_data.get("scenes", [])
        seo        = build_seo_pack(viral_data, story_data, raw_trend)

    # ── 5. Generate per-scene voices ────────────────────────────────
    print("\n[VOICE ENGINE] Generating " + str(len(scenes)) + " scene voices...")
    voice_results = await generate_all_voices(scenes, SCENE_D)

    total_duration = sum(vr["duration"] for vr in voice_results)
    print("Total duration: " + str(round(total_duration, 1)) + "s")

    # ── 6. Build per-scene visual + caption clips ───────────────────
    print("\n[VISUAL ENGINE] Building word-synced visuals...")
    scene_video_clips = []
    all_timings_offset = []    # for global caption layer
    time_offset        = 0.0
    whoosh_path        = get_whoosh()

    for vr in voice_results:
        scene    = vr["scene"]
        timings  = vr["timings"]
        dur      = vr["duration"]

        print("\n  Scene " + str(scene["id"]) + " [" + scene["emotion"] + "] " + str(round(dur, 1)) + "s")

        # Build visual for this scene
        vis_clip = build_scene_visuals(scene, dur)

        # Offset timings for global composite
        for t in timings:
            all_timings_offset.append({
                "word":     t["word"],
                "start":    t["start"] + time_offset,
                "end":      t["end"]   + time_offset,
                "duration": t["duration"],
            })

        # Set position in global timeline
        scene_video_clips.append(vis_clip.set_start(time_offset))
        time_offset += dur

    # ── 7. Concatenate all scene audio into one track ───────────────
    print("\n[AUDIO ENGINE] Building audio track...")
    all_voice_clips = [AudioFileClip(vr["voice"]) for vr in voice_results]
    final_voice     = concatenate_audioclips(all_voice_clips)

    bgm  = get_music("dark corporate suspense", total_duration)
    sfx_path = get_sfx("dramatic sting impact")
    sfx  = None
    if sfx_path:
        try:
            sfx = AudioFileClip(sfx_path).set_start(0.2).volumex(0.30)
        except Exception as e:
            print("SFX err: " + str(e))

    audio_layers = [final_voice]
    if bgm:
        audio_layers.append(bgm)
    if sfx:
        audio_layers.append(sfx)
    final_audio = (CompositeAudioClip(audio_layers)
                   if len(audio_layers) > 1 else final_voice)

    # ── 8. Build global caption layer ──────────────────────────────
    print("\n[CAPTION ENGINE] " + str(len(all_timings_offset)) + " word events...")
    cap_layer = build_caption_layer(all_timings_offset, total_duration)

    # ── 9. Brand watermark ──────────────────────────────────────────
    channel = os.getenv("CHANNEL_NAME", "THE EXPOSE")
    brand   = make_brand_watermark(channel, total_duration)

    # ── 10. Black base + all scene clips + captions + brand ─────────
    base = ColorClip(size=(CW, CH), color=(0, 0, 0)).set_duration(total_duration)
    composite_layers = [base] + scene_video_clips
    if cap_layer is not None:
        composite_layers.append(cap_layer)
    composite_layers.append(brand)

    final_video = (
        CompositeVideoClip(composite_layers, size=(CW, CH))
        .set_duration(total_duration)
        .set_audio(final_audio)
    )

    # ── 11. Render ──────────────────────────────────────────────────
    out_path = os.path.join(OUT, "final_reel.mp4")
    print("\n[RENDER] " + str(round(total_duration, 1)) + "s @ 30fps...")
    final_video.write_videofile(
        out_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="fast",
    )
    mb = os.path.getsize(out_path) / (1024 * 1024)
    print("FILE: " + out_path + " (" + str(round(mb, 1)) + " MB)")

    # ── 12. Mark + upload ───────────────────────────────────────────
    mark_posted(seo["title"])
    upload_to_youtube(out_path, seo)

    # ── 13. Final summary ───────────────────────────────────────────
    print("\n" + "=" * 55)
    print("  COMPLETE")
    print("  TITLE:     " + seo["title"])
    print("  DURATION:  " + str(round(total_duration, 1)) + "s")
    print("  SCENES:    " + str(len(scenes)))
    print("  FILE:      " + out_path)
    print("=" * 55)
    print("\nTHUMBNAIL TEXT TO USE: " + viral_data.get("thumbnail_text", "THEY KNEW."))
    print("ALT TITLES FOR A/B:")
    for alt in seo.get("alt_titles", []):
        print("  > " + alt)
    print("")

    return out_path


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception:
        traceback.print_exc()
        sys.exit(1)
