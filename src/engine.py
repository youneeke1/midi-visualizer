from dataclasses import dataclass, field
import shutil, subprocess
from typing import List
import mido
import numpy as np
import soundfile as sf

@dataclass
class Note:
    start: float
    end: float
    pitch: int
    velocity: int
    channel: int = 0

@dataclass
class MidiTrack:
    path: str
    name: str
    color: str
    enabled: bool = True
    offset: float = 0.0
    notes: List[Note] = field(default_factory=list)
    source_bpm: float = 120.0

    def load(self, project_bpm=None):
        mid = mido.MidiFile(self.path)
        tempo, ticks = 500000, 0
        active, events = {}, []
        for msg in mido.merge_tracks(mid.tracks):
            ticks += msg.time
            if msg.type == "set_tempo":
                tempo = msg.tempo
            sec = mido.tick2second(ticks, mid.ticks_per_beat, tempo)
            if msg.type == "note_on" and msg.velocity > 0:
                active[(msg.channel, msg.note)] = (sec, msg.velocity)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                key = (msg.channel, msg.note)
                if key in active:
                    start, vel = active.pop(key)
                    events.append(Note(start, max(start + .025, sec), msg.note, vel, msg.channel))
        end_time = mido.tick2second(ticks, mid.ticks_per_beat, tempo)
        for (channel, pitch), (start, vel) in active.items():
            events.append(Note(start, max(start + .05, end_time), pitch, vel, channel))
        self.source_bpm = 60000000 / tempo
        ratio = self.source_bpm / project_bpm if project_bpm and project_bpm > 0 else 1.0
        self.notes = [Note(n.start*ratio+self.offset, n.end*ratio+self.offset, n.pitch, n.velocity, n.channel) for n in events]
        return self.notes

def decode_audio(path, target_rate=22050):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        cmd = [ffmpeg, "-v", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(target_rate), "pipe:1"]
        try:
            raw = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            data = np.frombuffer(raw, dtype=np.float32).copy()
            if data.size:
                return data, target_rate
        except Exception:
            pass
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != target_rate and len(mono):
        n = int(len(mono) * target_rate / sr)
        mono = np.interp(np.arange(n)/target_rate, np.arange(len(mono))/sr, mono).astype(np.float32)
    return mono, target_rate

def audio_duration(path):
    try:
        return sf.info(path).duration
    except Exception:
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            out = subprocess.check_output([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path], text=True)
            return float(out.strip())
        raise RuntimeError("Cannot read audio duration. Install FFmpeg and add it to PATH.")
