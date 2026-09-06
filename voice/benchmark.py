#!/usr/bin/env python3
"""Local German TTS trial. No app data, cloud TTS, or voice cloning required."""
import argparse
import json
import time
import wave
from pathlib import Path

SAMPLE = 'Guten Abend, Marlon. Ich bin bereit. Sag mir einfach, was ich für dich erledigen soll.'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True, type=Path, help='Already downloaded model directory')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--speakers', nargs='+', default=['Ryan', 'Aiden'])
    args = parser.parse_args()
    import mlx.core as mx
    import numpy as np
    from mlx_audio.tts.utils import load_model

    # Keep this trial bounded on the owner's 8 GB M3; no persistent daemon.
    mx.set_cache_limit(128 * 1024 * 1024)
    mx.set_memory_limit(2 * 1024 * 1024 * 1024)
    args.output.mkdir(parents=True, exist_ok=True)
    loaded_at = time.monotonic()
    model = load_model(args.model, trust_remote_code=False)
    load_seconds = time.monotonic() - loaded_at
    print(f'Model loaded in {load_seconds:.2f}s', flush=True)
    measurements = []
    for speaker in args.speakers:
        mx.random.seed(42)
        started = time.monotonic()
        chunks = []
        first_audio_seconds = None
        for result in model.generate_custom_voice(
            text=SAMPLE, speaker=speaker, language='German',
            max_tokens=400, temperature=0.7, stream=True, streaming_interval=0.5,
        ):
            chunk = np.asarray(result.audio, dtype=np.float32).reshape(-1)
            if first_audio_seconds is None:
                first_audio_seconds = time.monotonic() - started
                print(f'{speaker}: first audio {first_audio_seconds:.2f}s', flush=True)
            chunks.append(chunk)
        elapsed = time.monotonic() - started
        if not chunks:
            raise RuntimeError('Model produced no audio')
        audio = np.concatenate(chunks)
        if not np.isfinite(audio).all() or np.max(np.abs(audio)) < 0.001:
            raise RuntimeError('Model produced invalid or silent audio')
        destination = args.output / f'{speaker.lower()}.wav'
        with wave.open(str(destination), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(model.sample_rate)
            wav.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())
        duration = len(audio) / model.sample_rate
        row = dict(speaker=speaker, first_audio_seconds=first_audio_seconds,
                   generation_seconds=elapsed, audio_seconds=duration,
                   real_time_factor=elapsed/duration, peak_memory_gb=mx.get_peak_memory()/1e9,
                   file=str(destination.resolve()))
        measurements.append(row)
        print(json.dumps(row), flush=True)
    (args.output/'benchmark.json').write_text(json.dumps(dict(
        sample=SAMPLE, load_seconds=load_seconds, voices=measurements), indent=2))


if __name__ == '__main__':
    main()
