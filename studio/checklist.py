"""What has to be added by hand on this computer before PeakCut works fully.

Keys, cookies and settings are kept out of the code on purpose (they are listed in .gitignore), so a fresh copy of
PeakCut starts without them. This list says, in one place, which of them are still missing and how to add each one.
It is shown in Settings, Setup, and the ones that matter show up as next steps on the home page until they are done.

Each item: {key, title, need, done, status, steps, tab}
  need:  "required" (PeakCut cannot work without it), "recommended" (works, but worse) or "optional"
  tab:   the Settings section where it is set from the page, or None when it is set in the .env file
"""
import time
from pathlib import Path

from . import config

ENV_FILE = ".env file in the PeakCut folder"


def _ffmpeg() -> dict:
    from . import tools
    gone = tools.missing()
    return {"key": "ffmpeg", "title": "ffmpeg", "need": "required", "done": not gone, "tab": None,
            "status": "Installed." if not gone else "Not installed, so videos cannot be cut.",
            "steps": [] if not gone else [tools.HELP, "PeakCut notices it within a minute, no restart needed."]}


def _ai() -> dict:
    from . import ai
    ok = ai.ready()
    return {"key": "ai", "title": "AI key", "need": "recommended", "done": ok, "tab": "ai",
            "status": f"Set up ({ai.label()})." if ok else "Not set. Clips are picked by loudness only.",
            "steps": [] if ok else ["Open Settings, AI.", "Choose a service, paste your key and pick a model, then press Save.",
                                    "The key is kept in the data folder, which is never published."]}


def _cookies() -> dict:
    """YouTube sometimes asks downloads to sign in ("confirm you're not a bot", age-restricted streams). Cookies from a
    signed-in browser get past that. They are set only in the .env file, so the page cannot change them."""
    how = ["In a browser signed in to YouTube, install a cookies.txt exporter (for example \"Get cookies.txt LOCALLY\") and export the cookies for youtube.com.",
           "Save the file as cookies.txt in the PeakCut folder. It is already in .gitignore, so it is never published.",
           f"Add this line to the {ENV_FILE}:  PEAKCUT_YT_COOKIES_FILE=<full path to cookies.txt>",
           "Restart PeakCut.",
           "Cookies are a login: never share the file. YouTube expires them after a while; export a new file when downloads start asking to sign in again."]
    item = {"key": "cookies", "title": "YouTube cookies", "need": "recommended", "tab": None}
    if config.YT_COOKIES_FILE:
        f = Path(config.YT_COOKIES_FILE)
        if not f.is_file():
            return {**item, "done": False, "status": f"The .env file points to a cookies file that is not there ({f.name}).",
                    "steps": ["Check the path in PEAKCUT_YT_COOKIES_FILE, or export the file again:"] + how}
        days = int((time.time() - f.stat().st_mtime) // 86400)
        old = days > 60
        return {**item, "done": True, "status": f"Using {f.name}, exported {days} day{'s' if days != 1 else ''} ago." +
                (" It may have expired: export a new one if YouTube downloads fail." if old else ""),
                "steps": how[:2] if old else []}
    if config.YT_COOKIES_BROWSER:
        return {**item, "done": True, "status": f"Using the cookies of the {config.YT_COOKIES_BROWSER} browser on this computer.", "steps": []}
    return {**item, "done": False, "status": "Not set. Some YouTube streams (age-restricted, or when YouTube suspects a bot) will not download.",
            "steps": how}


def _apps() -> dict:
    from . import accounts
    ready = [accounts.PLATFORM_NAMES[p] for p in accounts.PLATFORM_NAMES if accounts.can_connect(p)]
    return {"key": "apps", "title": "Posting apps", "need": "optional", "done": bool(ready), "tab": "apps",
            "status": ("Ready for " + ", ".join(ready) + ".") if ready else "None set up. Clips can still be downloaded and posted by hand.",
            "steps": [] if ready else ["Open Settings, Connected apps, and press Set up next to YouTube, Instagram or TikTok.",
                                       "Each one needs an app made on that platform's developer site; the page walks through it."]}


def _card() -> dict:
    from . import gpu
    s = gpu.status()
    if not s["card"]:
        return {"key": "card", "title": "Graphics card", "need": "optional", "done": True, "tab": "speed",
                "status": "No NVIDIA card in this computer. Everything runs on the processor.", "steps": []}
    on = [n for n, k in (("making clips", "encode"), ("transcripts", "speech")) if s[k]["active"]]
    broken = [s[k]["problem"] for k in ("encode", "speech") if s[k]["on"] and not s[k]["ok"]]
    return {"key": "card", "title": "Graphics card", "need": "optional", "done": not broken, "tab": "speed",
            "status": (broken[0] if broken else ("Used for " + " and ".join(on) + "." if on else "Found, not in use.")),
            "steps": ["Open Settings, Speed, to see what is missing."] if broken else []}


def _signin() -> list:
    """Only when PeakCut is a site other people sign in to (PEAKCUT_ACCOUNTS=1)."""
    from . import mailer
    cid, secret = config.google_client()
    mail = mailer.ready()
    return [
        {"key": "email", "title": "Email for sign-in links", "need": "required", "done": mail, "tab": None,
         "status": "Set up." if mail else "Not set. Sign-in and reset links are only written to the server log.",
         "steps": [] if mail else [f"Add PEAKCUT_SMTP_HOST, PEAKCUT_SMTP_USER, PEAKCUT_MAIL_FROM and PEAKCUT_SMTP_PASSWORD_FILE (a file holding the password) to the {ENV_FILE}.",
                                   "See .env.example for each one, then restart PeakCut."]},
        {"key": "google", "title": "Sign in with Google", "need": "optional", "done": bool(cid and secret), "tab": None,
         "status": "Set up." if cid and secret else "Not set. People sign in with email instead.",
         "steps": [] if cid and secret else [f"Add GOOGLE_CLIENT_FILE (the JSON Google lets you download) to the {ENV_FILE}, then restart PeakCut.",
                                             "Keep that JSON file outside the PeakCut folder, or name it *client_secret*.json so it is never published."]},
    ]


def _safe(fn, key, title):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - one broken check must not hide the rest of the list
        return {"key": key, "title": title, "need": "optional", "done": False, "tab": None,
                "status": "Could not be checked: " + str(e)[:150], "steps": []}


def items() -> list:
    out = [_safe(_ffmpeg, "ffmpeg", "ffmpeg"), _safe(_ai, "ai", "AI key"), _safe(_cookies, "cookies", "YouTube cookies"),
           _safe(_apps, "apps", "Posting apps"), _safe(_card, "card", "Graphics card")]
    if config.ACCOUNTS:
        try:
            out += _signin()
        except Exception:  # noqa: BLE001
            pass
    return out


def todo() -> list:
    """The few that the home page shows until they are done: required and recommended ones only. Quick: nothing
    here starts a program or opens the network (the graphics card and posting apps are left to Settings)."""
    return [{"key": i["key"], "title": i["title"], "status": i["status"], "tab": i["tab"]}
            for i in (_safe(_ffmpeg, "ffmpeg", "ffmpeg"), _safe(_ai, "ai", "AI key"), _safe(_cookies, "cookies", "YouTube cookies"))
            if not i["done"]]
