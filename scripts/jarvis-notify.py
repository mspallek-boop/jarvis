#!/usr/bin/env python3
"""Tell the JARVIS app something after the turn that started it has ended.

The bridge's /notify queue is the only way JARVIS reaches the app unasked: the
app polls it and puts each item into the chat — with a picture, as a JARVIS
message. Run this as the last step of background work:

    jarvis-notify "Der Hase ist fertig" --image /tmp/jarvis-media/hase.png
    jarvis-notify "Das Bild ging nicht" --text "pollinations.ai antwortet nicht"

An image outside /tmp/jarvis-media is copied in first, because the bridge reads
pictures from nowhere else. Exit status 0 only when the bridge took the item.
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
MEDIA = Path("/tmp/jarvis-media")
MEDIA_ROOTS = ("/tmp/jarvis-media/", "/private/tmp/jarvis-media/")
NOTIFY_URL = os.environ.get("JARVIS_NOTIFY_URL", "http://127.0.0.1:8770/notify")


def env_token(*names: str) -> str:
    """Tokens live in ~/.hermes/.env (600), never on the command line."""
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    try:
        found: dict[str, str] = {}
        for line in (HOME / ".hermes/.env").read_text().splitlines():
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            if key in names and value:
                found.setdefault(key, value)
        for name in names:
            if name in found:
                return found[name]
    except OSError:
        pass
    return ""


def stage(image: str) -> str:
    """A path the bridge will read: inside the media folder, a file of its own."""
    source = Path(image).expanduser()
    if not source.is_file():
        raise SystemExit(f"Bild nicht gefunden: {source}")
    if str(source).startswith(MEDIA_ROOTS) and "/" not in str(source).split("jarvis-media/", 1)[1] \
            and not source.name.startswith(".") and not source.is_symlink():
        return str(source)
    MEDIA.mkdir(exist_ok=True)
    target = MEDIA / f"{int(time.time())}-{source.name.lstrip('.')}"
    shutil.copyfile(source, target)
    return str(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("title", help="eine Zeile, höchstens 80 Zeichen")
    parser.add_argument("--text", default="", help="Zusatz, höchstens 200 Zeichen")
    parser.add_argument("--image", default="", help="PNG, JPEG, GIF, WEBP oder BMP")
    parser.add_argument("--kind", default="task", choices=["task", "info"])
    args = parser.parse_args()

    payload = {"kind": args.kind, "title": args.title, "text": args.text}
    if args.image:
        payload["image"] = stage(args.image)
    token = env_token("JARVIS_APP_TOKEN", "JARVIS_HUD_TOKEN")
    if not token:
        print("Kein JARVIS_APP_TOKEN in ~/.hermes/.env", file=sys.stderr)
        return 1
    request = urllib.request.Request(
        NOTIFY_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        body = json.loads(opener.open(request, timeout=8).read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        print(f"Bridge lehnt ab ({exc.code}): {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"Bridge nicht erreichbar: {exc}", file=sys.stderr)
        return 1
    item = body.get("notification", {})
    print(f"Gemeldet (#{item.get('id')}): {item.get('title')}"
          + (" — mit Bild" if args.image else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
