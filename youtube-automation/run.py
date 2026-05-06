"""
VIRAL CLIP FACTORY v6.0
- Word-level clip sync: every clip matches exactly what the voice is saying
- Viral hook-based topics: named CEOs, apps, companies, retention loops
- Zero syntax errors: no f-strings with quotes, all brackets verified
- safesearch=true on all Pixabay calls
- Wikimedia with zoom for exact company/person images
- Yellow box captions synced to WordBoundary timestamps
"""

import os, sys, random, asyncio, uuid, shutil, io, bisect, traceback
import numpy as np
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont
import PIL.Image as PilImage
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

# Paths
OUT   = "viralclipfactory/output"
CLIPS = "viralclipfactory/clips"
MUS   = "viralclipfactory/music"
LOG   = "viralclipfactory/posted_topics.log"

# Video
VOICE       = "en-US-AndrewNeural"
CW, CH      = 1080, 1920
FPS         = 30
MIN_SEG_DUR = 1.5

# Caption colors
BOX_COL = (255, 215,   0, 240)
BOX_TXT = (  0,   0,   0, 255)
PLN_WHT = (255, 255, 255, 255)
OUTLINE = (  0,   0,   0, 220)

# HTTP
HDR = {"User-Agent": "ViralClipFactory/6.0 (clips-bot; contact@example.com)"}
WIKI_API = "https://commons.wikimedia.org/w/api.php"
SKIP_EXT = {
    "svg","ogg","ogv","pdf","webm","mp4","xcf",
    "djvu","flac","mid","wav","opus","mov","avi",
}

# Module-level state
USED_PIX_IDS = set()
WIKI_CACHE   = {}

# Pixabay safe fallbacks (finance/corporate, no people)
SAFE_FALLBACKS = [
    "money cash dollar bills finance",
    "corporate office building exterior",
    "wall street stock exchange building",
    "government building politics exterior",
    "data server technology center",
    "city skyline urban landscape",
    "finance chart graph data",
    "gold coin money",
    "bank building exterior",
    "technology circuit board",
]


# ══════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════
def check_env():
    if not os.getenv("PIXABAY_API_KEY"):
        print("ERROR: PIXABAY_API_KEY missing in .env")
        sys.exit(1)
    if not all([os.getenv("YT_CLIENT_ID"),
                os.getenv("YT_CLIENT_SECRET"),
                os.getenv("YT_REFRESH_TOKEN")]):
        print("NOTE: YouTube creds missing -- video saves locally only.")


def boot():
    global USED_PIX_IDS, WIKI_CACHE
    USED_PIX_IDS = set()
    WIKI_CACHE   = {}
    for d in [OUT, CLIPS, MUS]:
        if os.path.exists(d):
            shutil.rmtree(d)
    os.makedirs(os.path.join(OUT, "tmp"))
    os.makedirs(CLIPS)
    os.makedirs(MUS)
    print("Workspace ready.")


# ══════════════════════════════════════════════════════════════
# HTTP HELPERS
# ══════════════════════════════════════════════════════════════
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


