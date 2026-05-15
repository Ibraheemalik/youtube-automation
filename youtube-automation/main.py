#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  DARK CONFESSIONS v4.0 — Viral Horror Documentary Engine            ║
║  Framework: MagnatesMedia × James Jani × Horror Narration           ║
║  Target: 1M–10M views | US/UK Audience | RPM $8–$18                 ║
║  Stack: Gemini + EdgeTTS + Pexels + Pixabay + FFmpeg                ║
╚══════════════════════════════════════════════════════════════════════╝

Usage:
  python main.py                          Auto-schedule mode
  python main.py --run-now                Generate + upload immediately
  python main.py --day sunday             Force specific upload slot
  python main.py --topic "stalker"        Custom story topic
  python main.py --skip-upload            Generate video, no upload
  python main.py --skip-video             Script + thumbnail only
  python main.py --viral-check "topic"    Score topic virality first
"""

import os, sys, re, json, time, random, asyncio, hashlib
import logging, argparse, textwrap, subprocess, urllib.parse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

import yaml, requests, numpy as np, edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

import google.generativeai as genai

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    import pickle
    UPLOAD_OK = True
except ImportError:
    UPLOAD_OK = False

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

def _load(path):
    with open(path) as f:
        return yaml.safe_load(f)

CFG   = _load(BASE_DIR / "config.yml")
SCH   = _load(BASE_DIR / "schedule.yml")
TEMP  = Path(CFG["output"]["folder"]) / "temp"
OUT   = Path(CFG["output"]["folder"])
TEMP.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
(TEMP / "clips").mkdir(exist_ok=True)
(TEMP / "graded").mkdir(exist_ok=True)

W, H  = CFG["video"]["resolution"]
FPS   = CFG["video"]["fps"]
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# ─────────────────────────────────────────────────────────────────
#  STEP 1 — VIRAL TOPIC ENGINE
#  The #1 factor in 10M views: topic selection + title CTR
# ─────────────────────────────────────────────────────────────────

VIRAL_SCORE_PROMPT = """
You are a YouTube viral strategist. Score this horror story topic for viral potential.
TOPIC: "{topic}"

Score each dimension 0–10:
- mass_curiosity: Would someone who doesn't watch horror click?
- emotional_hook: Fear + empathy + dread combination?
- title_ctr: Strength of unanswered-question potential?
- thumbnail_power: How alarming is the visual concept?
- retention_arc: How well can 6 escalating stories hold attention?

Generate 5 viral title options. Rules:
- Must include conflict, power, or transformation
- Must create unanswered curiosity gap
- No neutral language
- Horror specifics: "Nobody Believed", "Still Unexplained", "Deleted Their Account After"

Return ONLY JSON:
{{
  "scores": {{"mass_curiosity":8,"emotional_hook":9,"title_ctr":7,"thumbnail_power":8,"retention_arc":9}},
  "weighted_total": 82,
  "verdict": "STRONG — high 1M+ potential",
  "titles": ["title1","title2","title3","title4","title5"],
  "improvement_tip": "single actionable tip"
}}
"""

def score_virality(topic: str, model) -> Dict:
    """Score topic before committing to full production."""
    if not model:
        return {"weighted_total": 72, "verdict": "ESTIMATED GOOD (no Gemini key)", "titles": []}
    try:
        r   = model.generate_content(VIRAL_SCORE_PROMPT.format(topic=topic))
        raw = re.sub(r"```json|```", "", r.text).strip()
        return json.loads(raw)
    except Exception as e:
        log.warning(f"Viral score error: {e}")
        return {"weighted_total": 70, "verdict": "ESTIMATED", "titles": []}

# ─────────────────────────────────────────────────────────────────
#  STEP 2 — SCRIPT ENGINE
#  MagnatesMedia pacing × James Jani storytelling × NoSleep tension
# ─────────────────────────────────────────────────────────────────

SCRIPT_PROMPT = """
You are an elite horror documentary scriptwriter. Channels trained on: MagnatesMedia,
James Jani, Johnny Harris, Moon — plus Reddit NoSleep narration style.

TOPIC: {topic}

MISSION: Write a horror narration video script that:
1. Gets clicked (CTR optimized title + thumbnail)
2. Holds 70%+ audience retention
3. Converts viewers to subscribers
4. Feels like a REAL PERSON remembering trauma — not AI

═══ RETENTION PSYCHOLOGY (HARD RULES) ═══
- Every 8–12 seconds: new idea OR curiosity gap OR visual shift
- Every 15 seconds: one unresolved statement answered later
- NEVER fully explain immediately — delay payoff
- Payoff stacking: hint → hint again → deliver late
- Pattern interrupt every 90 seconds (tone/speed/emotion shift)
- Curiosity gap lines every ~12 seconds:
  "What she found next — nobody reported to the police."
  "Three days later the account was deleted."
  "That's not even the part that kept him awake."

═══ STRUCTURE ═══
0:00–0:15   SHOCK HOOK — scariest implication first, no explanation
0:15–0:40   SETUP — who we are, what this channel covers
0:40–1:00   SUBSCRIBE PLUG — urgent, personality-driven
1:00–END    6 STORIES (escalating: scare_level 3 → 10)

═══ PER-STORY STRUCTURE ═══
[REDDIT INTRO] one line — where/when posted
[BUILD] 3–4 calm lines — normal life
[SHIFT] moment things changed — one punchy line
[ESCALATION] 3–5 tense/whisper lines building dread
[REVEAL] ONE devastating line — maximum impact
[AFTERMATH] 2–3 calm lines — unresolved question
[TRANSITION] bridge to next story

═══ TONE TAGS (every line must have one) ═══
[hook]    confident, pulling viewer in
[calm]    slow, deep, conversational
[tense]   slightly faster, building
[whisper] slowest, most intimate, scariest
[reveal]  dramatic — pause before AND after

═══ HUMANOID WRITING ═══
- Max 12 words per sentence
- Fragments are good. Like this. And like this.
- "..." = natural pause (700ms)
- "—" = sudden stop (400ms)
- Mix lengths: short. short. short. Then one longer sentence.
- Never start 3 lines with same word

═══ SCENE BREAKDOWN (per scene) ═══
scene_id, timestamp, narration, tone, emotion_target,
visual_keywords [3–5 Pexels/Pixabay terms], edit_style,
retention_trigger (curiosity gap line or null),
clip_change_rate (fast=1.5s / medium=2.5s / slow=4s),
sfx_cue (sound type or null)

Visual priority order:
1. human emotion clips
2. real-world footage
3. symbolic (darkness, shadow, storm)
4. abstract — last resort
NEVER: coding screens, generic office clips, anything inappropriate

