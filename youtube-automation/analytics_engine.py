import random

def analytics():
    return {
        "ctr": round(random.uniform(4, 12), 2),
        "avg_view": random.randint(30, 80),
        "viral_score": random.randint(60, 95)
    }
