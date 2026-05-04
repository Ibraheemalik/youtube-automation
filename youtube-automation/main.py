import asyncio
import os
import random
import requests
import schedule
import time
from datetime import datetime
from dotenv import load_dotenv
from moviepy.editor import *
from PIL import Image, ImageDraw, ImageFont, ImageOps
import google.generativeai as genai
import edge_tts
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# ===================== CONFIG & SETUP =====================
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
PIXABAY_KEY = os.getenv("PIXABAY_API_KEY")

VOICE = "en-US-GuyNeural"
CUT_RATE = 1.8 # Fast pacing
WIDTH, HEIGHT = 1080, 1920
OUTPUT = "output"
TEMP = "temp"
os.makedirs(OUTPUT, exist_ok=True)
os.makedirs(TEMP, exist_ok=True)

# ===================== 30 FALLBACK TOPICS =====================
FALLBACK_TOPICS = [
    {"title": "The Stranger in the Backseat", "text": "A late-night drive turns terrifying when the driver spots someone hiding in the rearview mirror."},
    {"title": "Footsteps in the Attic", "text": "Living alone in a remote cabin, the homeowner hears heavy boots pacing upstairs every night at 3 AM."},
    {"title": "The Smiling Man", "text": "A midnight walk turns into a nightmare when a pedestrian is followed by a man grinning unnaturally."},
    {"title": "The Deep Woods Cabin", "text": "Hikers find a pristine cabin in the woods, but the photo album inside only has pictures of them sleeping."},
    {"title": "Left on Read", "text": "Getting text messages from a phone that was buried with a loved one six months ago."},
    {"title": "The Fake Cop", "text": "Pulled over on a deserted highway by a police car, but the officer's uniform is completely wrong."},
    {"title": "Night Shift Terror", "text": "A gas station attendant notices the same car circling the pumps for four hours in the dead of night."},
    {"title": "The Uninvited Roommate", "text": "Food goes missing, items move, and a hidden camera reveals someone living in the air vents."},
    {"title": "Don't Look Under the Bed", "text": "A child says there's a monster under the bed. The parent looks and finds an escaped convict hiding."},
    {"title": "The Craigslist Encounter", "text": "Meeting a stranger to buy a vintage item, only to realize the house is abandoned and a trap."},
    {"title": "The Hitchhiker's Warning", "text": "A hitchhiker is picked up, but begs to be let out immediately after seeing the driver's face."},
    {"title": "The Doppelganger", "text": "Returning home to find family members acting strangely, claiming you've been home all day."},
    {"title": "The Locked Room", "text": "Waking up to find every door and window locked from the outside."},
    {"title": "The Abandoned Hospital", "text": "Urban explorers get separated in a dark asylum and hear their names being whispered over the dead intercom."},
    {"title": "The Midnight Caller", "text": "Receiving voicemails from yourself, timestamped 24 hours in the future, screaming for help."},
    {"title": "The Hotel Peephole", "text": "Looking through a hotel door peephole and seeing nothing but solid red. It was someone's eye."},
    {"title": "The Forest Staircase", "text": "Finding an isolated, carpeted staircase deep in the national park that rangers refuse to acknowledge."},
    {"title": "The Babysitter's Nightmare", "text": "The parents call to check in and tell the babysitter: 'We don't have a clown statue.'"},
    {"title": "The Deep Web Package", "text": "Receiving an unordered package containing exact replicas of your house keys and a map."},
    {"title": "The Radio Static", "text": "Driving through a dead zone, the radio picks up a local broadcast reading out your current GPS coordinates."},
    {"title": "The Elevator Game", "text": "Following an urban legend's rules in an empty office building, only for the doors to open to a parallel, silent world."},
    {"title": "The Campfire Story", "text": "Friends telling scary stories realize a stranger has quietly joined their circle in the dark."},
    {"title": "The Subvay Stalker", "text": "Being the only person on a late-night train with a passenger who won't stop making unbroken eye contact."},
    {"title": "The Baby Monitor", "text": "Hearing a deep voice comforting the baby over the monitor when you are the only adult home."},
    {"title": "The Mirror Reflection", "text": "Turning off the bathroom light, but the reflection in the mirror reaches for the switch to turn it back on."},
    {"title": "The Dog Walker", "text": "Your dog refuses to enter a specific patch of woods, barking at empty air that slowly starts casting a shadow."},
    {"title": "The Sleepwalker", "text": "Setting up a camera to catch sleepwalking, only to record yourself standing over your partner with a knife."},
    {"title": "The Wrong House", "text": "Drunk and tired, you enter your apartment, go to sleep, and wake up to a family making breakfast who have never seen you before."},
    {"title": "The Taxi Ride", "text": "The taxi driver takes a wrong turn into a dark industrial park, locks the doors, and turns off the meter."},
    {"title": "The Polaroid Camera", "text": "Finding an old camera. Every picture taken of an empty room shows a tall, faceless figure getting closer to the lens."}
]

