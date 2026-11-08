# -*- coding: utf-8 -*-
"""
手机遥控器 v2 — 按键 / 触控板 / 语音 / 投屏
用法：双击 start.bat，手机连同一 Wi-Fi 打开控制台显示的地址。

新增：
  · 触控板：单指移动光标、轻点=左键、双指轻点=右键、双指上下滑=滚轮
  · 语音：优先浏览器识别（需 https/localhost）；不支持时走手机输入法语音
  · 投屏：Win+P 投影面板 / Win+K 连接无线显示器 / 打开「投影到此电脑」设置
"""

import ctypes
import os
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# pythonw（无窗口启动）时 stdout/stderr 是 None，print 会直接报错，先兜住
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

# ---------------------------------------------------------------- 键盘

KEYS = {
    "playpause": (0xB3, True),
    "next": (0xB0, True),
    "prev": (0xB1, True),
    "stop": (0xB2, True),
    "volup": (0xAF, True),
    "voldown": (0xAE, True),
    "mute": (0xAD, True),
    "left": (0x25, True),
    "right": (0x27, True),
    "up": (0x26, True),
    "down": (0x28, True),
    "space": (0x20, False),
    "enter": (0x0D, False),
    "esc": (0x1B, False),
    "f": (0x46, False),
    "pgup": (0x21, True),
    "pgdn": (0x22, True),
}

COMBOS = {
    "alttab": [(0x12, False), (0x09, False)],   # Alt+Tab
    "winp": [(0x5B, True), (0x50, False)],      # Win+P 投影面板
    "wink": [(0x5B, True), (0x4B, False)],      # Win+K 连接无线显示器
}


def tap(vk, extended=False, hold=0.02):
    flags = KEYEVENTF_EXTENDEDKEY if extended else 0
    user32.keybd_event(vk, 0, flags, 0)
    time.sleep(hold)
    user32.keybd_event(vk, 0, flags | KEYEVENTF_KEYUP, 0)


def send_key(name):
    if name in KEYS:
        vk, ext = KEYS[name]
        tap(vk, ext)
        return True
    if name in COMBOS:
        seq = COMBOS[name]
        for vk, ext in seq:
            user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY if ext else 0, 0)
        time.sleep(0.08)
        for vk, ext in reversed(seq):
            user32.keybd_event(
                vk, 0, (KEYEVENTF_EXTENDEDKEY if ext else 0) | KEYEVENTF_KEYUP, 0
            )
        return True
    return False


# ---------------------------------------------------------------- 鼠标

def mouse_move(dx, dy):
    if dx or dy:
        user32.mouse_event(MOUSEEVENTF_MOVE, int(dx), int(dy), 0, 0)


def mouse_click(btn):
    if btn == "left":
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    elif btn == "right":
        user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    elif btn == "down":
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    elif btn == "up":
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def mouse_scroll(delta):
    if delta:
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(delta), 0)


# ---------------------------------------------------------------- 文字输入

def _set_clipboard_text(text):
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

    buf = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(buf)
    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not h:
            return False
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, buf, size)
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(CF_UNICODETEXT, h)
    finally:
        user32.CloseClipboard()
    return True


def type_text(text):
    """把文字送进电脑当前光标处：写剪贴板 + Ctrl+V。"""
    if not text:
        return False
    old = None
    try:
        if user32.OpenClipboard(None):
            h = user32.GetClipboardData(13)
            if h:
                kernel32.GlobalLock.restype = ctypes.c_void_p
                p = kernel32.GlobalLock(ctypes.c_void_p(h))
                if p:
                    old = ctypes.wstring_at(p)
                    kernel32.GlobalUnlock(ctypes.c_void_p(h))
            user32.CloseClipboard()
    except Exception:
        old = None

    if not _set_clipboard_text(text):
        return False
    time.sleep(0.03)
    user32.keybd_event(0x11, 0, 0, 0)          # Ctrl
    time.sleep(0.01)
    user32.keybd_event(0x56, 0, 0, 0)          # V
    time.sleep(0.02)
    user32.keybd_event(0x56, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)

    if old:
        time.sleep(0.25)
        _set_clipboard_text(old)               # 还原剪贴板
    return True


