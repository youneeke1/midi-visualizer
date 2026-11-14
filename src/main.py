import sys
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, QUrl, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import *
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from .engine import MidiTrack, decode_audio, audio_duration
from .renderer import VideoRenderer

PALETTE=["#a970ff","#54c8ff","#ff6b82","#69d69a","#ffd166","#ff9f43","#d78bff","#9da8b8","#f47bd1","#8bc5a8"]

class Preview(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 520)
        self.setMaximumSize(430, 740)
        self.tracks = []
        self.bpm = 120
        self.mode = "MIDI GRID"
        self.position = 0
        self.duration = 1
        self.samples = np.array([], dtype=np.float32)
        self.sr = 11025
        self.glow = 0.7
        self.zoom = 1.0
        self.smoothed_bands = np.zeros(64, dtype=np.float32)

    def audio_bands(self, count=64):
        if self.samples.size == 0:
            return np.zeros(count, dtype=np.float32)
        size = 4096
        center = int(self.position * self.sr)
        start = max(0, center - size // 2)
        chunk = self.samples[start:start + size]
        if len(chunk) < size:
            chunk = np.pad(chunk, (0, size - len(chunk)))
        spectrum = np.abs(np.fft.rfft(chunk * np.hanning(size))).astype(np.float32)
        spectrum = spectrum[2: min(len(spectrum), 1400)]
        groups = np.array_split(spectrum, count)
        values = np.array([float(np.sqrt(np.mean(g * g))) if len(g) else 0.0 for g in groups], dtype=np.float32)
        peak = max(float(np.percentile(values, 90)), 1e-5)
        values = np.clip(values / peak, 0, 1)
        values = np.sqrt(values)
        self.smoothed_bands = self.smoothed_bands * 0.68 + values * 0.32
        return self.smoothed_bands

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor("#09090e"))
        p.setPen(QPen(QColor("#201d29")))
        for x in range(0, r.width(), 28):
            p.drawLine(x, 0, x, r.height())
        for y in range(0, r.height(), 28):
            p.drawLine(0, y, r.width(), y)
        p.setPen(QColor("#e9e4f2"))
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        p.drawText(12, 28, "MIDI VISUALIZER")
        p.setPen(QColor("#817c8d"))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(12, 47, f"{self.bpm} BPM   ·   {self.mode}")

        top, bottom = 85, r.height() - 105
        left, right = 16, r.width() - 16
        span = 8 / max(0.35, self.zoom)
        start = max(0.0, self.position - span * 0.2)
        enabled = [t for t in self.tracks if t.enabled]

        if self.mode == "MIDI GRID":
            for pitch in range(36, 97, 12):
                y = bottom - (pitch - 36) / 60 * (bottom - top)
                p.setPen(QPen(QColor("#292533")))
                p.drawLine(left, int(y), right, int(y))
            for t in enabled:
                c = QColor(t.color)
                for n in t.notes:
                    if n.end < start or n.start > start + span:
                        continue
                    x = left + (n.start - start) / span * (right - left)
                    ex = left + (n.end - start) / span * (right - left)
                    y = bottom - (n.pitch - 36) / 60 * (bottom - top)
                    active = n.start <= self.position < n.end
                    p.setPen(Qt.NoPen)
                    if active and self.glow > 0:
                        p.setBrush(QColor(c.red(), c.green(), c.blue(), int(30 + 65 * self.glow)))
                        p.drawRoundedRect(int(x - 3), int(y - 9), max(8, int(ex - x) + 6), 18, 8, 8)
                    p.setBrush(c if active else QColor(c.red(), c.green(), c.blue(), 145))
                    p.drawRoundedRect(int(x), int(y - 4), max(3, int(ex - x)), 8, 4, 4)

        elif self.mode == "WAVEFORM":
            bands = self.audio_bands(64)
            lane_h = (bottom - top) / max(1, len(enabled))
            for lane, t in enumerate(enabled):
                mid = top + (lane + 0.5) * lane_h
                c = QColor(t.color)
                p.setPen(QPen(QColor("#25212d"), 1))
                p.drawLine(left, int(mid), right, int(mid))
                bar_step = (right - left) / len(bands)
                bar_w = max(2, int(bar_step * 0.56))
                for i, value in enumerate(bands):
                    x = left + (i + 0.5) * bar_step
                    height = max(2, int(value * lane_h * 0.43))
                    if self.glow > 0:
                        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), int(35 * self.glow)), bar_w + 5))
                        p.drawLine(int(x), int(mid - height), int(x), int(mid + height))
                    p.setPen(Qt.NoPen)
                    p.setBrush(c)
                    p.drawRoundedRect(int(x - bar_w / 2), int(mid - height), bar_w, height * 2, 3, 3)
                p.setPen(QColor(t.color))
                p.setFont(QFont("Segoe UI", 7))
                p.drawText(left + 2, int(top + lane * lane_h + 13), t.name[:18])

        # The playhead follows the same time-to-pixel mapping as the MIDI notes.
        play_x = left + max(0.0, min(1.0, (self.position - start) / span)) * (right - left)
        p.setPen(QPen(QColor("#f3eaff"), 2))
        p.drawLine(int(play_x), top, int(play_x), bottom)
        p.setPen(QColor("#9b8cae"))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(12, r.height() - 18, "AUDIO REACTIVE  ·  9:16")

