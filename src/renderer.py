import math, os, shutil, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from .engine import decode_audio

def font(size, bold=False):
    paths = ["C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for path in paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

class VideoRenderer:
    def __init__(self, audio_path, tracks, bpm, mode="MIDI GRID", fps=60, width=1080, height=1920, glow=.7, zoom=1., waveform=True):
        self.audio_path, self.tracks, self.bpm, self.mode = audio_path, tracks, bpm, mode
        self.fps, self.width, self.height, self.glow, self.zoom, self.waveform = fps, width, height, glow, zoom, waveform
        self.samples, self.sr = decode_audio(audio_path, 11025)
        self.duration = len(self.samples)/self.sr if len(self.samples) else 0
        self.notes = [(t,n) for t in tracks if t.enabled for n in t.notes]

    def audio_bands(self, sec, count=96):
        size = 4096
        center = int(sec * self.sr)
        start = max(0, center - size // 2)
        chunk = self.samples[start:start + size]
        if len(chunk) < size:
            chunk = np.pad(chunk, (0, size - len(chunk)))
        spectrum = np.abs(np.fft.rfft(chunk * np.hanning(size))).astype(np.float32)
        spectrum = spectrum[2:min(len(spectrum), 1800)]
        groups = np.array_split(spectrum, count)
        values = np.array([float(np.sqrt(np.mean(g*g))) if len(g) else 0.0 for g in groups], dtype=np.float32)
        peak = max(float(np.percentile(values, 90)), 1e-5)
        return np.sqrt(np.clip(values / peak, 0, 1))

    def frame(self, sec):
        w,h=self.width,self.height
        im=Image.new("RGB",(w,h),"#09090e"); d=ImageDraw.Draw(im,"RGBA")
        for x in range(0,w,90): d.line((x,0,x,h),fill=(100,88,125,18))
        for y in range(0,h,90): d.line((0,y,w,y),fill=(100,88,125,18))
        d.text((64,54),"MIDI VISUALIZER",font=font(30,True),fill="#e9e4f2")
        d.text((64,102),f"{self.bpm:.1f} BPM     {sec:07.2f}s",font=font(21),fill="#817c8d")
        x0,x1,top,bottom=72,w-72,230,h-390
        span=8/max(.35,self.zoom); left=max(0,sec-span*.2); right=left+span
        if self.mode=="MIDI GRID":
            for pitch in range(36,97,12):
                yy=bottom-(pitch-36)/60*(bottom-top)
                d.line((x0,yy,x1,yy),fill=(180,170,205,28),width=2)
            for track,n in self.notes:
                if n.end<left or n.start>right: continue
                nx=x0+(n.start-left)/span*(x1-x0); ex=x0+(n.end-left)/span*(x1-x0)
                yy=bottom-(n.pitch-36)/60*(bottom-top); active=n.start<=sec<n.end
                if active and self.glow>0:
                    alpha=int(35+75*self.glow)
                    d.rounded_rectangle((nx-5,yy-15,max(nx+8,ex+5),yy+16),radius=12,fill=tuple(bytes.fromhex(track.color.lstrip("#")))+(alpha,))
                d.rounded_rectangle((nx,yy-9,max(nx+5,ex),yy+10),radius=8,fill=track.color+("ff" if active else "9a"))
        elif self.mode=="WAVEFORM":
            enabled=[t for t in self.tracks if t.enabled]
            bands=self.audio_bands(sec,96)
            lane=(bottom-top)/max(1,len(enabled))
            for i,t in enumerate(enabled):
                mid=top+(i+.5)*lane
                d.text((x0,top+i*lane+8),t.name[:22],font=font(17),fill=t.color)
                step=(x1-x0)/len(bands); bar_w=max(3,int(step*.58))
                rgb=tuple(bytes.fromhex(t.color.lstrip("#")))
                for j,value in enumerate(bands):
                    xx=x0+(j+.5)*step
                    amp=max(3,int(value*lane*.42))
                    if self.glow>0:
                        d.line((xx,mid-amp,xx,mid+amp),fill=rgb+(int(35*self.glow),),width=bar_w+10)
                    d.rounded_rectangle((xx-bar_w/2,mid-amp,xx+bar_w/2,mid+amp),radius=4,fill=t.color)
        # Match the note timeline mapping: at t=0 the playhead is at the first pixel.
        play_x=x0+max(0.0,min(1.0,(sec-left)/span))*(x1-x0)
        d.line((play_x,top-30,play_x,bottom+25),fill=(245,239,255,220),width=3)
        if self.waveform:
            wy=h-260; d.text((x0,wy-58),"AUDIO",font=font(18,True),fill="#8b829e"); pts=[]
            for xx in range(x0,x1,3):
                tm=left+(xx-x0)/(x1-x0)*span; idx=int(tm*self.sr)
                amp=float(np.max(np.abs(self.samples[idx:idx+max(1,int(self.sr*.02))]))) if 0<=idx<len(self.samples) else 0
                pts.append((xx,wy+(1 if len(pts)%2 else -1)*amp*110))
            if len(pts)>1: d.line(pts,fill="#9872c7",width=3)
            d.line((x0,wy,x1,wy),fill=(180,160,210,55),width=1)
        d.text((x0,h-92),"MIDI VISUALIZER  /  AUDIO REACTIVE",font=font(17),fill="#696474")
        return im

    def render(self, output_path, progress=None):
        ffmpeg=shutil.which("ffmpeg")
        if not ffmpeg:
            import imageio_ffmpeg
            ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
        total=max(1,math.ceil(self.duration*self.fps))
        cmd=[ffmpeg,"-y","-f","rawvideo","-vcodec","rawvideo","-pix_fmt","rgb24","-s",f"{self.width}x{self.height}","-r",str(self.fps),"-i","-","-i",self.audio_path,"-map","0:v:0","-map","1:a:0","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-shortest","-movflags","+faststart",output_path]
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            for i in range(total):
                proc.stdin.write(self.frame(i/self.fps).convert("RGB").tobytes())
                if progress: progress(int((i+1)*100/total))
            proc.stdin.close(); err=proc.stderr.read().decode("utf-8","replace"); code=proc.wait()
            if code: raise RuntimeError("FFmpeg export failed: "+err[-2500:])
        except Exception:
            proc.kill(); raise
        return output_path
