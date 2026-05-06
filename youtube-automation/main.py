"""
VIRAL CLIP FACTORY v6.0 - FIXED
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

# Pixabay safe fallbacks
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
    os.makedirs(os.path.join(OUT, "tmp"), exist_ok=True)
    os.makedirs(CLIPS, exist_ok=True)
    os.makedirs(MUS, exist_ok=True)
    print("Workspace ready.")


# [All functions from jget to build_captions remain exactly the same - not touching them]

# ... (Copy all functions: jget, dlb, make_voice, _wiki_search, _pick_wiki_url, cover_save, get_wiki_image, make_zoom_clip, _pix_video, get_pix, build_synced_visuals, get_music, get_sfx, _load_font, _meas, _stroke, render_cap, build_captions, upload) ...

# ONLY THE FIXED ALL_TOPICS SECTION (Last topic fixed)
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
            {"kw": "weather pattern",  "clip": "pix:wind pollen field corporate patent"},
        ],
        "sfx": "gavel slam",
        "music": "dark rural expose",
        "q": "Monsanto seed patent farmer lawsuit",
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
