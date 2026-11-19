"""The list of things added by hand (Settings, Setup, and the home page's next steps). Runs against the code directly,
with its own empty data folder and its own cookie file: nothing outside it is touched."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-setup-")
cookie = Path(tempfile.mkdtemp(prefix="pc-cookie-")) / "cookies.txt"
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_AI_PROVIDER="gemini", PEAKCUT_AI_MODELS="", PEAKCUT_AI_KEY="",
                  PEAKCUT_AI_KEY_FILE="", PEAKCUT_PUBLIC_URL="http://127.0.0.1:8765",
                  PEAKCUT_YT_COOKIES_FILE=str(cookie), PEAKCUT_YT_COOKIES_BROWSER="")    # set before the .env file is read
sys.path.insert(0, ".")
from fastapi.testclient import TestClient  # noqa: E402

from studio import checklist, config, db, server  # noqa: E402

db.init()
fails = []
BASE = "http://127.0.0.1:8765"
c = TestClient(server.app, base_url=BASE, follow_redirects=False)


def check(name, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {got!r}"))
    ok or fails.append(name)


def item(key):
    return next(i for i in c.get("/api/setup").json()["items"] if i["key"] == key)


# ---- the list itself
r = c.get("/api/setup")
check("Settings, Setup answers", r.status_code, 200)
keys = [i["key"] for i in r.json()["items"]]
check("it covers ffmpeg, the AI key, YouTube cookies, posting apps and the graphics card", keys, ["ffmpeg", "ai", "cookies", "apps", "card"])
check("every item says what it is, how much it matters and where it stands",
      all(set(i) >= {"key", "title", "need", "done", "status", "steps", "tab"} and i["need"] in ("required", "recommended", "optional") for i in r.json()["items"]))

# ---- YouTube cookies
it = item("cookies")
check("a cookies file that is not there counts as missing", it["done"], False)
check("...and says which file it looked for", "cookies.txt" in it["status"], True)
check("...and how to export it", any("export" in s.lower() for s in it["steps"]), True)
cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
it = item("cookies")
check("once the file is there it counts as done", it["done"], True)
check("...without showing the full path", str(cookie.parent) in it["status"], False)
old = time.time() - 90 * 86400
os.utime(cookie, (old, old))
it = item("cookies")
check("an old cookies file is still used, with a warning that it may have expired", (it["done"], "expired" in it["status"]), (True, True))
config.YT_COOKIES_FILE = ""
it = item("cookies")
check("no cookies at all: missing, with every step to add them", (it["done"], len(it["steps"]) >= 4), (False, True))
check("...and the steps say the file is never published", any("gitignore" in s for s in it["steps"]), True)
config.YT_COOKIES_BROWSER = "firefox"
check("borrowing a browser's cookies counts as done", item("cookies")["done"], True)
config.YT_COOKIES_BROWSER = ""

# ---- the home page's next steps
todo = c.get("/api/status").json()["setup"]
check("the home page lists what is still to do", sorted(x["key"] for x in todo), lambda k: "ai" in k and "cookies" in k)
check("...but never the optional ones", any(x["key"] in ("apps", "card") for x in todo), False)
check("...and the AI key opens the AI settings", next(x["tab"] for x in todo if x["key"] == "ai"), "ai")
check("...while cookies, set in the .env file, open Setup", next(x["tab"] for x in todo if x["key"] == "cookies"), None)

# ---- one broken check does not hide the others
real = checklist._ai
checklist._ai = lambda: 1 / 0
check("a check that breaks shows as one line, not an error page", item("ai")["status"].startswith("Could not be checked"), True)
check("...and the rest of the list is still there", len(c.get("/api/setup").json()["items"]), 5)
checklist._ai = real

print(f"\n{len(fails)} failed" if fails else "\nALL PASSED")
sys.exit(1 if fails else 0)
