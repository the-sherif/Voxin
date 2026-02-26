#!/usr/bin/env python3
"""
Worker-процесс: загружает faster-whisper, читает пути к WAV из stdin,
пишет распознанный текст в stdout.
"""
import sys
from faster_whisper import WhisperModel

model = WhisperModel("base", device="cpu", compute_type="int8")
sys.stdout.write("ready\n")
sys.stdout.flush()

for line in sys.stdin:
    path = line.strip()
    if not path:
        continue
    try:
        segments, _ = model.transcribe(path, beam_size=5)
        text = " ".join(seg.text for seg in segments).strip()
        sys.stdout.write(text + "\n")
    except Exception as e:
        sys.stdout.write(f"ERROR:{e}\n")
    sys.stdout.flush()
