#!/usr/bin/env python3
"""Keep XcodeGen's modern watchOS app in the iOS app's Watch directory."""

from pathlib import Path


project_file = Path(__file__).resolve().parents[1] / "JARVIS.xcodeproj" / "project.pbxproj"
contents = project_file.read_text(encoding="utf-8")
phase_name = "/* Embed Watch Content */ = {"
phase_start = contents.find(phase_name)
if phase_start < 0:
    raise SystemExit("Embed Watch Content build phase was not generated")

phase_end = contents.find("\n\t\t};", phase_start)
if phase_end < 0:
    raise SystemExit("Embed Watch Content build phase is malformed")

phase = contents[phase_start:phase_end]
phase = phase.replace('dstPath = "";', 'dstPath = "$(CONTENTS_FOLDER_PATH)/Watch";')
phase = phase.replace("dstSubfolderSpec = 13;", "dstSubfolderSpec = 16;")

if "dstSubfolderSpec = 16;" not in phase or "$(CONTENTS_FOLDER_PATH)/Watch" not in phase:
    raise SystemExit("Could not configure the Watch embedding destination")

contents = contents[:phase_start] + phase + contents[phase_end:]
project_file.write_text(contents, encoding="utf-8")