class ExportThread(QThread):
    progress=Signal(int); done=Signal(str); failed=Signal(str)
    def __init__(self,renderer,path): super().__init__(); self.renderer=renderer; self.path=path
    def run(self):
        try: self.renderer.render(self.path,self.progress.emit); self.done.emit(self.path)
        except Exception as e: self.failed.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("MIDI Visualizer"); self.resize(1450,950); self.setMinimumSize(1120,760)
        self.audio=None; self.duration=0; self.tracks=[]; self.wave=np.array([],dtype=np.float32); self.mode="MIDI GRID"
        self.player=QMediaPlayer(self); self.audio_out=QAudioOutput(self); self.player.setAudioOutput(self.audio_out)
        self.player.positionChanged.connect(self.on_position); self.player.durationChanged.connect(self.update_time)
        self.timer=QTimer(self); self.timer.timeout.connect(self.sync_preview); self.timer.start(40)
        self.build(); self.theme()
    def label(self,s):
        x=QLabel(s); x.setStyleSheet("color:#9a94a6;font-size:10px;font-weight:700;letter-spacing:1.4px"); return x
    def build(self):
        c=QWidget(); self.setCentralWidget(c); root=QVBoxLayout(c); root.setContentsMargins(20,18,20,18); root.setSpacing(12)
        head=QHBoxLayout(); title=QLabel("MIDI VISUALIZER"); title.setStyleSheet("font-size:20px;font-weight:800;letter-spacing:3px"); head.addWidget(title); head.addStretch()
        self.bpm=QSpinBox(); self.bpm.setRange(20,300); self.bpm.setValue(140); self.bpm.setSuffix(" BPM"); self.bpm.valueChanged.connect(self.reload_midis); head.addWidget(self.bpm)
        self.audio_btn=QPushButton("＋  Load Audio"); self.audio_btn.clicked.connect(self.load_audio); head.addWidget(self.audio_btn)
        add=QPushButton("＋  Add MIDI"); add.clicked.connect(self.add_midi); head.addWidget(add); root.addLayout(head)
        split=QSplitter(Qt.Horizontal); root.addWidget(split,1)
        left=QFrame(); left.setObjectName("panel"); l=QVBoxLayout(left); l.addWidget(self.label("PROJECT / MIDI SLOTS"))
        self.audio_label=QLabel("No audio loaded"); self.audio_label.setObjectName("muted"); self.audio_label.setWordWrap(True); l.addWidget(self.audio_label)
        self.slot_list=QListWidget(); self.slot_list.setSpacing(5); self.slot_list.currentRowChanged.connect(self.select_track); l.addWidget(self.slot_list,1)
        row=QHBoxLayout(); self.add_btn=QPushButton("Add MIDI"); self.add_btn.clicked.connect(self.add_midi); row.addWidget(self.add_btn)
        rem=QPushButton("Remove"); rem.clicked.connect(self.remove_track); row.addWidget(rem); l.addLayout(row)
        l.addWidget(self.label("TRACK OFFSET (SECONDS)")); self.offset=QDoubleSpinBox(); self.offset.setRange(-600,600); self.offset.setDecimals(3); self.offset.setSingleStep(.01); self.offset.valueChanged.connect(self.change_offset); l.addWidget(self.offset)
        l.addWidget(self.label("VISUAL MODE")); self.mode_box=QComboBox(); self.mode_box.addItems(["MIDI GRID","WAVEFORM"]); self.mode_box.currentTextChanged.connect(self.change_mode); l.addWidget(self.mode_box)
        self.glow=QSlider(Qt.Horizontal); self.glow.setRange(0,100); self.glow.setValue(70); self.glow.valueChanged.connect(self.update_visual_settings); l.addWidget(QLabel("Glow intensity")); l.addWidget(self.glow)
        self.zoom=QSlider(Qt.Horizontal); self.zoom.setRange(35,200); self.zoom.setValue(100); self.zoom.valueChanged.connect(self.update_visual_settings); l.addWidget(QLabel("Timeline zoom")); l.addWidget(self.zoom)
        self.wave_check=QCheckBox("Show audio waveform"); self.wave_check.setChecked(True); l.addWidget(self.wave_check); split.addWidget(left)
        right=QFrame(); right.setObjectName("panel"); rr=QVBoxLayout(right); top=QHBoxLayout(); top.addWidget(self.label("LIVE PREVIEW")); top.addStretch()
        self.status=QLabel("READY"); self.status.setObjectName("pill"); top.addWidget(self.status); rr.addLayout(top)
        self.preview=Preview(); rr.addWidget(self.preview,1,Qt.AlignCenter)
        controls=QHBoxLayout(); self.play=QPushButton("▶ Play"); self.play.clicked.connect(self.toggle_play); controls.addWidget(self.play)
        self.seek=QSlider(Qt.Horizontal); self.seek.setRange(0,1000); self.seek.sliderMoved.connect(self.seek_to); controls.addWidget(self.seek,1)
        self.time=QLabel("00:00 / 00:00"); self.time.setObjectName("muted"); controls.addWidget(self.time); rr.addLayout(controls)
        exp=QHBoxLayout(); exp.addWidget(self.label("EXPORT  ·  MP4 / 1080 × 1920")); exp.addStretch()
        self.fps=QComboBox(); self.fps.addItems(["30 FPS","60 FPS"]); self.fps.setCurrentIndex(1); exp.addWidget(self.fps)
        self.export=QPushButton("Export MP4"); self.export.clicked.connect(self.export_video); exp.addWidget(self.export); rr.addLayout(exp)
        self.progress=QProgressBar(); self.progress.setVisible(False); rr.addWidget(self.progress); split.addWidget(right); split.setSizes([340,1000])
        self.setStatusBar(QStatusBar()); self.statusBar().showMessage("Load an audio file and MIDI files to begin.")
    def theme(self):
        self.setStyleSheet("""QMainWindow,QWidget{background:#101014;color:#eeeaf4;font-family:Segoe UI;font-size:10pt} QFrame#panel{background:#18181f;border:1px solid #292933;border-radius:14px} QPushButton{background:#292733;border:1px solid #3a3745;border-radius:8px;padding:9px 13px;color:#f1edf8} QPushButton:hover{background:#383344;border-color:#8060ad} QSpinBox,QDoubleSpinBox,QComboBox{background:#22212a;border:1px solid #393744;border-radius:7px;padding:7px} QListWidget{background:transparent;border:0} QListWidget::item{background:#22212a;border:1px solid #32313d;border-radius:8px;padding:7px} QLabel#muted{color:#777786;font-size:9pt} QLabel#pill{color:#c8a8ff;background:#30243e;border:1px solid #533b70;padding:6px 12px;border-radius:9px} QProgressBar{background:#25232d;border:0;border-radius:4px;height:8px} QProgressBar::chunk{background:#a970ff;border-radius:4px}""")
    def load_audio(self):
        path,_=QFileDialog.getOpenFileName(self,"Load audio","","Audio (*.wav *.mp3 *.flac *.ogg *.m4a)")
        if not path:return
        try:
            self.audio=path; self.duration=audio_duration(path); samples,sr=decode_audio(path,11025); block=max(1,int(sr*.02))
            self.wave=np.array([np.max(np.abs(samples[i:i+block])) for i in range(0,len(samples),block)],dtype=np.float32)
            self.audio_label.setText(Path(path).name); self.audio_btn.setText("♪ "+Path(path).name[:20])
            self.player.setSource(QUrl.fromLocalFile(path)); self.preview.samples=samples; self.preview.sr=sr; self.preview.duration=self.duration; self.preview.smoothed_bands=np.zeros(64,dtype=np.float32); self.refresh_state()
        except Exception as e: QMessageBox.critical(self,"Audio error",str(e))
    def add_midi(self):
        paths,_=QFileDialog.getOpenFileNames(self,"Add MIDI files","","MIDI (*.mid *.midi)")
        for path in paths:
            if any(t.path==path for t in self.tracks):continue
            t=MidiTrack(path,Path(path).stem,PALETTE[len(self.tracks)%len(PALETTE)])
            try:t.load(self.bpm.value()); self.tracks.append(t)
            except Exception as e:QMessageBox.warning(self,"MIDI error",f"{Path(path).name}: {e}")
        self.refresh_slots(); self.refresh_state()
    def refresh_slots(self):
        self.slot_list.blockSignals(True); self.slot_list.clear()
        for i,t in enumerate(self.tracks):
            item=QListWidgetItem(); w=QWidget(); row=QHBoxLayout(w); row.setContentsMargins(4,2,4,2)
            chk=QCheckBox(); chk.setChecked(t.enabled); chk.stateChanged.connect(lambda v,j=i:self.set_enabled(j,v==Qt.Checked)); row.addWidget(chk)
            col=QPushButton("●"); col.setStyleSheet(f"color:{t.color};font-size:18px;border:0;background:transparent;padding:0"); col.clicked.connect(lambda _,j=i:self.choose_color(j)); row.addWidget(col)
            name=QLabel(t.name); name.setToolTip(t.path); row.addWidget(name,1); row.addWidget(QLabel(f"{len(t.notes)} notes"))
            w.setLayout(row); item.setSizeHint(w.sizeHint()); self.slot_list.addItem(item); self.slot_list.setItemWidget(item,w)
        self.slot_list.blockSignals(False)
    def select_track(self,i):
        self.offset.blockSignals(True); self.offset.setValue(self.tracks[i].offset if 0<=i<len(self.tracks) else 0); self.offset.blockSignals(False)
    def set_enabled(self,i,v): self.tracks[i].enabled=v; self.refresh_state()
    def choose_color(self,i):
        c=QColorDialog.getColor(QColor(self.tracks[i].color),self,"Track colour")
        if c.isValid():self.tracks[i].color=c.name();self.refresh_slots();self.refresh_state()
    def remove_track(self):
        i=self.slot_list.currentRow()
        if i>=0:self.tracks.pop(i);self.refresh_slots();self.refresh_state()
    def change_offset(self,v):
        i=self.slot_list.currentRow()
        if 0<=i<len(self.tracks):
            t=self.tracks[i];t.offset=v;t.load(self.bpm.value());self.refresh_slots();self.refresh_state()
    def reload_midis(self,v):
        for t in self.tracks:t.load(v)
        self.refresh_slots();self.refresh_state()
    def change_mode(self,m): self.mode=m; self.refresh_state()
    def update_visual_settings(self,*args):
        self.preview.glow=self.glow.value()/100
        self.preview.zoom=self.zoom.value()/100
        self.preview.update()
    def refresh_state(self):
        self.preview.glow=self.glow.value()/100; self.preview.zoom=self.zoom.value()/100
        self.preview.tracks=self.tracks;self.preview.bpm=self.bpm.value();self.preview.mode=self.mode;self.preview.update()
        self.export.setEnabled(bool(self.audio and self.tracks));self.play.setEnabled(bool(self.audio));self.seek.setEnabled(bool(self.audio))
    def toggle_play(self):
        if self.player.playbackState()==QMediaPlayer.PlayingState:self.player.pause();self.play.setText("▶ Play")
        else:self.player.play();self.play.setText("Ⅱ Pause")
    def on_position(self,pos):
        self.preview.position=pos/1000;self.preview.update();self.seek.blockSignals(True)
        self.seek.setValue(int(pos/max(1,self.player.duration())*1000));self.seek.blockSignals(False);self.update_time()
    def update_time(self,*args):
        p=self.player.position()/1000;d=self.player.duration()/1000
        self.time.setText(f"{int(p//60):02}:{int(p%60):02} / {int(d//60):02}:{int(d%60):02}")
    def seek_to(self,v): self.player.setPosition(int(v/1000*self.player.duration()))
    def sync_preview(self):
        if self.player.playbackState()==QMediaPlayer.PlayingState:self.preview.position=self.player.position()/1000;self.preview.update()
    def export_video(self):
        if not self.audio:return
        path,_=QFileDialog.getSaveFileName(self,"Export MP4",str(Path(self.audio).with_suffix(".mp4")),"MP4 Video (*.mp4)")
        if not path:return
        if not path.lower().endswith(".mp4"):path+=".mp4"
        try:
            for t in self.tracks:t.load(self.bpm.value())
            fps=30 if self.fps.currentIndex()==0 else 60
            renderer=VideoRenderer(self.audio,self.tracks,self.bpm.value(),self.mode,fps,1080,1920,self.glow.value()/100,self.zoom.value()/100,self.wave_check.isChecked())
            self.thread=ExportThread(renderer,path);self.thread.progress.connect(self.progress.setValue);self.thread.done.connect(self.export_done);self.thread.failed.connect(self.export_failed)
            self.progress.setValue(0);self.progress.setVisible(True);self.export.setEnabled(False);self.status.setText("RENDERING");self.thread.start()
        except Exception as e: QMessageBox.critical(self,"Export error",str(e))
    def export_done(self,path):
        self.progress.setVisible(False);self.export.setEnabled(True);self.status.setText("READY");QMessageBox.information(self,"Export complete",f"Video saved:\n{path}")
    def export_failed(self,error):
        self.progress.setVisible(False);self.export.setEnabled(True);self.status.setText("ERROR");QMessageBox.critical(self,"Export failed",error)

def main():
    app=QApplication(sys.argv);app.setApplicationName("MIDI Visualizer");win=MainWindow();win.show();sys.exit(app.exec())
