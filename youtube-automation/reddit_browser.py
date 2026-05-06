import json
import time
import random
from playwright.sync_api import sync_playwright

COOKIE_FILE = "reddit_cookies.json"


def save_cookies(context):
    cookies = context.cookies()
    with open(COOKIE_FILE, "w") as f:
        json.dump(cookies, f)


def load_cookies(context):
    try:
        with open(COOKIE_FILE, "r") as f:
            cookies = json.load(f)
        context.add_cookies(cookies)
        return True
    except:
        return False


def login_once():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://www.reddit.com/login/")
        print("Login manually. You have 90 seconds.")
        time.sleep(90)

        save_cookies(context)
        browser.close()


def fetch_posts(subreddit="LetsNotMeet", limit=10):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        load_cookies(context)

        page = context.new_page()
        page.goto(f"https://www.reddit.com/r/{subreddit}/top/?t=month")

        time.sleep(5)

        posts = []

        for _ in range(5):
            page.mouse.wheel(0, 3000)
            time.sleep(random.uniform(1.5, 3.5))

        cards = page.locator("shreddit-post").all()

        for card in cards[:limit]:
            try:
                title = card.get_attribute("post-title")
                url = card.get_attribute("content-href")
                posts.append({
                    "title": title,
                    "url": "https://reddit.com" + url
                })
            except:
                pass

        browser.close()
        return posts


if __name__ == "__main__":
    login_once()
    data = fetch_posts("LetsNotMeet", 15)
    print(data)
