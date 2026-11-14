import mido
from src.engine import MidiTrack

def test_midi_parser_reads_note_and_timing(tmp_path):
    mid=mido.MidiFile(ticks_per_beat=480); tr=mido.MidiTrack(); mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo",tempo=500000,time=0))
    tr.append(mido.Message("note_on",note=60,velocity=100,time=0))
    tr.append(mido.Message("note_off",note=60,velocity=0,time=480))
    path=tmp_path/"test.mid"; mid.save(path)
    parsed=MidiTrack(str(path),"test","#ffffff"); notes=parsed.load(120)
    assert len(notes)==1 and notes[0].pitch==60
    assert abs(notes[0].end-.5)<1e-4

def test_offset_is_applied(tmp_path):
    mid=mido.MidiFile(); tr=mido.MidiTrack(); mid.tracks.append(tr)
    tr.append(mido.Message("note_on",note=64,velocity=90,time=0))
    tr.append(mido.Message("note_off",note=64,velocity=0,time=480))
    path=tmp_path/"offset.mid"; mid.save(path)
    notes=MidiTrack(str(path),"test","#fff",offset=1.25).load(120)
    assert abs(notes[0].start-1.25)<1e-6
