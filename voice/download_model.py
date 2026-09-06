#!/usr/bin/env python3
"""Download only public weights/tokenizer data, pinned to the reviewed snapshot."""
import json
from pathlib import Path
from huggingface_hub import snapshot_download

REPO = 'mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-4bit'
REVISION = '08c72cad5e2fd0f41730c8bd1f28149585e46361'
DESTINATION = Path(__file__).resolve().parents[1] / 'LocalData/Runtime/voice-models/qwen3-0.6b-custom-4bit'

if __name__ == '__main__':
    snapshot_download(REPO, revision=REVISION, token=False, local_dir=DESTINATION,
                      allow_patterns=['*.json', '*.safetensors', '*.txt', '*.model',
                                      '*.tiktoken', '*.jinja', 'LICENSE*', 'README.md'])
    (DESTINATION/'jarvis-source.json').write_text(json.dumps(
        {'repo': REPO, 'revision': REVISION}, indent=2))
    print('Public model ready:', DESTINATION)
