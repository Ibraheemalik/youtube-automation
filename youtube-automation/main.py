from story_engine import generate_story
from script_engine import build_script
from render_engine import render
from seo_engine import generate_seo, thumbnail_prompt
from audio_engine import get_audio
from upload_engine import upload
from analytics_engine import analytics
from config import DURATION, UPLOAD_TIMES
import random

def run(topic="reddit horror", day="monday", manual=True):

    print("\n🚀 YOUTUBE AI FACTORY")

    # Story
    story = generate_story(topic)

    # Duration logic
    duration = DURATION["sunday"] if day == "sunday" else random.randint(
        DURATION["min"], DURATION["max"]
    )

    # Script
    script = build_script(story, duration)

    # Render
    render(script)

    # SEO
    seo = generate_seo(topic)

    # Thumbnail
    thumb = thumbnail_prompt(topic)

    # Audio
    audio = get_audio()

    # Upload
    mode = "MANUAL" if manual else f"SCHEDULED {UPLOAD_TIMES[day]}"

    vid = upload(seo["titles"], thumb, mode)

    # Analytics
    stats = analytics()

    print("\n🔥 FINAL OUTPUT")
    print({
        "video": vid,
        "stats": stats,
        "audio": audio,
        "duration": duration
    })


if __name__ == "__main__":
    run()
