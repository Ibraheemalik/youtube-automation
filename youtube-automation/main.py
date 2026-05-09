"""
╔══════════════════════════════════════════════════════════════════════╗
║  VIRAL FINANCIAL EXPOSE ENGINE — main.py                           ║
║  Full production system: trends → script → voice → visuals → upload║
║                                                                      ║
║  APIs used:                                                          ║
║    GEMINI_API_KEY      — script generation (Google Gemini Pro)      ║
║    NEWSAPI_KEY         — trending financial news                    ║
║    PIXABAY_API_KEY     — stock video + music + SFX                 ║
║    YT_CLIENT_ID        — YouTube upload                            ║
║    YT_CLIENT_SECRET    — YouTube upload                            ║
║    YT_REFRESH_TOKEN    — YouTube upload                            ║
║                                                                      ║
║  Run:  python main.py                                               ║
║  Deps: pip install -r requirements.txt                              ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── stdlib ─────────────────────────────────────────────────────────────
import os, sys, re, json, random, asyncio, uuid, shutil, io, bisect
import textwrap, traceback, time, math
from datetime import datetime, timedelta
from pathlib import Path

# ── third-party ────────────────────────────────────────────────────────
import numpy as np
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import PIL.Image as PilImage
import google.generativeai as genai

from moviepy.editor import (
    AudioFileClip, ColorClip, CompositeAudioClip,
    CompositeVideoClip, ImageClip, TextClip, VideoClip,
    VideoFileClip, concatenate_audioclips, concatenate_videoclips,
)
from moviepy.video.fx import all as vfx

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload

# ── load .env ──────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Pillow compat ──────────────────────────────────────────────────────
if not hasattr(PilImage, "ANTIALIAS"):
    PilImage.ANTIALIAS = PilImage.LANCZOS

# ══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════
OUT   = "output"
CLIPS = "output/clips"
MUS   = "output/music"
LOG   = "output/posted.log"

CW, CH      = 1080, 1920      # canvas: vertical short
FPS         = 30
VOICE_NAME  = "en-US-AndrewNeural"   # deep, authoritative
VOICE_RATE  = "+5%"
MIN_SEG     = 1.4             # min seconds per visual segment

# Caption palette
CAP_BOX  = (255, 214,   0, 245)   # yellow box
CAP_TXT  = (  0,   0,   0, 255)   # black text on yellow
CAP_WHT  = (255, 255, 255, 255)   # white surrounding words
CAP_BLK  = (  0,   0,   0, 215)   # outline

# HTTP
HDR = {"User-Agent": "FinExposeEngine/7.0 (research-bot; contact@example.com)"}
WIKI_API = "https://commons.wikimedia.org/w/api.php"
SKIP_EXT = {
    "svg","ogg","ogv","pdf","webm","mp4","xcf",
    "djvu","flac","mid","wav","opus","mov","avi","tif","tiff",
}

# State
USED_VID_IDS: set = set()
WIKI_CACHE:  dict = {}


# ══════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════
def validate_env():
    required = ["GEMINI_API_KEY", "PIXABAY_API_KEY"]
    missing  = [k for k in required if not os.getenv(k)]
    if missing:
        for m in missing:
            print("MISSING: " + m + " — add to .env")
        sys.exit(1)

    optional = ["NEWSAPI_KEY", "YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]
    for k in optional:
        if not os.getenv(k):
            print("OPTIONAL MISSING (degraded): " + k)

    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    print("ENV OK.")


def boot():
    global USED_VID_IDS, WIKI_CACHE
    USED_VID_IDS = set()
    WIKI_CACHE   = {}
    for d in [OUT, CLIPS, MUS, OUT + "/tmp"]:
        os.makedirs(d, exist_ok=True)
    print("Workspace ready.")


# ══════════════════════════════════════════════════════════════════════
# HTTP HELPERS
# ══════════════════════════════════════════════════════════════════════
def jget(url, params=None, timeout=14):
    try:
        r = requests.get(url, params=params, headers=HDR, timeout=timeout)
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
# STEP 1 — TREND DISCOVERY
# Pulls today's top financial/tech news.
# Falls back to a curated hook list if NewsAPI key is missing.
# ══════════════════════════════════════════════════════════════════════
FALLBACK_HOOKS = [
    "Nvidia just filed a patent that could end human decision-making",
    "The Federal Reserve quietly changed a rule that affects every American",
    "Apple's latest privacy update wiped 10 billion from Meta in 48 hours",
    "Amazon's internal AI system is firing workers without manager approval",
    "Sam Altman's Worldcoin iris scan database just passed 5 million people",
    "BlackRock's AI named Aladdin now manages more money than the US GDP",
    "TikTok's algorithm predicts pregnancy before the mother knows",
    "Goldman Sachs shorted the mortgages they sold to your pension fund",
    "Elon Musk's X platform is training Tesla robots on your tweets",
    "Ticketmaster raised fees above the ticket price on 40 percent of events",
    "Boeing spent 43 billion on bonuses the same years planes were falling",
    "Purdue Pharma paid 18000 doctors to create the opioid epidemic",
    "Your credit score rewards debt and punishes people who save",
    "Starbucks holds 1.6 billion dollars of customer money with zero banking oversight",
    "Shrinkflation hit 4000 products last year and required zero disclosure",
    "McDonald's makes almost no money from food — it is a real estate empire",
    "Uber lost 31 billion dollars on purpose to destroy the taxi industry",
    "The sugar lobby paid Harvard professors to blame fat for heart disease",
    "Disney uses facial recognition on children in theme parks in real time",
    "Private prisons pay states financial penalties if beds are not filled",
]


def get_trending_topic():
    """
    Try NewsAPI for today's top financial story.
    Falls back to curated hooks if key missing or API down.
    Returns a raw headline/hook string.
    """
    newsapi_key = os.getenv("NEWSAPI_KEY")
    if newsapi_key:
        try:
            url  = "https://newsapi.org/v2/top-headlines"
            params = {
                "apiKey":   newsapi_key,
                "category": "business",
                "country":  "us",
                "pageSize": 20,
            }
            r = requests.get(url, params=params, timeout=12)
            if r.status_code == 200:
                articles = r.json().get("articles", [])
                if articles:
                    # Filter for financial/corporate keywords
                    keywords = [
                        "billion", "trillion", "CEO", "fraud", "fed", "reserve",
                        "apple", "google", "meta", "amazon", "nvidia", "tesla",
                        "bank", "stock", "market", "crypto", "crypto", "debt",
                        "layoff", "merger", "antitrust", "lawsuit", "tariff",
                    ]
                    for art in articles:
                        title = art.get("title", "")
                        desc  = art.get("description", "")
                        combo = (title + " " + desc).lower()
                        if any(kw in combo for kw in keywords):
                            print("TRENDING: " + title)
                            return title + ". " + (desc or "")
        except Exception as e:
            print("NewsAPI err: " + str(e))

    # Fallback
    hook = random.choice(FALLBACK_HOOKS)
    print("FALLBACK TOPIC: " + hook)
    return hook


# ══════════════════════════════════════════════════════════════════════
# STEP 2 — GEMINI SCRIPT GENERATION
# Takes a trending hook and generates a complete structured topic:
#   title, hook, script, segments (word-sync clips), sfx, music
# ══════════════════════════════════════════════════════════════════════
GEMINI_SYSTEM = """
You are a viral financial expose scriptwriter. Your reels average 10 million views.