# ---------------------------------------------------------------- 页面

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0f1115">
<title>遥控器</title>
<style>
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  html,body{margin:0;height:100%;background:#0f1115;color:#e8ecf3;
    font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
    overscroll-behavior:none;user-select:none;-webkit-user-select:none}
  body{display:flex;flex-direction:column;padding:10px 12px calc(86px + env(safe-area-inset-bottom));gap:10px}
  .bar{display:flex;align-items:center;justify-content:space-between;padding:2px 2px 0}
  .title{font-size:14px;font-weight:600;color:#9aa7bd;letter-spacing:.4px}
  .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#2ee6a8;margin-right:6px;box-shadow:0 0 10px #2ee6a8}
  .hint{font-size:12px;color:#5d6b82}

  .tabs{display:grid;grid-template-columns:1fr 1fr;gap:8px;background:#161b26;padding:5px;border-radius:16px}
  .tabs button{height:44px;border-radius:12px;background:transparent;font-size:15px;color:#8a97ad;font-weight:600}
  .tabs button.on{background:#2a3448;color:#fff;box-shadow:0 2px 8px rgba(0,0,0,.35)}

  .view{display:none;flex-direction:column;gap:10px;flex:1;min-height:0}
  .view.on{display:flex}

  button{border:0;border-radius:18px;background:#1b2130;color:#e8ecf3;font-size:18px;font-weight:600;
    font-family:inherit;padding:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;
    box-shadow:0 2px 0 #0b0e14, inset 0 1px 0 rgba(255,255,255,.06);
    transition:transform .06s ease, background .12s ease}
  button .sub{font-size:11px;font-weight:400;color:#7c8aa3}
  button:active{transform:scale(.96);background:#2a3448}
  .primary{background:linear-gradient(160deg,#2f6bff,#1b47c9);box-shadow:0 3px 0 #12307e, inset 0 1px 0 rgba(255,255,255,.18)}
  .primary:active{background:linear-gradient(160deg,#3f79ff,#2252dd)}
  .primary .sub{color:#c8d8ff}
  .row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
  .row4{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .h76{height:76px}.h96{height:96px}.h58{height:56px;font-size:14px;border-radius:16px}
  .h58 .sub{font-size:10px}
  .sep{height:1px;background:#1e2637;margin:1px 2px}

  /* 触控板 */
  #pad{flex:1;min-height:230px;border-radius:22px;background:
      radial-gradient(120% 90% at 50% 0%,#1a2130 0%,#141922 70%);
      border:1px solid #232c3d;display:flex;align-items:center;justify-content:center;
      color:#41506b;font-size:13px;letter-spacing:.5px;position:relative;touch-action:none;overflow:hidden}
  #pad .ring{position:absolute;width:130px;height:130px;border-radius:50%;
      border:1px dashed #2b3648;opacity:.9;pointer-events:none}
  #pad.act{border-color:#2f6bff;box-shadow:0 0 0 1px rgba(47,107,255,.5) inset}
  #pad .lbl{position:absolute;bottom:14px;font-size:11px;color:#3d4a61;text-align:center;width:100%;line-height:1.6}
  .padbtns{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
  .padbtns button{height:60px;font-size:15px}

  /* 语音浮层 */
  #mask{position:fixed;inset:0;background:rgba(8,10,15,.92);display:none;flex-direction:column;
    align-items:center;justify-content:center;gap:18px;z-index:20;padding:24px;backdrop-filter:blur(6px)}
  #mask.on{display:flex}
  .wave{display:flex;gap:6px;align-items:flex-end;height:70px}
  .wave i{width:9px;border-radius:6px;background:linear-gradient(180deg,#4d8bff,#2ee6a8);animation:eq 1s infinite ease-in-out}
  .wave i:nth-child(1){animation-delay:0s}.wave i:nth-child(2){animation-delay:.12s}
  .wave i:nth-child(3){animation-delay:.24s}.wave i:nth-child(4){animation-delay:.36s}
  .wave i:nth-child(5){animation-delay:.48s}
  @keyframes eq{0%,100%{height:14px}50%{height:64px}}
  #heard{font-size:22px;font-weight:600;text-align:center;min-height:32px;line-height:1.4}
  #mask .tip{font-size:13px;color:#7c8aa3;text-align:center;line-height:1.7}
  #mask input{width:100%;max-width:420px;height:56px;border-radius:16px;border:1px solid #2b3648;
    background:#11161f;color:#e8ecf3;font-size:18px;padding:0 16px;font-family:inherit;outline:none}
  #mask input:focus{border-color:#2f6bff}
  #mask .row2{width:100%;max-width:420px;display:grid;grid-template-columns:1fr 1fr;gap:10px}
  #mask button{height:54px;font-size:16px}

  /* 底部语音键 */
  #voice{position:fixed;left:50%;transform:translateX(-50%);
    bottom:calc(16px + env(safe-area-inset-bottom));width:74px;height:74px;border-radius:50%;
    background:linear-gradient(160deg,#2f6bff,#1b47c9);font-size:28px;z-index:10;
    box-shadow:0 8px 24px rgba(47,107,255,.45), inset 0 1px 0 rgba(255,255,255,.2);gap:0}
  #voice:active{transform:translateX(-50%) scale(.93)}
  #voice .sub{font-size:10px;color:#c8d8ff;margin-top:-2px}
</style>
</head>
<body>

<div class="bar">
  <div class="title"><span class="dot"></span>遥控器</div>
  <div class="hint" id="tip">点按即生效</div>
</div>

<div class="tabs">
  <button id="tab1" class="on" onclick="show(1)">按键</button>
  <button id="tab2" onclick="show(2)">触控板</button>
</div>

<!-- ============ 按键 ============ -->
<div class="view on" id="v1">
  <div class="row3">
    <button class="h76" onclick="k('prev')">⏮<span class="sub">上一集</span></button>
    <button class="primary h96" onclick="k('playpause')">⏯<span class="sub">播放 / 暂停</span></button>
    <button class="h76" onclick="k('next')">⏭<span class="sub">下一集</span></button>
  </div>

  <div class="row3">
    <button class="h58" onclick="k('voldown')">🔉<span class="sub">音量 −</span></button>
    <button class="h58" onclick="k('mute')">🔇<span class="sub">静音</span></button>
    <button class="h58" onclick="k('volup')">🔊<span class="sub">音量 +</span></button>
  </div>

  <div class="sep"></div>

  <div class="row4">
    <button class="h58" onclick="k('left')">◀◀<span class="sub">后退 5s</span></button>
    <button class="h58" onclick="k('right')">▶▶<span class="sub">前进 5s</span></button>
    <button class="h58" onclick="k('pgup')">⤒<span class="sub">上一集*</span></button>
    <button class="h58" onclick="k('pgdn')">⤓<span class="sub">下一集*</span></button>
  </div>

  <div class="row4">
    <button class="h58" onclick="k('fullscreen')">⛶<span class="sub">全屏</span></button>
    <button class="h58" onclick="k('esc')">⎋<span class="sub">退出全屏</span></button>
    <button class="h58" onclick="k('stop')">■<span class="sub">停止</span></button>
    <button class="h58" onclick="k('alttab')">⇄<span class="sub">切窗口</span></button>
  </div>

  <div class="sep"></div>

  <div class="row3">
    <button class="h58" onclick="k('winp')">📺<span class="sub">投影 Win+P</span></button>
    <button class="h58" onclick="k('wink')">📶<span class="sub">无线投屏</span></button>
    <button class="h58" onclick="k('project_settings')">📱<span class="sub">手机投电脑</span></button>
  </div>

  <div class="hint" style="text-align:center;line-height:1.7">
    带 * 的按钮用于不认多媒体键的播放器<br>
    点底部蓝色圆钮说话：暂停 / 下一集 / 静音 / 大点声
  </div>
</div>

<!-- ============ 触控板 ============ -->
<div class="view" id="v2">
  <div id="pad">
    <div class="ring"></div>
    <div class="lbl">单指滑动移动光标 · 轻点 = 左键<br>双指轻点 = 右键 · 双指上下滑 = 滚轮</div>
  </div>
  <div class="padbtns">
    <button onclick="mouse('btn','left')">左键<span class="sub">单击</span></button>
    <button onclick="toggleHold(this)">按住<span class="sub">拖拽用</span></button>
    <button onclick="mouse('btn','right')">右键<span class="sub">单击</span></button>
  </div>
  <div class="row2">
    <button class="h58" onclick="k('playpause')">⏯<span class="sub">播放 / 暂停</span></button>
    <button class="h58" onclick="k('fullscreen')">⛶<span class="sub">全屏</span></button>
  </div>
</div>

<!-- ============ 语音浮层 ============ -->
<div id="mask">
  <div class="wave"><i></i><i></i><i></i><i></i><i></i></div>
  <div id="heard">正在听…</div>
  <div class="tip" id="vtip">说一句：暂停 / 下一集 / 大点声 / 全屏</div>

  <input id="vtext" placeholder="或在这里点输入法的麦克风说话" style="display:none">
  <div class="row2">
    <button onclick="closeVoice()">取消</button>
    <button class="primary" id="vbtn" onclick="voicePrimary()">停止</button>
  </div>
</div>

<button id="voice" onclick="openVoice()">🎙<span class="sub">语音</span></button>

<script>
/* ---------- 基础发送 ---------- */
const tip = document.getElementById('tip');
function flash(t){ tip.textContent = t; clearTimeout(flash._t); flash._t = setTimeout(()=>tip.textContent='点按即生效', 1200); }

function k(name, quiet){
  const n = name === 'fullscreen' ? 'full' : name;
  fetch('/api/key?k=' + encodeURIComponent(n), {cache:'no-store'})
    .then(r => { if(!quiet) flash(r.ok ? '已发送' : '失败'); })
    .catch(() => { if(!quiet) flash('连接断开'); });
}

let holdDown = false;
function toggleHold(btn){
  holdDown = !holdDown;
  fetch('/api/mouse?btn=' + (holdDown ? 'down' : 'up'), {cache:'no-store'});
  btn.classList.toggle('primary', holdDown);
  btn.querySelector('.sub').textContent = holdDown ? '松手' : '拖拽用';
  flash(holdDown ? '已按住，可拖动' : '已松开');
}

/* ---------- 视图切换 ---------- */
function show(n){
  document.getElementById('v1').classList.toggle('on', n===1);
  document.getElementById('v2').classList.toggle('on', n===2);
  document.getElementById('tab1').classList.toggle('on', n===1);
  document.getElementById('tab2').classList.toggle('on', n===2);
}

/* ---------- 触控板 ---------- */
const pad = document.getElementById('pad');
let lastX=0, lastY=0, moved=0, tStart=0, startFingers=0, dragging=false, scrollY=0;
let accX=0, accY=0, accS=0, sending=false;
const SENS = 2.0;

function flush(){
  if (!accX && !accY && !accS) { sending=false; return; }
  const dx = Math.round(accX), dy = Math.round(accY), s = Math.round(accS);
  accX = 0; accY = 0; accS = 0;
  let url = '/api/mouse?dx=' + dx + '&dy=' + dy;
  if (s) url += '&scroll=' + s;
  sending = true;
  fetch(url, {cache:'no-store'}).catch(()=>{}).finally(()=>{ sending=false; });
}
setInterval(()=>{ if(!sending) flush(); }, 40);

function mouse(q, v){ fetch('/api/mouse?' + q + '=' + v, {cache:'no-store'}).catch(()=>{}); }

pad.addEventListener('touchstart', e => {
  e.preventDefault();
  startFingers = e.touches.length;
  if (e.touches.length === 1){
    dragging = true; moved = 0; tStart = Date.now();
    lastX = e.touches[0].clientX; lastY = e.touches[0].clientY;
  } else if (e.touches.length === 2){
    dragging = false;
    scrollY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
  }
  pad.classList.add('act');
}, {passive:false});

pad.addEventListener('touchmove', e => {
  e.preventDefault();
  if (e.touches.length === 1 && dragging){
    const t = e.touches[0];
    let dx = (t.clientX - lastX) * SENS;
    let dy = (t.clientY - lastY) * SENS;
    lastX = t.clientX; lastY = t.clientY;
    moved += Math.abs(dx) + Math.abs(dy);
    accX += dx; accY += dy;
  } else if (e.touches.length === 2){
    const y = (e.touches[0].clientY + e.touches[1].clientY) / 2;
    const d = (scrollY - y) / 2.5;
    scrollY = y;
    if (Math.abs(d) >= 1) accS += d;
  }
}, {passive:false});

pad.addEventListener('touchend', e => {
  e.preventDefault();
  const dur = Date.now() - tStart;
  if (e.touches.length === 0){
    pad.classList.remove('act');
    if (startFingers === 2 && moved < 8){
      mouse('btn', 'right'); flash('右键');
    } else if (startFingers === 1 && dragging && moved < 10 && dur < 300){
      mouse('btn', 'left'); flash('左键');
    }
    dragging = false;
    flush();
  }
}, {passive:false});

/* ---------- 语音 ---------- */
const mask = document.getElementById('mask');
const heard = document.getElementById('heard');
const vtip = document.getElementById('vtip');
const vtext = document.getElementById('vtext');
const vbtn = document.getElementById('vbtn');

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const canSR = !!(SR && window.isSecureContext);
let recog = null, mode = 'sr', finalText = '';

const RULES = [
  [/不可/, null],
  [/暂停|停一下|停止|别放了/, 'stop2'],
  [/继续|接着放|播放/, 'playpause'],
  [/下一集|下集|下一个|下一首|下一个视频/, 'next'],
  [/上一集|上集|上一个|上一首|上一个视频/, 'prev'],
  [/大点声|大声|音量大|声音大|调大/, 'volup'],
  [/小点声|小声|音量小|声音小|调小/, 'voldown'],
  [/静音|别出声/, 'mute'],
  [/快进|前进|往后面/, 'right'],
  [/快退|后退|往前面/, 'left'],
  [/退出全屏|取消全屏/, 'esc'],
  [/全屏/, 'f'],
  [/投屏|投影/, 'winp'],
  [/切窗口|切换窗口/, 'alttab']
];

function handlePhrase(text){
  const t = (text || '').replace(/\s|，|。|！|？|、/g, '');
  if (!t) return;
  heard.textContent = '“' + text.trim() + '”';
  for (const [re, act] of RULES){
    if (re.test(t)){
      if (act === null) return finish('已取消');
      if (act === 'stop2'){ k('playpause', true); return finish('已暂停'); }
      k(act === 'f' ? 'full' : act, true);
      return finish('已执行：' + text.trim());
    }
  }
  /* 不是指令 → 当文字打到电脑上 */
  fetch('/api/text?t=' + encodeURIComponent(text.trim()), {cache:'no-store'})
    .then(()=>finish('已输入文字')).catch(()=>finish('发送失败'));
}

function finish(msg){
  vtip.textContent = msg;
  setTimeout(closeVoice, 700);
}

function openVoice(){
  mask.classList.add('on');
  heard.textContent = '正在听…';
  vtip.textContent = '说一句：暂停 / 下一集 / 大点声 / 全屏';
  finalText = '';

  if (canSR){
    mode = 'sr';
    vtext.style.display = 'none';
    vbtn.textContent = '停止';
    startSR();
  } else {
    mode = 'ime';
    vtext.style.display = 'block';
    vbtn.textContent = '发送';
    heard.textContent = '点下面输入框 → 用输入法的麦克风';
    vtip.textContent = '说完按「发送」，指令会执行，其他内容会打字到电脑上';
    setTimeout(()=>vtext.focus(), 120);
  }
}

function startSR(){
  try { recog && recog.abort(); } catch(e){}
  recog = new SR();
  recog.lang = 'zh-CN';
  recog.interimResults = true;
  recog.continuous = false;
  recog.onresult = ev => {
    let txt = '';
    for (let i = 0; i < ev.results.length; i++) txt += ev.results[i][0].transcript;
    heard.textContent = txt || '正在听…';
    finalText = txt;
  };
  recog.onerror = () => {
    vtip.textContent = '浏览器没能调用麦克风，改用输入法语音';
    setTimeout(()=>{ closeVoice(); openVoice(); }, 600);
  };
  recog.onend = () => { if (mask.classList.contains('on') && mode === 'sr' && finalText) handlePhrase(finalText); };
  try { recog.start(); } catch(e){}
}

function voicePrimary(){
  if (mode === 'ime'){
    const v = vtext.value.trim();
    if (!v) return closeVoice();
    vtext.value = '';
    handlePhrase(v);
  } else {
    try { recog.stop(); } catch(e){ closeVoice(); }
  }
}

function closeVoice(){
  try { recog && recog.abort(); } catch(e){}
  mask.classList.remove('on');
}

document.getElementById('vtext').addEventListener('keydown', e => {
  if (e.key === 'Enter'){ e.preventDefault(); voicePrimary(); }
});

if (location.hash === '#pad') show(2);

document.addEventListener('dblclick', e=>e.preventDefault(), {passive:false});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- 服务

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
            return
        if u.path == "/favicon.ico":
            self._send(204, "")
            return
        if u.path == "/api/ping":
            self._send(200, "pcr")
            return

        if u.path == "/api/key":
            name = (q.get("k") or [""])[0]
            if name in ("fullscreen", "full"):
                name = "f"
            elif name == "project_settings":
                try:
                    os.startfile("ms-settings:project")
                    self._send(200, "ok")
                except Exception:
                    self._send(500, "fail")
                return
            self._send(200 if send_key(name) else 400, "ok" if name else "unknown")
            return

        if u.path == "/api/mouse":
            try:
                dx = int(float((q.get("dx") or ["0"])[0]))
                dy = int(float((q.get("dy") or ["0"])[0]))
                sc = int(float((q.get("scroll") or ["0"])[0]))
            except ValueError:
                dx = dy = sc = 0
            if dx or dy:
                mouse_move(dx, dy)
            if sc:
                mouse_scroll(sc * 120)
            btn = (q.get("btn") or [""])[0]
            if btn:
                mouse_click(btn)
            self._send(200, "ok")
            return

        if u.path == "/api/text":
            txt = (q.get("t") or [""])[0][:500]
            self._send(200 if type_text(txt) else 400, "ok")
            return

        self._send(404, "not found")

    def do_POST(self):
        self._send(405, "use GET")


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def is_ours(port):
    """该端口上跑的是不是本程序"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=0.8) as r:
            return r.read(3) == b"pcr"
    except Exception:
        return False


def pause():
    """有控制台才等回车；pythonw 静默启动时直接退出"""
    try:
        if sys.stdin and sys.stdin.isatty():
            input("  按回车关闭…")
    except Exception:
        pass


def main():
    port = 8765
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    # 已经在跑就不再启一份（开机自启时可能被重复触发）
    for p in (8765, 8766, 8767):
        if is_ours(p):
            print("  已经有一份在运行了，不重复启动。")
            pause()
            return

    ip = lan_ip()
    print("=" * 52)
    print("  手机遥控器已启动  (关闭本窗口即停止)")
    print()
    print(f"  手机浏览器打开：  http://{ip}:{port}")
    print()
    print("  · 按键：播放 / 换集 / 音量 / 投屏")
    print("  · 触控板：单指点、双指滑")
    print("  · 语音：点底部圆钮说话")
    print()
    print("  首次启动如弹防火墙提示，请允许「专用网络」")
    print("=" * 52)

    srv = None
    for p in (port, port + 1, port + 2):
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", p), Handler)
            if p != port:
                print(f"  (端口 {port} 被占用，已改用 {p})")
                print(f"  手机浏览器打开：  http://{ip}:{p}")
            break
        except OSError:
            continue

    if srv is None:
        print("  启动失败：8765~8767 都被占用了。")
        pause()
        return

    # 后台静默启动时没有窗口，把地址写到文件里方便查看
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "遥控器地址.txt"), "w", encoding="utf-8-sig") as f:
            f.write(f"http://{ip}:{srv.server_address[1]}\n")
            f.write(time.strftime("启动时间：%Y-%m-%d %H:%M\n"))
            f.write("手机与电脑需连同一个 Wi-Fi。停止：双击 stop.bat\n")
    except Exception:
        pass

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
