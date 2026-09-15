# -*- coding: utf-8 -*-
"""公众号文章 → 科普视频 引擎 v2（数据驱动，可复用）。
edge-tts 配音 → 每段(图/卡片/视频素材)背景处理 + 运镜 + 科幻字幕 → 拼接 + BGM。
一次产出多个画幅（横版 1920x1080 + 竖版 1080x1920）。零 GPU。

用法：
  python build_video.py <storyboard.json> [--only tts|sub|clip|concat] [--profile h|v] [--from N]

⛔ 这条 3D 讲解片线上**只用它的 sub / clip / concat 三段**（配音走 chain.py tts，
   字幕走 subs.py 的一次性 ASS 烧录）。它自带的 edge-tts 配音和字幕图这里都不用。
"""
import json, sys, os, subprocess, asyncio, math, re
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import config as _C
    FONT_BD = _C.FONT_UI
    SUB_FONT = _C.get("fonts.display") or FONT_BD
except Exception:
    FONT_BD = "C:/Windows/Fonts/msyhbd.ttc"
    SUB_FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)),"fonts","SmileySans-Oblique.ttf")
VIDEXT = (".mp4",".mov",".webm",".mkv",".m4v",".gif")

def audio_path(base, sid):
    w = os.path.join(base,"tts",sid+".wav")
    return w if os.path.exists(w) else os.path.join(base,"tts",sid+".mp3")

# 多音字/读音修正：旁白里写 {{显示词|读音词}}，字幕取显示词、配音取读音词（同音异字骗过 TTS）
_OVR = re.compile(r"\{\{([^|{}]*)\|([^|{}]*)\}\}")
def to_tts(nar):     return _OVR.sub(lambda m: m.group(2), nar).replace("*","")
def to_display(nar): return _OVR.sub(lambda m: m.group(1), nar)

def run(cmd, cwd=None, retries=0):
    """retries>0 时失败重试。用于 xfade 这类会偶发进程崩溃(0xC0000005)的重活——
    实测同样的参数手动重跑就能过，属负载相关的不稳定，不是数据问题。"""
    for attempt in range(retries + 1):
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            if attempt: sys.stderr.write("  (第 %d 次重试成功)\n" % attempt)
            return r
        if attempt < retries:
            sys.stderr.write("  命令失败(rc=%s)，%d 秒后重试 %d/%d…\n" % (r.returncode, 3, attempt + 1, retries))
            time.sleep(3)
    sys.stderr.write("CMD FAIL: %s\n%s\n" % (" ".join(str(x) for x in cmd[:8]), r.stderr[-1600:]))
    raise SystemExit(1)

def probe_dur(path):
    return float(run(["ffprobe","-v","error","-show_entries","format=duration",
                      "-of","default=nk=1:nw=1", path]).stdout.strip())

# ---------- 1. TTS ----------
async def _tts(text, voice, rate, out):
    await edge_tts.Communicate(text, voice=voice, rate=rate).save(out)

def stage_tts(cfg, scenes, base):
    voice = cfg.get("voice","zh-CN-YunxiNeural"); rate = cfg.get("rate","+7%")
    tdir = os.path.join(base,"tts"); os.makedirs(tdir, exist_ok=True)
    durs = {}
    for s in scenes:
        nar = s.get("narration","").strip()
        out = os.path.join(tdir, s["id"]+".mp3")
        if nar:
            asyncio.run(_tts(to_tts(nar), voice, rate, out))
            durs[s["id"]] = probe_dur(out)
            print("tts %-5s %.2fs  %s" % (s["id"], durs[s["id"]], to_tts(nar)[:20]))
        else:
            durs[s["id"]] = 0.0
    json.dump(durs, open(os.path.join(base,"_durs.json"),"w"), indent=0)
    return durs

# ---------- 2. 字幕（科幻 HUD 风：半透玻璃条 + 青色辉光关键词 + 角标）----------
def wrap(text, font, maxw, maxlines):
    # 优先在标点处断行，避免把词组（如"工作流"）拦腰截断
    segs=[s for s in re.split(r'(?<=[，。、；：！？,.])', text) if s]
    lines=[]; cur=""
    for seg in segs:
        if not cur: cur=seg
        elif font.getlength(cur+seg)<=maxw: cur+=seg
        else: lines.append(cur); cur=seg
        while font.getlength(cur)>maxw and len(cur)>1:  # 单短语超宽兜底按字断
            i=len(cur)
            while i>1 and font.getlength(cur[:i])>maxw: i-=1
            lines.append(cur[:i]); cur=cur[i:]
    if cur: lines.append(cur)
    return lines[:maxlines]

def parse_emph(nar):
    plain=""; hi=set(); on=False
    for ch in nar:
        if ch=="*": on=not on; continue
        if on: hi.add(len(plain))
        plain+=ch
    return plain, hi

def _tick(d, x, y, dx, dy, col, w=4, L=20):
    d.line([(x+dx*L, y),(x, y),(x, y+dy*L)], fill=col, width=w)

