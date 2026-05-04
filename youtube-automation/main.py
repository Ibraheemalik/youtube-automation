import os
import json
import random
import requests
from moviepy.editor import *
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ================= ENV =================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
YT_API_KEY = os.getenv("YT_API_KEY")

OUTPUT_FILE = "final_output.mp4"


# ================= HIGH RPM TOPICS =================
TOPICS = [
    "AI predicting human future behavior",
    "A scientist enters simulated reality experiment",
    "The 4th dimension AI experiment goes wrong",
    "Machine starts rewriting reality rules",
    "Human consciousness uploaded to AI system",
    "AI discovers hidden layer of universe",
    "Time loop experiment controlled by AI",
    "A coder accidentally builds sentient system",
    "Simulation glitch causes disappearance",
    "AI begins rewriting human memories"
]


# ================= SEO HASHTAGS =================
HASHTAGS = [
    "#ai", "#shorts", "#science", "#tech", "#future",
    "#aiworld", "#simulation", "#mystery", "#story",
    "#viral", "#trending", "#space", "#technology",
    "#mindblown", "#documentary", "#futuretech",
    "#aiart", "#aivideo", "#innovation", "#unknown"
]


# ================= GEMINI SCRIPT =================
def generate_script(topic):
    if not GEMINI_API_KEY:
        topic = random.choice(TOPICS)

    prompt = f"""
Create a viral 60 second cinematic YouTube Short.

Theme: AI + reality distortion + sci-fi mystery

Rules:
- Hook in first 2 seconds
- Simple emotional storytelling
- Use: "He tried...", "Scientists discovered...", "Then everything changed..."
- No filler, no motivation speech

Topic: {topic}

Return JSON:
title, hook, scenes (5), final_twist, keywords
"""

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"

        res = requests.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}]
        })

        text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)

    except:
        return {
            "title": topic,
            "hook": topic,
            "scenes": [topic]*5,
            "final_twist": topic,
            "keywords": ["ai", "dark", "system", "code", "future"]
        }


# ================= WIKIMEDIA CLIPS =================
def fetch_clip(query):
    try:
        url = f"https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search&gsrsearch={query}&gsrlimit=1&prop=imageinfo&iiprop=url"

        res = requests.get(url).json()

        pages = res.get("query", {}).get("pages", {})

        for p in pages:
            return pages[p]["imageinfo"][0]["url"]

    except:
        return None


def get_clips(keywords):
    clips = []

    for k in keywords:
        clip = fetch_clip(k)
        if clip:
            clips.append(clip)

    if not clips:
        clips = ["fallback.mp4"]

    return clips


# ================= VIDEO BUILD =================
def create_video(clips):
    video_clips = []

    for c in clips:
        try:
            clip = VideoFileClip(c).subclip(0, 3)
            video_clips.append(clip)
        except:
            continue

    if not video_clips:
        raise Exception("No valid clips")

    final = concatenate_videoclips(video_clips, method="compose")
    final.write_videofile(OUTPUT_FILE, fps=24)


# ================= METADATA =================
def build_metadata(script):
    return {
        "title": script["title"],
        "description": script["final_twist"],
        "tags": HASHTAGS
    }


# ================= UPLOAD =================
def upload_video(file, meta):
    youtube = build("youtube", "v3", developerKey=YT_API_KEY)

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": meta["title"],
                "description": meta["description"],
                "tags": meta["tags"],
                "categoryId": "28"
            },
            "status": {
                "privacyStatus": "public"
            }
        },
        media_body=MediaFileUpload(file)
    )

    request.execute()


# ================= MAIN PIPELINE =================
def run():
    topic = random.choice(TOPICS)

    print("Generating script...")
    script = generate_script(topic)

    print("Fetching clips...")
    clips = get_clips(script["keywords"])

    print("Creating video...")
    create_video(clips)

    print("Building metadata...")
    meta = build_metadata(script)

    print("Uploading...")
    upload_video(OUTPUT_FILE, meta)

    print("DONE.")


if __name__ == "__main__":
    run()