Return ONLY this JSON (no markdown, no explanation):
{{
  "viral_titles": ["title1","title2","title3"],
  "best_title": "strongest CTR title",
  "youtube_title": "Full SEO title with emojis",
  "hook_concept": "one sentence — what makes this unmissable",
  "thumbnail_concept": {{
    "main_image": "visual description",
    "emotion_trigger": "fear emotion created",
    "text_overlay": "max 4 words",
    "color_scheme": "dark teal / blood red"
  }},
  "hook_lines": [
    {{"tone":"hook","text":"line"}},
    {{"tone":"hook","text":"line"}},
    {{"tone":"whisper","text":"line"}}
  ],
  "subscribe_plug": "personality-driven subscribe line",
  "stories": [
    {{
      "story_number": 1,
      "title": "Story Title",
      "scare_level": 3,
      "reddit_intro": "reddit context line",
      "scenes": [
        {{
          "scene_id": 1,
          "timestamp": "1:00–1:15",
          "narration": "exact voiceover",
          "tone": "calm",
          "emotion_target": "curiosity",
          "visual_keywords": ["dark bedroom","window night","lamp shadow"],
          "edit_style": "slow cinematic pan",
          "retention_trigger": null,
          "clip_change_rate": "slow",
          "sfx_cue": null
        }}
      ],
      "transition_line": {{"tone":"tense","text":"bridge line"}}
    }}
  ],
  "outro_scenes": [
    {{"tone":"whisper","text":"outro line","visual_keywords":["dark","void","fog"]}}
  ],
  "youtube_description": "300-word description with chapters and hooks",
  "tags": ["tag1","tag2"],
  "shorts_concept": "45-second short version idea",
  "viral_score": {{
    "ctr_potential":8,"retention_potential":9,
    "topic_size":7,"competition":6,"monetization":8,
    "total":76,"can_hit_1m":true
  }}
}}
"""

# ─── Built-in fallback (no Gemini key needed) ─────────────────────
def _fallback_script(topic: str) -> Dict:
    stories = [
        {
            "story_number": 1, "title": "The Breathing Under My Bed",
            "scare_level": 3,
            "reddit_intro": "Posted to r/nosleep at 2:47 AM. Deleted by morning.",
            "scenes": [
                {"scene_id":1,"timestamp":"1:00–1:12","narration":"I was twelve years old.","tone":"calm","emotion_target":"curiosity","visual_keywords":["dark bedroom","lamp nightstand","suburban house night"],"edit_style":"slow cinematic pan","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":None},
                {"scene_id":2,"timestamp":"1:12–1:27","narration":"I heard breathing. Under my mattress. Slow... deliberate.","tone":"tense","emotion_target":"tension","visual_keywords":["under bed dark","floorboards close","bedroom shadow"],"edit_style":"zoom-in","retention_trigger":"Nobody believed what he found under there.","clip_change_rate":"medium","sfx_cue":"heavy_breath"},
                {"scene_id":3,"timestamp":"1:27–1:42","narration":"I told myself it was the house. Houses don't breathe. I know that now.","tone":"whisper","emotion_target":"dread","visual_keywords":["empty hallway night","dark staircase","creaking wood"],"edit_style":"freeze","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":"door_creak"},
                {"scene_id":4,"timestamp":"1:42–1:58","narration":"I reached down. Something grabbed my wrist. Cold. Thin. Unmistakably human.","tone":"reveal","emotion_target":"shock","visual_keywords":["hand grabbing wrist","dark room flash","shadow figure"],"edit_style":"glitch","retention_trigger":None,"clip_change_rate":"fast","sfx_cue":"bass_impact"},
                {"scene_id":5,"timestamp":"1:58–2:18","narration":"My brother had been missing for three days. Police found him next morning. He never explained. He never spoke again.","tone":"calm","emotion_target":"dread","visual_keywords":["empty child bedroom","neighborhood night","abandoned toys"],"edit_style":"cinematic-pan","retention_trigger":"But that story is nothing compared to what comes next.","clip_change_rate":"medium","sfx_cue":None},
            ],
            "transition_line":{"tone":"tense","text":"But that story... is nothing compared to what comes next."}
        },
        {
            "story_number": 2, "title": "My Neighbor Knew Things He Shouldn't",
            "scare_level": 4,
            "reddit_intro": "r/Glitch_in_the_Matrix. 847 upvotes. Account since deleted.",
            "scenes": [
                {"scene_id":6,"timestamp":"2:25–2:38","narration":"He moved in on a Tuesday. Quiet man. Kept to himself.","tone":"calm","emotion_target":"curiosity","visual_keywords":["neighbor moving boxes","suburban street","curtain window"],"edit_style":"slow cinematic pan","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":None},
                {"scene_id":7,"timestamp":"2:38–2:55","narration":"Then he started describing my dreams. Over the fence. Like small talk.","tone":"tense","emotion_target":"tension","visual_keywords":["fence conversation","morning garden","neighbor back view"],"edit_style":"zoom-in","retention_trigger":"He described things never written down anywhere.","clip_change_rate":"medium","sfx_cue":None},
                {"scene_id":8,"timestamp":"2:55–3:14","narration":"The red hallway. The door with no handle. He named them both. Word for word.","tone":"whisper","emotion_target":"dread","visual_keywords":["red hallway dark","door no handle","dreamlike corridor"],"edit_style":"glitch","retention_trigger":None,"clip_change_rate":"fast","sfx_cue":"glitch_hit"},
                {"scene_id":9,"timestamp":"3:14–3:32","narration":"He said: I used to live there too. In that place. You should stop opening that door.","tone":"reveal","emotion_target":"shock","visual_keywords":["silhouette fence","shadow figure","dark garden dusk"],"edit_style":"freeze","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":"bass_impact"},
                {"scene_id":10,"timestamp":"3:32–3:52","narration":"I looked him up after he disappeared. He had died. Eleven years before we ever met.","tone":"calm","emotion_target":"dread","visual_keywords":["obituary paper","empty house forsale","foggy street"],"edit_style":"cinematic-pan","retention_trigger":"What she found next broke everything she thought was real.","clip_change_rate":"medium","sfx_cue":None},
            ],
            "transition_line":{"tone":"tense","text":"What she found next — changed everything she thought was real."}
        },
        {
            "story_number": 3, "title": "The Gas Station at Mile 47",
            "scare_level": 5,
            "reddit_intro": "r/LetsNotMeet. OP never returned to that highway.",
            "scenes": [
                {"scene_id":11,"timestamp":"3:58–4:12","narration":"Two in the morning. Nevada. One gas station. No signal.","tone":"calm","emotion_target":"curiosity","visual_keywords":["highway night desert","gas station isolated","dark road headlights"],"edit_style":"slow cinematic pan","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":None},
                {"scene_id":12,"timestamp":"4:12–4:28","narration":"The attendant smiled the entire time. Didn't blink. Not once. In twenty minutes.","tone":"tense","emotion_target":"tension","visual_keywords":["gas station attendant","fluorescent light","empty forecourt night"],"edit_style":"zoom-in","retention_trigger":"He was watching. Not blinking. Not moving.","clip_change_rate":"medium","sfx_cue":None},
                {"scene_id":13,"timestamp":"4:28–4:47","narration":"He leaned in. Said: the last three people who stopped here never left. You're lucky you're the fourth.","tone":"whisper","emotion_target":"dread","visual_keywords":["whisper shadow close","gas station flicker","dark figure lean"],"edit_style":"freeze","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":"heavy_breath"},
                {"scene_id":14,"timestamp":"4:47–5:05","narration":"I drove six hours without stopping. When I checked the map — Mile 47 doesn't exist. Never did.","tone":"reveal","emotion_target":"shock","visual_keywords":["map no marker","highway empty","driving away fast"],"edit_style":"glitch","retention_trigger":None,"clip_change_rate":"fast","sfx_cue":"bass_impact"},
            ],
            "transition_line":{"tone":"tense","text":"But the next story — she found something with no explanation at all."}
        },
        {
            "story_number": 4, "title": "The Woman in the Wedding Photos",
            "scare_level": 6,
            "reddit_intro": "r/Paranormal. The photographer confirmed: photos were unedited.",
            "scenes": [
                {"scene_id":15,"timestamp":"5:10–5:24","narration":"The wedding photos came back three weeks later. Beautiful. Perfect.","tone":"calm","emotion_target":"curiosity","visual_keywords":["wedding venue empty","church aisle","reception hall"],"edit_style":"slow cinematic pan","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":None},
                {"scene_id":16,"timestamp":"5:24–5:42","narration":"In seventeen photos there was a woman. Just behind the guests. Watching. Nobody recognized her.","tone":"tense","emotion_target":"tension","visual_keywords":["crowd background figure","dark corner party","silhouette behind people"],"edit_style":"zoom-in","retention_trigger":"Seventeen photos. Same woman. Different position. Same expression.","clip_change_rate":"medium","sfx_cue":None},
                {"scene_id":17,"timestamp":"5:42–6:00","narration":"Her mother went pale. Said: that's impossible. Her voice broke on the last word.","tone":"whisper","emotion_target":"dread","visual_keywords":["person looking photo shocked","shaking hands","woman sits slowly"],"edit_style":"freeze","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":"distant_scream"},
                {"scene_id":18,"timestamp":"6:00–6:20","narration":"It was her grandmother. Who had died four months before the wedding. In every photo — she was smiling.","tone":"reveal","emotion_target":"shock","visual_keywords":["old photograph","grandmother portrait","candle memorial"],"edit_style":"glitch","retention_trigger":None,"clip_change_rate":"fast","sfx_cue":"bass_impact"},
            ],
            "transition_line":{"tone":"tense","text":"That one has no explanation. But this next one does. And the explanation is worse."}
        },
        {
            "story_number": 5, "title": "What My Son Drew",
            "scare_level": 8,
            "reddit_intro": "r/Mommit. The post was flagged. The image was removed.",
            "scenes": [
                {"scene_id":19,"timestamp":"6:25–6:38","narration":"My son is four. He loves to draw. Houses. Dogs. Suns.","tone":"calm","emotion_target":"curiosity","visual_keywords":["child drawing table","crayon art","happy child bedroom"],"edit_style":"slow cinematic pan","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":None},
                {"scene_id":20,"timestamp":"6:38–6:55","narration":"Last Tuesday he handed me a drawing before bed. A tall dark figure. Standing over a small one. Sleeping.","tone":"tense","emotion_target":"tension","visual_keywords":["child drawing dark","stick figure paper","shadow drawing"],"edit_style":"zoom-in","retention_trigger":"She almost dismissed it as imagination. Almost.","clip_change_rate":"medium","sfx_cue":None},
                {"scene_id":21,"timestamp":"6:55–7:14","narration":"I asked who that was. He said: the man who watches me so you don't have to. He says don't turn on the lights.","tone":"whisper","emotion_target":"dread","visual_keywords":["child whispering","dark bedroom child","shadow wall bedroom"],"edit_style":"freeze","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":"heavy_breath"},
                {"scene_id":22,"timestamp":"7:14–7:34","narration":"There were scratch marks on the inside of his closet door. The wood gouged from the inside. No tool could have done it.","tone":"reveal","emotion_target":"shock","visual_keywords":["closet door scratches","wood damage close","dark closet interior"],"edit_style":"glitch","retention_trigger":None,"clip_change_rate":"fast","sfx_cue":"bass_impact"},
            ],
            "transition_line":{"tone":"whisper","text":"And the last story... this one has a recording. I need you to hear this."}
        },
        {
            "story_number": 6, "title": "The Last Voicemail",
            "scare_level": 10,
            "reddit_intro": "r/Glitch_in_the_Matrix. Highest upvoted post in the subreddit's history.",
            "scenes": [
                {"scene_id":23,"timestamp":"7:40–7:53","narration":"Phone rang at 3:17 AM. I didn't answer. Went to voicemail.","tone":"calm","emotion_target":"curiosity","visual_keywords":["phone ringing night","phone screen dark","3am clock"],"edit_style":"slow cinematic pan","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":None},
                {"scene_id":24,"timestamp":"7:53–8:10","narration":"In the morning I listened. It was my own voice. Saying my name. Over and over. Getting slower.","tone":"tense","emotion_target":"tension","visual_keywords":["person listening phone shocked","voicemail screen","pale face morning"],"edit_style":"zoom-in","retention_trigger":"Same voice. Same intonation. The exact way he says his own name.","clip_change_rate":"medium","sfx_cue":None},
                {"scene_id":25,"timestamp":"8:10–8:30","narration":"Getting quieter. Then silence. Then one final whisper. Don't go to work today.","tone":"whisper","emotion_target":"dread","visual_keywords":["phone speaker close","dark room listening","shadow wall"],"edit_style":"freeze","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":"heavy_breath"},
                {"scene_id":26,"timestamp":"8:30–8:55","narration":"Gas explosion at his office. Eight AM. His desk destroyed. Twelve injured. The number that called — was his own.","tone":"reveal","emotion_target":"shock","visual_keywords":["building smoke morning","emergency services","city morning aftermath"],"edit_style":"glitch","retention_trigger":None,"clip_change_rate":"fast","sfx_cue":"bass_impact"},
                {"scene_id":27,"timestamp":"8:55–9:20","narration":"Some things don't have answers. Some accounts get deleted. Some people stop talking about what they saw. Sleep well.","tone":"calm","emotion_target":"dread","visual_keywords":["dark empty road","fog night","black void"],"edit_style":"slow cinematic pan","retention_trigger":None,"clip_change_rate":"slow","sfx_cue":None},
            ],
            "transition_line":{"tone":"whisper","text":"Sleep well."}
        },
    ]

    chapters = (
        "0:00 – The Hook\n"
        "0:40 – Subscribe\n"
        "1:00 – The Breathing Under My Bed\n"
        "2:25 – My Neighbor Knew Things He Shouldn't\n"
        "3:58 – The Gas Station at Mile 47\n"
        "5:10 – The Woman in the Wedding Photos\n"
        "6:25 – What My Son Drew\n"
        "7:40 – The Last Voicemail (Most Disturbing)"
    )
    return {
        "viral_titles": [
            "😱 6 Reddit Horror Stories That Were Deleted by Morning",
            "These 6 Accounts Were Posted at 3 AM... Then Vanished",
            "6 True Stories Nobody Could Explain (Reddit's Darkest Posts)"
        ],
        "best_title": "😱 6 Reddit Horror Stories That Were Deleted by Morning",
        "youtube_title": "😱 6 Reddit Horror Stories That Were Deleted by Morning | Dark Confessions",
        "hook_concept": "Real accounts. Posted at 3 AM. Deleted before sunrise. Here is what they said.",
        "thumbnail_concept": {
            "main_image": "Dark silhouette in doorway, teal rim light, facing away",
            "emotion_trigger": "Dread + curiosity",
            "text_overlay": "DELETED BY MORNING",
            "color_scheme": "black background, teal atmosphere, red text"
        },
        "hook_lines": [
            {"tone":"hook",    "text":"These are real. Posted by real people."},
            {"tone":"hook",    "text":"Accounts deleted before sunrise."},
            {"tone":"whisper", "text":"Here is what they said."},
        ],
        "subscribe_plug": "Subscribe. Every Sunday we post what most channels are too scared to cover.",
        "stories": stories,
        "outro_scenes": [
            {"tone":"whisper","text":"Some things don't have answers.","visual_keywords":["dark void","fog","silence"]},
            {"tone":"whisper","text":"Some accounts get deleted. Some people stop talking.","visual_keywords":["deleted screen","empty room dark","abandoned"]},
            {"tone":"calm",  "text":"Sleep well.","visual_keywords":["black screen","dark bedroom","night"]},
        ],
        "youtube_description": (
            "These are 6 of the darkest accounts ever posted to Reddit. "
            "True stories submitted anonymously. Several posts were deleted within hours of going live.\n\n"
            "We don't explain everything. Some things don't have explanations.\n\n"
            f"📖 CHAPTERS\n{chapters}\n\n"
            "🔔 Subscribe — we post every Sunday 10 AM ET.\n"
            "New horror narration every week. US audience. Real stories only.\n\n"
            "#horrorstories #reddit #nosleep #scarystories #truehorror #darkconfessions"
        ),
        "tags": [
            "reddit horror stories","disturbing reddit","nosleep reddit",
            "scary stories true","horror narration 2024","dark reddit stories",
            "reddit creepy stories","true horror narration","let me not sleep",
            "reddit nosleep stories","scary narration","horror stories music",
            "true scary stories reddit","dark confessions","reddit 3am stories"
        ],
        "shorts_concept": (
            "45-sec Short: The voicemail was from his own number. "
            "He played it. It said: Don't go to work today. "
            "He didn't go. His office exploded at 8 AM. — end on black."
        ),
        "viral_score": {
            "ctr_potential":8,"retention_potential":9,
            "topic_size":8,"competition":6,"monetization":8,
            "total":78,"can_hit_1m":True
        }
    }

def init_gemini():
    key = CFG["api_keys"]["gemini_api_key"]
    if key == "YOUR_GEMINI_API_KEY_HERE":
        log.warning("⚠  Gemini key not set — using built-in fallback script")
        return None
    genai.configure(api_key=key)
    return genai.GenerativeModel("gemini-1.5-flash")

def generate_script(topic: str, model) -> Dict:
    if not model:
        return _fallback_script(topic)
    log.info(f"🧠 Generating viral script — topic: '{topic}'")
    try:
        r    = model.generate_content(SCRIPT_PROMPT.format(topic=topic))
        raw  = re.sub(r"```json|```", "", r.text).strip()
        data = json.loads(raw)
        vs   = data.get("viral_score", {})
        log.info(f"✅ Script ready | Viral score: {vs.get('total','?')}/100 | "
                 f"1M+ potential: {'YES' if vs.get('can_hit_1m') else 'MAYBE'}")
        return data
    except Exception as e:
        log.warning(f"Gemini error ({e}) — using fallback")
        return _fallback_script(topic)

# ─────────────────────────────────────────────────────────────────
#  STEP 3 — EDGE TTS ENGINE
#  Voice: en-US-ChristopherNeural | rate +8% | volume +10%
#  Humanoid tone-shift system — never monotone
# ─────────────────────────────────────────────────────────────────

VOICE = "en-US-ChristopherNeural"
TONE_MAP = {
    "hook":    {"rate": "+5%",  "pitch": "-3Hz",  "pause": 550},
    "calm":    {"rate": "+0%",  "pitch": "-8Hz",  "pause": 380},
    "tense":   {"rate": "+12%", "pitch": "-2Hz",  "pause": 280},
    "whisper": {"rate": "-12%", "pitch": "-14Hz", "pause": 700},
    "reveal":  {"rate": "-5%",  "pitch": "-5Hz",  "pause": 900},
}

def _ssml_line(text: str, tone: str) -> str:
    t    = TONE_MAP.get(tone, TONE_MAP["calm"])
    text = text.replace("...", '<break time="700ms"/>')
    text = text.replace("—",   '<break time="420ms"/>')
    text = text.replace(". ",  '. <break time="160ms"/>')
    return (
        f'<prosody rate="{t["rate"]}" pitch="{t["pitch"]}">'
        f'{text}'
        f'</prosody>'
        f'<break time="{t["pause"]}ms"/>'
    )

def _build_ssml(items: List[Dict]) -> str:
    body = ""
    prev = None
    for item in items:
        tone = item.get("tone", "calm")
        text = item.get("text") or item.get("narration", "")
        if not text.strip():
            continue
        if prev and prev != tone:
            body += '<break time="480ms"/>'   # humanoid tone-change gap
        body += _ssml_line(text, tone)
        prev = tone
    return (
        '<speak xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="en-US">'
        f'<voice name="{VOICE}">{body}</voice>'
        f'</speak>'
    )

async def _tts(ssml: str, path: str):
    await edge_tts.Communicate(ssml, VOICE).save(path)

def generate_all_audio(script: Dict) -> List[Dict]:
    """Scene-based audio — each story section = separate mp3 file for perfect sync."""
    segs = []

    # Hook
    path = str(TEMP / "aud_hook.mp3")
    asyncio.run(_tts(_build_ssml(script["hook_lines"]), path))
    segs.append({"id":"hook","path":path,"items":script["hook_lines"],"scenes":[]})
    log.info("✅ Audio: hook")

    # Subscribe plug
    sub  = [{"tone":"calm","text":script["subscribe_plug"]}]
    path = str(TEMP / "aud_sub.mp3")
    asyncio.run(_tts(_build_ssml(sub), path))
    segs.append({"id":"subscribe","path":path,"items":sub,"scenes":[]})
    log.info("✅ Audio: subscribe plug")

    # Stories — full story = one audio file, scenes used for visual sync
    for story in script["stories"]:
        sn    = story["story_number"]
        items = []
        items.append({"tone":"calm","text":story["reddit_intro"]})
        for sc in story["scenes"]:
            items.append({"tone":sc["tone"],"text":sc["narration"]})
        tl = story.get("transition_line")
        if tl:
            items.append(tl)
        path = str(TEMP / f"aud_story_{sn:02d}.mp3")
        asyncio.run(_tts(_build_ssml(items), path))
        segs.append({"id":f"story_{sn:02d}","path":path,
                      "items":items,"scenes":story["scenes"],
                      "title":story["title"]})
        log.info(f"✅ Audio: story {sn} — {story['title']}")

    # Outro
    path = str(TEMP / "aud_outro.mp3")
    asyncio.run(_tts(_build_ssml(script["outro_scenes"]), path))
    segs.append({"id":"outro","path":path,
                  "items":script["outro_scenes"],"scenes":[]})
    log.info("✅ Audio: outro")
    return segs

# ─────────────────────────────────────────────────────────────────
#  STEP 4 — DUAL VIDEO FETCHER
#  Pexels (priority) + Pixabay (fallback)
#  Visual priority: human emotion > real world > symbolic > abstract
# ─────────────────────────────────────────────────────────────────

HORROR_FALLBACKS = [
    "dark forest night mist", "empty hallway shadow", "foggy street night",
    "abandoned house interior", "dark bedroom window", "storm lightning sky",
    "candle flame dark room", "rain window night", "old attic dusty",
    "dark staircase shadow", "night road empty", "basement dark concrete",
    "moonlight shadow tree", "dark field night clouds", "city street night empty",
]

_cache: Dict[str, str] = {}

def _pixabay(query: str) -> Optional[str]:
    key = CFG["api_keys"].get("pixabay_api_key", "YOUR_PIXABAY_API_KEY_HERE")
    if key == "YOUR_PIXABAY_API_KEY_HERE":
        return None
    ck = "pix_" + hashlib.md5(query.encode()).hexdigest()[:10]
    if ck in _cache and os.path.exists(_cache[ck]):
        return _cache[ck]
    try:
        url  = (f"https://pixabay.com/api/videos/?key={key}"
                f"&q={urllib.parse.quote(query)}&per_page=5&min_width=1280")
        hits = requests.get(url, timeout=12).json().get("hits", [])
        random.shuffle(hits)
        for hit in hits:
            src = (hit.get("videos",{}).get("medium",{}).get("url") or
                   hit.get("videos",{}).get("small",{}).get("url"))
            if not src:
                continue
            fp = str(TEMP/"clips"/f"{ck}_{hit['id']}.mp4")
            if not os.path.exists(fp):
                r = requests.get(src, timeout=30, stream=True)
                with open(fp,"wb") as f:
                    for chunk in r.iter_content(65536): f.write(chunk)
            _cache[ck] = fp
            return fp
    except Exception as e:
        log.debug(f"Pixabay ({query}): {e}")
    return None

def _pexels(query: str) -> Optional[str]:
    key = CFG["api_keys"].get("pexels_api_key", "YOUR_PEXELS_API_KEY_HERE")
    if key == "YOUR_PEXELS_API_KEY_HERE":
        return None
    ck = "pex_" + hashlib.md5(query.encode()).hexdigest()[:10]
    if ck in _cache and os.path.exists(_cache[ck]):
        return _cache[ck]
    try:
        headers = {"Authorization": key}
        url     = (f"https://api.pexels.com/videos/search"
                   f"?query={urllib.parse.quote(query)}&per_page=5&min_width=1280")
        videos  = requests.get(url, headers=headers, timeout=12).json().get("videos", [])
        random.shuffle(videos)
        for vid in videos:
            files = sorted(vid.get("video_files",[]), key=lambda x:x.get("width",0), reverse=True)
            for vf in files:
                if vf.get("width",0) >= 1280:
                    fp = str(TEMP/"clips"/f"{ck}_{vid['id']}.mp4")
                    if not os.path.exists(fp):
                        r = requests.get(vf["link"], timeout=30, stream=True)
                        with open(fp,"wb") as f:
                            for chunk in r.iter_content(65536): f.write(chunk)
                    _cache[ck] = fp
                    return fp
    except Exception as e:
        log.debug(f"Pexels ({query}): {e}")
    return None

def get_clip(scene: Dict) -> Optional[str]:
    kws = scene.get("visual_keywords", []) + HORROR_FALLBACKS
    for kw in kws[:6]:
        c = _pexels(kw) or _pixabay(kw)
        if c:
            return c
    return None

def build_broll_pool(n: int = 40) -> List[str]:
    pool = []
    for q in HORROR_FALLBACKS:
        if len(pool) >= n: break
        c = _pexels(q) or _pixabay(q)
        if c: pool.append(c)
    if not pool:
        pool = _placeholders(n)
    log.info(f"✅ B-roll pool: {len(pool)} clips")
    return pool

def _placeholders(n: int) -> List[str]:
    colors = ["#020408","#030a0f","#040612","#050514","#030810"]
    paths  = []
    for i in range(min(n, 12)):
        p = str(TEMP/"clips"/f"ph_{i:03d}.mp4")
        if not os.path.exists(p):
            subprocess.run([
                "ffmpeg","-y","-f","lavfi",
                "-i",f"color=c={colors[i%len(colors)]}:size={W}x{H}:rate=30",
                "-t","8","-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",p
            ], capture_output=True)
        paths.append(p)
    return paths

# ─────────────────────────────────────────────────────────────────
#  STEP 5 — CINEMATIC GRADE ENGINE
#  Teal-orange LUT + grain + vignette + Ken Burns zoom
# ─────────────────────────────────────────────────────────────────

def _probe(path: str) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe","-v","quiet","-print_format","json","-show_streams",path]
        ).decode()
        for s in json.loads(out).get("streams",[]):
            if "duration" in s:
                return float(s["duration"])
    except: pass
    return 6.0

def grade_clip(src: str, dst: str, idx: int, dur: float = 6.0) -> str:
    """Teal-orange grade + grain + vignette + Ken Burns. Alternating zoom direction."""
    zoom_in = idx % 2 == 0
    zv      = "min(zoom+0.0007,1.06)" if zoom_in else "max(zoom-0.0007,1.0)"
    zs      = "1.0" if zoom_in else "1.06"

    grade = (
        "curves=r='0/0 0.5/0.54 1/1':g='0/0 0.3/0.32 1/1':b='0/0.04 0.3/0.38 0.7/0.70 1/0.95',"
        "eq=contrast=1.14:brightness=-0.04:saturation=0.82,"
        "noise=alls=20:allf=t+u,"
        "vignette=angle=PI/3.5:mode=backward:eval=frame"
    )
    zoom_f = (
        f"scale={W*2}:{H*2}:flags=lanczos,"
        f"zoompan=z='if(lte(on\\,1)\\,{zs}\\,{zv})':"
        f"d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}"
    )
    cmd = ["ffmpeg","-y","-i",src,"-vf",f"{zoom_f},{grade}",
           "-t",str(dur),"-r",str(FPS),"-c:v","libx264","-preset","fast",
           "-crf","20","-pix_fmt","yuv420p","-an",dst]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        # Simple fallback
        subprocess.run([
            "ffmpeg","-y","-i",src,
            "-vf",f"eq=contrast=1.1:brightness=-0.05:saturation=0.8,"
                   f"noise=alls=16:allf=t,scale={W}:{H}",
            "-t",str(dur),"-r",str(FPS),"-c:v","libx264","-preset","ultrafast",
            "-crf","22","-pix_fmt","yuv420p","-an",dst
        ], capture_output=True)
    return dst

# ─────────────────────────────────────────────────────────────────
#  STEP 6 — EDITING ENGINE
#  Cut every 1.5–4s per scene emotion | Glitch on reveals
#  No static frame > 2.5s | Zoom movement every 3–6s
# ─────────────────────────────────────────────────────────────────

EDIT_RULES = {
    "slow cinematic pan": {"interval":4.0, "glitch":False},
    "zoom-in":            {"interval":2.0, "glitch":False},
    "glitch":             {"interval":1.5, "glitch":True },
    "freeze":             {"interval":3.5, "glitch":False},
    "slow-motion":        {"interval":4.0, "glitch":False},
    "whip-cut":           {"interval":1.2, "glitch":True },
    "cinematic-pan":      {"interval":3.0, "glitch":False},
}
RATE_MAP = {"fast":1.5,"medium":2.5,"slow":4.0}

def _glitch(src: str, dst: str, dur: float) -> str:
    cmd = [
        "ffmpeg","-y","-i",src,
        "-vf",f"noise=alls=45:allf=t,rgbashift=rh=4:bh=-4:gh=0,scale={W}:{H}",
        "-t",str(dur),"-r",str(FPS),"-c:v","libx264","-preset","fast",
        "-crf","22","-pix_fmt","yuv420p","-an",dst
    ]
    r = subprocess.run(cmd, capture_output=True)
    return dst if r.returncode == 0 else src

def build_scene_clip(scene: Dict, broll: List[str], sid: str, idx: int) -> str:
    rule   = EDIT_RULES.get(scene.get("edit_style","cinematic-pan"),
                              EDIT_RULES["cinematic-pan"])
    rate   = RATE_MAP.get(scene.get("clip_change_rate","medium"), 2.5)
    dur    = rate * 3

    src    = get_clip(scene)
    if not src:
        src = random.choice(broll) if broll else _placeholders(1)[0]

    graded = str(TEMP/"graded"/f"{sid}_{idx:03d}.mp4")
    grade_clip(src, graded, idx, dur)

    if rule["glitch"]:
        glit = str(TEMP/"graded"/f"{sid}_{idx:03d}_g.mp4")
        return _glitch(graded, glit, dur)
    return graded

# ─────────────────────────────────────────────────────────────────
#  STEP 7 — SUBTITLE ENGINE
#  Word-by-word animation | Glow + drop shadow | Scale fade-in
# ─────────────────────────────────────────────────────────────────

def _font(size: int):
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def _sub_frame(text: str, prog: float) -> np.ndarray:
    img  = Image.new("RGBA",(W,H),(0,0,0,0))
    draw = ImageDraw.Draw(img)
    size = int(CFG["video"]["text"]["size"] * (0.75 + 0.25*prog))
    font = _font(size)
    lns  = textwrap.wrap(text, width=40)
    lh   = size+10
    y0   = H - len(lns)*lh - 88
    al   = int(255*prog)

    for i, ln in enumerate(lns):
        bb = draw.textbbox((0,0),ln,font=font)
        tw = bb[2]-bb[0]; x=(W-tw)//2; y=y0+i*lh
        # Glow
        gl = Image.new("RGBA",(W,H),(0,0,0,0))
        gd = ImageDraw.Draw(gl)
        for dx in range(-8,9,3):
            for dy in range(-8,9,3):
                gd.text((x+dx,y+dy),ln,font=font,fill=(255,255,255,max(0,al//5)))
        img   = Image.alpha_composite(img, gl.filter(ImageFilter.GaussianBlur(5)))
        draw  = ImageDraw.Draw(img)
        draw.text((x+3,y+3),ln,font=font,fill=(0,0,0,int(al*0.75)))
        draw.text((x,y),ln,font=font,fill=(255,255,255,al))
    return np.array(img)[:,:,:3]

def render_subs(items: List[Dict], total_sec: float, sid: str) -> str:
    out = str(TEMP/f"subs_{sid}.mp4")
    wd  = CFG["video"]["text"]["word_duration"]

    # Word-by-word timeline
    timeline: List[Tuple[float,float,str]] = []
    t = 0.0
    for item in items:
        text  = item.get("text") or item.get("narration","")
        words = text.split()
        for wi,w in enumerate(words):
            timeline.append((t, t+wd, " ".join(words[:wi+1])))
            t += wd
        t += 0.35

    n = int(total_sec * FPS)
    pipe = subprocess.Popen([
        "ffmpeg","-y","-f","rawvideo","-vcodec","rawvideo",
        "-s",f"{W}x{H}","-pix_fmt","rgb24","-r",str(FPS),"-i","pipe:0",
        "-c:v","libx264","-preset","fast","-crf","18","-pix_fmt","yuv420p",out
    ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    blank = np.zeros((H,W,3),dtype=np.uint8)
    for fi in range(n):
        sec = fi/FPS
        f   = blank.copy()
        for (s,e,ph) in timeline:
            if s <= sec < e:
                f = _sub_frame(ph, min(1.0,(sec-s)/0.1))
                break
        pipe.stdin.write(f.tobytes())
    pipe.stdin.close(); pipe.wait()
    return out

# ─────────────────────────────────────────────────────────────────
#  RED BOX REVEAL — Animated red border + glitch text
# ─────────────────────────────────────────────────────────────────

def red_reveal(text: str, dur: float, sid: str) -> str:
    out  = str(TEMP/f"rb_{sid}.mp4")
    n    = int(dur*FPS)
    font = _font(64)
    pipe = subprocess.Popen([
        "ffmpeg","-y","-f","rawvideo","-vcodec","rawvideo",
        "-s",f"{W}x{H}","-pix_fmt","rgb24","-r",str(FPS),"-i","pipe:0",
        "-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p",out
    ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for fi in range(n):
        t    = fi/FPS
        img  = Image.new("RGBA",(W,H),(0,0,0,0))
        draw = ImageDraw.Draw(img)
        prog = min(1.0, t/0.25)
        gx   = int(random.uniform(-6,6)*max(0,1-t*4))
        al   = int(220*prog)
        bw   = int(W*0.72); bh=130
        bx   = (W-bw)//2+gx; by=H//2-bh//2
        draw.rectangle([bx,by,bx+bw,by+bh],fill=(180,10,10,int(35*prog)))
        draw.rectangle([bx,by,bx+bw,by+bh],outline=(210,20,20,al),width=3)
        bb   = draw.textbbox((0,0),text,font=font)
        tx   = (W-(bb[2]-bb[0]))//2+gx; ty=by+(bh-(bb[3]-bb[1]))//2
        draw.text((tx+2,ty+2),text,font=font,fill=(0,0,0,int(al*0.7)))
        draw.text((tx,ty),text,font=font,fill=(255,55,55,al))
        pipe.stdin.write(np.array(img)[:,:,:3].tobytes())
    pipe.stdin.close(); pipe.wait()
    return out

# ─────────────────────────────────────────────────────────────────
#  FREEZE FRAME — Desaturated still at peak dread moment
# ─────────────────────────────────────────────────────────────────

def freeze(src: str, at: float, fdur: float, sid: str) -> str:
    out = str(TEMP/f"frz_{sid}.mp4")
    img = str(TEMP/f"frz_img_{sid}.png")
    subprocess.run(["ffmpeg","-y","-ss",str(at),"-i",src,"-frames:v","1",img],
                   capture_output=True)
    still = str(TEMP/f"frz_still_{sid}.mp4")
    subprocess.run([
        "ffmpeg","-y","-loop","1","-i",img,
        "-vf",f"eq=saturation=0.18:contrast=1.35,scale={W}:{H}",
        "-t",str(fdur),"-r",str(FPS),"-c:v","libx264",
        "-preset","fast","-pix_fmt","yuv420p","-an",still
    ], capture_output=True)

    p1 = str(TEMP/f"frz_p1_{sid}.mp4")
    p3 = str(TEMP/f"frz_p3_{sid}.mp4")
    subprocess.run(["ffmpeg","-y","-i",src,"-t",str(at),
                    "-c:v","libx264","-preset","fast","-an",p1],capture_output=True)
    subprocess.run(["ffmpeg","-y","-ss",str(at+fdur),"-i",src,
                    "-c:v","libx264","-preset","fast","-an",p3],capture_output=True)

    ct = str(TEMP/f"frz_list_{sid}.txt")
    with open(ct,"w") as f:
        for p in [p1,still,p3]:
            if os.path.exists(p) and os.path.getsize(p)>0:
                f.write(f"file '{p}'\n")
    subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",ct,
                    "-c:v","libx264","-preset","fast","-crf","20",
                    "-pix_fmt","yuv420p",out], capture_output=True)
    return out if os.path.exists(out) else src

# ─────────────────────────────────────────────────────────────────
#  BG MUSIC — Layered dark ambient drone
# ─────────────────────────────────────────────────────────────────

def gen_music(total_dur: float) -> str:
    out = str(TEMP/"bg.mp3")
    if os.path.exists(out): return out
    vol   = CFG["video"]["audio"]["background_music_volume"]
    freqs = [42,55,82,110,165,220]
    inps  = []; flt=[]; maps=[]
    for i,f in enumerate(freqs):
        inps  += ["-f","lavfi","-i",f"sine=frequency={f}:duration={total_dur}"]
        flt   += f"[{i}]volume=0.18[a{i}];"
        maps  += f"[a{i}]"
    amix = f"{''.join(maps)}amix=inputs={len(freqs)}:dropout_transition=3,volume={vol}"
    cmd  = ["ffmpeg","-y",*inps,"-filter_complex","".join(flt)+amix,
            "-ar","44100","-ac","2","-codec:a","libmp3lame","-b:a","128k",out]
    r    = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        subprocess.run([
            "ffmpeg","-y","-f","lavfi","-i",f"sine=frequency=55:duration={total_dur}",
            "-af",f"volume={vol}","-ar","44100",out
        ], capture_output=True)
    log.info("✅ BG music generated")
    return out

def mix_audio(nar: str, music: str, offset: float,
               dur: float, has_reveal: bool, sid: str) -> str:
    out  = str(TEMP/f"mix_{sid}.mp3")
    nv   = CFG["video"]["audio"]["narration_volume"]
    bv   = CFG["video"]["audio"]["background_music_volume"]
    rev  = ",aecho=0.7:0.88:500:0.25" if has_reveal else ""
    subprocess.run([
        "ffmpeg","-y","-i",nar,"-ss",str(offset),"-i",music,
        "-filter_complex",
        f"[0:a]volume={nv}{rev}[nav];"
        f"[1:a]volume={bv}[bg];"
        f"[nav][bg]amix=inputs=2:duration=first:dropout_transition=2[out]",
        "-map","[out]","-t",str(dur),
        "-ar","44100","-ac","2","-codec:a","libmp3lame","-b:a","192k",out
    ], capture_output=True)
    return out

# ─────────────────────────────────────────────────────────────────
#  SEGMENT ASSEMBLER — Full compositing per segment
# ─────────────────────────────────────────────────────────────────

def assemble(seg: Dict, broll: List[str],
              music: str, music_offset: float) -> Tuple[str,float]:
    sid    = seg["id"]
    nar    = seg["path"]
    items  = seg["items"]
    scenes = seg.get("scenes",[])
    dur    = _probe(nar)
    has_rv = any(sc.get("tone")=="reveal" for sc in scenes)
    log.info(f"  ▶ Assembling: {sid} ({dur:.1f}s)")

    # 1. Scene clips (graded, edit-style-specific)
    scene_clips = []
    for i,sc in enumerate(scenes if scenes else [{}]):
        scene_clips.append(build_scene_clip(sc, broll, sid, i))
    if not scene_clips:
        dummy = random.choice(broll) if broll else _placeholders(1)[0]
        g     = str(TEMP/"graded"/f"{sid}_000.mp4")
        grade_clip(dummy, g, 0, dur)
        scene_clips = [g]

    # 2. Loop clips to cover narration duration
    ct  = str(TEMP/f"vlist_{sid}.txt")
    tot = 0.0
    with open(ct,"w") as f:
        cycle = scene_clips * (int(dur // max(1,len(scene_clips)))+3)
        for vc in cycle:
            if tot >= dur+1: break
            if os.path.exists(vc) and os.path.getsize(vc)>0:
                f.write(f"file '{vc}'\n")
                tot += _probe(vc)

    vis = str(TEMP/f"vis_{sid}.mp4")
    subprocess.run([
        "ffmpeg","-y","-f","concat","-safe","0","-i",ct,
        "-vf",f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
        "-c:v","libx264","-preset","fast","-crf","19",
        "-pix_fmt","yuv420p","-t",str(dur+0.5),"-an",vis
    ], capture_output=True)

    # 3. Freeze on reveal
    if has_rv and os.path.exists(vis):
        vis = freeze(vis, dur*0.58, 1.0, sid)

    # 4. Subtitles
    subs = render_subs(items, dur, sid)

    # 5. Red box on reveal
    rv_texts = [sc.get("narration","")[:38] for sc in scenes if sc.get("tone")=="reveal"]
    rb = None
    if rv_texts and has_rv:
        rb = red_reveal(rv_texts[0], 2.5, sid)

    # 6. Composite
    in_args = ["-i",vis,"-i",subs]
    fc      = "[0:v][1:v]overlay=0:0[base]"
    out_map = "[base]"
    if rb and os.path.exists(rb):
        rs = max(0, dur*0.57)
        in_args += ["-i",rb]
        fc += f";[base][2:v]overlay=0:0:enable='between(t,{rs:.1f},{rs+2.5:.1f})'[out]"
        out_map = "[out]"

    comp = str(TEMP/f"comp_{sid}.mp4")
    r = subprocess.run([
        "ffmpeg","-y",*in_args,"-filter_complex",fc,"-map",out_map,
        "-c:v","libx264","-preset","fast","-crf","18",
        "-pix_fmt","yuv420p","-t",str(dur),comp
    ], capture_output=True, text=True)
    if r.returncode != 0:
        comp = vis

    # 7. Mix audio
    mixed = mix_audio(nar, music, music_offset, dur, has_rv, sid)

    # 8. Mux
    muxed = str(TEMP/f"muxed_{sid}.mp4")
    subprocess.run([
        "ffmpeg","-y","-i",comp,"-i",mixed,
        "-c:v","copy","-c:a","aac","-b:a","192k","-shortest",muxed
    ], capture_output=True)

    final = muxed if (os.path.exists(muxed) and os.path.getsize(muxed)>1000) else comp
    log.info(f"  ✅ Done: {sid}")
    return final, dur

# ─────────────────────────────────────────────────────────────────
#  CINEMATIC TRANSITION — Glitch + noise crossfade
# ─────────────────────────────────────────────────────────────────

def transition(a: str, b: str, idx: int) -> Optional[str]:
    out = str(TEMP/f"trans_{idx:02d}.mp4")
    da  = _probe(a)
    ts  = max(0, da-0.3)
    cmd = [
        "ffmpeg","-y","-i",a,"-i",b,
        "-filter_complex",
        f"[0:v]trim=start={ts:.2f}:duration=0.6,setpts=PTS-STARTPTS,"
        f"noise=alls=55:allf=t+u[va];"
        f"[1:v]trim=start=0:duration=0.6,setpts=PTS-STARTPTS[vb];"
        f"[va][vb]xfade=transition=fade:duration=0.4:offset=0.2[vout]",
        "-map","[vout]","-c:v","libx264","-preset","fast",
        "-crf","21","-pix_fmt","yuv420p","-t","0.6",out
    ]
    r = subprocess.run(cmd, capture_output=True)
    return out if (r.returncode==0 and os.path.exists(out)) else None

# ─────────────────────────────────────────────────────────────────
#  THUMBNAIL ENGINE — CTR maximized
#  Dark + teal atmosphere | Silhouette | Red danger text
# ─────────────────────────────────────────────────────────────────

def make_thumbnail(script: Dict) -> str:
    tc  = CFG["thumbnail"]
    out = str(OUT/f"thumb_{_ts()}.jpg")
    W2,H2 = tc["width"], tc["height"]
    img  = Image.new("RGB",(W2,H2),tuple(tc["background_color"]))
    draw = ImageDraw.Draw(img)

    # Teal atmospheric gradient
    for y in range(H2):
        a = 1.0-(y/H2)*0.8
        draw.line([(0,y),(W2,y)],fill=(0,int(180*a*0.18),int(170*a*0.20)))

    # Faceless silhouette figure (right side, dark with teal rim)
    fx,fy = W2//2+210, H2//5; fh=H2-fy-20
    draw.ellipse([fx-38,fy-55,fx+38,fy+8],fill=(5,5,10))
    draw.rectangle([fx-50,fy+8,fx+50,fy+fh],fill=(4,4,8))
    for o in range(1,10):
        draw.rectangle([fx-50-o,fy+8-o,fx+50+o,fy+fh+o],
                        outline=(0,max(0,150+o*10),max(0,160+o*8)))

    # Film grain
    arr   = np.array(img).astype(np.float32)
    grain = np.random.normal(0,13,arr.shape)
    img   = Image.fromarray(np.clip(arr+grain,0,255).astype(np.uint8))
    draw  = ImageDraw.Draw(img)

    # Text
    concept  = script.get("thumbnail_concept",{})
    overlay  = concept.get("text_overlay","DELETED BY MORNING").upper()
    title    = re.sub(r"[^\w\s!?]","",script.get("best_title","HORROR STORIES")).upper()[:55]
    top_txt  = "DISTURBING REDDIT STORIES"

    f_big = _font(tc["font_main_size"])
    f_med = _font(tc["font_sub_size"])
    f_xl  = _font(90)
    f_sm  = _font(34)

    # Red top label
    draw.text((42,44),top_txt,font=f_med,fill=(0,0,0))
    draw.text((40,42),top_txt,font=f_med,fill=tuple(tc["danger_color"]))

    # White main title
    words = title.split()
    l1    = " ".join(words[:4]); l2=" ".join(words[4:8])
    for i,ln in enumerate([l1,l2]):
        if not ln: continue
        bb = draw.textbbox((0,0),ln,font=f_big)
        x=40; y=100+i*(tc["font_main_size"]+6)
        draw.text((x+3,y+3),ln,font=f_big,fill=(0,0,0))
        draw.text((x,y),ln,font=f_big,fill=tuple(tc["text_color"]))

    # Red overlay text (large, CTR trigger)
    ob = draw.textbbox((0,0),overlay,font=f_xl)
    ox = W2//2-(ob[2]-ob[0])//2; oy=H2-175
    draw.text((ox+3,oy+3),overlay,font=f_xl,fill=(0,0,0))
    draw.text((ox,oy),overlay,font=f_xl,fill=tuple(tc["danger_color"]))

    # Teal bottom accent line
    draw.rectangle([0,H2-8,W2,H2],fill=tuple(tc["accent_color"]))

    img.save(out,"JPEG",quality=95)
    log.info(f"✅ Thumbnail: {Path(out).name}")
    return out

# ─────────────────────────────────────────────────────────────────
#  YOUTUBE UPLOAD
# ─────────────────────────────────────────────────────────────────

def _yt_service():
    if not UPLOAD_OK: return None
    secrets = CFG["api_keys"]["youtube_client_secrets"]
    if not os.path.exists(secrets):
        log.warning(f"⚠  OAuth file not found: {secrets}")
        return None
    creds = None; tok = "yt_token.pickle"
    if os.path.exists(tok):
        with open(tok,"rb") as f: creds=pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(secrets,SCOPES)
            creds = flow.run_local_server(port=0)
        with open(tok,"wb") as f: pickle.dump(creds,f)
    return build("youtube","v3",credentials=creds)

def upload(video: str, thumb: str, script: Dict, publish: bool) -> Optional[str]:
    svc  = _yt_service()
    if not svc:
        log.warning("⚠  Upload skipped — no credentials")
        return None
    priv = "public" if publish else CFG["youtube_seo"]["default_privacy"]
    tags = list(dict.fromkeys((script.get("tags") or [])
                               + CFG["youtube_seo"]["default_tags"]))[:50]
    body = {
        "snippet": {
            "title":           script.get("youtube_title","")[:100],
            "description":     script.get("youtube_description","")[:5000],
            "tags":            tags,
            "categoryId":      CFG["youtube_seo"]["default_category"],
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus":           priv,
            "madeForKids":             False,
            "selfDeclaredMadeForKids": False,
        }
    }
    log.info(f"📤 Uploading as {priv}...")
    media  = MediaFileUpload(video,mimetype="video/mp4",
                              resumable=True,chunksize=5*1024*1024)
    req    = svc.videos().insert(part=",".join(body),body=body,media_body=media)
    resp   = None
    while resp is None:
        st,resp = req.next_chunk()
        if st: log.info(f"  {int(st.progress()*100)}%")
    vid_id = resp["id"]
    log.info(f"✅ https://www.youtube.com/watch?v={vid_id}")
    try:
        svc.thumbnails().set(videoId=vid_id,
            media_body=MediaFileUpload(thumb,mimetype="image/jpeg")).execute()
        log.info("✅ Thumbnail uploaded")
    except Exception as e:
        log.warning(f"Thumbnail: {e}")
    return vid_id

# ─────────────────────────────────────────────────────────────────
#  SCHEDULER
# ─────────────────────────────────────────────────────────────────

def next_slot(day_override: Optional[str]=None) -> Optional[datetime]:
    import pytz
    tz     = pytz.timezone(SCH["schedule"]["timezone"])
    now    = datetime.now(tz)
    weekly = SCH["schedule"]["weekly"]
    dn     = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,
               "friday":4,"saturday":5,"sunday":6}
    if day_override:
        dk = day_override.lower()
        if dk not in weekly: return None
        h,m  = map(int,weekly[dk]["upload_time"].split(":"))
        diff = (dn[dk]-now.weekday())%7
        t    = now.replace(hour=h,minute=m,second=0,microsecond=0)+timedelta(days=diff)
        if t<now: t+=timedelta(days=7)
        return t
    cands = []
    for off in range(8):
        td = now+timedelta(days=off)
        dk = list(dn.keys())[td.weekday()]
        if dk not in weekly: continue
        h,m = map(int,weekly[dk]["upload_time"].split(":"))
        st  = td.replace(hour=h,minute=m,second=0,microsecond=0)
        if st>now: cands.append((st,dk,weekly[dk]))
    if cands:
        t,d,s = sorted(cands,key=lambda x:x[0])[0]
        log.info(f"⏰ Next upload: {d.title()} {s['upload_time']} ET — {s['label']}")
        return t
    return None

# ─────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _cleanup():
    if not CFG["output"]["keep_temp_files"]:
        import shutil
        shutil.rmtree(str(TEMP),ignore_errors=True)
        TEMP.mkdir(exist_ok=True)
        log.info("🧹 Temp cleaned")

def _banner():
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║  DARK CONFESSIONS v4.0 — Viral Horror Documentary Engine            ║
║  Framework: MagnatesMedia × James Jani × NoSleep Narration          ║
║  Voice: en-US-ChristopherNeural | Rate +8% | Volume +10%            ║
║  Target: 1M–10M views | US/UK | RPM $8–$18                          ║
╚══════════════════════════════════════════════════════════════════════╝""")

