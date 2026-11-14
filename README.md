# MIDI Visualizer

Windows desktop app for multi-track MIDI + audio visualisation.

## Included
- Multiple MIDI slots with per-track colours, enable/disable and independent time offset
- MIDI note parsing (pitch, velocity, duration and tempo)
- Project BPM scaling for MIDI timing
- Audio import: WAV, MP3, FLAC, OGG and M4A
- Two visual modes: MIDI GRID and smooth audio-reactive WAVEFORM bars
- Portrait 9:16 preview and offline MP4 export at 1080x1920, 30 or 60 FPS
- Dark interface, working glow intensity and timeline zoom controls; smooth waveform bars react to the playing audio
- Windows EXE build through GitHub Actions

## Run on Windows 10/11
Install Python 3.11 x64 and FFmpeg (add its bin folder to PATH), then run:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

Load audio and MIDI files, set project BPM and offsets, choose a visual mode, then export MP4. The renderer generates frames offline and muxes the original audio into H.264/AAC MP4.

## Notes
MIDI tempo scaling changes MIDI event timing; it does not time-stretch the audio. For tight sync, set the project BPM to the audio's actual tempo. Qt Multimedia playback codecs depend on Windows codec availability; FFmpeg is used for waveform decoding and MP4 rendering. Automatic BPM detection, project save/load and export cancellation remain future improvements.

Run tests with `python -m pytest -q`.
