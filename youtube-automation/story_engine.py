import random

def generate_story(topic):
    hooks = [
        f"I found something disturbing about {topic}",
        f"This {topic} incident was never explained",
        f"Reddit users shared terrifying stories about {topic}",
        f"What happened with {topic} still doesn’t make sense"
    ]

    return {
        "title": random.choice(hooks),
        "topic": topic,
        "raw": f"Cinematic escalation story about {topic}"
    }