def _report(script: Dict, video: str, thumb: str):
    vs = script.get("viral_score",{})
    sc = script.get("viral_score",{})
    print(f"""
╔══════════════════════════════════════════════════════╗
║  📊  PRODUCTION COMPLETE
╠══════════════════════════════════════════════════════╣
║  📹  {Path(video).name if video else 'N/A'}
║  🖼   {Path(thumb).name if thumb else 'N/A'}
╠══════════════════════════════════════════════════════╣
║  📌  {script.get('youtube_title','')[:50]}
╠══════════════════════════════════════════════════════╣
║  🔥  Viral Score    : {vs.get('total','?')}/100
║  📈  CTR Potential  : {vs.get('ctr_potential','?')}/10
║  ⏱   Retention      : {vs.get('retention_potential','?')}/10
║  💰  Monetization   : {vs.get('monetization','?')}/10
║  🚀  1M+ Potential  : {'YES ✅' if vs.get('can_hit_1m') else 'MAYBE ⚠'}
╠══════════════════════════════════════════════════════╣
║  📱  Shorts Concept:
║  {script.get('shorts_concept','')[:50]}
╠══════════════════════════════════════════════════════╣
║  📅  SCHEDULE (US Eastern)
║  Mon/Tue 9AM · Wed 10AM · Thu 1PM
║  Fri 12PM · Sat 10AM · Sun 10AM ← PEAK
╚══════════════════════════════════════════════════════╝""")

