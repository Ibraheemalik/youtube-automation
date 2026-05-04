import asyncio
import os
import random
import requests
import json
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import *
import moviepy.video.fx.all as vfx
import edge_tts
from google import genai
from google.genai import types
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# --- 1. CONFIG & SAFETY ---
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
PIXABAY_KEY = os.getenv("PIXABAY_API_KEY")
WIDTH, HEIGHT = 1080, 1920
TEMP, OUTPUT = "temp", "output"
[os.makedirs(d, exist_ok=True) for d in [TEMP, OUTPUT]]

# Asset Fallbacks
FONT_PATH = "fonts/Bold.ttf" if os.path.exists("fonts/Bold.ttf") else None
HAS_TOKEN = os.path.exists("token.json")

# --- 2. WIKIMEDIA & PIXABAY SCRAPER ---
def get_wikimedia_image(query):
    """Fetches high-res context images from Wikimedia Commons."""
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "prop": "pageimages|imageinfo",
        "titles": query,
        "pithumbsize": 1080,
        "iiprop": "url",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrlimit": 1
    }
    try:
        res = requests.get(url, params=params).json()
        pages = res.get("query", {}).get("pages", {})
        for p in pages.values():
            return p.get("thumbnail", {}).get("source")
    except: return None

def get_pixabay_video(query):
    """Fetches dark/silhouette B-roll from Pixabay."""
    safe_query = f"{query} dark silhouette"
    url = f"https://pixabay.com/api/videos/?key={PIXABAY_KEY}&q={requests.utils.quote(safe_query)}&orientation=vertical"
    try:
        res = requests.get(url).json()
        return res['hits'][0]['videos']['large']['url'] if res['hits'] else None
    except: return None

# --- 3. CINEMATIC EFFECTS (ZOOM & SFX) ---
def apply_zoom_and_fx(clip, duration):
    """Applies the 1.0 -> 1.15 Cinematic Zoom (Ken Burns)."""
    return clip.resize(lambda t: 1.0 + 0.15 * (t/duration)).set_duration(duration)

# --- 4. YOUTUBE UPLOAD ENGINE ---
def upload_to_youtube(video_path, metadata):
    if not HAS_TOKEN:
        print("⚠️ No token.json found. Skipping upload.")
        return
    
    creds = Credentials.from_authorized_user_file('token.json')
    youtube = build('youtube', 'v3', credentials=creds)
    
    body = {
        'snippet': {
            'title': metadata['yt_title'],
            'description': f"{metadata['description']}\n\n#TrueCrime #RedditStories",
            'categoryId': '24'
        },
        'status': {'privacyStatus': 'public'}
    }
    
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    youtube.videos().insert(part='snippet,status', body=body, media_body=media).execute()
    print("🚀 Uploaded to YouTube!")

# --- 5. MAIN ASSEMBLY ---
async def production_run():
    # A. Determine Length (18m Weekday / 25m Sunday)
    target_len = 25 if datetime.now().weekday() == 6 else 18
    
    # B. Intro (0:00 - 0:10)
    print("🎬 Building Intro...")
    black = ColorClip((WIDTH, HEIGHT), color=(0,0,0)).set_duration(4)
    intro_vid_url = get_pixabay_video("hooded phone silhouette")
    if intro_vid_url:
        intro_vid = VideoFileClip(intro_vid_url, target_resolution=(HEIGHT, WIDTH)).subclip(0, 6)
        intro_vid = apply_zoom_and_fx(intro_vid, 6).fx(vfx.colorx, 0.7)
    else:
        intro_vid = ColorClip((WIDTH, HEIGHT), color=(0,0,50)).set_duration(6) # Dark blue fallback
    
    # C. Dynamic Story Loop (Wikimedia + Pixabay)
    # Gemini provides 'visual_cues' list
    visual_cues = ["dark hallway", "empty gym", "creepy attic"]
    clips = [black, intro_vid]
    
    for cue in visual_cues:
        # Try Wikimedia first for realism
        img_url = get_wikimedia_image(cue)
        if img_url:
            img_path = f"{TEMP}/wiki_{cue}.jpg"
            with open(img_path, 'wb') as f: f.write(requests.get(img_url).content)
            c = ImageClip(img_path).set_duration(5)
            clips.append(apply_zoom_and_fx(c, 5))
        else:
            # Fallback to Pixabay Video
            vid_url = get_pixabay_video(cue)
            if vid_url:
                c = VideoFileClip(vid_url, target_resolution=(HEIGHT, WIDTH)).subclip(0, 5)
                clips.append(apply_zoom_and_fx(c, 5))

    # D. Audio Layers (BGM & SFX)
    # Note: Ensure 'assets/bgm.mp3' exists for 8% volume eerie drone
    bgm_path = "assets/bgm.mp3"
    bgm = AudioFileClip(bgm_path).volumex(0.08).loop(duration=target_len*60) if os.path.exists(bgm_path) else None

    # E. Final Render
    final_video = concatenate_videoclips(clips, method="compose")
    if bgm: final_video = final_video.set_audio(bgm)
    
    output_path = f"{OUTPUT}/final_viral_video.mp4"
    final_video.write_videofile(output_path, fps=24, codec="libx264")
    
    # F. Upload
    meta = {"yt_title": "Terrifying Reddit Case", "description": "Viral Story"}
    upload_to_youtube(output_path, meta)

if __name__ == "__main__":
    asyncio.run(production_run())