def stage_sub(cfg, scenes, base, prof):
    W,H = prof["canvas"]; land = W>=H
    fs = prof.get("sub_size", cfg.get("sub_size",46))
    fpath = cfg.get("sub_font", SUB_FONT)
    if not os.path.exists(fpath): fpath = FONT_BD
    font = ImageFont.truetype(fpath, fs); lh = fs+16
    sdir = os.path.join(base,"sub_"+prof["name"]); os.makedirs(sdir, exist_ok=True)
    maxw = W-300 if land else W-110
    maxlines = 3 if land else 4
    AC=(58,230,255); TXT=(238,244,250)
    for s in scenes:
        img=Image.new("RGBA",(W,H),(0,0,0,0)); d=ImageDraw.Draw(img)
        gt=H-int(H*0.24)
        for y in range(gt,H):
            d.line([(0,y),(W,y)],fill=(0,0,0,int(110*(y-gt)/(H-gt))))
        nar=s.get("narration","").strip()
        if nar:
            plain,hi=parse_emph(to_display(nar))
            lines=wrap(plain,font,maxw,maxlines)
            tw=max(font.getlength(l) for l in lines); th=lh*len(lines)
            padx,pady=52,24; pw=int(tw)+2*padx; ph=th+2*pady
            px=(W-pw)//2; pb=H-int(H*(0.035 if land else 0.055)); py=pb-ph
            # 酷黑科幻 HUD：斜切角 + 纯黑面板 + 亮青边框 + 角括号 + 顶部数据刻度
            cut=22
            poly=[(px+cut,py),(px+pw,py),(px+pw,py+ph-cut),(px+pw-cut,py+ph),(px,py+ph),(px,py+cut)]
            panel=Image.new("RGBA",(W,H),(0,0,0,0)); pd=ImageDraw.Draw(panel)
            pd.polygon(poly,fill=(0,0,0,206))
            img=Image.alpha_composite(img,panel); d=ImageDraw.Draw(img)
            d.line(poly+[poly[0]],fill=AC+(190,),width=2)
            d.rectangle([px+12,py+cut,px+17,py+ph-12],fill=AC+(255,))          # 左侧实心青条
            d.rectangle([px+36,py-1,px+126,py+2],fill=AC+(255,))               # 顶部亮条
            for k in range(3):
                d.rectangle([px+pw-42-k*16,py-1,px+pw-36-k*16,py+3],fill=AC+(220,))  # 顶部数据刻度
            d.line([(px+pw-26,py+8),(px+pw-8,py+8),(px+pw-8,py+26)],fill=AC+(255,),width=3)  # 右上角括号
            d.line([(px+8,py+ph-26),(px+8,py+ph-8),(px+26,py+ph-8)],fill=AC+(255,),width=3)  # 左下角括号
            # 关键词辉光层
            glow=Image.new("RGBA",(W,H),(0,0,0,0)); gd=ImageDraw.Draw(glow)
            idx=0; y=py+pady
            for ln in lines:
                cx=(W-font.getlength(ln))//2
                for j,ch in enumerate(ln):
                    if (idx+j) in hi: gd.text((cx,y),ch,font=font,fill=AC+(255,))
                    cx+=font.getlength(ch)
                idx+=len(ln); y+=lh
            img=Image.alpha_composite(img,glow.filter(ImageFilter.GaussianBlur(13))); d=ImageDraw.Draw(img)
            idx=0; y=py+pady
            for ln in lines:
                cx=(W-font.getlength(ln))//2
                for j,ch in enumerate(ln):
                    col=AC if (idx+j) in hi else TXT
                    d.text((cx,y),ch,font=font,fill=col+(255,),stroke_width=3,stroke_fill=(0,0,0,200))
                    cx+=font.getlength(ch)
                idx+=len(ln); y+=lh
        img.save(os.path.join(sdir,s["id"]+".png"))
    print("sub[%s] %d 张" % (prof["name"], len(scenes)))

# ---------- 3. 每段渲染 clip ----------
def scene_dur(cfg, s, durs):
    t=durs.get(s["id"],0.0)
    if t<=0: return float(s.get("dur",3.0))
    return max(cfg.get("min_dur",2.0), round(cfg.get("head_pad",0.12)+t+cfg.get("tail_pad",0.4),2))

def resolve_visual(base, prof, vis):
    if vis.startswith("cards/"): vis = prof["cards"]+"/"+vis[len("cards/"):]
    return os.path.normpath(os.path.join(base, vis))

def _seg_filter(i, kind, W, H, fps, zoom=1.0, kb=False):
    if kind in ("image","card") and kb:   # 静帧/卡片慢推：kb=true 每帧 +0.15%（2 秒约 9%）；kb 给浮点数则按该速率（卡片用 0.0003，10 秒约 9%）
        rate = 0.0015 if kb is True else float(kb)
        fit = "increase,crop=%d:%d"%(W,H) if kind=="image" else "decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=0x090E16"%(W,H)
        return ("[%d:v]scale=%d:%d:force_original_aspect_ratio=%s,"
                "zoompan=z='1+%.5f*on':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=%dx%d:fps=%d,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v%d]"
                %(i,W,H,fit,rate,W,H,fps,i))
    if kind=="video":
        return ("[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,fps=%d,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v%d]"
                %(i,int(W*zoom),int(H*zoom),W,H,fps,i))
    if kind=="card":
        return ("[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=0xFCFBF4,fps=%d,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v%d]"
                %(i,W,H,W,H,fps,i))
    return ("[%d:v]split[b%d][f%d];[b%d]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,boxblur=22:2,eq=brightness=-0.05:saturation=1.08[bb%d];"
            "[f%d]scale=%d:%d:force_original_aspect_ratio=decrease[ff%d];[bb%d][ff%d]overlay=(W-w)/2:(H-h)/2,fps=%d,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v%d]"
            )%(i,i,i, i,W,H,W,H,i, i,W,H,i, i,i, fps, i)

def shot_segments(shots, plain, D):
    """按关键词在句中的字符位置估算每个素材的切换时刻，返回各段时长。"""
    N=len(shots); L=max(1,len(plain)); starts=[]
    for i,sh in enumerate(shots):
        if sh.get("t") is not None:          # 显式切点（秒，已含 head_pad；由对齐工具写入）
            starts.append(max(0.0,min(float(sh["t"]),D-0.4))); continue
        at=sh.get("at")
        p = plain.find(at)/L if (at and at in plain) else i/N
        starts.append(max(0.0,min(0.95,p))*D)
    starts[0]=0.0
    for i in range(1,N):
        starts[i]=min(max(starts[i], starts[i-1]+0.5), D-0.4*(N-i))
    return [round(starts[i+1]-starts[i],3) for i in range(N-1)]+[round(D-starts[-1],3)]

def extract_frame(vis, seek, out):
    run(["ffmpeg","-y","-ss","%.3f"%seek,"-i",vis,"-frames:v","1",out])