# ─────────────────────────────────────────────────────────────────
#  MASTER PIPELINE
# ─────────────────────────────────────────────────────────────────

TOPIC_ROTATION = [
    "someone was already in the house when they got home",
    "things found in abandoned places that nobody can explain",
    "the night a stranger called and knew too much",
    "accounts posted at 3am that were deleted by sunrise",
    "wrong person wrong place wrong time — true stories",
    "the last messages people sent before disappearing",
    "neighbors who turned out to be something else entirely",
]

def run(topic: str, run_now: bool=False, day: Optional[str]=None,
        skip_upload: bool=False, skip_video: bool=False,
        viral_check_only: bool=False) -> Dict:

    _banner()
    result = {}
    gemini = init_gemini()

    # Optional viral pre-check
    if viral_check_only:
        score = score_virality(topic, gemini)
        print(f"\n{'─'*54}")
        print(f"  🔥 VIRAL SCORE: {score.get('weighted_total',score.get('total','?'))}/100")
        print(f"  📢 Verdict    : {score.get('verdict','')}")
        print(f"  💡 Tip        : {score.get('improvement_tip','')}")
        print(f"  🏆 Best title : {(score.get('titles') or ['—'])[0]}")
        print(f"{'─'*54}\n")
        result["viral_check"] = score
        return result

    # ── 1. Script ─────────────────────────────────────────────────
    log.info("━━━ [1/9] Viral Script Generation ━━━")
    script = generate_script(topic, gemini)
    result["script"] = script

    # ── 2. Audio (scene-based files) ──────────────────────────────
    log.info("━━━ [2/9] EdgeTTS Voice Generation ━━━")
    log.info(f"   {VOICE} | +8% rate | +10% volume | Humanoid tone system")
    segments = generate_all_audio(script)
    result["segments"] = segments

    # ── 3. Thumbnail ──────────────────────────────────────────────
    log.info("━━━ [3/9] CTR Thumbnail ━━━")
    thumb = make_thumbnail(script)
    result["thumbnail"] = thumb

    if skip_video:
        _report(script,"(skipped)",thumb)
        return result

    # ── 4. B-Roll Pool ────────────────────────────────────────────
    log.info("━━━ [4/9] B-Roll Fetching (Pexels + Pixabay) ━━━")
    broll = build_broll_pool(n=40)

    # ── 5. BG Music ───────────────────────────────────────────────
    log.info("━━━ [5/9] Dark Ambient Music ━━━")
    total_dur = sum(_probe(s["path"]) for s in segments)
    music     = gen_music(total_dur + 60)

    # ── 6. Segment Assembly ───────────────────────────────────────
    log.info("━━━ [6/9] Scene-by-Scene Assembly ━━━")
    seg_paths = []
    m_offset  = 0.0
    for seg in segments:
        path, dur = assemble(seg, broll, music, m_offset)
        seg_paths.append(path)
        m_offset += dur

    # ── 7. Transitions ────────────────────────────────────────────
    log.info("━━━ [7/9] Cinematic Transitions ━━━")
    transitions = [transition(seg_paths[i], seg_paths[i+1], i)
                   for i in range(len(seg_paths)-1)]

    # ── 8. Final Render ───────────────────────────────────────────
    log.info("━━━ [8/9] Final Render ━━━")
    out_path = OUT / f"{CFG['output']['video_filename_prefix']}{_ts()}.mp4"
    interleaved = []
    for i,sp in enumerate(seg_paths):
        interleaved.append(sp)
        if i < len(transitions) and transitions[i]:
            interleaved.append(transitions[i])

    ct = str(TEMP/"final_list.txt")
    with open(ct,"w") as f:
        for p in interleaved:
            if p and os.path.exists(p) and os.path.getsize(p)>500:
                f.write(f"file '{p}'\n")

    cmd = [
        "ffmpeg","-y","-f","concat","-safe","0","-i",ct,
        "-vf",f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
        "-c:v","libx264","-preset","medium","-crf","17",
        "-c:a","aac","-b:a","192k","-pix_fmt","yuv420p",
        "-movflags","+faststart",str(out_path)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log.warning("Retry concat without transitions...")
        simple = str(TEMP/"simple_list.txt")
        with open(simple,"w") as f:
            for p in seg_paths:
                if p and os.path.exists(p) and os.path.getsize(p)>500:
                    f.write(f"file '{p}'\n")
        subprocess.run(["ffmpeg","-y","-f","concat","-safe","0",
                         "-i",simple,"-c","copy",str(out_path)],
                        capture_output=True)

    result["video"] = str(out_path)
    log.info(f"✅ Final video: {out_path.name}")
    _report(script, str(out_path), thumb)

    if skip_upload:
        _cleanup()
        return result

    # ── 9. Upload ─────────────────────────────────────────────────
    log.info("━━━ [9/9] YouTube Upload ━━━")
    if run_now:
        vid_id = upload(str(out_path), thumb, script, publish=True)
    else:
        t = next_slot(day)
        if t and SCH["schedule"].get("enabled"):
            import pytz
            tz  = pytz.timezone(SCH["schedule"]["timezone"])
            now = datetime.now(tz)
            wait_sec = max(0,(t-now).total_seconds())
            if wait_sec > 0:
                log.info(f"⏳ Waiting {wait_sec/3600:.1f}h for scheduled slot...")
                time.sleep(wait_sec)
        vid_id = upload(str(out_path), thumb, script, publish=True)
    result["youtube_id"] = vid_id

    _cleanup()
    log.info("🎉 PIPELINE COMPLETE!")
    if vid_id:
        log.info(f"   ▶ https://www.youtube.com/watch?v={vid_id}")
    return result

# ─────────────────────────────────────────────────────────────────
#  CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Dark Confessions v4.0 — Viral Horror Documentary Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python main.py                              Auto-schedule mode
          python main.py --run-now                    Upload immediately
          python main.py --day sunday                 Force Sunday slot (PEAK)
          python main.py --topic "stalker stories"    Custom topic
          python main.py --skip-upload                Video only, no upload
          python main.py --skip-video                 Script + thumbnail only
          python main.py --viral-check "my topic"     Score virality first
        """)
    )
    parser.add_argument("--run-now",      action="store_true",
                         help="Generate and upload immediately")
    parser.add_argument("--day",          type=str, default=None,
                         help="Override upload day (monday–sunday)")
    parser.add_argument("--topic",        type=str, default=None,
                         help="Custom horror topic")
    parser.add_argument("--skip-upload",  action="store_true",
                         help="Generate video but skip upload")
    parser.add_argument("--skip-video",   action="store_true",
                         help="Script + thumbnail only, no video")
    parser.add_argument("--viral-check",  type=str, default=None,
                         metavar="TOPIC",
                         help="Score topic virality before production")
    args = parser.parse_args()

    if args.viral_check:
        run(args.viral_check, viral_check_only=True)
        return

    topic = args.topic or TOPIC_ROTATION[datetime.now().weekday() % len(TOPIC_ROTATION)]
    log.info(f"🎬 Topic: {topic}")

    run(
        topic        = topic,
        run_now      = args.run_now,
        day          = args.day,
        skip_upload  = args.skip_upload,
        skip_video   = args.skip_video,
    )

if __name__ == "__main__":
    main()
