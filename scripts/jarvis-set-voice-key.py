#!/usr/bin/env python3
"""Store the ElevenLabs API key in ~/.hermes/.env and switch speech over to it.

The key is read from the terminal, never from argv or an environment variable,
so it stays out of shell history and out of `ps`. It is never printed back.
"""
import getpass
import os
import stat
import sys
from pathlib import Path

ENV = Path.home() / ".hermes" / ".env"
SETTINGS = {"JARVIS_TTS_PROVIDER": "elevenlabs"}


def main() -> int:
    if not ENV.exists():
        print(f"{ENV} fehlt.", file=sys.stderr)
        return 1

    key = getpass.getpass("ElevenLabs API-Key (Eingabe bleibt unsichtbar): ").strip()
    if not key:
        print("Kein Key eingegeben, nichts geändert.")
        return 1
    if "\n" in key or "\r" in key:
        print("Der Key darf keinen Zeilenumbruch enthalten.", file=sys.stderr)
        return 1

    values = dict(SETTINGS, ELEVENLABS_API_KEY=key)
    lines = ENV.read_text().splitlines()
    seen = set()
    out = []
    for line in lines:
        name = line.split("=", 1)[0] if "=" in line else ""
        if name in values:
            out.append(f"{name}={values[name]}")
            seen.add(name)
        else:
            out.append(line)
    for name, value in values.items():
        if name not in seen:
            out.append(f"{name}={value}")

    ENV.write_text("\n".join(out) + "\n")
    os.chmod(ENV, stat.S_IRUSR | stat.S_IWUSR)
    print(f"Key gesetzt ({len(key)} Zeichen) und Sprachausgabe auf ElevenLabs gestellt.")
    print("Jetzt Bridge neu starten:")
    print("  launchctl kickstart -k gui/$(id -u)/com.jarvis.bridge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