def make_compare_overlay(W, H, labels, out, vertical=True):
    """对比分屏的标注层：中缝青线 + 两个角标 + 中央 VS 徽章。"""
    img=Image.new("RGBA",(W,H),(0,0,0,0)); d=ImageDraw.Draw(img)
    AC=(58,230,255)
    fp=SUB_FONT if os.path.exists(SUB_FONT) else FONT_BD
    font=ImageFont.truetype(fp, 46 if vertical else 40)
    mid = H//2 if vertical else W//2
    if vertical:
        d.rectangle([0,mid-3,W,mid+3], fill=AC+(235,))
        # VS 徽章
        r=54; cx,cy=W//2,mid
        d.ellipse([cx-r,cy-r,cx+r,cy+r], fill=(9,15,26,235), outline=AC+(255,), width=4)
        vf=ImageFont.truetype(fp,44); tw=d.textlength("VS",font=vf)
        d.text((cx-tw/2,cy-30),"VS",font=vf,fill=AC+(255,))
        anchors=[(46,44),(46,mid+40)]
    else:
        d.rectangle([mid-3,0,mid+3,H], fill=AC+(235,))
        anchors=[(46,44),(mid+46,44)]
    for (lx,ly),txt in zip(anchors, labels):
        tw=d.textlength(txt,font=font)
        d.rounded_rectangle([lx-16,ly-10,lx+tw+18,ly+62],radius=12,fill=(9,15,26,225),outline=AC+(200,),width=2)
        d.text((lx,ly),txt,font=font,fill=(238,244,250,255),stroke_width=2,stroke_fill=(0,0,0,200))
    img.save(out)

