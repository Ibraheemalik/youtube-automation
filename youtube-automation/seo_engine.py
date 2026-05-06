import random

def generate_seo(topic):
    titles = [
        f"The Dark Truth About {topic}",
        f"This {topic} Story Is Terrifying",
        f"I Should NOT Have Seen This {topic}..."
    ]

    tags = ["reddit", "horror", "true story", topic]

    return {
        "titles": titles,
        "tags": tags
    }


def thumbnail_prompt(topic):
    return f"dark cinematic fog silhouette horror {topic}"
