"""
Read the notifications that are currently showing on your Android phone ("read my instagram notifications").

How it works: `adb shell dumpsys notification --noredact` lists every active notification as text. Without
--noredact Android hides the contents, so the flag is what makes the title and message readable. We split
the dump into notification records, pull out the app (pkg), title and text, filter by app, and speak a short summary.

If you say "unlock my phone and read ...", the phone is unlocked first using JARVIS's existing unlock flow.
Honest limit: only notifications that are still showing on the phone can be read, not ones you already dismissed.
"""
import re

META = {
    "name": "phone_notifications",
    "description": "Reads active notifications (optionally for one app) from the connected Android phone",
    "triggers": [
        # "read my instagram notifications", "any whatsapp notifications", "unlock my phone and read my insta notifications"
        r"\b(?:read|check|show|any|what(?:'s| are| is)?)\b.*\b(?P<app>instagram|insta|whatsapp|telegram|gmail)\b.*\bnotifications?\b",
        # "read my phone notifications"
        r"\b(?:read|check|show)\b.*\bphone\b.*\bnotifications?\b",
    ],
    "permissions": ["phone", "phone_unlock"],
}

APPS = {                       # spoken name -> (Android package, name to say aloud)
    "instagram": ("com.instagram.android", "Instagram"),
    "insta": ("com.instagram.android", "Instagram"),
    "whatsapp": ("com.whatsapp", "WhatsApp"),
    "telegram": ("org.telegram.messenger", "Telegram"),
    "gmail": ("com.google.android.gm", "Gmail"),
}
MAX_READ = 5                   # how many notifications to read out loud


def _extra(block, key):
    """Value of an 'android.title=String (Hello)' style line inside one notification record, or ''."""
    m = re.search(rf"^\s*{re.escape(key)}=\w+ \((.*)\)\s*$", block, re.M)
    return m.group(1).strip() if m else ""


def parse_notifications(dump):
    """dumpsys text -> [{'pkg', 'title', 'text'}], duplicates removed, newest-first order as Android lists them."""
    dump = dump.replace("\r", "")
    found, seen = [], set()
    for block in dump.split("NotificationRecord(")[1:]:
        pkg = re.search(r"\bpkg=(\S+)", block)
        if not pkg:
            continue
        title = _extra(block, "android.title")
        text = _extra(block, "android.bigText") or _extra(block, "android.text")
        if title.lower() == "null":
            title = ""
        if text.lower() == "null":
            text = ""
        if not (title or text):
            continue
        key = (pkg.group(1), title, text)
        if key in seen:                                  # the dump can list the same notification twice
            continue
        seen.add(key)
        found.append({"pkg": pkg.group(1), "title": title, "text": text})
    return found


def run(ctx, command, match):
    if not ctx.phone_connected():
        return "My phone isn't connected. Plug it in with USB debugging switched on."

    if re.search(r"\bunlock", command):                  # "unlock my phone and read ..." -> reuse the existing unlock flow
        result = ctx.unlock_phone()
        unlocked = "Unlocked" in result or "already unlocked" in result
        if ctx.cancelled or not unlocked:
            return result

    spoken = (match.groupdict().get("app") or "").lower()
    pkg, label = APPS.get(spoken, (None, "phone"))

    rc, out = ctx.adb("shell", "dumpsys notification --noredact | head -c 400000", timeout=25)
    if rc != 0 or not out.strip():
        return "I couldn't read the notifications. Some phones block that over USB."

    items = parse_notifications(out)
    if "NotificationRecord(" in out and not items:        # the format is not what we expected: save it so it can be fixed
        with open(ctx.data_path("raw_dump.txt"), "w", encoding="utf-8") as f:
            f.write(out)
        return "I found notifications but couldn't understand their format. I saved a sample for debugging."
    if pkg:
        items = [i for i in items if i["pkg"] == pkg]
    if not items:
        return f"There are no {label} notifications showing right now."

    n = len(items)
    lines = [f"You have {n} {label} notification{'s' if n != 1 else ''}."]
    for i in items[:MAX_READ]:
        lines.append(f"{i['title']}: {i['text']}." if i["title"] and i["text"] else f"{i['title'] or i['text']}.")
    if n > MAX_READ:
        lines.append(f"And {n - MAX_READ} more.")
    return " ".join(lines)