RULES:
- Script: 70-90 words. THRILLER pacing. Short punchy sentences max 9 words each.
- First sentence = THE HOOK. Must create immediate paranoia or shock.
- The word "you" or "your" must appear at least 5 times.
- Each claim must include a specific number or name (CEO name, dollar amount, percentage).
- End with a cliffhanger or personal threat: "And it gets worse."
- NO filler words: no "interestingly", "furthermore", "in conclusion".
- Style: documentary narrator meets whistleblower. Urgent. Factual. Personal.

SEGMENTS:
Each segment maps a KEY PHRASE from the script to a specific visual clip.
- "wiki:X" = Wikimedia Commons image of X (use for: CEO faces, company HQs, specific products)
- "pix:X"  = Pixabay stock video of X (use for: abstract concepts, money, data, crowds)
- Choose 8-12 segments that cover the entire script chronologically.
- The "kw" field is the FIRST UNIQUE WORD of that phrase in the script (for sync matching).

OUTPUT: Valid JSON only. No markdown. No explanation. Exactly this schema:
{
  "title": "Clickbait but factual title under 60 chars",
  "hook": "Single sentence that stops a scroll",
  "script": "Full VO script here",
  "segments": [
    {"kw": "first_unique_word", "clip": "wiki:CEO name"},
    {"kw": "another_word", "clip": "pix:money finance chart"}
  ],
  "sfx": "pixabay sound effect search query",
  "music": "pixabay music mood search query",
  "yt_tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}
"""

def generate_topic_with_gemini(raw_trend):
    """Call Gemini to turn a trending headline into a complete topic JSON."""
    try:
        model  = genai.GenerativeModel("gemini-1.5-pro")
        prompt = (
            "Here is today's trending financial topic:\n\n"
            + raw_trend
            + "\n\nGenerate a viral 10M-view financial expose reel based on this. "
            + "Use real names, real numbers, real companies. Make it feel like a leaked secret."
        )
        resp = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.85),
            system_instruction=GEMINI_SYSTEM,
        )
        text = resp.text.strip()
        # Strip markdown code fences if Gemini adds them
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        data = json.loads(text)
        print("Gemini OK: " + data.get("title", "?"))
        return data
    except Exception as e:
        print("Gemini err: " + str(e))
        return None


def fallback_topic():
    """Handcrafted fallback if Gemini fails."""
    return {
        "title": "Nvidia Just Became The Most Dangerous Company On Earth",
        "hook": "You think Nvidia makes graphics cards. You are catastrophically wrong.",
        "script": (
            "You think Nvidia makes graphics cards. You are catastrophically wrong. "
            "Jensen Huang just became the most powerful unelected person alive. "
            "Every AI deciding your credit score, your job application, and your medical diagnosis "
            "runs on Nvidia hardware. They do not sell chips. "
            "They sell the permission to think. "
            "Only the richest companies in the world can afford that permission. "
            "And Jensen Huang decides who gets it."
        ),
        "segments": [
            {"kw": "You",        "clip": "pix:gaming GPU graphics card technology"},
            {"kw": "Jensen",     "clip": "wiki:Jensen Huang Nvidia CEO portrait"},
            {"kw": "unelected",  "clip": "pix:election vote democracy ballot"},
            {"kw": "credit",     "clip": "pix:credit score finance report"},
            {"kw": "job",        "clip": "pix:job application rejection screen"},
            {"kw": "medical",    "clip": "pix:medical AI diagnosis technology"},
            {"kw": "permission", "clip": "wiki:Nvidia H100 GPU chip"},
            {"kw": "richest",    "clip": "wiki:Nvidia headquarters Santa Clara"},
            {"kw": "Jensen Huang","clip": "pix:AI data center infrastructure server"},
        ],
        "sfx": "dramatic impact",
        "music": "dark corporate suspense",
        "yt_tags": ["nvidia", "AI", "jensen huang", "tech secrets", "financial expose"],
    }


# ══════════════════════════════════════════════════════════════════════
# STEP 3 — VOICE ENGINE
# Edge TTS streams WordBoundary events for ms-accurate per-word timing.
# No artificial pauses — they misalign captions.
# Even-split fallback if WordBoundary returns nothing.
# ══════════════════════════════════════════════════════════════════════
async def generate_voice(script, out_path):
    timings = []
    com = edge_tts.Communicate(script, VOICE_NAME, rate=VOICE_RATE)

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

    # Fallback
    if not timings:
        print("WordBoundary empty — even-split fallback.")
        ac    = AudioFileClip(out_path)
        dur   = ac.duration
        ac.close()
        words = [w for w in script.split() if w]
        per   = dur / max(len(words), 1)
        timings = [
            {"word": w, "start": i * per, "end": (i + 1) * per, "duration": per}
            for i, w in enumerate(words)
        ]

    ac    = AudioFileClip(out_path)
    total = ac.duration
    ac.close()
    print("Voice: " + str(len(timings)) + " words, " + str(round(total, 1)) + "s")
    return timings, total


# ══════════════════════════════════════════════════════════════════════
# STEP 4 — VISUAL ASSETS
# ══════════════════════════════════════════════════════════════════════

# ── Wikimedia Commons ──────────────────────────────────────────────────
def _wiki_search(q, limit=25):
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


def cover_crop(img):
    """Scale-to-cover → center-crop → 1080x1920."""
    iw, ih = img.size
    scale  = max(CW / iw, CH / ih)
    nw     = max(int(iw * scale), CW)
    nh     = max(int(ih * scale), CH)
    img    = img.resize((nw, nh), Image.LANCZOS)
    x0, y0 = (nw - CW) // 2, (nh - CH) // 2
    return img.crop((x0, y0, x0 + CW, y0 + CH))


def apply_cinematic_grade(img):
    """
    Dark cinematic color grade:
    - Slight desaturation
    - Crushed blacks
    - Slight blue tint in shadows
    This makes every frame look like a documentary thriller.
    """
    # Slight desaturation
    img_rgb = img.convert("RGB")
    enhancer = ImageEnhance.Color(img_rgb)
    img_rgb  = enhancer.enhance(0.82)

    # Darken overall
    enhancer = ImageEnhance.Brightness(img_rgb)
    img_rgb  = enhancer.enhance(0.88)

    # Subtle contrast boost
    enhancer = ImageEnhance.Contrast(img_rgb)
    img_rgb  = enhancer.enhance(1.12)

    return img_rgb


def add_vignette(img):
    """Add dark edges to pull focus to center."""
    w, h   = img.size
    mask   = Image.new("L", (w, h), 255)
    draw   = ImageDraw.Draw(mask)
    layers = 40
    for i in range(layers):
        val = int(255 * (i / layers) ** 1.8)
        draw.rectangle([i, i, w - i, h - i], outline=val)

    # Gaussian blur the mask for smooth vignette
    mask = mask.filter(ImageFilter.GaussianBlur(radius=w // 6))

    black = Image.new("RGB", (w, h), (0, 0, 0))
    img   = img.convert("RGB")
    img   = Image.composite(img, black, mask)
    return img


def get_wiki_image(query):
    if query in WIKI_CACHE:
        return WIKI_CACHE[query]

    attempts = [query, query + " photo", query + " portrait", query + " building"]
    seen, unique = set(), []
    for a in attempts:
        a = a.strip()
        if a and a not in seen:
            seen.add(a)
            unique.append(a)

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
            img  = apply_cinematic_grade(img)
            img  = add_vignette(img)
            dest = os.path.join(CLIPS, "wiki_" + uuid.uuid4().hex[:7] + ".jpg")
            img.save(dest, "JPEG", quality=92)
            WIKI_CACHE[query] = dest
            print("Wiki OK: " + query)
            return dest
        except Exception as e:
            print("Wiki err (" + attempt + "): " + str(e))

    print("Wiki miss: " + query)
    WIKI_CACHE[query] = None
    return None


def make_wiki_clip(path, dur):
    """Ken Burns zoom-in 1.0 → 1.08 over the clip duration."""
    return (
        ImageClip(path)
        .set_duration(dur)
        .fx(vfx.resize, lambda t: 1.0 + 0.08 * (t / max(dur, 0.001)))
        .set_position("center")
    )


# ── Pixabay videos ────────────────────────────────────────────────────
SAFE_FALLBACKS = [
    "money cash dollar bills finance",
    "corporate office building finance",
    "wall street stock exchange",
    "government building politics",
    "data server technology",
    "city skyline architecture",
    "finance chart graph data",
    "gold coins money wealth",
    "bank building exterior",
    "technology circuit corporate",
]


def _pix_video(api_key, q, dur):
    global USED_VID_IDS
    d = jget("https://pixabay.com/api/videos/", {
        "key":         api_key, "q": q,
        "per_page":    30, "orientation": "vertical",
        "safesearch":  "true", "min_duration": 3,
    })
    if not d:
        return None
    hits = d.get("hits", [])
    if not hits:
        return None

    random.shuffle(hits)
    for hit in hits:
        hid  = hit.get("id")
        if hid and hid in USED_VID_IDS:
            continue
        vs   = hit.get("videos", {})
        info = vs.get("medium") or vs.get("small") or vs.get("large") or vs.get("tiny")
        if not info or not info.get("url"):
            continue
        try:
            raw = dlb(info["url"])
            if not raw:
                continue
            dest = os.path.join(CLIPS, "pix_" + uuid.uuid4().hex[:7] + ".mp4")
            with open(dest, "wb") as f:
                f.write(raw)
            vc  = VideoFileClip(dest).without_audio()
            if vc.duration < 0.5:
                vc.close()
                continue
            sub = vc.subclip(0, min(dur, vc.duration - 0.05))
            # Cover-crop to 1080x1920
            rv, rc = sub.w / sub.h, CW / CH
            if rv > rc:
                sub = sub.resize(height=CH).crop(x_center=sub.w / 2, width=CW)
            else:
                sub = sub.resize(width=CW).crop(y_center=sub.h / 2, height=CH)
            if hid:
                USED_VID_IDS.add(hid)
            print("Pix OK: " + q)
            return sub
        except Exception as e:
            print("Pix err (" + q + "): " + str(e))
    return None


def get_pix(api_key, q, dur):
    for query in [q] + SAFE_FALLBACKS:
        vc = _pix_video(api_key, query, dur)
        if vc is not None:
            return vc
    return None


# ── Music ─────────────────────────────────────────────────────────────
def get_music(music_q, total):
    api_key = os.getenv("PIXABAY_API_KEY")
    if not api_key:
        return None
    queries = [music_q, "dark corporate investigation",
               "suspense cinematic thriller", "tension mystery dark"]
    for q in queries:
        try:
            r = requests.get(
                "https://pixabay.com/api/music/",
                params={"key": api_key, "q": q, "per_page": 10},
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
                dest = os.path.join(MUS, "bg_" + uuid.uuid4().hex[:6] + ".mp3")
                with open(dest, "wb") as f:
                    f.write(raw)
                c = AudioFileClip(dest)
                if c.duration < 2.0:
                    c.close()
                    continue
                loops  = int(total / c.duration) + 2
                looped = concatenate_audioclips([c] * loops)
                music  = looped.subclip(0, total).volumex(0.058)
                print("Music: " + str(round(music.duration, 1)) + "s")
                return music
        except Exception as e:
            print("Music err: " + str(e))
    return None


# ── SFX ───────────────────────────────────────────────────────────────
def get_sfx(sfx_q):
    api_key = os.getenv("PIXABAY_API_KEY")
    if not api_key:
        return None
    for q in [sfx_q, "dramatic impact hit", "cinematic sting", "whoosh"]:
        try:
            r = requests.get(
                "https://pixabay.com/api/sounds/",
                params={"key": api_key, "q": q, "per_page": 10},
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
            dest = os.path.join(MUS, "sfx_" + uuid.uuid4().hex[:6] + ".mp3")
            with open(dest, "wb") as f:
                f.write(raw)
            print("SFX: " + q)
            return dest
        except Exception as e:
            print("SFX err: " + str(e))
    return None


# ══════════════════════════════════════════════════════════════════════
# STEP 5 — WORD-SYNCED VISUAL TIMELINE
# Maps each segment's keyword to the exact timestamp in voice timings.
# Clips switch when the voice speaks that keyword.
# ══════════════════════════════════════════════════════════════════════
def build_visual_timeline(data, timings, total):
    """Returns list of MoviePy clips with set_start(), ready to composite."""
    segments = data.get("segments", [])
    api_key  = os.getenv("PIXABAY_API_KEY")

    if not segments:
        fb = ColorClip(size=(CW, CH), color=(0, 0, 0)).set_duration(total)
        return [fb]

    # Build normalised word list from timings
    tw_list = [t["word"].lower().strip(".,;:!?'\"—-") for t in timings]

    seg_times  = []
    search_pos = 0

    for seg in segments:
        kw       = seg["kw"].lower().strip(".,;:!?'\"—-").split()[0]
        found_at = None

        for i in range(search_pos, len(tw_list)):
            if tw_list[i] == kw or tw_list[i].startswith(kw[:4]):
                found_at   = timings[i]["start"]
                search_pos = i + 1
                break

        if found_at is None:
            frac     = len(seg_times) / max(len(segments), 1)
            found_at = frac * total

        seg_times.append(found_at)

    # First seg always at t=0
    if seg_times and seg_times[0] > 0.3:
        seg_times[0] = 0.0

    # Build clips
    all_clips = []
    base = ColorClip(size=(CW, CH), color=(0, 0, 0)).set_duration(total)
    all_clips.append(base)

    for i, (seg, start_t) in enumerate(zip(segments, seg_times)):
        end_t    = seg_times[i + 1] if i + 1 < len(seg_times) else total
        seg_dur  = max(end_t - start_t, MIN_SEG)

        clip_src = seg.get("clip", "pix:money finance")
        if ":" in clip_src:
            src_type, src_q = clip_src.split(":", 1)
        else:
            src_type, src_q = "pix", clip_src
        src_type = src_type.strip().lower()
        src_q    = src_q.strip()

        clip_obj = None

        if src_type == "wiki":
            path = get_wiki_image(src_q)
            if path:
                try:
                    clip_obj = make_wiki_clip(path, seg_dur)
                except Exception as e:
                    print("Wiki clip err: " + str(e))

        if clip_obj is None and api_key:
            clip_obj = _pix_video(api_key, src_q, seg_dur)
            if clip_obj is None:
                clip_obj = get_pix(api_key, "corporate finance money", seg_dur)

        if clip_obj is None:
            clip_obj = ColorClip(size=(CW, CH), color=(10, 10, 25)).set_duration(seg_dur)

        # Clamp duration
        try:
            if hasattr(clip_obj, "duration") and clip_obj.duration > seg_dur + 0.1:
                clip_obj = clip_obj.subclip(0, seg_dur)
        except Exception:
            pass

        all_clips.append(clip_obj.set_start(start_t))

    print("Timeline: " + str(len(all_clips) - 1) + " word-synced clips")
    return all_clips


# ══════════════════════════════════════════════════════════════════════
# STEP 6 — HOOK FRAME
# The first 0.5s is a black frame with the hook text in white/yellow.
# This is the "scroll-stopper" — shown before any video starts.
# ══════════════════════════════════════════════════════════════════════
def make_hook_frame(hook_text, duration=2.2):
    """
    Creates a dramatic hook overlay:
    - Black background
    - Large yellow text, centered
    - Word-wrapped to fit 1080px width
    """
    W, H     = CW, CH
    img      = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    draw     = ImageDraw.Draw(img)

    # Load fonts
    font_paths_lg = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    font_lg = None
    for p in font_paths_lg:
        if os.path.exists(p):
            try:
                font_lg = ImageFont.truetype(p, 88)
                break
            except Exception:
                continue
    if font_lg is None:
        font_lg = ImageFont.load_default()

    # Word-wrap
    words   = hook_text.split()
    lines   = []
    current = []
    for word in words:
        test = " ".join(current + [word])
        try:
            bb = draw.textbbox((0, 0), test, font=font_lg)
            w  = bb[2] - bb[0]
        except AttributeError:
            w, _ = draw.textsize(test, font=font_lg)
        if w > W - 80 and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))

    # Measure total height
    line_h  = 100
    total_h = len(lines) * line_h
    start_y = (H - total_h) // 2

    for li, line in enumerate(lines):
        y = start_y + li * line_h
        # Shadow
        draw.text((42, y + 4), line, font=font_lg, fill=(0, 0, 0, 200))
        # Yellow text
        draw.text((40, y), line, font=font_lg, fill=(255, 214, 0, 255))

    # Red accent line above text
    draw.rectangle([40, start_y - 28, W - 40, start_y - 14], fill=(220, 30, 30, 255))

    dest = os.path.join(CLIPS, "hook_" + uuid.uuid4().hex[:5] + ".png")
    img.save(dest, "PNG")

    c = (ImageClip(dest)
         .set_duration(duration)
         .set_position("center"))
    return c


# ══════════════════════════════════════════════════════════════════════
# STEP 7 — CAPTION ENGINE
# 3-word sliding window, yellow box on active word.
# PIL pre-renders all frames → VideoClip with alpha mask.
# Synced to exact WordBoundary timestamps.
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


FA = _load_font(90)   # active word font
FO = _load_font(70)   # surrounding words font


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


def render_caption_frame(prev_w, curr_w, next_w):
    """RGBA strip (210, 1080, 4) for one word event."""
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

    CAP_Y, CAP_H = 1370, 210
    words  = [t["word"]  for t in timings]
    starts = [t["start"] for t in timings]
    ends   = [t["end"]   for t in timings]

    print("Pre-rendering " + str(len(timings)) + " caption frames...")
    frames = [
        render_caption_frame(
            words[i - 1] if i > 0             else None,
            words[i],
            words[i + 1] if i < len(words) - 1 else None,
        )
        for i in range(len(timings))
    ]

    blank_rgb  = np.zeros((CH, CW, 3), dtype=np.uint8)
    blank_mask = np.zeros((CH, CW),    dtype=float)

    def active_idx(t):
        idx = bisect.bisect_right(starts, t) - 1
        if idx < 0:
            return None
        return idx if t <= ends[idx] + 0.07 else None

    def make_rgb(t):
        idx = active_idx(t)
        if idx is None:
            return blank_rgb
        out = blank_rgb.copy()
        out[CAP_Y:CAP_Y + CAP_H, :, :] = frames[idx][:, :, :3]
        return out

    def make_mask(t):
        idx = active_idx(t)
        if idx is None:
            return blank_mask
        m = blank_mask.copy()
        m[CAP_Y:CAP_Y + CAP_H, :] = frames[idx][:, :, 3] / 255.0
        return m

    vc = VideoClip(make_rgb,  duration=total).set_fps(FPS)
    mc = VideoClip(make_mask, duration=total, ismask=True).set_fps(FPS)
    return vc.set_mask(mc)


# ══════════════════════════════════════════════════════════════════════
# STEP 8 — BRANDING OVERLAY
# Channel name + episode number watermark, top-right corner.
# Subtle, not intrusive. Builds brand recognition.
# ══════════════════════════════════════════════════════════════════════
def make_brand_overlay(channel_name, total):
    """Top-right watermark. Fades in at 0.3s, stays throughout."""
    W, H   = 420, 80
    img    = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(img)

    font_path = None
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]:
        if os.path.exists(p):
            font_path = p
            break

    font = ImageFont.truetype(font_path, 36) if font_path else ImageFont.load_default()

    # Red bullet + channel name
    draw.ellipse([12, 22, 42, 52], fill=(220, 30, 30, 220))
    draw.text((54, 20), channel_name.upper(), font=font, fill=(255, 255, 255, 200))

    dest = os.path.join(CLIPS, "brand.png")
    img.save(dest, "PNG")

    c = (ImageClip(dest)
         .set_duration(total)
         .set_position((CW - W - 20, 50))
         .set_opacity(0.85))
    return c


# ══════════════════════════════════════════════════════════════════════
# STEP 9 — YOUTUBE UPLOAD
# Env-var auth. SEO description. 25 hashtags. Category 27.
# ══════════════════════════════════════════════════════════════════════
YT_HASHTAGS = [
    "#FinancialFreedom", "#WealthMindset", "#USPolitics", "#CorporateSecrets",
    "#ConsumerAwareness", "#MoneyHacks2026", "#WallStreetSecrets", "#CentralBank",
    "#InflationAlert", "#PersonalFinanceTips", "#EconomicReality", "#HiddenTruths",
    "#SmartInvesting", "#DebtFreeJourney", "#AmericanEconomy", "#MarketInsights",
    "#BillionaireMindset", "#FinancialLiteracy", "#SocialEngineering", "#MindsetMatters",
    "#PassiveIncomeIdeas", "#TechSecrets", "#ConsumerRights", "#TruthSeeker", "#ShortsFeed",
]


def upload_to_youtube(path, data):
    rt = os.getenv("YT_REFRESH_TOKEN")
    ci = os.getenv("YT_CLIENT_ID")
    cs = os.getenv("YT_CLIENT_SECRET")
    if not all([rt, ci, cs]):
        print("YouTube creds missing — saved locally: " + path)
        return

    print("Uploading: " + data["title"])

    extra_tags = data.get("yt_tags", [])
    desc = (
        data["title"] + "\n" + "─" * 42 + "\n"
        + data["script"] + "\n\n"
        + "The truth is hiding in plain sight.\n\n"
        + " ".join(YT_HASHTAGS)
    )
    try:
        creds = Credentials(
            token=None, refresh_token=rt,
            client_id=ci, client_secret=cs,
            token_uri="https://oauth2.googleapis.com/token",
        )
        yt   = build("youtube", "v3", credentials=creds)
        body = {
            "snippet": {
                "title":       data["title"],
                "description": desc,
                "categoryId":  "27",
                "tags":        ["finance", "expose", "secrets", "2026"] + extra_tags,
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
        vid_id = res.get("id", "?")
        print("LIVE: https://youtube.com/shorts/" + vid_id)
    except Exception as e:
        print("Upload err: " + str(e))
        print("Saved at: " + path)


# ══════════════════════════════════════════════════════════════════════
# STEP 10 — POSTED LOG (anti-duplicate)
# ══════════════════════════════════════════════════════════════════════
def was_posted(title):
    if not os.path.exists(LOG):
        return False
    with open(LOG) as f:
        return title in f.read()


def mark_posted(title):
    with open(LOG, "a") as f:
        f.write(datetime.now().isoformat() + " | " + title + "\n")


# ══════════════════════════════════════════════════════════════════════
# CHANNEL SETTINGS GENERATOR
# Prints recommended channel settings to help set up the channel.
# ══════════════════════════════════════════════════════════════════════
def print_channel_settings():
    print("\n" + "=" * 60)
    print("  CHANNEL SETUP — WHAT A 10M VIEW CHANNEL LOOKS LIKE")
    print("=" * 60)
    print("""
NAME:      "The Expose" / "Finance Files" / "Corporate Leaks"
           Short. Dark. One word that implies power.

LOGO:      White text on pure black background.
           No gradients. No faces. No color except maybe red accent.
           Font: Bold condensed. Think newspaper headline.

BANNER:    Dark background. One sentence only:
           "We find what they don't want you to know."
           No stock photos. No busy design.

BIO:       7 words max. Example:
           "Corporate secrets. Your money. The real story."

PINNED VIDEO: Your most explosive topic. Not your newest.

PINNED COMMENT (on every video):
           "Follow for the next leak. Drop is tomorrow."
           This drives return visits.

POST TIME: 6:30am - 9:00am EST (Mon-Fri)
           US audience waking up = highest competition for early push.

POSTING FREQUENCY: 1 per day minimum. 2 if content quality holds.

THUMBNAIL RULE:
           - One face OR one logo (not both)
           - Red or yellow text. 3 words max.
           - Dark or grainy background
           - Numbers perform: "$47 BILLION" "146 MILLION PEOPLE"
           - Emotion: shock face, leaked document, court paper

DESCRIPTION STRUCTURE:
           Line 1: Hook sentence (same as video hook)
           Line 2: blank
           Line 3: Short paragraph (2-3 sentences) expanding the claim
           Line 4: blank
           Line 5: All hashtags
           Line 6: "New expose drops daily. Subscribe."

WHAT MAKES THE DIFFERENCE:
           The #1 thing separating 10M from 100K is SPECIFICITY.
           Not "banks are corrupt" but "JPMorgan paid $2.6B to avoid
           criminal prosecution and the DOJ sealed the case for 3 years."
           Names. Numbers. Dates. Documents.
""")
    print("=" * 60 + "\n")


# ══════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════
async def run():
    print_channel_settings()

    validate_env()
    boot()

    # ── 1. Get trending topic ───────────────────────────────────────
    raw_trend = get_trending_topic()

    # ── 2. Generate structured topic with Gemini ────────────────────
    data = generate_topic_with_gemini(raw_trend)
    if data is None:
        print("Gemini failed — using fallback topic.")
        data = fallback_topic()

    title = data.get("title", "Financial Expose")
    hook  = data.get("hook",  "The truth they don't want you to know.")

    if was_posted(title):
        print("Already posted: " + title + " — picking fallback.")
        data  = fallback_topic()
        title = data["title"]
        hook  = data["hook"]

    print("\n" + "─" * 55)
    print("TITLE:  " + title)
    print("HOOK:   " + hook)
    print("─" * 55 + "\n")

    # ── 3. Generate voice ───────────────────────────────────────────
    v_path         = os.path.join(OUT, "tmp", "voice.mp3")
    timings, total = await generate_voice(data["script"], v_path)
    voice          = AudioFileClip(v_path)

    # ── 4. Download audio assets ────────────────────────────────────
    bgm      = get_music(data.get("music", "dark corporate suspense"), total)
    sfx_path = get_sfx(data.get("sfx", "dramatic impact"))
    sfx      = None
    if sfx_path:
        try:
            sfx = AudioFileClip(sfx_path).set_start(0.3).volumex(0.32)
        except Exception as e:
            print("SFX load err: " + str(e))

    audio_layers = [voice]
    if bgm:
        audio_layers.append(bgm)
    if sfx:
        audio_layers.append(sfx)
    final_audio = (CompositeAudioClip(audio_layers)
                   if len(audio_layers) > 1 else voice)

    # ── 5. Build word-synced visual timeline ────────────────────────
    visual_layers = build_visual_timeline(data, timings, total)

    # ── 6. Captions (yellow box, word-level sync) ───────────────────
    cap_layer = build_caption_layer(timings, total)

    # ── 7. Brand watermark ──────────────────────────────────────────
    channel_name = os.getenv("CHANNEL_NAME", "THE EXPOSE")
    brand_layer  = make_brand_overlay(channel_name, total)

    # ── 8. Composite all layers ─────────────────────────────────────
    all_layers = visual_layers[:]
    if cap_layer is not None:
        all_layers.append(cap_layer)
    all_layers.append(brand_layer)

    final_video = (
        CompositeVideoClip(all_layers, size=(CW, CH))
        .set_duration(total)
        .set_audio(final_audio)
    )

    # ── 9. Render ───────────────────────────────────────────────────
    out_path = os.path.join(OUT, "final_reel.mp4")
    print("Rendering " + str(round(total, 1)) + "s @ " + str(FPS) + "fps...")
    final_video.write_videofile(
        out_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="fast",
    )
    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    print("DONE: " + out_path + " (" + str(round(size_mb, 1)) + " MB)")

    # ── 10. Mark posted + upload ────────────────────────────────────
    mark_posted(title)
    upload_to_youtube(out_path, data)

    print("\n" + "=" * 55)
    print("  REEL COMPLETE")
    print("  " + title)
    print("=" * 55)
    return out_path


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception:
        traceback.print_exc()
        sys.exit(1)