# ===================== CORE FUNCTIONS =====================

def fetch_reddit_story():
    """Fetches terrifying real stories from Reddit via pullpush, or falls back to the 30 hardcoded list."""
    try:
        url = "https://be.api.pullpush.io/reddit/search/submission/?subreddit=LetsNotMeet,CreepyEncounters,TrueCrime&size=15"
        res = requests.get(url, timeout=10).json()
        posts = [p for p in res['data'] if len(p.get('selftext', '')) > 2500] # Ensure long stories
        if posts:
            post = random.choice(posts)
            return {"title": post['title'], "text": post['selftext']}
    except Exception as e:
        print("⚠️ Reddit fetch failed, using fallback topic...")
    
    return random.choice(FALLBACK_TOPICS)

def fetch_visuals(query, index):
    """Fetches images from Pixabay based on keywords."""
    img_path = f"{TEMP}/img_{index}.jpg"
    try:
        url = f"https://pixabay.com/api/?key={PIXABAY_KEY}&q={requests.utils.quote(query)}&image_type=photo&orientation=vertical&safesearch=true"
        res = requests.get(url, timeout=10).json()
        if res['hits']:
            img_url = res['hits'][0]['largeImageURL']
            img_data = requests.get(img_url, timeout=10).content
            with open(img_path, "wb") as f:
                f.write(img_data)
            return img_path
    except:
        pass
    return None

def apply_effects(image_path, duration):
    """Applies Ken Burns zoom and a slight freeze effect at the end."""
    img = Image.open(image_path)
    img = ImageOps.fit(img, (WIDTH, HEIGHT), centering=(0.5, 0.5), method=Image.Resampling.LANCZOS)
    img.save(image_path)
    
    clip = ImageClip(image_path).set_duration(duration)
    # Ken burns zoom in
    zoomed_clip = clip.resize(lambda t: 1.0 + 0.15 * (t / duration))
    return zoomed_clip

def generate_thumbnail(image_path, title, output_path):
    """Creates a cinematic thumbnail."""
    try:
        img = Image.open(image_path).convert("RGBA")
        img = img.resize((1280, 720))
        
        # Add dark vignette/overlay
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 150))
        img = Image.alpha_composite(img, overlay)
        
        draw = ImageDraw.Draw(img)
        # Assuming a default font is available, fallback to default PIL font
        try:
            font = ImageFont.truetype("arialbd.ttf", 65)
        except:
            font = ImageFont.load_default()
            
        # Draw red banner
        draw.rectangle([(0, 600), (1280, 720)], fill=(180, 0, 0, 255))
        
        # Add Title text
        short_title = (title[:35] + '...') if len(title) > 35 else title
        draw.text((40, 620), short_title.upper(), fill="white", font=font, stroke_width=2, stroke_fill="black")
        
        img.convert("RGB").save(output_path)
        print("📸 Thumbnail generated successfully.")
        return output_path
    except Exception as e:
        print(f"⚠️ Thumbnail generation failed: {e}")
        return None

def upload_to_youtube(video_file, thumbnail_file, title, description):
    """Uploads to YouTube using standard OAuth tokens (Requires client_secrets.json)."""
    try:
        print("⏳ Uploading to YouTube...")
        creds = Credentials.from_authorized_user_file('token.json', ['https://www.googleapis.com/auth/youtube.upload'])
        youtube = build('youtube', 'v3', credentials=creds)

        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': ['TrueCrime', 'Mystery', 'ScaryStories', 'RedditStories'],
                'categoryId': '24' # Entertainment
            },
            'status': {
                'privacyStatus': 'public' # or 'private' for testing
            }
        }

        request = youtube.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=MediaFileUpload(video_file, chunksize=-1, resumable=True)
        )
        response = request.execute()
        
        if thumbnail_file:
            youtube.thumbnails().set(
                videoId=response['id'],
                media_body=MediaFileUpload(thumbnail_file)
            ).execute()
            
        print(f"🔥 Successfully uploaded! Video ID: {response['id']}")
    except Exception as e:
        print(f"⚠️ YouTube Upload failed (Check API Tokens): {e}")


# ===================== MAIN PIPELINE =====================