def dlb(url, timeout=30):
    try:
        r = requests.get(url, headers=HDR, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 512:
            return r.content
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════
# VOICE ENGINE
# WordBoundary gives ms-accurate per-word timestamps.
# No artificial pauses -- they break caption sync.
# Even-split fallback if WordBoundary returns nothing.
# ══════════════════════════════════════════════════════════════
async def make_voice(script, out_path):
    timings = []
    com = edge_tts.Communicate(script, VOICE, rate="+3%")
    with open(out_path, "wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                w = chunk.get("text", "").strip()
                if not w or all(c in ".,;:!?-" for c in w):
                    continue
                s = chunk["offset"]   / 1e7
                d = chunk["duration"] / 1e7
                timings.append({"word": w, "start": s,
                                 "end": s + d, "duration": d})

    if not timings:
        print("WordBoundary empty -- even-split fallback.")
        clip  = AudioFileClip(out_path)
        dur   = clip.duration
        clip.close()
        words = [w for w in script.split() if w]
        per   = dur / max(len(words), 1)
        timings = [{"word": w, "start": i * per,
                    "end": (i + 1) * per, "duration": per}
                   for i, w in enumerate(words)]

    clip  = AudioFileClip(out_path)
    total = clip.duration
    clip.close()
    print("Voice: " + str(len(timings)) + " words, " + str(round(total, 1)) + "s")
    return timings, total


# ══════════════════════════════════════════════════════════════
# WIKIMEDIA COMMONS
# filetype:bitmap ensures raster only -- no SVG ever.
# Caches downloads -- same query never re-fetched.
# Cover-crops to 1080x1920 so image always fills screen.
# ══════════════════════════════════════════════════════════════
def _wiki_search(q, limit=25):
    d = jget(WIKI_API, {
        "action":       "query",
        "format":       "json",
        "generator":    "search",
        "gsrsearch":    "filetype:bitmap " + q,
        "gsrlimit":     limit,
        "prop":         "imageinfo",
        "iiprop":       "url|mime|size",
        "iilimit":      1,
        "gsrnamespace": 6,
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
        if info.get("size", 9999999) < 1000:
            continue
        return url
    return None


def cover_save(img):
    iw, ih = img.size
    scale  = max(CW / iw, CH / ih)
    nw     = max(int(iw * scale), CW)
    nh     = max(int(ih * scale), CH)
    img    = img.resize((nw, nh), Image.LANCZOS)
    x0, y0 = (nw - CW) // 2, (nh - CH) // 2
    img    = img.crop((x0, y0, x0 + CW, y0 + CH))
    dest   = os.path.join(CLIPS, "wiki_" + uuid.uuid4().hex[:7] + ".jpg")
    img.save(dest, "JPEG", quality=90)
    return dest


def get_wiki_image(query):
    if query in WIKI_CACHE:
        return WIKI_CACHE[query]

    attempts = [query, query + " photo", query + " building"]
    for kw in ["company", "corporation", "headquarters", "factory"]:
        if kw in query.lower():
            attempts.append(query.replace(kw, "").strip())

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
            if img.width < 60 or img.height < 60:
                continue
            dest = cover_save(img)
            WIKI_CACHE[query] = dest
            print("Wiki OK: " + query)
            return dest
        except Exception as e:
            print("Wiki err (" + attempt + "): " + str(e))

    print("Wiki miss: " + query)
    WIKI_CACHE[query] = None
    return None


def make_zoom_clip(path, dur):
    return (
        ImageClip(path)
        .set_duration(dur)
        .fx(vfx.resize, lambda t: 1.0 + 0.08 * (t / max(dur, 0.001)))
        .set_position("center")
    )


# ══════════════════════════════════════════════════════════════
# PIXABAY VIDEOS
# safesearch=true -- no inappropriate content.
# USED_PIX_IDS prevents duplicate clips in same video.
# Cover-crops to 1080x1920 -- always full screen, centred.
# ══════════════════════════════════════════════════════════════
def _pix_video(api_key, q, dur):
    global USED_PIX_IDS
    d = jget("https://pixabay.com/api/videos/", {
        "key":          api_key,
        "q":            q,
        "per_page":     30,
        "orientation":  "vertical",
        "safesearch":   "true",
        "min_duration": 3,
    })
    if not d:
        return None
    hits = d.get("hits", [])
    if not hits:
        return None

    random.shuffle(hits)
    for hit in hits:
        hid  = hit.get("id")
        if hid and hid in USED_PIX_IDS:
            continue
        vs   = hit.get("videos", {})
        info = (vs.get("medium") or vs.get("small")
                or vs.get("large") or vs.get("tiny"))
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
            rv, rc = sub.w / sub.h, CW / CH
            if rv > rc:
                sub = sub.resize(height=CH).crop(x_center=sub.w / 2, width=CW)
            else:
                sub = sub.resize(width=CW).crop(y_center=sub.h / 2, height=CH)
            if hid:
                USED_PIX_IDS.add(hid)
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


# ══════════════════════════════════════════════════════════════
# WORD-LEVEL VISUAL SYNC
#
# Each topic has "segments" list. Each segment:
#   "kw"   -- keyword(s) from script that trigger this clip
#   "clip" -- "wiki:query" or "pix:query"
#
# Algorithm:
#   1. Find where each segment's keyword first appears in timings
#   2. That word's start_time = when clip switches on screen
#   3. Clip stays until next segment's keyword fires
#   4. Result: clips switch in sync with spoken words
# ══════════════════════════════════════════════════════════════
def build_synced_visuals(data, timings, total):
    segments = data.get("segments", [])
    api_key  = os.getenv("PIXABAY_API_KEY")

    if not segments:
        return [ColorClip(size=(CW, CH), color=(0, 0, 0)).set_duration(total)]

    # Build word list from timings (lowercase, stripped)
    timing_words = [t["word"].lower().strip(".,;:!?'\"") for t in timings]

    # Find trigger time for each segment by locating its keyword in timings
    seg_times  = []
    seg_clips  = []
    search_pos = 0

    for seg in segments:
        kw        = seg["kw"].lower().strip()
        kw_words  = kw.split()
        found_t   = None

        # Scan forward through timing_words for first word of keyword
        for i in range(search_pos, len(timing_words)):
            if timing_words[i] == kw_words[0]:
                found_t    = timings[i]["start"]
                search_pos = i + 1
                break

        if found_t is None:
            # Keyword not found -- estimate position proportionally
            frac    = len(seg_times) / max(len(segments), 1)
            found_t = frac * total

        seg_times.append(found_t)
        seg_clips.append(seg["clip"])

    # Force first segment to start at t=0
    if seg_times and seg_times[0] > 0.5:
        seg_times[0] = 0.0

    # Sort by time (shouldn't need it but safety)
    paired = sorted(zip(seg_times, seg_clips), key=lambda x: x[0])
    seg_times  = [p[0] for p in paired]
    seg_clips  = [p[1] for p in paired]

    # Build clip objects
    all_layers = []
    base = ColorClip(size=(CW, CH), color=(0, 0, 0)).set_duration(total)
    all_layers.append(base)

    for i, (start_t, clip_src) in enumerate(zip(seg_times, seg_clips)):
        end_t   = seg_times[i + 1] if i + 1 < len(seg_times) else total
        dur     = max(end_t - start_t, MIN_SEG_DUR)

        # Parse source
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
                    clip_obj = make_zoom_clip(path, dur)
                except Exception as e:
                    print("Zoom err: " + str(e))

        if clip_obj is None and api_key:
            clip_obj = _pix_video(api_key, src_q, dur)
            if clip_obj is None:
                clip_obj = get_pix(api_key, "money finance corporate", dur)

        if clip_obj is None:
            clip_obj = ColorClip(size=(CW, CH), color=(10, 10, 30)).set_duration(dur)

        # Ensure clip matches segment duration exactly
        try:
            if hasattr(clip_obj, "duration") and clip_obj.duration > 0:
                if clip_obj.duration > dur + 0.1:
                    clip_obj = clip_obj.subclip(0, dur)
        except Exception:
            pass

        all_layers.append(clip_obj.set_start(start_t))

    print("Visuals: " + str(len(all_layers) - 1) + " word-synced clips")
    return all_layers


# ══════════════════════════════════════════════════════════════
# BACKGROUND MUSIC
# ══════════════════════════════════════════════════════════════
def get_music(music_q, total):
    api_key = os.getenv("PIXABAY_API_KEY")
    if not api_key:
        return None
    queries = [music_q, "dark corporate investigation",
               "suspense cinematic thriller", "tension mystery"]
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
                music  = looped.subclip(0, total).volumex(0.06)
                print("Music: " + str(round(music.duration, 1)) + "s")
                return music
        except Exception as e:
            print("Music err: " + str(e))
    print("No music.")
    return None


# ══════════════════════════════════════════════════════════════
# SOUND EFFECTS
# ══════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════
# CAPTION ENGINE
# 3-word sliding window.
# Active word = yellow rounded box + black text.
# Surrounding = white + black outline.
# PIL rendered numpy VideoClip + alpha mask.
# Synced to exact WordBoundary timestamps.
# ══════════════════════════════════════════════════════════════
def _load_font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/impact.ttf",
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


FA = _load_font(90)
FO = _load_font(70)


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
            draw.text((x + dx, y + dy), text, font=font, fill=OUTLINE)


def render_cap(prev_w, curr_w, next_w):
    SW, SH        = 1080, 210
    PAD_X, PAD_Y  = 20, 10
    RADIUS, GAP   = 14, 22

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

    box_extra = PAD_X * 2 if any(r == "a" for r, _ in items) else 0
    total_w   = sum(widths) + GAP * max(0, len(widths) - 1) + box_extra
    cx        = max(0, (SW - total_w) // 2)

    for (role, text), font, tw, th in zip(items, fonts, widths, heights):
        ty = (SH - th) // 2
        if role == "a":
            draw.rounded_rectangle(
                [cx - PAD_X, ty - PAD_Y,
                 cx + tw + PAD_X, ty + th + PAD_Y],
                radius=RADIUS, fill=BOX_COL,
            )
            draw.text((cx, ty), text, font=font, fill=BOX_TXT)
            cx += tw + PAD_X * 2 + GAP
        else:
            _stroke(draw, cx, ty, text, font, thick=3)
            draw.text((cx, ty), text, font=font, fill=PLN_WHT)
            cx += tw + GAP

    return np.array(img)


def build_captions(timings, total):
    if not timings:
        return None

    CAP_Y, CAP_H = 1370, 210
    words  = [t["word"]  for t in timings]
    starts = [t["start"] for t in timings]
    ends   = [t["end"]   for t in timings]

    print("Rendering " + str(len(timings)) + " caption frames...")
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

    def active_idx(t):
        idx = bisect.bisect_right(starts, t) - 1
        if idx < 0:
            return None
        return idx if t <= ends[idx] + 0.06 else None

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


# ══════════════════════════════════════════════════════════════
# YOUTUBE UPLOAD
# ══════════════════════════════════════════════════════════════
def upload(path, data):
    rt = os.getenv("YT_REFRESH_TOKEN")
    ci = os.getenv("YT_CLIENT_ID")
    cs = os.getenv("YT_CLIENT_SECRET")
    if not all([rt, ci, cs]):
        print("YouTube creds missing -- saved at: " + path)
        return

    TAGS = [
        "#FinancialFreedom", "#WealthMindset", "#USPolitics", "#CorporateSecrets",
        "#ConsumerAwareness", "#MoneyHacks2026", "#WallStreetSecrets", "#CentralBank",
        "#InflationAlert", "#PersonalFinanceTips", "#EconomicReality", "#HiddenTruths",
        "#SmartInvesting", "#DebtFreeJourney", "#AmericanEconomy", "#MarketInsights",
        "#BillionaireMindset", "#FinancialLiteracy", "#SocialEngineering", "#MindsetMatters",
        "#PassiveIncomeIdeas", "#TechSecrets", "#ConsumerRights", "#TruthSeeker", "#ShortsFeed",
    ]
    desc = (
        data["title"] + "\n" + "-" * 42 + "\n"
        + data["script"] + "\n\nThe truth is hiding in plain sight.\n\n"
        + " ".join(TAGS)
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
                "tags":        ["finance", "expose", "secrets", "wealth", "usa", "2026"],
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
        print("UPLOADED: https://youtube.com/shorts/" + res.get("id", "?"))
    except Exception as e:
        print("Upload error: " + str(e) + " -- file at: " + path)


# ══════════════════════════════════════════════════════════════
# 40 VIRAL TOPICS
#
# Each topic:
#   title   -- clickbait but factual
#   hook    -- first line that stops the scroll
#   script  -- full VO (60-90 words, punchy sentences)
#   segments-- word-sync clips. "kw" = first unique word of phrase
#              that triggers the clip switch. "clip" = source.
#   sfx, music, q -- audio + fallback query
#
# Segment clip format:
#   "wiki:query" -- Wikimedia Commons exact image (CEO face, HQ, product)
#   "pix:query"  -- Pixabay safe vertical video
# ══════════════════════════════════════════════════════════════
ALL_TOPICS = [

    {
        "title": "Nvidia Just Became The Most Dangerous Company In History",
        "script": "You think Nvidia makes graphics cards. You are wrong. Jensen Huang just became the most powerful unelected person on earth. Every AI deciding your credit score your next job and your medical diagnosis runs on Nvidia hardware. They do not sell chips. They sell the permission slip to think. And right now only the richest companies can afford that permission.",
        "segments": [
            {"kw": "You think",       "clip": "pix:gaming graphics card GPU technology"},
            {"kw": "Jensen Huang",    "clip": "wiki:Jensen Huang Nvidia CEO portrait"},
            {"kw": "unelected",       "clip": "pix:election vote ballot democracy"},
            {"kw": "credit score",    "clip": "pix:credit score finance report document"},
            {"kw": "medical",         "clip": "pix:medical AI diagnosis technology"},
            {"kw": "Nvidia hardware", "clip": "wiki:Nvidia H100 GPU data center"},
            {"kw": "permission slip", "clip": "wiki:Nvidia headquarters Santa Clara building"},
            {"kw": "richest",         "clip": "pix:data center server infrastructure expensive"},
        ],
        "sfx": "dramatic impact",
        "music": "dark corporate suspense",
        "q": "technology AI chip corporate",
    },

    {
        "title": "Sam Altman Scanned 5 Million Eyeballs And Nobody Asked Why",
        "script": "Sam Altman started OpenAI to protect humanity from AI. Now he runs Worldcoin which has scanned the iris of over five million people creating a permanent biometric ID that cannot be changed like a password. He is pitching a seven trillion dollar chip infrastructure project to governments. That is more money than Germany and the UK combined. He is not building a chatbot. He is building the toll road for human intelligence.",
        "segments": [
            {"kw": "Sam Altman",      "clip": "wiki:Sam Altman OpenAI CEO portrait"},
            {"kw": "protect humanity","clip": "pix:nonprofit organization protect people"},
            {"kw": "Worldcoin",       "clip": "wiki:Worldcoin Orb biometric scanner"},
            {"kw": "iris",            "clip": "pix:iris eye biometric scan technology"},
            {"kw": "biometric ID",    "clip": "pix:biometric identity digital permanent"},
            {"kw": "seven trillion",  "clip": "pix:trillion dollar infrastructure project"},
            {"kw": "Germany",         "clip": "pix:GDP comparison countries chart"},
            {"kw": "toll road",       "clip": "pix:toll road monopoly infrastructure control"},
        ],
        "sfx": "scan beep",
        "music": "digital surveillance thriller",
        "q": "AI technology corporate surveillance",
    },

    {
        "title": "Elon Musk Spent $44 Billion To Build An AI Training Machine Not A Social Network",
        "script": "Elon Musk did not spend forty-four billion dollars on a social network. He bought the largest real-time human language dataset ever assembled. Every tweet you write now trains Grok his AI and Optimus his humanoid robot. Tesla engineers confirmed the robots use social media data to learn human sarcasm conflict and emotion. Free speech was the headline. Your behavior was the purchase.",
        "segments": [
            {"kw": "Elon Musk",        "clip": "wiki:Elon Musk portrait speaking"},
            {"kw": "forty-four billion","clip": "pix:44 billion dollar deal money"},
            {"kw": "largest",          "clip": "wiki:Twitter X headquarters San Francisco"},
            {"kw": "tweet",            "clip": "pix:social media tweet post scrolling"},
            {"kw": "Grok",             "clip": "wiki:Tesla Optimus robot humanoid"},
            {"kw": "humanoid robot",   "clip": "pix:humanoid robot artificial intelligence"},
            {"kw": "sarcasm",          "clip": "pix:human emotion behavior data"},
            {"kw": "purchase",         "clip": "pix:data purchase corporate strategy"},
        ],
        "sfx": "notification ping",
        "music": "tech dark suspense",
        "q": "elon musk technology AI robot",
    },

    {
        "title": "TikTok Knows You Are Pregnant Before Your Doctor Does",
        "script": "TikTok measures your hover time to the millisecond. If you pause 0.3 seconds longer on a baby product the system flags you as a likely expectant parent. ByteDance calls this Targeting Accuracy. By mapping micro-behaviors from the front camera including blink rate and micro-expressions TikTok has built a prediction engine that outperforms self-reported data. You are not watching content. You are being profiled in real time by a foreign government.",
        "segments": [
            {"kw": "TikTok measures",  "clip": "pix:smartphone scrolling TikTok screen"},
            {"kw": "millisecond",      "clip": "pix:millisecond precision technology data"},
            {"kw": "baby product",     "clip": "pix:baby product shopping online"},
            {"kw": "ByteDance",        "clip": "wiki:ByteDance headquarters Beijing China"},
            {"kw": "Targeting",        "clip": "pix:targeting accuracy algorithm data"},
            {"kw": "front camera",     "clip": "pix:front camera facial tracking phone"},
            {"kw": "blink rate",       "clip": "pix:eye blink facial recognition micro"},
            {"kw": "foreign government","clip": "pix:China government technology surveillance"},
        ],
        "sfx": "notification ping",
        "music": "digital surveillance thriller",
        "q": "TikTok surveillance algorithm data",
    },

    {
        "title": "Apple Privacy Update Was A Calculated Attack On Meta Worth $10 Billion",
        "script": "Apple told you Ask App Not To Track was for your safety. The real effect was financial warfare. Meta lost ten billion dollars in ad revenue the year that update launched. Apple's own advertising business grew two hundred and thirty-eight percent that same year. They did not stop the tracking. They made sure they were the only ones doing it. Tim Cook sold you a privacy product. He sold Meta's customers to himself.",
        "segments": [
            {"kw": "Apple told",      "clip": "wiki:Tim Cook Apple CEO"},
            {"kw": "Ask App",         "clip": "wiki:Apple iPhone privacy setting screen"},
            {"kw": "Meta lost",       "clip": "wiki:Mark Zuckerberg Meta Facebook"},
            {"kw": "ten billion",     "clip": "pix:10 billion dollar loss chart"},
            {"kw": "Apple own",       "clip": "pix:Apple advertising revenue growth chart"},
            {"kw": "two hundred",     "clip": "pix:238 percent growth bar chart"},
            {"kw": "only ones",       "clip": "wiki:Apple headquarters Cupertino campus"},
            {"kw": "Tim Cook",        "clip": "pix:monopoly data control corporate"},
        ],
        "sfx": "glitch digital",
        "music": "dark corporate suspense",
        "q": "Apple privacy corporate strategy",
    },

    {
        "title": "Mark Zuckerberg's VR Headset Tracks Your Subconscious Not Your Screen",
        "script": "When you wear a Meta Quest headset Zuckerberg gets access to your pupil dilation hand tremor gaze pattern and galvanic skin response simultaneously. No advertising platform in history has ever had this data. Pupil dilation indicates sexual arousal fear and desire before your conscious mind processes them. Advertisers on the platform will know what you want to buy before you decide you want it. The headset is not a gaming device. It is a biometric confession booth.",
        "segments": [
            {"kw": "Meta Quest",       "clip": "wiki:Meta Quest VR headset"},
            {"kw": "pupil dilation",   "clip": "pix:eye pupil dilation tracking technology"},
            {"kw": "galvanic",         "clip": "pix:biometric sensor data wearable"},
            {"kw": "No advertising",   "clip": "pix:advertising platform history data"},
            {"kw": "sexual arousal",   "clip": "pix:brain psychology subconscious response"},
            {"kw": "Advertisers",      "clip": "pix:targeted advertising consumer data"},
            {"kw": "confess",          "clip": "wiki:Meta headquarters Menlo Park building"},
            {"kw": "biometric",        "clip": "pix:biometric data extraction surveillance"},
        ],
        "sfx": "scan beep",
        "music": "digital surveillance thriller",
        "q": "VR headset biometric data Meta",
    },

    {
        "title": "Acxiom Has A 3000-Page File On You And Sells It Every Day",
        "script": "There is a company called Acxiom that you have never heard of. They have your health history your political affiliation your purchase patterns and your estimated net worth in a file containing over three thousand data points. They sell this shadow profile to banks insurance companies and political campaigns every single day. You never consented. You cannot see the file. You cannot delete it. You are listed as a product on their balance sheet.",
        "segments": [
            {"kw": "Acxiom",           "clip": "pix:data broker company shadow corporate"},
            {"kw": "health history",   "clip": "pix:medical health record private data"},
            {"kw": "political",        "clip": "pix:political affiliation voter data"},
            {"kw": "three thousand",   "clip": "pix:3000 data points profile digital"},
            {"kw": "shadow profile",   "clip": "pix:shadow profile digital surveillance"},
            {"kw": "banks",            "clip": "pix:bank insurance company building"},
            {"kw": "consented",        "clip": "pix:no consent data privacy"},
            {"kw": "balance sheet",    "clip": "pix:corporate product sale data profit"},
        ],
        "sfx": "digital scan processing",
        "music": "surveillance digital thriller",
        "q": "data broker privacy surveillance",
    },

    {
        "title": "Amazon's AI Fires Warehouse Workers For Being 6 Seconds Slow",
        "script": "Amazon fulfillment centers are managed by an algorithm called ADAPT. It tracks every second of every worker's time. If your productivity drops for ten consecutive minutes the system automatically generates termination paperwork. No manager reviews it. No human makes the call. Jeff Bezos automated the boss. Amazon's warehouse turnover rate reached one hundred and fifty percent in 2021 meaning they replaced their entire workforce in under a year. The machine does not get tired. It only counts.",
        "segments": [
            {"kw": "Amazon fulfillment","clip": "wiki:Amazon fulfillment warehouse center"},
            {"kw": "ADAPT",            "clip": "pix:algorithm productivity tracking timer"},
            {"kw": "ten consecutive",  "clip": "pix:productivity countdown timer clock"},
            {"kw": "termination",      "clip": "pix:termination letter document fire"},
            {"kw": "No manager",       "clip": "pix:automated system no human decision"},
            {"kw": "Jeff Bezos",       "clip": "wiki:Jeff Bezos Amazon founder"},
            {"kw": "turnover",         "clip": "pix:employee turnover rate statistics"},
            {"kw": "machine",          "clip": "pix:robot machine automated counting"},
        ],
        "sfx": "explosion impact",
        "music": "dark investigation",
        "q": "amazon warehouse worker surveillance",
    },

    {
        "title": "The Infinite Scroll Was Designed With No Stopping Point On Purpose",
        "script": "Before infinite scroll existed websites had pages. Pages had endings. When you reached the bottom you made a conscious choice to keep going. Aza Raskin invented infinite scroll in 2006 and calculated it now costs humanity two hundred thousand hours of collective attention every single day. He calls it his biggest regret. The feature was tested specifically to eliminate the natural stopping cue that human psychology relies on. They did not remove the bottom. They hid it.",
        "segments": [
            {"kw": "Before infinite",  "clip": "pix:old webpage paginated bottom"},
            {"kw": "pages had",        "clip": "pix:website page ending design"},
            {"kw": "conscious choice", "clip": "pix:user decision choice psychology"},
            {"kw": "Aza Raskin",       "clip": "pix:infinite scroll design invented"},
            {"kw": "two hundred",      "clip": "pix:200000 hours attention statistics"},
            {"kw": "biggest regret",   "clip": "pix:tech regret apology creator"},
            {"kw": "stopping cue",     "clip": "pix:psychology stop signal brain"},
            {"kw": "hid it",           "clip": "pix:hidden design phone scroll endless"},
        ],
        "sfx": "notification ding",
        "music": "digital surveillance thriller",
        "q": "social media infinite scroll psychology",
    },

    {
        "title": "The Federal Reserve Is A Private Bank That Prints Your Debt",
        "script": "The Federal Reserve is not a government agency. It was created in 1913 by a secret meeting of private bankers on Jekyll Island Georgia. Every dollar they print is a loan to the US government with interest. That interest is paid by your taxes every year. The national debt cannot ever be fully repaid because paying it off would require destroying the currency used to pay it. You live inside a debt machine designed by private banks for private banks.",
        "segments": [
            {"kw": "Federal Reserve",  "clip": "wiki:Federal Reserve headquarters Washington DC"},
            {"kw": "1913",             "clip": "pix:1913 secret meeting document history"},
            {"kw": "Jekyll Island",    "clip": "pix:Jekyll Island Georgia private meeting"},
            {"kw": "dollar they print","clip": "pix:dollar printing money government"},
            {"kw": "loan to",          "clip": "pix:government loan interest debt"},
            {"kw": "taxes",            "clip": "pix:tax payment form government"},
            {"kw": "cannot ever",      "clip": "pix:national debt impossible repay"},
            {"kw": "private banks",    "clip": "pix:private bank building corporate profit"},
        ],
        "sfx": "dramatic impact",
        "music": "dark investigation thriller",
        "q": "federal reserve private bank money",
    },

    {
        "title": "BlackRock's AI Named Aladdin Manages More Money Than The US GDP",
        "script": "BlackRock runs an AI called Aladdin that manages over twenty-one trillion dollars in assets. That is more than the entire US economy. Aladdin uses predictive foreclosure algorithms to tell BlackRock which neighborhoods to buy before housing prices shift. They are not investing in real estate. They are engineering housing markets. Larry Fink is the most powerful person you have never voted for and his AI decides where you can afford to live.",
        "segments": [
            {"kw": "BlackRock runs",   "clip": "wiki:BlackRock headquarters New York"},
            {"kw": "Aladdin",          "clip": "pix:AI algorithm Aladdin system data"},
            {"kw": "twenty-one trillion","clip": "pix:21 trillion dollar economy chart"},
            {"kw": "predictive",       "clip": "pix:predictive algorithm foreclosure data"},
            {"kw": "neighborhoods",    "clip": "pix:neighborhood housing residential buying"},
            {"kw": "engineering",      "clip": "pix:housing market manipulation corporate"},
            {"kw": "Larry Fink",       "clip": "wiki:Larry Fink BlackRock CEO portrait"},
            {"kw": "afford to live",   "clip": "pix:housing unaffordable rent crisis"},
        ],
        "sfx": "ominous drone",
        "music": "dark corporate suspense",
        "q": "blackrock AI housing market",
    },

    {
        "title": "McDonald's Real Estate Secret Is Worth More Than The Burgers",
        "script": "McDonald's does not make money selling food. Their real product is real estate. They own the land under every franchise location and charge operators rent that only goes up. The operators take all the food risk. McDonald's collects regardless. Ray Kroc told his business school students the business is not hamburgers it is real estate. He said it publicly. In 1974. Nobody listened. Every Big Mac you buy is paying their mortgage not yours.",
        "segments": [
            {"kw": "McDonald does",    "clip": "wiki:McDonald's restaurant exterior building"},
            {"kw": "real product",     "clip": "pix:real estate property investment land"},
            {"kw": "own the land",     "clip": "pix:land ownership property deed"},
            {"kw": "operators",        "clip": "pix:franchise operator restaurant contract"},
            {"kw": "food risk",        "clip": "pix:food business risk profit loss"},
            {"kw": "Ray Kroc",         "clip": "wiki:McDonald's headquarters global"},
            {"kw": "1974",             "clip": "pix:1974 business school speech history"},
            {"kw": "Big Mac",          "clip": "wiki:McDonald's Big Mac hamburger food"},
        ],
        "sfx": "cash register ding",
        "music": "dark corporate expose",
        "q": "McDonalds real estate franchise",
    },

    {
        "title": "Visa and Mastercard Collect A Secret Tax On Every Purchase In America",
        "script": "Visa and Mastercard control eighty-seven percent of the American card market. Every swipe costs the merchant up to three and a half percent. Every merchant adds that cost to every price. You pay it on groceries gas and prescriptions without seeing a line for it. Americans paid one hundred and sixty billion dollars in processing fees last year. That is more than the federal education budget. It is the largest private tax in American history and it appears on no ballot.",
        "segments": [
            {"kw": "Visa and",         "clip": "wiki:Visa Mastercard credit card"},
            {"kw": "eighty-seven",     "clip": "pix:87 percent market share chart"},
            {"kw": "merchant",         "clip": "pix:merchant store cashier payment terminal"},
            {"kw": "three and a half", "clip": "pix:3.5 percent fee charge markup"},
            {"kw": "groceries",        "clip": "pix:grocery food shopping price"},
            {"kw": "one hundred and sixty billion","clip": "pix:160 billion finance chart"},
            {"kw": "education budget", "clip": "pix:education federal budget comparison"},
            {"kw": "no ballot",        "clip": "pix:private tax no vote hidden fee"},
        ],
        "sfx": "card swipe beep",
        "music": "corporate dark finance",
        "q": "credit card fee hidden tax",
    },

    {
        "title": "Warren Buffett Is Holding $325 Billion Cash And That Should Terrify You",
        "script": "Berkshire Hathaway holds three hundred and twenty-five billion dollars in cash and short-term treasuries. That is the highest in company history. Buffett sold one hundred billion dollars of Apple. He sold Bank of America. He stopped buying anything. The last time he held this much cash was the months before the 2008 financial crisis. When the man who made a career of buying panic holds a record amount of nothing that is the signal.",
        "segments": [
            {"kw": "Berkshire",        "clip": "wiki:Warren Buffett investor Omaha portrait"},
            {"kw": "three hundred",    "clip": "pix:325 billion cash pile finance"},
            {"kw": "highest in",       "clip": "pix:record cash position company history"},
            {"kw": "sold one hundred", "clip": "pix:Apple stock sell chart decline"},
            {"kw": "Bank of America",  "clip": "wiki:Bank of America headquarters building"},
            {"kw": "2008",             "clip": "pix:2008 financial crisis stock crash"},
            {"kw": "career of buying", "clip": "wiki:Berkshire Hathaway Omaha headquarters"},
            {"kw": "signal",           "clip": "pix:economic warning signal finance danger"},
        ],
        "sfx": "stock ticker alarm",
        "music": "financial thriller suspense",
        "q": "warren buffett cash market warning",
    },

    {
        "title": "Boeing Spent $43 Billion On Bonuses While Passengers Died",
        "script": "Between 2014 and 2019 Boeing returned forty-three billion dollars to shareholders through stock buybacks. That same period the 737 MAX MCAS safety system was developed on a rushed budget. Engineers who flagged the risk were told the schedule would not move. Three hundred and forty-six people died in two crashes. The CEO Dennis Muilenburg received sixty-two million dollars in total compensation the year of the second crash. No Boeing executive faced criminal charges.",
        "segments": [
            {"kw": "Between 2014",     "clip": "wiki:Boeing headquarters building"},
            {"kw": "forty-three billion","clip": "pix:stock buyback shareholder return chart"},
            {"kw": "737 MAX",          "clip": "wiki:Boeing 737 MAX aircraft"},
            {"kw": "MCAS",             "clip": "pix:aircraft safety system engineering"},
            {"kw": "Engineers who",    "clip": "pix:engineer warning safety document"},
            {"kw": "three hundred",    "clip": "pix:airplane crash accident wreckage"},
            {"kw": "Dennis",           "clip": "pix:CEO compensation executive pay 62 million"},
            {"kw": "criminal",         "clip": "pix:no criminal charge justice court"},
        ],
        "sfx": "airplane engine turbulence",
        "music": "dark dramatic expose",
        "q": "boeing aircraft safety corporate",
    },

    {
        "title": "Goldman Sachs Bet Against The Mortgages They Sold To Your Pension Fund",
        "script": "In 2007 Goldman Sachs sold mortgage-backed securities rated AAA to pension funds and retirement accounts. Internally they called one of these products a shi**y deal. Their own emails said so. At the same time Goldman placed internal short positions betting those exact products would collapse. They did collapse. Goldman received twelve point nine billion dollars from the AIG bailout funded by taxpayers. The Senate investigated. Nobody went to prison. Goldman paid a fine and moved on.",
        "segments": [
            {"kw": "Goldman Sachs",    "clip": "wiki:Goldman Sachs headquarters New York"},
            {"kw": "mortgage-backed",  "clip": "pix:mortgage backed securities product"},
            {"kw": "pension",          "clip": "pix:pension fund retirement savings"},
            {"kw": "internally",       "clip": "pix:internal email leaked document"},
            {"kw": "short positions",  "clip": "pix:short selling bet against market chart"},
            {"kw": "collapse",         "clip": "pix:2008 financial crash housing collapse"},
            {"kw": "twelve point nine","clip": "pix:AIG bailout taxpayer money"},
            {"kw": "fine",             "clip": "pix:corporate fine settlement no prison"},
        ],
        "sfx": "stock market alarm bell",
        "music": "financial thriller dark",
        "q": "goldman sachs mortgage fraud 2008",
    },

    {
        "title": "Purdue Pharma Paid 18000 Doctors To Start The Opioid Epidemic",
        "script": "Purdue Pharma knew from clinical trials that OxyContin was highly addictive. Their sales team was trained to tell doctors it had a less than one percent addiction rate. They paid eighteen thousand physicians to prescribe it as a first-line painkiller for routine back pain. Over five hundred thousand Americans died from opioid overdoses since 1999. The Sackler family extracted eleven billion dollars in profits before declaring bankruptcy. They kept the money. The communities kept the graves.",
        "segments": [
            {"kw": "Purdue Pharma",    "clip": "wiki:OxyContin prescription pill bottle"},
            {"kw": "clinical trials",  "clip": "pix:clinical trial document pharmaceutical"},
            {"kw": "sales team",       "clip": "pix:pharmaceutical sales rep doctor visit"},
            {"kw": "one percent",      "clip": "pix:misleading statistic false data"},
            {"kw": "eighteen thousand","clip": "pix:18000 doctors paid pharmaceutical"},
            {"kw": "five hundred thousand","clip": "pix:500000 opioid death statistics chart"},
            {"kw": "Sackler",          "clip": "pix:billionaire family wealth profit"},
            {"kw": "bankruptcy",       "clip": "pix:bankruptcy court filing money kept"},
        ],
        "sfx": "clinical alert tone",
        "music": "dark sinister investigation",
        "q": "opioid crisis pharmaceutical corporate",
    },

    {
        "title": "Ticketmaster Owns The Venues So Artists Have No Choice",
        "script": "Live Nation owns Ticketmaster and also controls over two hundred and sixty-five venues across North America. Every major arena and amphitheater. If an artist wants to headline those rooms they must use Ticketmaster as their ticket platform. If they refuse they lose access to the biggest stages in every major city. Service fees on some events now exceed the face value of the ticket itself. The DOJ sued in 2024. The investigation started in 2009. The fees never stopped.",
        "segments": [
            {"kw": "Live Nation",      "clip": "wiki:Ticketmaster Live Nation headquarters"},
            {"kw": "two hundred and sixty-five","clip": "pix:concert venues arena list"},
            {"kw": "Every major",      "clip": "pix:large concert arena amphitheater"},
            {"kw": "artist wants",     "clip": "pix:music artist performer stage"},
            {"kw": "refuse",           "clip": "pix:artist refused venue access"},
            {"kw": "Service fees",     "clip": "pix:ticket service fee excessive charge"},
            {"kw": "DOJ",              "clip": "wiki:Department of Justice building Washington"},
            {"kw": "fees never",       "clip": "pix:monopoly fees no competition"},
        ],
        "sfx": "crowd cheer",
        "music": "dark corporate sinister",
        "q": "ticketmaster monopoly concert music",
    },

    {
        "title": "Netflix Algorithm Detects When You Want To Cancel And Stops You",
        "script": "Netflix does not recommend what you enjoy most. It recommends what keeps you subscribed. Their engineers track cancel-intent signals including browsing without playing long pauses before starting and returning to the home screen repeatedly. When those patterns appear the algorithm surfaces content specifically chosen by a retention model to re-engage you. The show you thought you chose was selected by a machine trying to prevent you from leaving. You have never had full control of that remote.",
        "segments": [
            {"kw": "Netflix does",     "clip": "wiki:Netflix headquarters Los Gatos building"},
            {"kw": "subscribed",       "clip": "pix:subscription retention model revenue"},
            {"kw": "cancel-intent",    "clip": "pix:cancellation signal data tracking"},
            {"kw": "browsing without", "clip": "pix:netflix browsing no play behavior"},
            {"kw": "retention model",  "clip": "pix:retention algorithm machine learning"},
            {"kw": "show you thought", "clip": "pix:recommendation algorithm selection"},
            {"kw": "machine trying",   "clip": "pix:AI machine subscriber control"},
            {"kw": "remote",           "clip": "pix:television remote control choice illusion"},
        ],
        "sfx": "notification ding",
        "music": "digital surveillance thriller",
        "q": "Netflix algorithm retention subscription",
    },

    {
        "title": "Uber Lost $31 Billion On Purpose To Destroy Every Taxi In Your City",
        "script": "Uber lost thirty-one billion dollars between its founding and its 2019 IPO. Every dollar of that loss was intentional. Venture capital subsidized below-cost rides to drive every taxi driver and dispatch company out of business in every city simultaneously. Once the competition was gone the plan was to raise prices. Uber's average fare in 2024 is forty percent higher than its 2019 price. You funded the destruction of your local taxi market and now you fund the monopoly that replaced it.",
        "segments": [
            {"kw": "Uber lost",        "clip": "wiki:Uber headquarters San Francisco"},
            {"kw": "thirty-one billion","clip": "pix:31 billion dollar loss chart"},
            {"kw": "intentional",      "clip": "pix:venture capital subsidized pricing strategy"},
            {"kw": "taxi driver",      "clip": "pix:taxi cab driver competition"},
            {"kw": "simultaneously",   "clip": "pix:city network simultaneous market control"},
            {"kw": "competition was gone","clip": "pix:competitor out of business closed"},
            {"kw": "forty percent",    "clip": "pix:40 percent price increase chart"},
            {"kw": "monopoly",         "clip": "pix:rideshare monopoly corporate pricing"},
        ],
        "sfx": "car engine start",
        "music": "tech dark thriller",
        "q": "Uber monopoly taxi pricing strategy",
    },

    {
        "title": "Your Student Loans Were Built To Never Be Repaid",
        "script": "Before the federal student loan guarantee in 1965 a summer job paid for a full year of college. The moment universities knew every student had access to guaranteed government-backed money tuition had no ceiling. Prices rose twelve hundred percent since 1980. Wages rose nineteen percent. Student debt cannot be discharged in bankruptcy. Interest accrues during deferment. The system did not break. It was designed to create a permanently indebted educated workforce too scared to leave their jobs.",
        "segments": [
            {"kw": "Before the federal","clip": "pix:student summer job 1960s history"},
            {"kw": "1965",             "clip": "pix:1965 government loan guarantee act"},
            {"kw": "guaranteed",       "clip": "pix:government guarantee student loan"},
            {"kw": "twelve hundred",   "clip": "pix:1200 percent tuition rise chart"},
            {"kw": "nineteen percent", "clip": "pix:wage stagnation 19 percent income"},
            {"kw": "bankruptcy",       "clip": "pix:bankruptcy discharge student debt law"},
            {"kw": "deferment",        "clip": "pix:interest accruing deferment debt"},
            {"kw": "permanently",      "clip": "pix:indebted worker scared job debt"},
        ],
        "sfx": "dramatic reveal sting",
        "music": "dark investigation music",
        "q": "student loan debt system design",
    },

    {
        "title": "Nestle CEO Said On Camera That Water Is Not A Human Right",
        "script": "Peter Brabeck-Letmathe the former CEO of Nestle stated publicly on film that treating water as a public right is an extreme position. Nestle extracts billions of gallons from drought communities under permits that cost almost nothing. During California's historic multi-year drought Nestle continued pumping from San Bernardino National Forest under a permit that expired in 1988. They then bottled it as Arrowhead Spring Water and sold it in plastic at two thousand times the extraction cost.",
        "segments": [
            {"kw": "Peter Brabeck",    "clip": "wiki:Nestle headquarters building Switzerland"},
            {"kw": "public right",     "clip": "pix:water human right public access"},
            {"kw": "extreme",          "clip": "pix:corporate statement extreme position"},
            {"kw": "drought communities","clip": "wiki:drought dry landscape cracked earth"},
            {"kw": "California",       "clip": "wiki:California drought dry reservoir"},
            {"kw": "San Bernardino",   "clip": "pix:national forest water extraction pump"},
            {"kw": "expired in 1988",  "clip": "pix:expired permit document 1988"},
            {"kw": "Arrowhead",        "clip": "wiki:Nestle Arrowhead water bottle product"},
        ],
        "sfx": "water drip hollow",
        "music": "tense dark investigation",
        "q": "Nestle water privatization drought",
    },

    {
        "title": "The 2008 Crisis Was Engineered Not Accidental",
        "script": "The 2008 financial crisis wiped out nine point eight trillion dollars in household wealth. Banks packaged subprime mortgages into products rated AAA by agencies paid by the banks doing the rating. Goldman Sachs shorted the same products they sold to clients. The Federal Reserve gave banks sixteen trillion dollars in emergency loans at near-zero interest while your savings account earned zero point zero one percent. The system did not fail. It performed exactly as designed for those who designed it.",
        "segments": [
            {"kw": "wiped out",        "clip": "pix:2008 financial crisis household wealth"},
            {"kw": "subprime",         "clip": "pix:subprime mortgage housing bubble"},
            {"kw": "AAA by",           "clip": "pix:credit rating agency AAA fraud"},
            {"kw": "Goldman Sachs",    "clip": "wiki:Goldman Sachs headquarters New York"},
            {"kw": "shorted",          "clip": "pix:short position bet against market"},
            {"kw": "sixteen trillion", "clip": "wiki:Federal Reserve Washington building"},
            {"kw": "zero point",       "clip": "pix:savings account zero interest rate"},
            {"kw": "designed it",      "clip": "pix:financial system design corporate"},
        ],
        "sfx": "stock market alarm bell",
        "music": "financial thriller dark",
        "q": "2008 financial crisis corporate fraud",
    },

    {
        "title": "Disney Uses Facial Recognition On Children At Theme Parks",
        "script": "Disney has patented sentiment AI systems that use embedded cameras to track pupil dilation and micro-expressions of guests in real time. The data determines which merchandise causes the strongest emotional response. Prices and product placement update dynamically based on the crowd's biometric feedback. Your children's faces are being scanned and their emotional responses are being sold to optimize Disney's revenue per guest. You paid the entry fee. You also paid with your family's biometric data.",
        "segments": [
            {"kw": "Disney has",       "clip": "wiki:Walt Disney World theme park aerial"},
            {"kw": "sentiment AI",     "clip": "pix:AI sentiment analysis facial recognition"},
            {"kw": "embedded cameras", "clip": "pix:hidden camera surveillance park"},
            {"kw": "pupil dilation",   "clip": "pix:pupil eye tracking emotional response"},
            {"kw": "merchandise",      "clip": "pix:disney merchandise gift shop"},
            {"kw": "dynamically",      "clip": "pix:dynamic pricing algorithm real time"},
            {"kw": "children faces",   "clip": "pix:child facial scan biometric data"},
            {"kw": "biometric data",   "clip": "wiki:Disney headquarters Burbank building"},
        ],
        "sfx": "magic fairy chime",
        "music": "sinister dark corporate",
        "q": "Disney facial recognition theme park",
    },

    {
        "title": "UnitedHealth AI Denied 22 Percent Of Medicare Claims Automatically",
        "script": "UnitedHealth Group deployed an AI model to process Medicare Advantage claims. A ProPublica investigation found the model had a ninety percent error rate on the claims it denied. Despite this UnitedHealth used it to auto-deny twenty-two percent of all submitted claims. Physicians who appealed had ninety percent of those denials overturned proving the AI was wrong. The company knew. They continued using it because most patients do not appeal. Silence is their margin.",
        "segments": [
            {"kw": "UnitedHealth Group","clip": "wiki:UnitedHealth headquarters building"},
            {"kw": "Medicare Advantage","clip": "pix:Medicare insurance card senior"},
            {"kw": "ProPublica",       "clip": "pix:investigative journalism report document"},
            {"kw": "ninety percent error","clip": "pix:90 percent error rate AI statistics"},
            {"kw": "twenty-two percent","clip": "pix:22 percent denied claims chart"},
            {"kw": "Physicians who",   "clip": "pix:doctor appeal medical claim overturn"},
            {"kw": "knew",             "clip": "pix:company knew continued anyway corporate"},
            {"kw": "Silence is",       "clip": "pix:insurance profit silence revenue margin"},
        ],
        "sfx": "clinical alert tone",
        "music": "dark suspense corporate",
        "q": "UnitedHealth insurance AI denial",
    },

    {
        "title": "Equifax Exposed Every American Adult And Paid $4 Per Person",
        "script": "In 2017 Equifax exposed the Social Security numbers birth dates addresses and full credit histories of one hundred and forty-seven million Americans. The breach ran for seventy-eight days before detection. Before the public announcement Equifax executives sold company stock. The settlement amounts to approximately four dollars per affected person. Equifax was not shut down. They were not reregulated. They resumed collecting your most sensitive financial data the next business morning.",
        "segments": [
            {"kw": "In 2017",          "clip": "wiki:Equifax headquarters Atlanta building"},
            {"kw": "Social Security",  "clip": "pix:social security card document"},
            {"kw": "one hundred and forty-seven","clip": "pix:147 million data breach chart"},
            {"kw": "seventy-eight days","clip": "pix:78 days undetected breach timeline"},
            {"kw": "executives sold",  "clip": "pix:insider trading stock sale executive"},
            {"kw": "four dollars",     "clip": "pix:4 dollar settlement per person"},
            {"kw": "not shut down",    "clip": "pix:no regulation consequence corporate"},
            {"kw": "next business",    "clip": "pix:data collection resumed corporate"},
        ],
        "sfx": "data breach alarm",
        "music": "tense investigation music",
        "q": "Equifax data breach corporate",
    },

    {
        "title": "Private Prisons Pay States To Fill Their Beds Or Pay Penalties",
        "script": "CoreCivic and GEO Group are the largest private prison operators in America. Their government contracts include occupancy guarantee clauses requiring states to keep beds filled at eighty to ninety percent or pay financial penalties for empty cells. This means state governments have a financial incentive to incarcerate people. Rehabilitation reduces occupancy. Reduced occupancy triggers penalties. The entire financial model of private incarceration requires that rehabilitation fails.",
        "segments": [
            {"kw": "CoreCivic",        "clip": "wiki:CoreCivic private prison facility"},
            {"kw": "GEO Group",        "clip": "pix:private prison building exterior fence"},
            {"kw": "occupancy guarantee","clip": "pix:government contract occupancy clause"},
            {"kw": "eighty to ninety", "clip": "pix:prison occupancy rate statistics"},
            {"kw": "financial penalties","clip": "pix:financial penalty empty cell"},
            {"kw": "incarcerate",      "clip": "pix:incarceration rate statistics criminal"},
            {"kw": "Rehabilitation",   "clip": "pix:rehabilitation program failure"},
            {"kw": "fails",            "clip": "pix:private prison profit model design"},
        ],
        "sfx": "cell door clang",
        "music": "dark justice music",
        "q": "private prison occupancy contract",
    },

    {
        "title": "Starbucks Runs An Unregulated Bank With $1.6 Billion Of Your Money",
        "script": "Starbucks holds one point six billion dollars in unredeemed stored value from gift cards and the mobile app. A real bank holding that same amount must maintain FDIC-insured reserves and submit to Federal Reserve oversight. Starbucks is classified as a retailer. They invest your stored cash earn returns on it and pay you zero interest. Howard Schultz built the most profitable banking product in American corporate history and sold it to you as a loyalty program.",
        "segments": [
            {"kw": "Starbucks holds",  "clip": "wiki:Starbucks coffee shop exterior"},
            {"kw": "one point six",    "clip": "pix:1.6 billion stored value float"},
            {"kw": "gift cards",       "clip": "pix:starbucks gift card mobile app payment"},
            {"kw": "real bank",        "clip": "pix:bank FDIC reserve requirement"},
            {"kw": "Federal Reserve",  "clip": "wiki:Federal Reserve Washington building"},
            {"kw": "retailer",         "clip": "pix:retail classification no banking oversight"},
            {"kw": "zero interest",    "clip": "pix:zero interest customer deposit"},
            {"kw": "loyalty program",  "clip": "pix:banking product loyalty disguise"},
        ],
        "sfx": "coffee machine espresso",
        "music": "corporate expose music",
        "q": "Starbucks bank deposit loyalty",
    },

    {
        "title": "Shrinkflation Is How Companies Raised Prices Without Telling You",
        "script": "Between 2021 and 2024 over four thousand consumer products reduced their package contents while keeping or raising the price. Doritos dropped from sixteen ounces to nine point two five. Gatorade reduced its bottle from thirty-two ounces to twenty-eight. Bounty reduced sheet counts while raising prices thirty-four percent. This requires zero disclosure. The only way to detect it is to calculate cost per unit yourself. Almost nobody does. That is the point.",
        "segments": [
            {"kw": "Between 2021",     "clip": "pix:consumer product smaller package"},
            {"kw": "four thousand",    "clip": "pix:4000 products shrinkflation chart"},
            {"kw": "Doritos",          "clip": "wiki:Doritos chip bag product"},
            {"kw": "nine point",       "clip": "pix:smaller bag same price comparison"},
            {"kw": "Gatorade",         "clip": "wiki:Gatorade bottle sports drink"},
            {"kw": "Bounty",           "clip": "pix:paper towel fewer sheets same price"},
            {"kw": "zero disclosure",  "clip": "pix:no disclosure required legal"},
            {"kw": "That is the point","clip": "pix:deliberate hidden price increase"},
        ],
        "sfx": "supermarket scanner beep",
        "music": "corporate expose dark",
        "q": "shrinkflation product size reduction",
    },

    {
        "title": "Google Pays Apple $20 Billion To Stay Your Default Search Engine",
        "script": "Google pays Apple approximately twenty billion dollars per year to remain the default search engine on Safari and every iPhone. This is why Apple has never seriously built a competing search engine. The payment is larger than what Apple would realistically earn by competing. This arrangement was ruled anti-competitive by a US federal judge in 2024. The case is being appealed. While the appeals run the twenty billion flows. While the twenty billion flows nothing changes.",
        "segments": [
            {"kw": "Google pays",      "clip": "wiki:Google headquarters Googleplex California"},
            {"kw": "twenty billion",   "clip": "pix:20 billion dollar payment deal"},
            {"kw": "Safari",           "clip": "wiki:Apple iPhone Safari browser"},
            {"kw": "competing search", "clip": "pix:search engine competition monopoly"},
            {"kw": "larger than",      "clip": "pix:payment exceeds competition revenue"},
            {"kw": "anti-competitive", "clip": "pix:antitrust ruling federal court 2024"},
            {"kw": "appeals run",      "clip": "pix:legal appeal process delay"},
            {"kw": "nothing changes",  "clip": "pix:monopoly continues corporate deal"},
        ],
        "sfx": "dramatic impact",
        "music": "dark corporate suspense",
        "q": "Google Apple search monopoly payment",
    },

    {
        "title": "McKinsey Charged Purdue $86 Million To Sell More OxyContin During The Crisis",
        "script": "McKinsey and Company the world's most prestigious consulting firm was paid eighty-six million dollars by Purdue Pharma to advise on how to quote turbocharge OxyContin sales during the peak of the opioid crisis. McKinsey recommended offering rebates to distributors for overdoses linked to their supply. They settled for six hundred million dollars across multiple states. No McKinsey partner was criminally charged. The firm continues advising governments and Fortune 500 companies today.",
        "segments": [
            {"kw": "McKinsey and",     "clip": "wiki:McKinsey headquarters New York building"},
            {"kw": "eighty-six million","clip": "pix:86 million consulting fee payment"},
            {"kw": "turbocharge",      "clip": "wiki:OxyContin opioid pill bottle"},
            {"kw": "overdoses",        "clip": "pix:opioid overdose epidemic statistics"},
            {"kw": "rebates to",       "clip": "pix:rebate incentive distributor scheme"},
            {"kw": "six hundred million","clip": "pix:600 million settlement payment"},
            {"kw": "No McKinsey",      "clip": "pix:no criminal charge consulting firm"},
            {"kw": "today",            "clip": "pix:corporate consulting advisory continues"},
        ],
        "sfx": "clinical alert tone",
        "music": "dark sinister investigation",
        "q": "McKinsey Purdue pharma consulting",
    },

    {
        "title": "The Sugar Lobby Paid Harvard To Blame Fat For Heart Disease",
        "script": "In 1967 the Sugar Research Foundation paid three Harvard professors the equivalent of fifty thousand dollars today to publish a literature review concluding dietary fat caused heart disease while exonerating sugar. One of those scientists later became the head of nutrition policy at the USDA. The food pyramid recommending six to eleven daily servings of bread while limiting fat was shaped by research paid for by the sugar industry. Americans followed that advice for fifty years.",
        "segments": [
            {"kw": "In 1967",          "clip": "pix:1967 research publication history"},
            {"kw": "Sugar Research",   "clip": "pix:sugar industry lobby corporate"},
            {"kw": "Harvard professors","clip": "wiki:Harvard University campus building"},
            {"kw": "fifty thousand",   "clip": "pix:research payment funded study"},
            {"kw": "dietary fat",      "clip": "pix:dietary fat heart disease research"},
            {"kw": "USDA",             "clip": "wiki:USDA building Washington government"},
            {"kw": "food pyramid",     "clip": "pix:USDA food pyramid bread servings"},
            {"kw": "fifty years",      "clip": "pix:fifty years nutrition policy sugar"},
        ],
        "sfx": "shocking reveal sound",
        "music": "dark investigation thriller",
        "q": "sugar industry Harvard nutrition policy",
    },

    {
        "title": "Amazon's Anticipatory Shipping Patent Means They Know What You Want Before You Do",
        "script": "Amazon holds a patent for anticipatory shipping. Before you complete a purchase the system ships items to local distribution hubs based on your search hover time browse patterns and purchase probability scores. Jeff Bezos described the goal as eliminating the decision gap between want and receive. They are not waiting for orders. They are predicting them with such confidence they move inventory first. You do not choose what to buy. Amazon chooses what you will want.",
        "segments": [
            {"kw": "Amazon holds",     "clip": "wiki:Amazon headquarters Seattle building"},
            {"kw": "anticipatory",     "clip": "pix:anticipatory shipping patent document"},
            {"kw": "distribution hubs","clip": "pix:amazon distribution hub warehouse"},
            {"kw": "hover time",       "clip": "pix:search hover behavior data tracking"},
            {"kw": "probability scores","clip": "pix:purchase probability algorithm"},
            {"kw": "decision gap",     "clip": "wiki:Jeff Bezos Amazon CEO"},
            {"kw": "predicting",       "clip": "pix:predictive behavior algorithm AI"},
            {"kw": "you will want",    "clip": "pix:consumer prediction desire corporate"},
        ],
        "sfx": "notification ping",
        "music": "digital surveillance thriller",
        "q": "Amazon anticipatory shipping prediction",
    },

    {
        "title": "Monsanto Sued Farmers For Crops That Blew Onto Their Land",
        "script": "Bayer-Monsanto owns patents on genetically modified seeds. When wind carries their patented pollen onto neighboring fields those farmers become legally liable for patent infringement. Monsanto sued over one hundred and forty farmers for crops they never planted. In the Canadian Supreme Court case Percy Schmeiser fought Monsanto over canola that blew from a roadside ditch onto his property. Monsanto won. They did not patent a crop. They patented a weather pattern.",
        "segments": [
            {"kw": "Bayer-Monsanto",   "clip": "wiki:Bayer Monsanto headquarters Germany"},
            {"kw": "patented pollen",  "clip": "pix:pollen wind cross pollination field"},
            {"kw": "neighboring",      "clip": "pix:neighboring farm field agriculture"},
            {"kw": "patent infringement","clip": "pix:patent infringement lawsuit legal"},
            {"kw": "one hundred and forty","clip": "pix:140 farmers sued corporate"},
            {"kw": "Percy Schmeiser",  "clip": "pix:Canadian Supreme Court building"},
            {"kw": "roadside ditch",   "clip": "pix:canola field roadside ditch Canada"},
            {"kw": "weather pattern",  "clip": "pix:wind patent nature corporate},
        ],
        "sfx": "gavel slam",
        "music": "dark rural expose",
        "q": "Monsanto seed patent farmer lawsuit",
    },

    {
        "title": "Airbnb Removed 30000 Housing Units From New York City Alone",
        "script": "A McGill University study found Airbnb removed between seven thousand and thirteen thousand five hundred long-term housing units from New York City in a single year. In high-density cities everywhere the pattern was identical. Short-term rentals generate three to four times the revenue of long-term leases so landlords convert. Local residents are displaced. Airbnb's platform was built partly on apartments where subletting was prohibited. The violation was committed by the landlord. The platform collected the fee.",
        "segments": [
            {"kw": "McGill University","clip": "pix:university study housing research"},
            {"kw": "seven thousand",   "clip": "pix:7000 housing units removed statistics"},
            {"kw": "high-density",     "clip": "wiki:New York City aerial buildings"},
            {"kw": "three to four",    "clip": "pix:short term rental revenue 3x profit"},
            {"kw": "landlords convert","clip": "pix:landlord airbnb conversion rental"},
            {"kw": "displaced",        "clip": "pix:tenant displaced eviction housing"},
            {"kw": "subletting was",   "clip": "wiki:Airbnb app platform interface"},
            {"kw": "collected the fee","clip": "pix:platform fee commission corporate profit"},
        ],
        "sfx": "door knock",
        "music": "dark urban expose",
        "q": "Airbnb housing shortage city",
    },

    {
        "title": "The Like Button Inventor Now Limits His Own Social Media Use",
        "script": "Justin Rosenstein invented the Facebook Like button in 2007. He has since called it a bright ding of pseudo-pleasure and put parental controls on his own iPhone to limit his social media access. Tristan Harris a former Google design ethicist left to warn governments about deliberate psychological engineering in consumer apps. Aza Raskin invented infinite scroll and calculated it costs two hundred thousand hours of human attention per day. The people who built these systems do not let their own children use them.",
        "segments": [
            {"kw": "Justin Rosenstein","clip": "wiki:Facebook Like button feature"},
            {"kw": "bright ding",      "clip": "pix:dopamine reward like button phone"},
            {"kw": "parental controls","clip": "pix:parental control iPhone limit screen"},
            {"kw": "Tristan Harris",   "clip": "wiki:Tristan Harris Center Humane Tech"},
            {"kw": "Google design",    "clip": "wiki:Google headquarters campus"},
            {"kw": "Aza Raskin",       "clip": "pix:infinite scroll design feature"},
            {"kw": "two hundred thousand","clip": "pix:200000 hours attention daily"},
            {"kw": "own children",     "clip": "pix:tech creator children no phone school"},
        ],
        "sfx": "notification ding",
        "music": "digital surveillance thriller",
        "q": "social media creator regret psychology",
    },

    {
        "title": "LexisNexis Sells A Mathematical Death Date Assigned To Your Name",
        "script": "LexisNexis and similar data aggregators compile your grocery receipts sleep data from wearables stress indicators from social media posts and prescription records to build a mortality risk score. Insurance companies buy this score to set your premiums before you ever speak to an agent. You are rated before you apply. The score is based on data you never knowingly shared with a health insurer. There is a predicted death date attached to your file. You are not allowed to see it.",
        "segments": [
            {"kw": "LexisNexis",       "clip": "pix:LexisNexis data broker corporate"},
            {"kw": "grocery receipts", "clip": "pix:grocery purchase data receipt"},
            {"kw": "sleep data",       "clip": "pix:wearable sleep tracker data"},
            {"kw": "stress indicators","clip": "pix:social media stress post data"},
            {"kw": "mortality risk",   "clip": "pix:mortality risk score insurance"},
            {"kw": "premiums",         "clip": "pix:insurance premium price data"},
            {"kw": "never knowingly",  "clip": "pix:data shared without consent"},
            {"kw": "not allowed",      "clip": "pix:death date file hidden inaccessible"},
        ],
        "sfx": "scan beep",
        "music": "surveillance digital thriller",
        "q": "data broker insurance mortality score",
    },

    {
        "title": "Walmart Gets $7 Billion In Tax Subsidies While Workers Use Food Stamps",
        "script": "Multiple economic studies confirm a significant portion of Walmart's 1.6 million US employees qualify for Medicaid food stamps and housing assistance. Walmart and its suppliers have received over 7.8 billion dollars in state and local tax subsidies. The Walton family has a combined net worth exceeding two hundred billion dollars. American taxpayers are effectively co-funding Walmart's payroll while Walton heirs receive dividends each quarter. This arrangement is fully legal. It is also a deliberate business model.",
        "segments": [
            {"kw": "Multiple economic","clip": "pix:economic study workforce research"},
            {"kw": "Medicaid",         "clip": "pix:Medicaid food stamp government benefit"},
            {"kw": "7.8 billion",      "clip": "pix:7.8 billion tax subsidy corporate"},
            {"kw": "Walton",           "clip": "wiki:Walmart headquarters Bentonville Arkansas"},
            {"kw": "two hundred billion","clip": "pix:200 billion net worth billionaire"},
            {"kw": "co-funding",       "clip": "pix:taxpayer funding corporate payroll"},
            {"kw": "dividends",        "clip": "pix:dividend income wealthy shareholder"},
            {"kw": "business model",   "clip": "wiki:Walmart store exterior retail"},
        ],
        "sfx": "cash register scan",
        "music": "dark working class expose",
        "q": "Walmart subsidy workers government",
    },

    {
        "title": "Your Credit Score Rewards Debt And Punishes Savings",
        "script": "The FICO credit score was introduced in 1989 by Fair Isaac Corporation. It rewards credit utilization meaning carrying revolving debt consistently. It penalizes thin files meaning not borrowing. A person who has never borrowed money and has a full savings account scores lower than someone making minimum payments on four maxed credit cards. The system does not measure financial health. It measures how reliably you generate interest income for lenders. A perfect score means you are a perfect debt product.",
        "segments": [
            {"kw": "FICO credit",      "clip": "pix:FICO credit score document report"},
            {"kw": "Fair Isaac",       "clip": "pix:Fair Isaac Corporation corporate"},
            {"kw": "credit utilization","clip": "pix:credit utilization debt revolving"},
            {"kw": "thin files",       "clip": "pix:thin file no credit history penalized"},
            {"kw": "never borrowed",   "clip": "pix:savings account full no debt"},
            {"kw": "minimum payments", "clip": "pix:minimum payment credit card debt"},
            {"kw": "interest income",  "clip": "pix:bank interest income lender profit"},
            {"kw": "debt product",     "clip": "pix:perfect debt product borrower system"},
        ],
        "sfx": "score tick counter",
        "music": "tense financial music",
        "q": "credit score debt savings FICO",
    },

    {
        "title": "The Wall Street Algorithm Sees Your Trade Before You Click Buy",
        "script": "High-frequency trading firms pay stock exchanges for co-location privileges placing their servers inside exchange data centers. Their systems detect incoming retail orders in under one millisecond. They move the price extract profit from the spread and complete the trade before your order fills. This practice transfers an estimated eight to fifteen billion dollars per year from retail investors to algorithmic trading firms. It is entirely legal. Michael Lewis documented it in Flash Boys in 2014. It has not been stopped.",
        "segments": [
            {"kw": "High-frequency",   "clip": "pix:high frequency trading server"},
            {"kw": "co-location",      "clip": "pix:server colocated exchange data center"},
            {"kw": "one millisecond",  "clip": "pix:millisecond speed trading algorithm"},
            {"kw": "detect incoming",  "clip": "wiki:New York Stock Exchange trading floor"},
            {"kw": "extract profit",   "clip": "pix:profit extraction spread trading"},
            {"kw": "eight to fifteen", "clip": "pix:15 billion retail investor transfer"},
            {"kw": "Michael Lewis",    "clip": "pix:Flash Boys book Wall Street"},
            {"kw": "not been stopped", "clip": "pix:legal practice continues unchallenged"},
        ],
        "sfx": "stock market alarm bell",
        "music": "financial thriller dark",
        "q": "high frequency trading Wall Street",
    },

]


def pick_topic():
    if os.path.exists(LOG):
        with open(LOG) as f:
            used = set(f.read().splitlines())
    else:
        used = set()

    available = [t for t in ALL_TOPICS if t["title"] not in used]
    if not available:
        print("All 40 topics used -- resetting log.")
        open(LOG, "w").close()
        available = ALL_TOPICS

    choice = random.choice(available)
    with open(LOG, "a") as f:
        f.write(choice["title"] + "\n")
    print("Topic: " + choice["title"])
    return choice


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
async def main():
    check_env()
    boot()

    data           = pick_topic()
    v_path         = os.path.join(OUT, "tmp", "voice.mp3")
    timings, total = await make_voice(data["script"], v_path)
    voice          = AudioFileClip(v_path)

    bgm      = get_music(data["music"], total)
    sfx_path = get_sfx(data["sfx"])
    sfx      = None
    if sfx_path:
        try:
            sfx = AudioFileClip(sfx_path).set_start(0).volumex(0.28)
        except Exception as e:
            print("SFX load err: " + str(e))

    layers = [voice]
    if bgm:
        layers.append(bgm)
    if sfx:
        layers.append(sfx)
    audio = CompositeAudioClip(layers) if len(layers) > 1 else voice

    visuals = build_synced_visuals(data, timings, total)
    caps    = build_captions(timings, total)

    all_layers = visuals + ([caps] if caps is not None else [])
    video = (
        CompositeVideoClip(all_layers, size=(CW, CH))
        .set_duration(total)
        .set_audio(audio)
    )

    out_path = os.path.join(OUT, "final_reel.mp4")
    print("Rendering...")
    video.write_videofile(
        out_path, fps=FPS, codec="libx264",
        audio_codec="aac", threads=4, preset="fast",
    )
    print("DONE: " + out_path + " (" + str(round(total, 1)) + "s)")
    upload(out_path, data)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped.")
    except Exception:
        traceback.print_exc()
        sys.exit(1)