def build_compare_clip(cfg, s, base, prof, durs, cdir, sdir):
    """上下(竖屏)/左右(横屏)分屏对比：before|after 同时播放，配文案。"""
    W,H=prof["canvas"]; fps=cfg.get("fps",30); vertical=H>=W
    D=scene_dur(cfg,s,durs); cp=s["compare"]
    sw,sh = (W, H//2) if vertical else (W//2, H)
    tmpdir=os.path.join(cdir,"_cmp"); os.makedirs(tmpdir,exist_ok=True)
    cmd=["ffmpeg","-y"]; segfilt=[]
    for i,side in enumerate([cp["top"],cp["bottom"]] if vertical else [cp["left"],cp["right"]]):
        vis=resolve_visual(base,prof,side["src"]); seek=float(side.get("seek",0))
        ext=os.path.splitext(vis)[1].lower(); is_video=ext in VIDEXT
        if side.get("freeze") and is_video:      # 抽一帧当静止图
            fr=os.path.join(tmpdir,"%s_frz%d.png"%(s["id"],i)); extract_frame(vis,seek,fr)
            vis=fr; is_video=False
        if is_video:
            vdur=probe_dur(vis)
            if vdur-seek<D+0.1: cmd+=["-stream_loop","-1"]
            if seek>0: cmd+=["-ss","%.3f"%seek]
            cmd+=["-t","%.3f"%D,"-i",vis]
        else:
            cmd+=["-loop","1","-t","%.3f"%D,"-framerate",str(fps),"-i",vis]
        z=float(side.get("zoom",1.0))
        cy = "0" if side.get("anchor")=="top" else "(ih-oh)/2"
        segfilt.append("[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d:(iw-ow)/2:%s,fps=%d,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[s%d]"
                       %(i, int(sw*z),int(sh*z), sw,sh, cy, fps, i))
    stack="vstack" if vertical else "hstack"
    # 标注层 + 字幕层
    ov=os.path.join(tmpdir,"%s_ov.png"%s["id"]); make_compare_overlay(W,H,cp.get("labels",["原始","AI 生成"]),ov,vertical)
    cmd+=["-loop","1","-framerate",str(fps),"-i",ov]           # 输入2
    cmd+=["-loop","1","-framerate",str(fps),"-i",os.path.join(sdir,s["id"]+".png")]  # 输入3
    filt=segfilt+["[s0][s1]%s[stk]"%stack,"[stk][2:v]overlay=0:0[o1]","[o1][3:v]overlay=0:0,format=yuv420p[v]"]
    tts=audio_path(base,s["id"]); has_a=os.path.exists(tts) and durs.get(s["id"],0)>0
    out=os.path.join(cdir,s["id"]+".mp4")
    if has_a:
        cmd+=["-i",tts]; hp=int(cfg.get('head_pad',0.12)*1000)
        filt.append("[4:a]adelay=%d|%d,apad[a]"%(hp,hp))
        cmd+=["-filter_complex",";".join(filt),"-map","[v]","-map","[a]"]
    else:
        cmd+=["-f","lavfi","-t","%.3f"%D,"-i","anullsrc=r=44100:cl=stereo"]
        cmd+=["-filter_complex",";".join(filt),"-map","[v]","-map","4:a"]
    cmd+=["-t","%.3f"%D,"-r",str(fps),"-c:v","libx264","-preset","medium","-crf","20",
          "-pix_fmt","yuv420p","-c:a","aac","-ar","44100","-ac","2","-b:a","160k","-shortest",out]
    run(cmd)
    print("clip[%s] %-5s %.2fs 对比 %s"%(prof["name"],s["id"],D,"/".join(cp.get("labels",[]))))

def make_stack_overlay(W, H, labels, out, seps=None, horiz=False):
    """N 格堆叠的标注层：格间青线 + 每格角标 + 分隔处 +/= 徽章。horiz=True 为左右排列。"""
    N=len(labels); step=(W//N if horiz else H//N)
    img=Image.new("RGBA",(W,H),(0,0,0,0)); d=ImageDraw.Draw(img); AC=(58,230,255)
    fp=SUB_FONT if os.path.exists(SUB_FONT) else FONT_BD
    fsz=34 if horiz else 44
    font=ImageFont.truetype(fp,fsz); bigf=ImageFont.truetype(fp,52 if not horiz else 40)
    for i in range(1,N):
        p=step*i
        if horiz: d.rectangle([p-3,0,p+3,H],fill=AC+(235,))
        else:     d.rectangle([0,p-3,W,p+3],fill=AC+(235,))
        sym=(seps[i-1] if seps and i-1<len(seps) else None)
        if sym:
            r=48 if not horiz else 36
            cx,cy=(p,H//2) if horiz else (W//2,p)
            d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=(9,15,26,240),outline=AC+(255,),width=4)
            tw=d.textlength(sym,font=bigf); d.text((cx-tw/2,cy-(36 if not horiz else 26)),sym,font=bigf,fill=AC+(255,))
    for i,lab in enumerate(labels):
        if not lab: continue
        if horiz: lx,ly=step*i+16, 28
        else:     lx,ly=40, step*i+28
        tw=d.textlength(lab,font=font)
        d.rounded_rectangle([lx-12,ly-8,lx+tw+14,ly+fsz+16],radius=10,fill=(9,15,26,228),outline=AC+(200,),width=2)
        d.text((lx,ly),lab,font=font,fill=(238,244,250,255),stroke_width=2,stroke_fill=(0,0,0,200))
    img.save(out)

def build_stack_clip(cfg, s, base, prof, durs, cdir, sdir):
    """N 行竖向堆叠对比（如 原视频 / 脸图 / 换脸后）。"""
    W,H=prof["canvas"]; fps=cfg.get("fps",30); D=scene_dur(cfg,s,durs)
    items=s["stack"]["items"]; N=len(items)
    # dir="h" 左右排列：竖版画布上每列 W/N × H 是竖条，和全身人像比例接近，
    # 裁切也能保住整个人；默认的上下排列每行是 W × H/N 横条，竖图只会剩一条横带。
    horiz = s["stack"].get("dir","v")=="h"
    cw,rh = (W//N, H) if horiz else (W, H//N)
    tmpdir=os.path.join(cdir,"_stk"); os.makedirs(tmpdir,exist_ok=True)
    cmd=["ffmpeg","-y"]; seg=[]; labels=[]
    for i,it in enumerate(items):
        vis=resolve_visual(base,prof,it["src"]); seek=float(it.get("seek",0))
        ext=os.path.splitext(vis)[1].lower(); is_video=ext in VIDEXT
        if it.get("freeze") and is_video:
            fr=os.path.join(tmpdir,"%s_f%d.png"%(s["id"],i)); extract_frame(vis,seek,fr); vis=fr; is_video=False
        if is_video:
            vdur=probe_dur(vis)
            if vdur-seek<D+0.1: cmd+=["-stream_loop","-1"]
            if seek>0: cmd+=["-ss","%.3f"%seek]
            cmd+=["-t","%.3f"%D,"-i",vis]
        else:
            cmd+=["-loop","1","-t","%.3f"%D,"-framerate",str(fps),"-i",vis]
        z=float(it.get("zoom",1.0)); cy="0" if it.get("anchor")=="top" else "(ih-oh)/2"
        # 分屏每行是 W×(H/N) 的横条，竖版素材按 cover 裁只会露出中间一条横带（主体看不全）。
        # 所以 stack 默认走 contain（整图缩进去+虚化补边），要裁满得显式写 fit:"cover"。
        # 左右排列时默认 cover（竖条裁切能留住整个人）；上下排列时默认 contain（防只剩横带）
        default_fit = "cover" if horiz else "contain"
        if it.get("fit",default_fit)!="cover":   # 完整显示整张(脸图/竖图不裁切)，虚化补边
            seg.append("[%d:v]split[b%d][f%d];[b%d]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,boxblur=22:2,eq=brightness=-0.06[bb%d];"
                       "[f%d]scale=%d:%d:force_original_aspect_ratio=decrease[ff%d];[bb%d][ff%d]overlay=(W-w)/2:(H-h)/2,fps=%d,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[s%d]"
                       %(i,i,i, i,cw,rh,cw,rh,i, i,cw,rh,i, i,i, fps,i))
        else:
            seg.append("[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d:(iw-ow)/2:%s,fps=%d,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[s%d]"
                       %(i,int(cw*z),int(rh*z),cw,rh,cy,fps,i))
        labels.append(it.get("label",""))
    seg.append("".join("[s%d]"%i for i in range(N))+("hstack" if horiz else "vstack")+"=inputs=%d[stk]"%N)
    ov=os.path.join(tmpdir,"%s_ov.png"%s["id"]); make_stack_overlay(W,H,labels,ov,s["stack"].get("seps"),horiz)
    cmd+=["-loop","1","-framerate",str(fps),"-i",ov]
    cmd+=["-loop","1","-framerate",str(fps),"-i",os.path.join(sdir,s["id"]+".png")]
    seg+=["[stk][%d:v]overlay=0:0[o1]"%N,"[o1][%d:v]overlay=0:0,format=yuv420p[v]"%(N+1)]
    tts=audio_path(base,s["id"]); has_a=os.path.exists(tts) and durs.get(s["id"],0)>0
    out=os.path.join(cdir,s["id"]+".mp4")
    if has_a:
        cmd+=["-i",tts]; hp=int(cfg.get('head_pad',0.12)*1000)
        seg.append("[%d:a]adelay=%d|%d,apad[a]"%(N+2,hp,hp))
        cmd+=["-filter_complex",";".join(seg),"-map","[v]","-map","[a]"]
    else:
        cmd+=["-f","lavfi","-t","%.3f"%D,"-i","anullsrc=r=44100:cl=stereo"]
        cmd+=["-filter_complex",";".join(seg),"-map","[v]","-map","%d:a"%(N+2)]
    cmd+=["-t","%.3f"%D,"-r",str(fps),"-c:v","libx264","-preset","medium","-crf","20",
          "-pix_fmt","yuv420p","-c:a","aac","-ar","44100","-ac","2","-b:a","160k","-shortest",out]
    run(cmd)
    print("clip[%s] %-5s %.2fs 堆叠x%d %s"%(prof["name"],s["id"],D,N,"/".join(labels)))

def build_shots_clip(cfg, s, base, prof, durs, cdir, sdir):
    """一句话内多素材：按 shots 顺序硬切成小蒙太奇，旁白贯穿整段、字幕不变。"""
    W,H=prof["canvas"]; fps=cfg.get("fps",30)
    D=scene_dur(cfg,s,durs); shots=s["shots"]; N=len(shots)
    plain=to_display(s.get("narration","")).replace("*","")
    segs=shot_segments(shots, plain, D)
    # 镜头之间的溶解。默认 0（其他项目不受影响），只有 storyboard 里写了 shot_xfade 才开。
    # ⛔ 必须**不改变总时长**：字幕和拍点都按 align 的绝对秒排，短一点点就整片错位。
    #    做法是把除最后一段外的每一段多取 XT 秒素材，再用 XT 秒的 xfade 叠回去，
    #    总长 = Σ(d_i + XT) − (N−1)·XT = Σd_i，而且每个切点仍然落在原来那一帧上。
    XT = float(cfg.get("shot_xfade", 0) or 0)
    if N < 2:
        XT = 0.0
    cmd=["ffmpeg","-y"]; filt=[]; labels=""
    for i,(sh,d) in enumerate(zip(shots,segs)):
        vis=resolve_visual(base,prof,sh["src"])
        if not os.path.exists(vis): raise SystemExit("缺素材(shots): "+vis)
        ext=os.path.splitext(vis)[1].lower()
        is_video=ext in VIDEXT; is_card=("/"+prof["cards"]+"/") in vis.replace("\\","/")
        kind="video" if is_video else ("card" if is_card else "image")
        dd = d + (XT if (XT and i < N-1) else 0.0)
        if is_video:
            seek=float(sh.get("seek",0)); vdur=probe_dur(vis)
            if vdur-seek<dd+0.1: cmd+=["-stream_loop","-1"]
            if seek>0: cmd+=["-ss","%.3f"%seek]
            cmd+=["-t","%.3f"%dd,"-i",vis]
        else:
            cmd+=["-loop","1","-t","%.3f"%dd,"-framerate",str(fps),"-i",vis]
        filt.append(_seg_filter(i,kind,W,H,fps,float(sh.get("zoom",1.0)),sh.get("kb"))); labels+="[v%d]"%i
    if XT:
        # ⛔ xfade 要求输入是**恒定帧率**。上面几路里，卡片走 zoompan、图片走 overlay，
        #    再接 setpts 之后时基就变成 1/0（未定义），xfade 直接报
        #    "The inputs needs to be a constant frame rate; current rate of 1/0 is invalid"
        #    并且整条 filtergraph 一帧都不输出。所以进 xfade 前先把每一路钉成 CFR。
        for i in range(N):
            # ⛔ fps 必须放在**最后**：setpts/settb 会把 link 上的 frame_rate 清成 1/0，
            #    而 xfade 恰恰查的就是这个属性。先 setpts 归零再 fps 钉帧率。
            filt.append("[v%d]settb=1/%d,setpts=N/%d/TB,fps=%d[w%d]"%(i,fps,fps,fps,i))
        acc=0.0; cur="[w0]"
        for i in range(1,N):
            acc+=segs[i-1]
            nxt="[vcat]" if i==N-1 else "[x%d]"%i
            filt.append("%s[w%d]xfade=transition=fade:duration=%.3f:offset=%.3f%s"%(cur,i,XT,acc,nxt))
            cur=nxt
    else:
        filt.append("%sconcat=n=%d:v=1[vcat]"%(labels,N))
    cmd+=["-loop","1","-framerate",str(fps),"-i",os.path.join(sdir,s["id"]+".png")]  # 输入 N = 字幕
    filt.append("[vcat][%d:v]overlay=0:0,format=yuv420p[v]"%N)
    tts=audio_path(base,s["id"]); has_a=os.path.exists(tts) and durs.get(s["id"],0)>0
    out=os.path.join(cdir,s["id"]+".mp4")
    if has_a:
        cmd+=["-i",tts]  # 输入 N+1
        hp=int(cfg.get('head_pad',0.12)*1000)
        filt.append("[%d:a]adelay=%d|%d,apad[a]"%(N+1,hp,hp))
        cmd+=["-filter_complex",";".join(filt),"-map","[v]","-map","[a]"]
    else:
        cmd+=["-f","lavfi","-t","%.3f"%D,"-i","anullsrc=r=44100:cl=stereo"]
        cmd+=["-filter_complex",";".join(filt),"-map","[v]","-map","%d:a"%(N+1)]
    cmd+=["-t","%.3f"%D,"-r",str(fps),"-c:v","libx264","-preset","medium","-crf","20",
          "-pix_fmt","yuv420p","-c:a","aac","-ar","44100","-ac","2","-b:a","160k","-shortest",out]
    run(cmd)
    print("clip[%s] %-5s %.2fs 多素材x%d %s"%(prof["name"],s["id"],D,N,
          " ".join("%.1fs"%x for x in segs)))

# ---------- 运镜表达式 ----------
# 借鉴 shotcraft 的缓动/呼吸律/锚点推进思路，用 zoompan 的 z/x/y 表达式实现。
# 详见 参考-镜头与节奏设计.md 第一、三节。
PUSH_ANCHOR={"push-tl":(0.15,0.15),"push-tr":(0.85,0.15),
             "push-bl":(0.15,0.85),"push-br":(0.85,0.85)}

def kb_expr(motion, N, amp=0.06, hold=0.0):
    """返回 (z, x, y) 三个 zoompan 表达式串（含引号）。

    amp  运动幅度：氛围 0.03-0.04 / 常规 0.06 / 强调 0.10-0.14（>0.2 失去压迫感）
    hold 尾部静止占比（呼吸律）：0.3 = 前 70% 时间做完运动，后 30% 静止让观众读
    缓动 smoothstep t^2*(3-2t)：起步慢、中段快、收尾缓；线性运动读作廉价 PPT
    """
    ne=max(1,int(round(N*(1.0-min(max(hold,0.0),0.8)))))
    p="min(on/%d,1)"%ne                      # 线性进度 clamp 到 [0,1]
    s="(pow(%s,2)*(3-2*%s))"%(p,p)           # 缓动进度
    cx,cy="'iw/2-(iw/zoom/2)'","'ih/2-(ih/zoom/2)'"
    if motion=="static":
        return "'1.0'",cx,cy
    if motion=="out":
        return "'%.4f-%.4f*%s'"%(1.0+amp,amp,s),cx,cy
    if motion in ("pan-l","pan-r","pan-u","pan-d"):
        z="'%.4f'"%(1.0+max(amp,0.08))       # 摇镜需先放大留出可移动余量
        f=s if motion in ("pan-r","pan-d") else "(1-%s)"%s
        if motion in ("pan-l","pan-r"):
            return z,"'(iw-iw/zoom)*%s'"%f,cy
        return z,cx,"'(ih-ih/zoom)*%s'"%f
    if motion in PUSH_ANCHOR:                 # 推向画面某角（重点不在中心时）
        ax,ay=PUSH_ANCHOR[motion]
        return ("'1.0+%.4f*%s'"%(max(amp,0.10),s),
                "'(iw-iw/zoom)*%.2f'"%ax,"'(ih-ih/zoom)*%.2f'"%ay)
    if motion=="drift":                       # 氛围垫镜：极缓斜向漂移，替代 static 防死板
        return ("'1.0+%.4f*%s'"%(min(amp,0.04),s),
                "'(iw-iw/zoom)*(0.35+0.30*%s)'"%s,
                "'(ih-ih/zoom)*(0.60-0.25*%s)'"%s)
    return "'1.0+%.4f*%s'"%(amp,s),cx,cy      # 默认 in

def stage_clip(cfg, scenes, base, durs, prof, start_from=0):
    W,H=prof["canvas"]; fps=cfg.get("fps",30); BW,BH=W*2,H*2
    cdir=os.path.join(base,"clips_"+prof["name"]); os.makedirs(cdir,exist_ok=True)
    sdir=os.path.join(base,"sub_"+prof["name"])
    for k,s in enumerate(scenes):
        if k<start_from: continue
        if s.get("stack"):
            build_stack_clip(cfg,s,base,prof,durs,cdir,sdir); continue
        if s.get("compare"):
            build_compare_clip(cfg,s,base,prof,durs,cdir,sdir); continue
        if s.get("shots"):
            build_shots_clip(cfg,s,base,prof,durs,cdir,sdir); continue
        dur=scene_dur(cfg,s,durs); N=max(1,round(dur*fps))
        vis=resolve_visual(base,prof,s["visual"])
        if not os.path.exists(vis): raise SystemExit("缺素材: "+vis)
        sub=os.path.join(sdir,s["id"]+".png"); tts=audio_path(base,s["id"])
        has_a=os.path.exists(tts) and durs.get(s["id"],0)>0
        ext=os.path.splitext(vis)[1].lower()
        is_video = ext in VIDEXT
        is_card  = ("/"+prof["cards"]+"/") in vis.replace("\\","/")
        out=os.path.join(cdir,s["id"]+".mp4")
        cmd=["ffmpeg","-y"]
        if is_video:
            seek=float(s.get("seek",0)); vdur=probe_dur(vis)
            pre=[]
            if vdur-seek < dur+0.1: pre+=["-stream_loop","-1"]
            if seek>0: pre+=["-ss","%.3f"%seek]
            cmd+=pre+["-i",vis,"-loop","1","-framerate",str(fps),"-i",sub]
            z=float(s.get("zoom",1.0))
            if s.get("fit")=="contain":   # 完整显示不裁切（横板/方形素材放竖屏用）
                vf=("[0:v]split[bg][fg];"
                    "[bg]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,boxblur=24:2,eq=brightness=-0.06:saturation=1.05[bgb];"
                    "[fg]scale=%d:%d:force_original_aspect_ratio=decrease[fgc];"
                    "[bgb][fgc]overlay=(W-w)/2:(H-h)/2,fps=%d,setsar=1,setpts=PTS-STARTPTS[v0];"
                    "[v0][1:v]overlay=0:0:shortest=1,format=yuv420p[v]")%(W,H,W,H,W,H,fps)
            else:
                vf=("[0:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,fps=%d,setpts=PTS-STARTPTS[v0];"
                    "[v0][1:v]overlay=0:0:shortest=1,format=yuv420p[v]")%(int(W*z),int(H*z),W,H,fps)
        elif is_card:
            cmd+=["-loop","1","-framerate",str(fps),"-i",vis,"-loop","1","-framerate",str(fps),"-i",sub]
            cardvf=("[0:v]scale=%d:%d:force_original_aspect_ratio=decrease,"
                    "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=0xFCFBF4,setsar=1")%(BW,BH,BW,BH)
            mo=s.get("motion","static")
            if mo=="static":
                vf=("[0:v]scale=%d:%d:force_original_aspect_ratio=decrease,"
                    "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=0xFCFBF4,setsar=1[v0];"
                    "[v0][1:v]overlay=0:0,format=yuv420p[v]")%(W,H,W,H)
            else:
                # 卡片是满屏文字，放大会裁掉边缘字：幅度硬上限 0.03，摇镜一律降级为 drift
                amp=min(float(s.get("amp",0.03)),0.03)
                mo2="drift" if mo.startswith("pan-") or mo.startswith("push-") else mo
                if mo2!=mo or float(s.get("amp",0.03))>0.03:
                    print("  [card] %s: %s/amp%.2f -> %s/amp%.2f（防裁字）"%(
                        s["id"],mo,float(s.get("amp",0.03)),mo2,amp))
                ze,xe,ye=kb_expr(mo2,N,amp,float(s.get("hold",0)))
                vf=(cardvf+"[cb];"
                    "[cb]zoompan=z=%s:d=%d:x=%s:y=%s:s=%dx%d:fps=%d[zm];"
                    "[zm][1:v]overlay=0:0:shortest=1,format=yuv420p[v]")%(ze,N,xe,ye,W,H,fps)
        else:  # 照片：虚化背景 + Ken Burns
            motion=s.get("motion","in" if k%2==0 else "out")
            ze,xe,ye=kb_expr(motion,N,float(s.get("amp",0.06)),float(s.get("hold",0)))
            cmd+=["-i",vis,"-loop","1","-framerate",str(fps),"-i",sub]
            vf=("[0:v]split[bg][fg];"
                "[bg]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,boxblur=22:2,eq=brightness=-0.05:saturation=1.08[bgb];"
                "[fg]scale=%d:%d:force_original_aspect_ratio=decrease[fgc];"
                "[bgb][fgc]overlay=(W-w)/2:(H-h)/2[base];"
                "[base]zoompan=z=%s:d=%d:x=%s:y=%s:s=%dx%d:fps=%d[zm];"
                "[zm][1:v]overlay=0:0:shortest=1,format=yuv420p[v]")%(BW,BH,BW,BH,BW,BH,ze,N,xe,ye,W,H,fps)
        if has_a:
            hp=int(cfg.get('head_pad',0.12)*1000)
            cmd+=["-i",tts,"-filter_complex",vf+";[2:a]adelay=%d|%d,apad[a]"%(hp,hp),
                  "-map","[v]","-map","[a]"]
        else:
            cmd+=["-f","lavfi","-t",str(dur),"-i","anullsrc=r=44100:cl=stereo",
                  "-filter_complex",vf,"-map","[v]","-map","2:a"]
        cmd+=["-t",str(dur),"-r",str(fps),"-c:v","libx264","-preset","medium","-crf","20",
              "-pix_fmt","yuv420p","-c:a","aac","-ar","44100","-ac","2","-b:a","160k","-shortest",out]
        run(cmd)
        kind="视频" if is_video else ("卡片" if is_card else "照片")
        print("clip[%s] %-5s %.2fs %s %s"%(prof["name"],s["id"],dur,kind,os.path.basename(s["visual"])))

# ---------- 4. 拼接 + BGM ----------
# 转场按「两镜关系」选型，不按序号轮换（见 参考-镜头与节奏设计.md 第四节）。
# scene.rel 描述本段与「上一段」的关系；缺省 flat。同组内轮换保证不单调，相邻不重复。
TRANS_BY_REL = {
    "flat":  ["dissolve","smoothleft","smoothright","smoothup"],   # 并列/枚举：平滑过渡
    "step":  ["zoomin","circleopen","smoothup"],                   # 递进/因果：向前推进感
    # 注：squeezev 已移除——本机 ffmpeg 该滤镜必崩(0xC0000005 访问违例)，
    #     单独测过 13 种转场只有它挂，与负载无关。换成 smoothup 同样是"向前推进"语义。
    "turn":  ["fadeblack","fadegrays","hlslice"],                  # 转折/对立：较重，节制用
    # 注：pixelize 已移出——中间态像画面损坏/马赛克，观感被判「怪」，改用 fadegrays 去饱和过渡
    "jump":  ["fadewhite","radial","circlecrop"],                  # 时间跳跃：干净断开
}
TRANS = TRANS_BY_REL["flat"]   # 兼容旧调用

def pick_trans(rels):
    """按每个接缝的 rel 选转场；同组内轮换、相邻不重复。"""
    idx={k:0 for k in TRANS_BY_REL}; out=[]; prev=None
    for r in rels:
        pool=TRANS_BY_REL.get(r or "flat", TRANS_BY_REL["flat"])
        for _ in range(len(pool)):
            t=pool[idx[r or "flat"] % len(pool)]; idx[r or "flat"]+=1
            if t!=prev: break
        out.append(t); prev=t
    return out

# 统一冷暗电影调色（把杂来源实拍/图统一成一个片子的质感）
GRADE = ("eq=contrast=1.05:saturation=0.93:brightness=-0.008,"
         "colorbalance=rs=-0.02:bs=0.04:rm=-0.01:bm=0.02,"
         "vignette=PI/6")

def _xfade_flat(clips, T, out, trans=None):
    """一次性 xfade+acrossfade 一小串 clip(输入数受控)。trans 为逐接缝转场名。"""
    if len(clips)==1:
        run(["ffmpeg","-y","-i",clips[0],"-c","copy",out]); return
    durs=[probe_dur(c) for c in clips]
    if not trans: trans=pick_trans(["flat"]*(len(clips)-1))
    cmd=["ffmpeg","-y"]
    for c in clips: cmd+=["-i",c]
    vf=[]; off=durs[0]-T; prev="0:v"
    for i in range(1,len(clips)):
        tr=trans[i-1]
        lab="vx%d"%i
        vf.append("[%s][%d:v]xfade=transition=%s:duration=%.3f:offset=%.3f[%s]"%(prev,i,tr,T,off,lab))
        prev=lab; off+=durs[i]-T
    vout=prev; prevA="0:a"
    for i in range(1,len(clips)):
        lab="ax%d"%i
        vf.append("[%s][%d:a]acrossfade=d=%.3f[%s]"%(prevA,i,T,lab)); prevA=lab
    cmd+=["-filter_complex",";".join(vf),"-map","[%s]"%vout,"-map","[%s]"%prevA,
          "-c:v","libx264","-preset","medium","-crf","20","-pix_fmt","yuv420p",
          "-c:a","aac","-ar","44100","-ac","2","-b:a","160k",out]
    run(cmd, retries=3)   # xfade 偶发进程崩溃，重试通常就过

def build_xfade(clips, T, out, rels=None):
    """xfade 链成一条。段数 >K 时分块做二级 xfade，避免 ffmpeg 多输入崩溃(0xC0000005)。
    段间同样 xfade，所以所有转场都保留。rels 逐接缝关系(len=段数-1)。"""
    K=10
    if rels is None: rels=["flat"]*(len(clips)-1)
    trans=pick_trans(rels)
    if len(clips)<=K:
        _xfade_flat(clips, T, out, trans); return
    segs=[]; seam=[]
    for j in range(0,len(clips),K):
        seg="%s.seg%d.mp4"%(out, j//K)
        _xfade_flat(clips[j:j+K], T, seg, trans[j:j+K-1]); segs.append(seg)
        if j+K < len(clips): seam.append(trans[j+K-1])   # 块间接缝沿用该处关系
    _xfade_flat(segs, T, out, seam)

def apply_sfx(cfg, scenes, cdir, raw, T, fps):
    """把各段 scene.sfx 铺成一条整片音效轨混进 raw，返回新的 raw 路径。

    钉帧一律相对镜头起点（scene.sfx[].at 是本段内偏移秒），镜头时长一改自动跟随。
    scene.sfx 可为 [{"name","at","vol"}]，或字符串 "outro" 用收尾固定句式。
    没有任何 sfx 时原样返回，不引入 numpy 依赖。
    """
    has=any(s.get("sfx") for s in scenes)
    if not has: return raw
    try:
        from sfx_bed import build_bed, outro_events
    except Exception as e:
        print("  [sfx] 跳过（sfx_bed 不可用：%s）"%e); return raw
    durs=[probe_dur(os.path.join(cdir,s["id"]+".mp4")) for s in scenes]
    gv=float(cfg.get("sfx_vol",1.0))
    ev=[]; acc=0.0
    for i,s in enumerate(scenes):
        st = acc - (i*float(T) if T else 0.0)
        spec=s.get("sfx")
        if spec:
            if spec=="outro" or spec==["outro"]:
                ev+=outro_events(max(0.0,st), fps=fps, vol=gv)
            else:
                for e in (spec if isinstance(spec,list) else [spec]):
                    if isinstance(e,str): e={"name":e,"at":0.0}
                    ev.append({"name":e["name"], "t":max(0.0,st+float(e.get("at",0.0))),
                               "vol":float(e.get("vol",0.35))*gv,
                               **({"dur":e["dur"]} if e.get("dur") else {})})
        acc+=durs[i]
    total=probe_dur(raw)
    bed=os.path.join(cdir,"_sfx.wav")
    info=build_bed(ev, total, bed, fps=fps)
    print("  [sfx] %d 个事件，轨长 %.1fs，峰值 %.3f"%(info["events"],info["dur"],info["peak"]))
    out=os.path.join(cdir,"_raw_sfx.mp4")
    run(["ffmpeg","-y","-i",raw,"-i",bed,"-filter_complex",
         "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
         "-map","0:v","-map","[a]","-c:v","copy","-c:a","aac","-ar","44100","-ac","2","-b:a","192k",out])
    return out

def stage_concat(cfg, scenes, base, prof):
    cdir=os.path.join(base,"clips_"+prof["name"]); odir=os.path.join(base,"out"); os.makedirs(odir,exist_ok=True)
    raw=os.path.join(cdir,"_raw.mp4")
    T=cfg.get("transition",0)
    if T and len(scenes)>1:
        clips=[os.path.join(cdir,s["id"]+".mp4") for s in scenes]
        build_xfade(clips, float(T), raw, [s.get("rel","flat") for s in scenes[1:]])
    else:
        with open(os.path.join(cdir,"_concat.txt"),"w",encoding="utf-8") as f:
            for s in scenes: f.write("file '%s.mp4'\n"%s["id"])
        run(["ffmpeg","-y","-f","concat","-safe","0","-i","_concat.txt","-c","copy",os.path.abspath(raw)],cwd=cdir)
    raw=apply_sfx(cfg, scenes, cdir, raw, T, cfg.get("fps",30))
    final=os.path.join(odir, cfg.get("outfile","final")+prof.get("suffix","")+".mp4")
    g=cfg.get("grade"); gf=(g if isinstance(g,str) else GRADE) if g else None
    venc=["-c:v","libx264","-preset","medium","-crf","20","-pix_fmt","yuv420p"]
    bgm=cfg.get("bgm")
    if bgm and os.path.exists(os.path.normpath(os.path.join(base,bgm))):
        bgmp=os.path.normpath(os.path.join(base,bgm)); vol=cfg.get("bgm_vol",0.09)
        afc=("[1:a]volume=%.3f,afade=t=in:st=0:d=1.5,afade=t=out:st=%.1f:d=2[b];"
             "[0:a][b]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
             %(vol, probe_dur(raw)-2))
        if gf:
            run(["ffmpeg","-y","-i",raw,"-stream_loop","-1","-i",bgmp,"-filter_complex",
                 "[0:v]"+gf+"[v];"+afc,"-map","[v]","-map","[a]"]+venc+
                 ["-c:a","aac","-b:a","192k","-shortest",final])
        else:
            run(["ffmpeg","-y","-i",raw,"-stream_loop","-1","-i",bgmp,"-filter_complex",afc,
                 "-map","0:v","-map","[a]","-c:v","copy","-c:a","aac","-b:a","192k","-shortest",final])
    else:
        if gf:
            run(["ffmpeg","-y","-i",raw,"-vf",gf]+venc+["-c:a","copy",final])
        else:
            run(["ffmpeg","-y","-i",raw,"-c","copy",final])
    print("成片[%s] -> %s  %.1fs"%(prof["name"],final,probe_dur(final)))

def main():
    sb=sys.argv[1]; cfg=json.load(open(sb,encoding="utf-8"))
    base=os.path.dirname(os.path.abspath(sb)); scenes=cfg["scenes"]
    only=sys.argv[sys.argv.index("--only")+1] if "--only" in sys.argv else None
    pfilter=sys.argv[sys.argv.index("--profile")+1] if "--profile" in sys.argv else None
    start_from=int(sys.argv[sys.argv.index("--from")+1]) if "--from" in sys.argv else 0
    profiles=cfg.get("profiles") or [{"name":"h","canvas":cfg.get("canvas",[1920,1080]),
                                      "cards":"cards","suffix":"","sub_size":cfg.get("sub_size",54)}]
    if pfilter: profiles=[p for p in profiles if p["name"]==pfilter]
    dpath=os.path.join(base,"_durs.json")
    durs=json.load(open(dpath)) if os.path.exists(dpath) else {}
    if only in (None,"tts"): durs=stage_tts(cfg,scenes,base)
    for prof in profiles:
        if only in (None,"sub"):    stage_sub(cfg,scenes,base,prof)
        if only in (None,"clip"):   stage_clip(cfg,scenes,base,durs,prof,start_from)
        if only in (None,"concat"): stage_concat(cfg,scenes,base,prof)

if __name__=="__main__": main()