async def run_pipeline(custom_title=None):
    print(f"🚀 True Crime Bot Started - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    is_sunday = datetime.now().strftime("%A") == "Sunday"
    target_duration = 25 if is_sunday else 16 # Target 15+ mins

    # 1. Story
    story = fetch_reddit_story()
    story_title = custom_title or story['title']
    print(f"📖 Selected Story: {story_title}")

    # 2. Script Generation
    model = genai.GenerativeModel('gemini-2.0-flash')
    prompt = f"""Write a highly suspenseful {target_duration} minute YouTube script based on this terrifying real story.
    Title: {story_title}
    Story: {story['text']}
    
    CRITICAL RULES:
    - Use ellipses (...) and line breaks for dramatic pauses.
    - Structure:
      * Part 1: Powerful Hook + Story Setup + Cliffhanger.
      * Part 2: Terrifying escalation + Twists.
      * Part 3: Climax + Resolution + Islamic Moral (Tawakkul, relying on Allah, situational awareness).
    - Tone: Dark, gritty documentary style. Do not sound artificial.
    """
    
    script = model.generate_content(prompt).text

    # 3. Voiceover (With Pauses)
    # The '+2%' rate keeps it steady, guy neural is deep. The ellipses in script trigger Edge-TTS pauses.
    communicate = edge_tts.Communicate(script, voice=VOICE, rate="-5%")
    await communicate.save(f"{TEMP}/audio.mp3")
    print("🎙️ Voiceover Generated")

    audio = AudioFileClip(f"{TEMP}/audio.mp3")
    total_duration = audio.duration

    # 4. Visuals + 1.8s Cuts + Ken Burns + Freeze
    clips = []
    visual_queries = ["dark misty road", "abandoned house dark", "creepy forest night", "shadow figure", "police lights night", "empty dark hallway"]
    
    first_image_path = None

    print("🎬 Rendering Visuals...")
    for i in range(int(total_duration / CUT_RATE) + 1):
        query = random.choice(visual_queries)
        img_path = fetch_visuals(query, i)
        
        if img_path:
            if first_image_path is None:
                first_image_path = img_path
            try:
                clip = apply_effects(img_path, CUT_RATE)
                clips.append(clip)
            except:
                clips.append(ColorClip((WIDTH, HEIGHT), color=(5, 10, 15)).set_duration(CUT_RATE))
        else:
            # Fallback color clip if Pixabay limits are hit
            clips.append(ColorClip((WIDTH, HEIGHT), color=(5, 10, 15)).set_duration(CUT_RATE))

    video = concatenate_videoclips(clips, method="compose")
    final_video = video.set_audio(audio)

    # 5. Export
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_video_path = f"{OUTPUT}/TrueCrime_{timestamp}.mp4"
    output_thumb_path = f"{OUTPUT}/Thumb_{timestamp}.jpg"
    
    final_video.write_videofile(
        output_video_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        bitrate="5000k", # Optimized for fast rendering
        threads=8,
        preset="ultrafast",
        logger=None # Keeps console clean
    )
    print(f"✅ VIDEO READY: {output_video_path}")

    # 6. Generate Thumbnail
    if first_image_path:
        generate_thumbnail(first_image_path, story_title, output_thumb_path)
    
    # 7. Upload to YouTube
    description = f"Terrifying real true crime and mystery story: {story_title}.\n\nAlways rely on Allah and practice situational awareness. Subscribe for more mysteries."
    upload_to_youtube(output_video_path, output_thumb_path, story_title, description)


# ===================== SCHEDULER =====================
schedule.every().monday.at("09:00").do(lambda: asyncio.run(run_pipeline()))
schedule.every().tuesday.at("09:00").do(lambda: asyncio.run(run_pipeline()))
schedule.every().wednesday.at("10:00").do(lambda: asyncio.run(run_pipeline()))
schedule.every().thursday.at("13:00").do(lambda: asyncio.run(run_pipeline()))
schedule.every().friday.at("12:00").do(lambda: asyncio.run(run_pipeline()))
schedule.every().saturday.at("10:00").do(lambda: asyncio.run(run_pipeline()))
schedule.every().sunday.at("10:00").do(lambda: asyncio.run(run_pipeline()))

if __name__ == "__main__":
    print("\n=== True Crime Auto Bot v2.0 (The Powerhouse) ===")
    print("M = Manual Run | S = Scheduler Mode")
    choice = input("Choose mode: ").strip().upper()
    
    if choice == "M":
        custom = input("Custom Title (press Enter for auto-fetch): ").strip()
        asyncio.run(run_pipeline(custom if custom else None))
    else:
        print("⏰ Scheduler Activated - Keep Replit Tab Open")
        while True:
            schedule.run_pending()
            time.sleep(60)
