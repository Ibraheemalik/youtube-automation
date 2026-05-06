import random

def build_script(story, duration):
    segments = []
    total = duration * 6

    emotions = ["hook", "tension", "curiosity", "shock", "reveal"]

    for i in range(total):
        segments.append({
            "t": i,
            "emotion": random.choice(emotions),
            "visual": "faceless cinematic broll",
            "audio": "ambient_drone",
            "cut": random.choice(["zoom", "glitch", "fade", "parallax"])
        })

    return {
        "title": story["title"],
        "segments": segments,
        "duration": duration
    }
