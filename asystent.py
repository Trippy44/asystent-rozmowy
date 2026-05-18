# -*- coding: utf-8 -*-
"""
Asystent-Rozmowy AI v13.1
"""
import flet as ft
import base64, io, json, threading, wave, time, pathlib, struct, audioop
import urllib.request, urllib.error
from datetime import datetime
try:
    import pdfplumber
    PDF_OK = True
except ImportError:
    PDF_OK = False

try:
    import pyaudio
    AUDIO_OK = True
except ImportError:
    AUDIO_OK = False

BACKEND      = "https://liquid-backend.onrender.com"
VERSION_URL  = "https://raw.githubusercontent.com/Trippy44/asystent-rozmowy/main/version.json"
DOWNLOAD_URL = "https://github.com/Trippy44/asystent-rozmowy/releases/latest"
VERSION    = "13.1"
RATE       = 16000
CHUNK      = 1024
TOKEN_FILE = pathlib.Path.home() / ".asystent_token.json"

def save_token(d):
    TOKEN_FILE.write_text(json.dumps(d), encoding="utf-8")

def load_token():
    try:
        if TOKEN_FILE.exists():
            return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None

def clear_token():
    try: TOKEN_FILE.unlink()
    except Exception: pass

def check_update():
    """Sprawdza czy jest nowsza wersja na GitHubie."""
    try:
        url = "https://raw.githubusercontent.com/Trippy44/asystent-rozmowy/main/version.json"
        req = urllib.request.Request(url, headers={"User-Agent": "AsystentRozmowy"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read().decode())
        latest = data.get("version", "0")
        download_url = data.get("download_url", "")
        if latest != VERSION:
            return latest, download_url
    except Exception:
        pass
    return None, None

def check_update(current_version, on_update=None):
    """Sprawdza czy dostepna jest nowa wersja aplikacji."""
    try:
        req  = urllib.request.Request(VERSION_URL,
               headers={"Cache-Control": "no-cache"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read().decode())
        latest = data.get("version", "")
        url    = data.get("download_url", DOWNLOAD_URL)
        if latest and latest != current_version:
            if on_update:
                on_update(latest, url)
    except Exception:
        pass  # Brak internetu lub plik nie istnieje - ignoruj

def api(method, path, body=None, token=None):
    url  = BACKEND + path
    data = json.dumps(body).encode() if body else None
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req  = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode()), e.code
        except Exception:
            return {"detail": str(e)}, e.code
    except Exception as e:
        return {"detail": str(e)}, 0

DARK = {
    "BASE":"#06070D","L1":"#0C0D1A","L3":"#181A30",
    "EDGE_HI":"#2A2D50","EDGE_LO":"#13152A",
    "GREEN":"#2EE89A","GREEN_DIM":"#0B2A1A","GREEN_G":"#17C980",
    "RED":"#FF5F6D","RED_DIM":"#280A0A","YELLOW":"#FFD166",
    "WHITE":"#ECEEFF","GRAY":"#8890BB","DIM":"#3E4266",
    "AI_BG":"#0A1C11","AI_EDGE":"#163023",
    "USR_BG":"#0C0D1A","USR_EDGE":"#1A1C32","is_dark":True,
}
LIGHT = {
    "BASE":"#F0F2F8","L1":"#FFFFFF","L3":"#DDE0EE",
    "EDGE_HI":"#B0B8D8","EDGE_LO":"#C8CEDE",
    "GREEN":"#0E9E6A","GREEN_DIM":"#D0F0E4","GREEN_G":"#0BB860",
    "RED":"#E03040","RED_DIM":"#FFE0E3","YELLOW":"#C07800",
    "WHITE":"#1A1E35","GRAY":"#4A5070","DIM":"#8890AA",
    "AI_BG":"#E8F5EE","AI_EDGE":"#A8D8BC",
    "USR_BG":"#FFFFFF","USR_EDGE":"#C8CEDE","is_dark":False,
}

def get_devices():
    if not AUDIO_OK: return []
    pa = pyaudio.PyAudio()
    devs = []
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            devs.append({"index": i, "name": info["name"],
                         "ch": int(info["maxInputChannels"]),
                         "rate": int(info["defaultSampleRate"])})
    pa.terminate()
    return devs

def find_stereo_mix():
    kw = ["stereo mix", "wave out", "loopback", "stereomix", "miks stereo"]
    for d in get_devices():
        if any(k in d["name"].lower() for k in kw):
            return d["index"]
    return None

def open_stream(pa, device_index):
    if device_index is not None:
        try:
            info = pa.get_device_info_by_index(device_index)
            ch   = min(int(info["maxInputChannels"]), 2)
            sr   = int(info["defaultSampleRate"])
            configs = [(ch, sr), (1, sr), (1, 44100), (1, 48000), (1, 16000)]
        except Exception:
            configs = [(1, 16000)]
    else:
        configs = [(1, 16000), (1, 44100), (2, 44100)]
    for ch, sr in configs:
        try:
            s = pa.open(format=pyaudio.paInt16, channels=ch, rate=sr,
                        input=True, input_device_index=device_index,
                        frames_per_buffer=CHUNK)
            return s, ch, sr
        except Exception:
            continue
    return None, 1, 16000

def to_wav(frames, channels, rate):
    raw = b"".join(frames)
    if channels == 2:
        try: raw = audioop.tomono(raw, 2, 0.5)
        except Exception:
            sh  = struct.unpack(f"{len(raw)//2}h", raw)
            raw = struct.pack(f"{len(sh)//2}h",
                              *[(sh[i]+sh[i+1])//2 for i in range(0, len(sh)-1, 2)])
    if rate != RATE:
        try: raw, _ = audioop.ratecv(raw, 2, 1, rate, RATE, None)
        except Exception: pass
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2)
        w.setframerate(RATE); w.writeframes(raw)
    return buf.getvalue()

class Recorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._thread  = None
        self._frames  = []
        self._ch      = 1
        self._rate    = RATE
        self.device   = None
        self.on_done  = None
        self._level   = 0

    def start(self):
        with self._lock:
            if self._running: return
            self._running = True
            self._frames  = []
            self._thread  = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            if not self._running: return
            self._running = False
        if self._thread: self._thread.join(timeout=2)
        frames = list(self._frames)
        if not frames: return
        wav = to_wav(frames, self._ch, self._rate)
        if self.on_done: self.on_done(wav)

    def _loop(self):
        pa = pyaudio.PyAudio()
        stream, ch, rate = open_stream(pa, self.device)
        if stream is None:
            pa.terminate(); self._running = False; return
        self._ch = ch; self._rate = rate
        while self._running:
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                self._frames.append(data)
                try:
                    rms = audioop.rms(data, 2)
                    self._level = min(100, int(rms / 300))
                except Exception:
                    self._level = 0
            except: time.sleep(0.01)
        self._level = 0
        stream.stop_stream(); stream.close(); pa.terminate()

rec = Recorder()
rec.device = find_stereo_mix()

def main(page: ft.Page):
    page.title      = "Asystent-Rozmowy AI"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding    = 0
    try:
        page.window.width = 400; page.window.height = 640
        page.window.min_width = 360; page.window.min_height = 500
        page.window.always_on_top = True; page.window.maximizable = False
    except Exception:
        page.window_width = 400; page.window_height = 640
        page.window_min_width = 360; page.window_min_height = 500
        page.window_always_on_top = True; page.window_maximizable = False

    T  = dict(DARK)
    st = {"token": "", "email": "", "name": "", "plan": "",
          "has_sub": False, "ok": False, "busy": False,
          "rec": False, "hist": [], "n": 0, "ctx_focused": False,
          "cv_text": ""}
    page.bgcolor = T["BASE"]

    def show(screen):
        page.clean(); page.add(screen); page.update()

    # ── FORGOT PASSWORD ────────────────────────────────────────────────────────
    def forgot_screen():
        err  = ft.Text("", size=11, color=T["RED"], text_align="center")
        ok_msg = ft.Text("", size=11, color=T["GREEN"], text_align="center")
        spin = ft.ProgressRing(color=T["GREEN"], bgcolor="transparent",
                                stroke_width=2, width=14, height=14, visible=False)
        ef = ft.TextField(hint_text="Twoj email",
                           border_color=T["EDGE_LO"],
                           focused_border_color=T["GREEN"],
                           color=T["WHITE"],
                           hint_style=ft.TextStyle(color=T["DIM"]),
                           bgcolor=T["L3"], border_radius=12, height=48,
                           text_style=ft.TextStyle(size=13, color=T["WHITE"]),
                           cursor_color=T["GREEN"],
                           keyboard_type=ft.KeyboardType.EMAIL)

        def do_forgot(email):
            data, code = api("POST", "/auth/forgot_password", {"email": email})
            spin.visible = False
            if code == 200:
                ok_msg.value = "Jesli konto istnieje, wyslalismy email z linkiem."
                err.value = ""
            else:
                err.value = data.get("detail", f"Blad {code}")
                ok_msg.value = ""
            page.update()

        def submit(e):
            email = ef.value.strip()
            if not email or "@" not in email:
                err.value = "Podaj prawidlowy email"
                page.update(); return
            spin.visible = True
            err.value = ""
            ok_msg.value = "Wysylam..."
            page.update()
            threading.Thread(target=do_forgot, args=(email,), daemon=True).start()

        ef.on_submit = submit

        return ft.Container(bgcolor=T["BASE"], expand=True,
            content=ft.Column([
                ft.Container(expand=True),
                ft.Column([
                    ft.Row([
                        ft.Container(width=10, height=10, bgcolor=T["GREEN"],
                                      border_radius=3,
                                      shadow=ft.BoxShadow(blur_radius=18,
                                                           color=T["GREEN_G"],
                                                           spread_radius=3)),
                        ft.Container(width=10),
                        ft.Text("Asystent", size=22, weight="bold", color=T["WHITE"]),
                        ft.Text("-Rozmowy AI", size=22, weight="bold", color=T["GREEN"]),
                    ], alignment="center", spacing=0),
                ], horizontal_alignment="center"),
                ft.Container(height=28),
                ft.Container(
                    content=ft.Column([
                        ft.Container(height=1, bgcolor=T["EDGE_HI"],
                                      border_radius=ft.border_radius.only(
                                          top_left=16, top_right=16),
                                      margin=ft.margin.only(bottom=18)),
                        ft.Text("Reset hasla", size=16, weight="bold",
                                color=T["WHITE"], text_align="center"),
                        ft.Container(height=4),
                        ft.Text("Podaj email — wysylamy link resetujacy.\nLink wazny 1 godzine.",
                                size=11, color=T["GRAY"], text_align="center"),
                        ft.Container(height=16),
                        ef,
                        ft.Container(height=12),
                        ft.ElevatedButton(
                            content=ft.Row([spin,
                                            ft.Text("WYSLIJ LINK", weight="bold",
                                                     color=T["BASE"], size=13)],
                                            alignment="center", spacing=8),
                            bgcolor=T["GREEN"], height=50,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=12),
                                overlay_color="#00000020",
                                shadow_color="transparent"),
                            on_click=submit, expand=True),
                        ft.Container(height=10),
                        err, ok_msg,
                        ft.Container(height=10),
                        ft.GestureDetector(
                            content=ft.Text("Wróc do logowania",
                                             size=11, color=T["GREEN"],
                                             text_align="center"),
                            on_tap=lambda e: show(login_screen())),
                    ], spacing=0, horizontal_alignment="center"),
                    bgcolor=T["L1"], border_radius=18,
                    padding=ft.padding.only(left=20, right=20, bottom=20),
                    border=ft.border.all(1, T["EDGE_HI"]),
                    shadow=ft.BoxShadow(blur_radius=40, color="#000000BB",
                                         offset=ft.Offset(0, 10)),
                    margin=ft.margin.symmetric(horizontal=20),
                ),
                ft.Container(expand=True),
            ], horizontal_alignment="center", expand=True),
        )

    # ── LOGIN ──────────────────────────────────────────────────────────────────
    def login_screen(msg=""):
        is_login = [True]
        err  = ft.Text(msg, size=11, color=T["RED"], text_align="center")
        spin = ft.ProgressRing(color=T["GREEN"], bgcolor="transparent",
                                stroke_width=2, width=14, height=14, visible=False)
        ef = ft.TextField(hint_text="Email", border_color=T["EDGE_LO"],
                           focused_border_color=T["GREEN"], color=T["WHITE"],
                           hint_style=ft.TextStyle(color=T["DIM"]),
                           bgcolor=T["L3"], border_radius=12, height=48,
                           text_style=ft.TextStyle(size=13, color=T["WHITE"]),
                           cursor_color=T["GREEN"],
                           keyboard_type=ft.KeyboardType.EMAIL)
        pf = ft.TextField(hint_text="Haslo", password=True, can_reveal_password=True,
                           border_color=T["EDGE_LO"], focused_border_color=T["GREEN"],
                           color=T["WHITE"], hint_style=ft.TextStyle(color=T["DIM"]),
                           bgcolor=T["L3"], border_radius=12, height=48,
                           text_style=ft.TextStyle(size=13, color=T["WHITE"]),
                           cursor_color=T["GREEN"])
        nf = ft.TextField(hint_text="Imie (opcjonalnie)",
                           border_color=T["EDGE_LO"], focused_border_color=T["GREEN"],
                           color=T["WHITE"], hint_style=ft.TextStyle(color=T["DIM"]),
                           bgcolor=T["L3"], border_radius=12, height=48,
                           text_style=ft.TextStyle(size=13, color=T["WHITE"]),
                           cursor_color=T["GREEN"], visible=False)
        btn_lbl = ft.Text("ZALOGUJ SIE", weight="bold", color=T["BASE"], size=13)
        sw_lbl  = ft.Text("Nie masz konta? Zarejestruj sie",
                           size=11, color=T["GREEN"], text_align="center")

        def switch(e):
            is_login[0] = not is_login[0]
            nf.visible   = not is_login[0]
            btn_lbl.value = "ZALOGUJ SIE" if is_login[0] else "ZAREJESTRUJ SIE"
            sw_lbl.value  = ("Nie masz konta? Zarejestruj sie" if is_login[0]
                             else "Masz juz konto? Zaloguj sie")
            err.value = ""; page.update()

        def do_login(email, pw, name):
            if is_login[0]:
                data, code = api("POST", "/auth/login",
                                 {"email": email, "password": pw})
            else:
                data, code = api("POST", "/auth/register",
                                 {"email": email, "password": pw,
                                  "name": name or None})
            if code == 200:
                st.update({"token": data["token"], "email": data["email"],
                           "name": data.get("name", ""),
                           "plan": data.get("plan", "free"),
                           "has_sub": data.get("has_sub", False), "ok": True})
                save_token({"token": data["token"], "email": data["email"],
                            "name": data.get("name", ""),
                            "plan": data.get("plan", "free")})
                spin.visible = False
                show(app_screen() if st["has_sub"] else no_sub_screen())
            else:
                err.value = data.get("detail", f"Blad {code}")
                err.color = T["RED"]
                spin.visible = False
                page.update()

        def submit(e):
            email = ef.value.strip()
            pw    = pf.value.strip()
            name  = nf.value.strip()
            if not email or not pw:
                err.value = "Wypelnij email i haslo"
                err.color = T["RED"]; page.update(); return
            if len(pw) < 8:
                err.value = "Haslo min. 8 znakow"
                err.color = T["RED"]; page.update(); return
            spin.visible = True
            err.value = "Laczenie..."
            err.color = T["GRAY"]
            page.update()
            threading.Thread(target=do_login,
                             args=(email, pw, name), daemon=True).start()

        ef.on_submit = submit
        pf.on_submit = submit

        return ft.Container(bgcolor=T["BASE"], expand=True,
            content=ft.Column([
                ft.Container(expand=True),
                ft.Column([
                    ft.Row([
                        ft.Container(width=10, height=10, bgcolor=T["GREEN"],
                                      border_radius=3,
                                      shadow=ft.BoxShadow(blur_radius=18,
                                                           color=T["GREEN_G"],
                                                           spread_radius=3)),
                        ft.Container(width=10),
                        ft.Text("Asystent", size=26, weight="bold", color=T["WHITE"]),
                        ft.Text("-Rozmowy AI", size=26, weight="bold", color=T["GREEN"]),
                    ], alignment="center", spacing=0),
                    ft.Container(height=6),
                    ft.Text("Interview Assistant  v" + VERSION,
                            size=11, color=T["GRAY"], text_align="center"),
                ], horizontal_alignment="center"),
                ft.Container(height=28),
                ft.Container(
                    content=ft.Column([
                        ft.Container(height=1, bgcolor=T["EDGE_HI"],
                                      border_radius=ft.border_radius.only(
                                          top_left=16, top_right=16),
                                      margin=ft.margin.only(bottom=18)),
                        ef, ft.Container(height=8),
                        pf, ft.Container(height=8),
                        nf, ft.Container(height=12),
                        ft.ElevatedButton(
                            content=ft.Row([spin, btn_lbl],
                                            alignment="center", spacing=8),
                            bgcolor=T["GREEN"], height=50,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=12),
                                overlay_color="#00000020",
                                shadow_color="transparent"),
                            on_click=submit, expand=True),
                        ft.Container(height=10),
                        err,
                        ft.Container(height=6),
                        ft.GestureDetector(content=sw_lbl, on_tap=switch),
                        ft.Container(height=8),
                        # Zapomniałem hasła
                        ft.GestureDetector(
                            content=ft.Text("Zapomnialem hasla",
                                             size=11, color=T["DIM"],
                                             text_align="center"),
                            on_tap=lambda e: show(forgot_screen())),
                    ], spacing=0),
                    bgcolor=T["L1"], border_radius=18,
                    padding=ft.padding.only(left=20, right=20, bottom=20),
                    border=ft.border.all(1, T["EDGE_HI"]),
                    shadow=ft.BoxShadow(blur_radius=40, color="#000000BB",
                                         offset=ft.Offset(0, 10)),
                    margin=ft.margin.symmetric(horizontal=20),
                ),
                ft.Container(expand=True),
                ft.Text("Dane chronione  RODO", size=10, color=T["DIM"],
                        text_align="center"),
                ft.Container(height=20),
            ], horizontal_alignment="center", expand=True),
        )

    # ── NO SUB ─────────────────────────────────────────────────────────────────
    def no_sub_screen():
        buy_status = ft.Text("", size=11, color=T["YELLOW"], text_align="center")

        def buy_sub(e):
            buy_status.value = "Lacze z platnoscia..."
            buy_status.color = T["GRAY"]
            page.update()

            def do_buy():
                data, code = api("POST", "/stripe/create_checkout",
                                 {"plan": "monthly"}, token=st["token"])
                if code == 200:
                    url = data.get("checkout_url", "")
                    if url:
                        buy_status.value = ""
                        page.update()
                        import webbrowser
                        webbrowser.open(url)
                    else:
                        buy_status.value = "Blad - brak URL"
                        buy_status.color = T["RED"]
                        page.update()
                else:
                    buy_status.value = data.get("detail", f"Blad {code}")
                    buy_status.color = T["RED"]
                    page.update()

            threading.Thread(target=do_buy, daemon=True).start()

        def check_sub(e):
            def do_check():
                data, code = api("GET", "/auth/me", token=st["token"])
                if code == 200 and data.get("has_sub"):
                    st.update({"has_sub": True, "plan": data["plan"]})
                    show(app_screen())
                else:
                    buy_status.value = "Subskrypcja jeszcze nieaktywna"
                    buy_status.color = T["YELLOW"]
                    page.update()
            threading.Thread(target=do_check, daemon=True).start()

        return ft.Container(bgcolor=T["BASE"], expand=True,
            content=ft.Column([
                ft.Container(expand=True),
                ft.Column([
                    ft.Text("Subskrypcja nieaktywna", size=18, weight="bold",
                            color=T["WHITE"], text_align="center"),
                    ft.Container(height=8),
                    ft.Text(f"Konto: {st['email']}", size=12,
                            color=T["GRAY"], text_align="center"),
                    ft.Container(height=24),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Asystent-Rozmowy AI Pro",
                                    size=14, weight="bold",
                                    color=T["WHITE"], text_align="center"),
                            ft.Container(height=8),
                            ft.Text("49 PLN / miesiac",
                                    size=22, weight="bold",
                                    color=T["GREEN"], text_align="center"),
                            ft.Container(height=8),
                            ft.Text("Nieograniczony dostep · PTT · Historia",
                                    size=12, color=T["GRAY"], text_align="center"),
                        ], horizontal_alignment="center"),
                        bgcolor=T["L3"], border_radius=14, padding=20,
                        border=ft.border.all(1, T["EDGE_LO"]),
                        margin=ft.margin.symmetric(horizontal=24)),
                    ft.Container(height=16),
                    ft.Container(
                        content=ft.ElevatedButton(
                            content=ft.Text("KUP SUBSKRYPCJE",
                                            weight="bold", color=T["BASE"], size=13),
                            bgcolor=T["GREEN"], height=50,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=12),
                                overlay_color="#00000020",
                                shadow_color="transparent"),
                            on_click=buy_sub, expand=True),
                        margin=ft.margin.symmetric(horizontal=24)),
                    ft.Container(height=8),
                    buy_status,
                    ft.Container(height=8),
                    ft.GestureDetector(
                        content=ft.Text("Oplaciles? Kliknij tutaj aby odswiezye",
                                         size=11, color=T["GREEN"],
                                         text_align="center"),
                        on_tap=check_sub),
                    ft.Container(height=24),
                    ft.ElevatedButton(
                        content=ft.Text("Wyloguj sie", color=T["GRAY"], size=12),
                        bgcolor=T["L3"], height=44,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=10),
                            side=ft.BorderSide(1, T["EDGE_LO"]),
                            shadow_color="transparent"),
                        on_click=lambda e: (clear_token(), show(login_screen()))),
                ], horizontal_alignment="center"),
                ft.Container(expand=True),
            ], horizontal_alignment="center", expand=True),
        )

    # ── HELP MODAL ─────────────────────────────────────────────────────────────
    def build_help_modal():
        overlay = ft.Container(visible=False, expand=True)
        def close(e): overlay.visible = False; page.update()
        def open_h(e=None): overlay.visible = True; page.update()

        def tile(ico, title, body):
            return ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Text(ico, size=13),
                        ft.Container(width=6),
                        ft.Text(title, size=12, weight="bold",
                                color=T["WHITE"],
                                overflow="ellipsis", max_lines=1),
                    ], spacing=0),
                    ft.Container(
                        content=ft.Text(body, size=11,
                                        color=T["GRAY"], height=1.7),
                        margin=ft.margin.only(left=22, top=4)),
                ], spacing=0),
                bgcolor=T["L3"], border_radius=10,
                padding=ft.padding.symmetric(horizontal=12, vertical=10),
                border=ft.border.all(1, T["EDGE_LO"]),
            )

        cards = ft.Column(scroll="auto", spacing=7, controls=[
            tile("🔴  Przycisk TRZYMAJ", "Push-To-Talk",
                 "1. Gdy rekruter mowi - wcisnij i TRZYMAJ MIC. 2. Gdy skonczy - PUSC. 3. Poczekaj 2 sek. Skrot: SPACJA"),
            tile("✏️  Pole tekstowe", "Wpisywanie reczne",
                 "Wpisz pytanie rekrutera w pole tekstowe i nacisnij ENTER lub strzalke w gore."),
            tile("⚡  Szybkie pytania", "Mocne strony / STAR / Dlaczego",
                 "Mocne strony - gdy rekruter pyta o atuty. STAR - przyklad osiagniecia. Dlaczego tu? - motywacja."),
            tile("🎤  Urzadzenie audio", "Zmiana zrodla dzwieku",
                 "Kliknij zielony przycisk z nazwa urzadzenia. Stereo Mix = dzwiek z Teams/Zoom."),
            tile("🌙  Motyw", "Dark / Light mode",
                 "Ikona slonca/ksiezyca w naglowku. Przelacza miedzy ciemnym a jasnym wygledem."),
            tile("📌  PIN", "Zawsze na wierzchu",
                 "Przelacznik PIN - gdy wlaczony okno jest zawsze widoczne nad Teams i Zoom."),
            tile("🗑️  Kosz", "Wyczysc historie",
                 "Ikona kosza usuwa cala historie. AI zapomina kontekst. Uzywaj przed kazda nowa rozmowa."),
            tile("🔑  Wyloguj", "Zmiana konta",
                 "Wylogowuje z konta. Token zapisany lokalnie - auto-login przy nastepnym uruchomieniu."),
        ])

        overlay.content = ft.Stack([
            ft.Container(expand=True, bgcolor="#000000DD"),
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Column([
                            ft.Text("Instrukcja obslugi", size=16,
                                    weight="bold", color=T["WHITE"]),
                            ft.Text("Asystent-Rozmowy AI  v" + VERSION,
                                    size=10, color=T["DIM"]),
                        ], spacing=3, expand=True),
                        ft.IconButton(
                            ft.icons.CLOSE,
                            icon_color=T["GRAY"], icon_size=20,
                            style=ft.ButtonStyle(bgcolor=T["L3"],
                                                  shape=ft.CircleBorder()),
                            on_click=close),
                    ], alignment="spaceBetween"),
                    ft.Divider(height=1, color=T["EDGE_LO"]),
                    ft.Container(content=cards, expand=True),
                    ft.Divider(height=1, color=T["EDGE_LO"]),
                    ft.Container(
                        content=ft.Text(
                            "Audio -> Whisper (OpenAI). Odpowiedzi -> GPT-4o (OpenAI). Nic nie jest zapisywane.",
                            size=10, color=T["DIM"], text_align="center"),
                        bgcolor=T["L3"], border_radius=8, padding=10,
                        border=ft.border.all(1, T["EDGE_LO"])),
                ], spacing=10, expand=True),
                bgcolor=T["L1"], border_radius=20, padding=18,
                border=ft.border.all(1, T["EDGE_HI"]),
                shadow=ft.BoxShadow(blur_radius=60, color="#000000CC",
                                     offset=ft.Offset(0, 16)),
                width=364, height=580, left=18, top=24,
            ),
        ])
        return overlay, open_h

    # ── APP ────────────────────────────────────────────────────────────────────
    def app_screen():
        # ── UPDATE BANNER ──────────────────────────────────────────────────
        update_banner = ft.Container(visible=False, bgcolor="#1A1400",
            border=ft.border.only(bottom=ft.BorderSide(1, "#FFD16640")),
            padding=ft.padding.symmetric(horizontal=12, vertical=6))

        def show_update(version, url):
            def open_url(e):
                import webbrowser
                webbrowser.open(url)
            update_banner.content = ft.Row([
                ft.Text("🆕", size=12),
                ft.Container(width=6),
                ft.Text(f"Dostepna aktualizacja v{version}",
                        size=11, color=T["YELLOW"], expand=True),
                ft.GestureDetector(
                    content=ft.Container(
                        content=ft.Text("Pobierz", size=11,
                                        color=T["BASE"], weight="bold"),
                        bgcolor=T["YELLOW"], border_radius=6,
                        padding=ft.padding.symmetric(horizontal=10, vertical=4)),
                    on_tap=open_url),
                ft.Container(width=4),
                ft.GestureDetector(
                    content=ft.Text("✕", size=12, color=T["DIM"]),
                    on_tap=lambda e: (
                        setattr(update_banner, "visible", False),
                        page.update())),
            ], vertical_alignment="center", spacing=0)
            update_banner.visible = True
            try: page.update()
            except Exception: pass

        # Sprawdz aktualizacje w tle
        threading.Thread(
            target=check_update,
            args=(VERSION, show_update),
            daemon=True).start()

        chat   = ft.Column(scroll="auto", spacing=8, expand=True)
        n_lbl  = ft.Text("0", size=10, color=T["DIM"])
        pin_sw = ft.Switch(value=True, active_color=T["GREEN"],
                            inactive_thumb_color=T["DIM"], scale=0.65)
        status = ft.Text("", size=10, color=T["RED"])
        ctx    = ft.TextField(
            hint_text="Wpisz pytanie lub SPACJA...",
            multiline=True, min_lines=1, max_lines=2,
            border_color=T["EDGE_LO"], focused_border_color=T["GREEN"],
            color=T["WHITE"], hint_style=ft.TextStyle(color=T["GRAY"], size=11),
            bgcolor=T["L3"], border_radius=11,
            text_style=ft.TextStyle(size=12, color=T["WHITE"]),
            cursor_color=T["GREEN"], expand=True)
        ctx.on_focus = lambda e: st.update({"ctx_focused": True})
        ctx.on_blur  = lambda e: st.update({"ctx_focused": False})

        def bdg(txt, color, bg):
            return ft.Container(
                content=ft.Text(txt, size=8, color=color, weight="bold"),
                bgcolor=bg, border_radius=4,
                padding=ft.padding.symmetric(horizontal=6, vertical=2))

        def bbl_ai(text, tag="AI", error=False):
            ts = datetime.now().strftime("%H:%M")
            return ft.Container(
                content=ft.Column([
                    ft.Row([bdg(f"+ {tag}", T["GREEN"], T["GREEN_DIM"]),
                            ft.Text(ts, size=9, color=T["DIM"])], spacing=7),
                    ft.Container(height=7),
                    ft.Markdown(text, selectable=True,
                                extension_set="gitHubFlavored",
                                md_style_sheet=ft.MarkdownStyleSheet(
                                    p_text_style=ft.TextStyle(
                                        color=T["RED"] if error else T["WHITE"],
                                        size=12, height=1.65),
                                    code_text_style=ft.TextStyle(
                                        color=T["GREEN"], size=11))),
                ], spacing=0),
                bgcolor=T["AI_BG"], border_radius=14, padding=13,
                border=ft.border.all(1, T["AI_EDGE"]),
                shadow=ft.BoxShadow(blur_radius=12, color="#00000022",
                                     offset=ft.Offset(0, 3)))

        def bbl_user(text):
            ts = datetime.now().strftime("%H:%M")
            return ft.Container(
                content=ft.Column([
                    ft.Row([bdg("TY", T["GRAY"], T["L3"]),
                            ft.Text(ts, size=9, color=T["DIM"])], spacing=7),
                    ft.Container(height=5),
                    ft.Text(text, color=T["GRAY"], size=12, height=1.55),
                ], spacing=0),
                bgcolor=T["USR_BG"], border_radius=12, padding=11,
                border=ft.border.all(1, T["USR_EDGE"]))

        def push_ai(text, tag="AI", error=False):
            chat.controls.append(bbl_ai(text, tag, error))
            page.update(); chat.scroll_to(offset=-1, duration=150)

        def push_user(text):
            chat.controls.append(bbl_user(text))
            page.update(); chat.scroll_to(offset=-1, duration=150)

        def stream_bubble():
            txt  = ft.Text("", color=T["WHITE"], size=12, height=1.65, selectable=True)
            sp   = ft.ProgressRing(color=T["GREEN"], bgcolor="transparent",
                                    stroke_width=1.5, width=10, height=10)
            ts   = datetime.now().strftime("%H:%M")
            hdr  = ft.Row([bdg("+ PTT", T["GREEN"], T["GREEN_DIM"]),
                            ft.Text(ts, size=9, color=T["DIM"]), sp], spacing=7)
            box  = ft.Container(
                content=ft.Column([hdr, ft.Container(height=7), txt], spacing=0),
                bgcolor=T["AI_BG"], border_radius=14, padding=13,
                border=ft.border.all(1, T["AI_EDGE"]),
                shadow=ft.BoxShadow(blur_radius=12, color="#00000022",
                                     offset=ft.Offset(0, 3)))
            return box, txt, hdr, sp

        mic_icon  = ft.Icon(ft.icons.MIC, color=T["GREEN"], size=24)
        mic_label = ft.Text("TRZYMAJ", size=9, color=T["GRAY"], weight="bold")
        mic_btn   = ft.ElevatedButton(
            content=ft.Column([mic_icon, mic_label],
                               horizontal_alignment="center", spacing=2),
            bgcolor=T["L3"], height=62, width=68,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12),
                side=ft.BorderSide(1, T["EDGE_LO"]),
                shadow_color="transparent"))

        def set_mic(recording):
            if recording:
                mic_btn.bgcolor = T["RED_DIM"]
                mic_btn.style   = ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=12),
                    side=ft.BorderSide(2, T["RED"]),
                    shadow_color="transparent")
                mic_icon.color  = T["RED"]
                mic_label.value = "PUSC"
                mic_label.color = T["RED"]
                status.value    = "Nagrywanie... pusc aby wyslac"
                status.color    = T["RED"]
            else:
                mic_btn.bgcolor = T["L3"]
                mic_btn.style   = ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=12),
                    side=ft.BorderSide(1, T["EDGE_LO"]),
                    shadow_color="transparent")
                mic_icon.color  = T["GREEN"]
                mic_label.value = "TRZYMAJ"
                mic_label.color = T["GRAY"]
                status.value    = "Przetwarzanie..."
                status.color    = T["GRAY"]
            page.update()

        def mic_start():
            if not AUDIO_OK:
                push_ai("Zainstaluj:  pip install pyaudio", error=True); return
            if st["rec"]: return
            st["rec"] = True; set_mic(True); rec.start()

        def mic_stop():
            if not st["rec"]: return
            st["rec"] = False; set_mic(False)
            threading.Thread(target=rec.stop, daemon=True).start()

        def send_wav_thread(wav):
            size_kb = len(wav)/1024
            if size_kb < 1:
                status.value = "Za krotkie — trzymaj dluzej"
                status.color = T["YELLOW"]; page.update()
                time.sleep(2); status.value = ""; page.update(); return

            b64 = base64.b64encode(wav).decode()
            box, txt, hdr, sp = stream_bubble()
            chat.controls.append(box); page.update()
            chat.scroll_to(offset=-1, duration=150)

            req = urllib.request.Request(
                BACKEND + "/audio_chunk",
                data=json.dumps({"audio_data": b64,
                                 "conversation_history": st["hist"][-6:],
                                 "language": "pl",
                                 "cv_text": st["cv_text"]}).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {st['token']}"},
                method="POST")
            try:
                resp = urllib.request.urlopen(req, timeout=45)
                full_text = ""
                transcript = ""
                tokens = []
                spinner_removed = False

                for line in resp:
                    line = line.decode("utf-8").strip()
                    if not line.startswith("data:"): continue
                    try: ev = json.loads(line[5:].strip())
                    except: continue
                    t = ev.get("type")

                    if t == "skip":
                        if box in chat.controls:
                            chat.controls.remove(box)
                        status.value = "Nie wykryto mowy"
                        status.color = T["GRAY"]; page.update()
                        time.sleep(2); status.value = ""; page.update(); return

                    elif t == "transcript":
                        transcript = ev.get("text", "")
                        idx = chat.controls.index(box)
                        chat.controls.insert(idx, bbl_user(f"  {transcript}"))
                        page.update()

                    elif t == "token":
                        tokens.append(ev.get("text", ""))
                        txt.value = "".join(tokens)
                        if not spinner_removed:
                            spinner_removed = True
                            if sp in hdr.controls:
                                hdr.controls.remove(sp)
                        page.update()

                    elif t == "done":
                        full_text = ev.get("full", "".join(tokens))
                        if transcript:
                            st["hist"].append({"role": "user",
                                               "content": f"Rekruter: {transcript}"})
                        st["hist"].append({"role": "assistant",
                                           "content": full_text})
                        st["n"] += 1; n_lbl.value = str(st["n"])
                        idx = chat.controls.index(box)
                        chat.controls[idx] = bbl_ai(full_text, "PTT")
                        status.value = ""; page.update()
                        chat.scroll_to(offset=-1, duration=150)

                    elif t == "error":
                        txt.value = f"Blad: {ev.get('msg', '')}"
                        if sp in hdr.controls: hdr.controls.remove(sp)
                        status.value = ""; page.update()

            except urllib.error.HTTPError as e:
                if e.code == 402:
                    if box in chat.controls: chat.controls.remove(box)
                    show(no_sub_screen()); return
                txt.value = f"Blad HTTP {e.code}"
                if sp in hdr.controls: hdr.controls.remove(sp)
                status.value = ""; page.update()
            except Exception as ex:
                txt.value = f"Blad: {str(ex)[:60]}"
                if sp in hdr.controls: hdr.controls.remove(sp)
                status.value = ""; page.update()

        def on_wav(wav):
            threading.Thread(target=send_wav_thread, args=(wav,), daemon=True).start()
        rec.on_done = on_wav

        def do_chat_thread(msg):
            data, code = api("POST", "/chat",
                             {"message": msg,
                              "conversation_history": st["hist"][-8:],
                              "cv_text": st["cv_text"]},
                             token=st["token"])
            if code == 200:
                ans = data.get("answer", "")
                st["hist"].append({"role": "assistant", "content": ans})
                push_ai(ans)
            elif code == 402:
                show(no_sub_screen())
            else:
                push_ai(f"Blad: {data.get('detail','')}", error=True)
            st["busy"] = False
            ctx.disabled = False; page.update()

        def submit_chat(e):
            msg = ctx.value.strip()
            if not msg or st["busy"]: return
            ctx.value = ""; push_user(msg)
            st["hist"].append({"role": "user", "content": msg})
            st["busy"] = True; ctx.disabled = True; page.update()
            threading.Thread(target=do_chat_thread, args=(msg,), daemon=True).start()

        ctx.on_submit = submit_chat

        def on_key(e: ft.KeyboardEvent):
            if e.key == " " and not st["ctx_focused"]:
                if st["rec"]: mic_stop_with_level()
                else: mic_start_with_level()
        page.on_keyboard_event = on_key

        level_bars = [
            ft.Container(width=4, height=6 + i*3, bgcolor=T["GREEN"],
                         border_radius=2, opacity=0.2) for i in range(5)
        ]
        level_row = ft.Row(controls=level_bars, spacing=2,
                            vertical_alignment="end", visible=False)

        def update_level():
            while st["rec"]:
                level = rec._level
                for i, bar in enumerate(level_bars):
                    threshold = (i + 1) * 20
                    bar.opacity = 1.0 if level >= threshold else 0.2
                    if level >= threshold:
                        bar.bgcolor = (T["GREEN"] if level < 60 else
                                       T["YELLOW"] if level < 85 else T["RED"])
                try: page.update()
                except Exception: pass
                time.sleep(0.1)
            for bar in level_bars:
                bar.opacity = 0.2; bar.bgcolor = T["GREEN"]
            try:
                level_row.visible = False; page.update()
            except Exception: pass

        def mic_start_with_level():
            mic_start()
            level_row.visible = True; page.update()
            threading.Thread(target=update_level, daemon=True).start()

        def mic_stop_with_level():
            mic_stop()

        mic_gesture = ft.GestureDetector(
            content=ft.Column([level_row, ft.Container(height=2), mic_btn],
                               horizontal_alignment="center", spacing=0),
            on_tap_down=lambda e: mic_start_with_level(),
            on_tap_up=lambda e: mic_stop_with_level(),
            on_pan_end=lambda e: mic_stop_with_level())

        devices = get_devices() if AUDIO_OK else []
        dev_lbl = ft.Text(
            "domyslne" if rec.device is None else
            next((d["name"][:14] for d in devices
                  if d["index"] == rec.device), "?"),
            size=9, color=T["GREEN"], weight="bold",
            max_lines=1, overflow="ellipsis")
        dev_modal = ft.Container(visible=False, expand=True)

        def _drow(idx, name, sub, is_l, sel):
            def pick(e):
                rec.device = idx
                dev_lbl.value = ("domyslne" if idx is None else
                                 next((d["name"][:14] for d in devices
                                       if d["index"] == idx), "?"))
                dev_lbl.color = T["GREEN"] if (is_l or idx is None) else T["GRAY"]
                dev_modal.visible = False
                chat.controls.clear(); welcome(); page.update()
            icon = "🔊" if is_l else "🎤"
            return ft.Container(
                content=ft.Row([
                    ft.Text(icon, size=16), ft.Container(width=10),
                    ft.Column([
                        ft.Text(name, size=12,
                                color=T["GREEN"] if sel else T["WHITE"],
                                weight="bold" if sel else "normal",
                                max_lines=1, overflow="ellipsis"),
                        ft.Text(sub, size=10, color=T["DIM"]),
                    ], spacing=2, expand=True),
                    ft.Container(
                        content=ft.Text("✓", size=14, color=T["GREEN"], weight="bold"),
                        visible=sel, width=20),
                ], spacing=0, vertical_alignment="center"),
                bgcolor=T["GREEN_DIM"] if sel else T["L3"], border_radius=10,
                padding=ft.padding.symmetric(horizontal=12, vertical=10),
                border=ft.border.all(2 if sel else 1,
                                      T["GREEN"] if sel else T["EDGE_LO"]),
                on_click=pick)

        def show_devices(e):
            rows = [_drow(None, "Domyslne (system)", "Urzadzenie domyslne Windows",
                          False, rec.device is None)]
            for d in devices:
                is_l = any(k in d["name"].lower() for k in
                           ["stereo mix", "wave out", "loopback", "mix"])
                rows.append(_drow(d["index"],
                                  ("  " if is_l else "  ") + d["name"],
                                  "Dzwiek systemowy" if is_l else "Mikrofon",
                                  is_l, rec.device == d["index"]))
            dev_modal.content = ft.Stack([
                ft.Container(expand=True, bgcolor="#000000DD"),
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text("Urzadzenie audio", size=14, weight="bold",
                                    color=T["WHITE"], expand=True),
                            ft.IconButton(ft.icons.CLOSE, icon_color=T["GRAY"],
                                           icon_size=18,
                                           style=ft.ButtonStyle(bgcolor=T["L3"],
                                                                 shape=ft.CircleBorder()),
                                           on_click=lambda e: (
                                               setattr(dev_modal, "visible", False),
                                               page.update())),
                        ], alignment="spaceBetween"),
                        ft.Divider(height=1, color=T["EDGE_LO"]),
                        ft.Column(rows, scroll="auto", spacing=6),
                    ], spacing=8),
                    bgcolor=T["L1"], border_radius=18, padding=18,
                    border=ft.border.all(1, T["EDGE_HI"]),
                    shadow=ft.BoxShadow(blur_radius=40, color="#000000CC",
                                         offset=ft.Offset(0, 12)),
                    width=364, height=460, left=18, top=60),
            ])
            dev_modal.visible = True; page.update()

        dev_btn = ft.GestureDetector(
            content=ft.Container(
                content=ft.Row([ft.Icon(ft.icons.MIC, color=T["GREEN"], size=11),
                                 ft.Container(width=3), dev_lbl], spacing=0),
                bgcolor=T["GREEN_DIM"], border_radius=6,
                padding=ft.padding.symmetric(horizontal=7, vertical=3),
                border=ft.border.all(1, T["AI_EDGE"]), tooltip="Zmien urzadzenie"),
            on_tap=show_devices)

        def toggle_theme(e):
            currently_dark = T.get("is_dark", True)
            T.clear(); T.update(LIGHT if currently_dark else DARK)
            page.theme_mode = (ft.ThemeMode.LIGHT
                               if not T["is_dark"] else ft.ThemeMode.DARK)
            page.bgcolor = T["BASE"]; show(app_screen())

        theme_btn = ft.IconButton(
            icon=ft.icons.LIGHT_MODE if T["is_dark"] else ft.icons.DARK_MODE,
            icon_color=T["GRAY"], icon_size=17, tooltip="Zmien motyw",
            on_click=toggle_theme,
            style=ft.ButtonStyle(overlay_color=T["L3"]))

        help_overlay, open_help = build_help_modal()

        cv_lbl = ft.Text("CV: brak" if not st["cv_text"] else "CV: wczytane",
                          size=9,
                          color=T["DIM"] if not st["cv_text"] else T["GREEN"],
                          weight="bold")

        def parse_cv(path: str) -> str:
            text = ""
            try:
                if path.lower().endswith(".pdf"):
                    if PDF_OK:
                        import pdfplumber
                        with pdfplumber.open(path) as pdf:
                            for pg in pdf.pages:
                                text += pg.extract_text() or ""
                    else:
                        return "BLAD: Zainstaluj pdfplumber: pip install pdfplumber"
                else:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
            except Exception as ex:
                return f"BLAD: {ex}"
            return text[:4000].strip()

        def on_cv_pick(e: ft.FilePickerResultEvent):
            if not e.files: return
            path = e.files[0].path
            def load():
                text = parse_cv(path)
                if text.startswith("BLAD"):
                    cv_lbl.value = "CV: blad"; cv_lbl.color = T["RED"]
                    st["cv_text"] = ""
                else:
                    st["cv_text"] = text
                    cv_lbl.value = "CV: wczytane ✓"; cv_lbl.color = T["GREEN"]
                    chat.controls.clear(); welcome()
                page.update()
            threading.Thread(target=load, daemon=True).start()

        cv_picker = ft.FilePicker(on_result=on_cv_pick)
        page.overlay.append(cv_picker)

        def open_cv_picker(e):
            cv_picker.pick_files(dialog_title="Wybierz CV (PDF lub TXT)",
                                  allowed_extensions=["pdf", "txt"],
                                  allow_multiple=False)

        cv_btn = ft.GestureDetector(
            content=ft.Container(
                content=ft.Row([
                    ft.Icon(ft.icons.UPLOAD_FILE,
                            color=T["GREEN"] if st["cv_text"] else T["DIM"], size=11),
                    ft.Container(width=3), cv_lbl], spacing=0),
                bgcolor=T["GREEN_DIM"] if st["cv_text"] else T["L3"],
                border_radius=6,
                padding=ft.padding.symmetric(horizontal=7, vertical=3),
                border=ft.border.all(1, T["AI_EDGE"] if st["cv_text"] else T["EDGE_LO"]),
                tooltip="Kliknij aby wczytac CV (PDF/TXT)"),
            on_tap=open_cv_picker)

        def do_clear(e):
            st["hist"] = []; st["n"] = 0; n_lbl.value = "0"
            chat.controls.clear(); welcome(); page.update()

        def do_logout(e):
            clear_token(); show(login_screen())

        def do_pin(e):
            try: page.window.always_on_top = pin_sw.value
            except: page.window_always_on_top = pin_sw.value
            page.update()
        pin_sw.on_change = do_pin

        send_btn = ft.ElevatedButton(
            content=ft.Icon(ft.icons.ARROW_UPWARD, color=T["WHITE"], size=17),
            bgcolor=T["L3"], height=42, width=44,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=11),
                side=ft.BorderSide(1, T["EDGE_LO"]),
                shadow_color="transparent"),
            on_click=submit_chat)

        pills = [
            ("Mocne strony", "Jakie sa moje mocne strony jako kandydat?"),
            ("STAR",         "Podaj przyklad osiagniecia metoda STAR"),
            ("Dlaczego tu?", "Dlaczego chce pracowac w tej firmie?"),
        ]
        def qtap(p):
            def h(e): ctx.value = p; page.update()
            return h

        def welcome():
            pb = ft.Container(
                content=ft.Text(
                    ("PRO" if st["has_sub"] else "FREE") + " - " + (st["name"] or st["email"]),
                    size=9, color=T["GREEN"] if st["has_sub"] else T["GRAY"], weight="bold"),
                bgcolor=T["GREEN_DIM"] if st["has_sub"] else T["L3"], border_radius=6,
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                border=ft.border.all(1, T["AI_EDGE"] if st["has_sub"] else T["EDGE_LO"]))

            current_dev_name = next((d["name"] for d in get_devices()
                                     if d["index"] == rec.device), "") if rec.device is not None else ""
            stereo_ok = any(k in current_dev_name.lower() for k in ["stereo", "mix", "loopback"])

            if stereo_ok:
                audio_card = ft.Container(
                    content=ft.Row([
                        ft.Text("🔊", size=16), ft.Container(width=8),
                        ft.Column([
                            ft.Text("Stereo Mix aktywny", size=12, weight="bold", color=T["GREEN"]),
                            ft.Text("Slyszysz glos rekrutera z Zoom/Teams", size=10, color=T["GRAY"]),
                        ], spacing=2, expand=True),
                    ], spacing=0, vertical_alignment="center"),
                    bgcolor=T["GREEN_DIM"], border_radius=10, padding=12,
                    border=ft.border.all(1, T["AI_EDGE"]))
            else:
                audio_card = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text("⚠️", size=16), ft.Container(width=8),
                            ft.Column([
                                ft.Text("Ustaw Stereo Mix", size=12, weight="bold", color=T["YELLOW"]),
                                ft.Text("Bez tego AI nie slyszy rekrutera", size=10, color=T["DIM"]),
                            ], spacing=2, expand=True),
                        ], spacing=0, vertical_alignment="center"),
                        ft.Container(height=6),
                        ft.Text("Jak wlaczyc: Ustawienia dzwieku -> Nagrywanie -> Prawy klik -> Pokaz wylaczone -> Stereo Mix -> Wlacz",
                                size=11, color=T["GRAY"], weight="bold"),
                    ], spacing=0),
                    bgcolor="#1A1400", border_radius=10, padding=12,
                    border=ft.border.all(1, T["YELLOW"]))

            chat.controls.append(ft.Container(
                content=ft.Column([
                    ft.Container(
                        content=ft.Icon(ft.icons.AUTO_AWESOME, color=T["GREEN"], size=20),
                        bgcolor=T["GREEN_DIM"], border_radius=10, padding=9,
                        width=40, height=40, border=ft.border.all(1, T["AI_EDGE"]),
                        alignment=ft.alignment.center),
                    ft.Container(height=8), pb, ft.Container(height=8),
                    ft.Text("Asystent gotowy", size=14, weight="bold",
                            color=T["WHITE"], text_align="center"),
                    ft.Container(height=10),
                    audio_card,
                    ft.Container(height=10),
                    ft.Container(
                        content=ft.Row([
                            ft.Text("📄", size=14), ft.Container(width=8),
                            ft.Column([
                                ft.Text(
                                    "CV wczytane - AI odpowiada na podstawie Twoich danych" if st["cv_text"]
                                    else "Brak CV - AI odpowiada ogolnie",
                                    size=11, weight="bold",
                                    color=T["GREEN"] if st["cv_text"] else T["GRAY"]),
                                ft.Text(
                                    "Kliknij ikone CV w naglowku aby zmienic" if st["cv_text"]
                                    else "Kliknij ikone CV w naglowku aby wczytac PDF",
                                    size=10, color=T["DIM"]),
                            ], spacing=2, expand=True),
                        ], spacing=0, vertical_alignment="center"),
                        bgcolor=T["GREEN_DIM"] if st["cv_text"] else T["L3"],
                        border_radius=10, padding=12,
                        border=ft.border.all(1, T["AI_EDGE"] if st["cv_text"] else T["EDGE_LO"])),
                    ft.Container(height=10),
                    ft.Container(
                        content=ft.Row([
                            ft.Container(
                                content=ft.Text("SPACJA", size=10, color=T["GREEN"], weight="bold"),
                                bgcolor=T["GREEN_DIM"], border_radius=6,
                                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                border=ft.border.all(1, T["AI_EDGE"])),
                            ft.Text("= trzymaj / pusc mikrofon", size=11, color=T["GRAY"]),
                        ], spacing=8, alignment="center"),
                        bgcolor=T["L3"], border_radius=10, padding=12,
                        border=ft.border.all(1, T["EDGE_LO"])),
                ], horizontal_alignment="center"),
                alignment=ft.alignment.center,
                padding=ft.padding.symmetric(vertical=18)))
        welcome()

        return ft.Container(bgcolor=T["BASE"], expand=True,
            content=ft.Stack([
                ft.Column([
                    ft.Container(
                        content=ft.Column([
                            ft.Container(height=1, bgcolor=T["EDGE_HI"],
                                          margin=ft.margin.only(bottom=8)),
                            ft.Row([
                                ft.Row([
                                    ft.Container(width=8, height=8, bgcolor=T["GREEN"],
                                                  border_radius=2,
                                                  shadow=ft.BoxShadow(blur_radius=10,
                                                                       color=T["GREEN_G"],
                                                                       spread_radius=1)),
                                    ft.Container(width=7),
                                    ft.Text("Asystent-Rozmowy AI", size=12,
                                             weight="bold", color=T["WHITE"]),
                                ], spacing=0),
                                ft.Row([
                                    ft.Row([n_lbl, ft.Text(" analiz", size=9, color=T["DIM"])]),
                                    ft.Container(
                                        content=ft.Row([
                                            ft.Container(width=5, height=5, bgcolor=T["GREEN"],
                                                          border_radius=3),
                                            ft.Container(width=4),
                                            ft.Text("ON", size=8, color=T["GREEN"], weight="bold"),
                                        ], spacing=0),
                                        bgcolor=T["GREEN_DIM"], border_radius=20,
                                        padding=ft.padding.symmetric(horizontal=9, vertical=4),
                                        border=ft.border.all(1, T["AI_EDGE"])),
                                ], spacing=6),
                            ], alignment="spaceBetween"),
                            ft.Container(height=5),
                            ft.Row([
                                ft.Row([
                                    ft.Icon(ft.icons.PUSH_PIN_OUTLINED, size=10, color=T["DIM"]),
                                    pin_sw], spacing=0),
                                dev_btn, ft.Container(width=6), cv_btn,
                                ft.Container(expand=True),
                                theme_btn,
                                ft.IconButton(ft.icons.HELP_OUTLINE, icon_size=16,
                                               icon_color=T["GRAY"], tooltip="Instrukcja obslugi",
                                               on_click=open_help,
                                               style=ft.ButtonStyle(overlay_color=T["L3"])),
                                ft.IconButton(ft.icons.LOGOUT, icon_size=15,
                                               icon_color=T["DIM"], tooltip="Wyloguj",
                                               on_click=do_logout,
                                               style=ft.ButtonStyle(overlay_color=T["L3"])),
                                ft.IconButton(ft.icons.DELETE_SWEEP, icon_size=15,
                                               icon_color=T["DIM"], tooltip="Wyczysc",
                                               on_click=do_clear,
                                               style=ft.ButtonStyle(overlay_color=T["L3"])),
                            ], spacing=2, vertical_alignment="center"),
                        ], spacing=0),
                        bgcolor=T["L1"],
                        padding=ft.padding.only(left=12, right=8, bottom=8),
                        border=ft.border.only(bottom=ft.BorderSide(1, T["EDGE_LO"])),
                        shadow=ft.BoxShadow(blur_radius=12, color="#00000033",
                                             offset=ft.Offset(0, 2))),
                    update_banner,
                    ft.Container(content=chat, expand=True, padding=ft.padding.all(10)),
                    ft.Container(
                        content=ft.Column([
                            ft.Container(height=1, bgcolor=T["EDGE_HI"],
                                          margin=ft.margin.only(bottom=8)),
                            ft.Row([
                                ft.GestureDetector(
                                    content=ft.Container(
                                        content=ft.Text(l, size=10, color=T["GRAY"]),
                                        bgcolor=T["L3"], border_radius=14,
                                        padding=ft.padding.symmetric(horizontal=10, vertical=5),
                                        border=ft.border.all(1, T["EDGE_LO"])),
                                    on_tap=qtap(p))
                                for l, p in pills
                            ], scroll="auto", spacing=5),
                            ft.Container(height=8),
                            ft.Row([ctx, ft.Container(width=5),
                                    send_btn, ft.Container(width=5),
                                    mic_gesture],
                                   spacing=0, vertical_alignment="center"),
                            ft.Container(
                                content=ft.Row([status], alignment="center"),
                                height=16, margin=ft.margin.only(top=5)),
                            ft.Container(
                                content=ft.Text("SPACJA = mic  ·  Enter = wyslij",
                                                size=10, color=T["GRAY"], text_align="center"),
                                margin=ft.margin.only(top=3)),
                        ], spacing=0),
                        bgcolor=T["L1"],
                        padding=ft.padding.only(left=10, right=10, bottom=12),
                        border=ft.border.only(top=ft.BorderSide(1, T["EDGE_LO"])),
                        shadow=ft.BoxShadow(blur_radius=16, color="#00000033",
                                             offset=ft.Offset(0, -2))),
                ], spacing=0, expand=True),
                dev_modal,
                help_overlay,
            ]))

    # ── BOOT ───────────────────────────────────────────────────────────────────
    def boot():
        saved = load_token()
        if saved:
            data, code = api("GET", "/auth/me", token=saved["token"])
            if code == 200:
                st.update({"token": saved["token"],
                           "email": data["email"],
                           "name": data["name"],
                           "plan": data["plan"],
                           "has_sub": data["has_sub"],
                           "ok": True})
                show(app_screen() if st["has_sub"] else no_sub_screen())
                return
            clear_token()
        show(login_screen())

    # ── UPDATE BANNER ──
    update_text = ft.Text("", size=11, color="#FFD166", expand=True)
    update_dl_btn = ft.GestureDetector(
        content=ft.Container(
            content=ft.Text("Pobierz", size=11, color="#06070D", weight="bold"),
            bgcolor="#FFD166", border_radius=6,
            padding=ft.padding.symmetric(horizontal=10, vertical=4)),
        on_tap=lambda e: None)
    update_banner = ft.Container(
        visible=False,
        content=ft.Row([
            ft.Icon(ft.icons.SYSTEM_UPDATE, color="#FFD166", size=14),
            ft.Container(width=6),
            update_text,
            update_dl_btn,
            ft.Container(width=6),
            ft.GestureDetector(
                content=ft.Icon(ft.icons.CLOSE, color=T["DIM"], size=14),
                on_tap=lambda e: (
                    setattr(update_banner, "visible", False),
                    page.update())),
        ], vertical_alignment="center"),
        bgcolor="#1A1500",
        border=ft.border.only(bottom=ft.BorderSide(1, "#FFD166")),
        padding=ft.padding.symmetric(horizontal=14, vertical=8))

    def check_update_ui():
        latest, download_url = check_update()
        if not latest or not download_url:
            return
        update_text.value = f"Nowa wersja v{latest} dostepna!"
        def open_dl(e):
            import webbrowser
            webbrowser.open(download_url)
        update_dl_btn.on_tap = open_dl
        update_banner.visible = True
        try: page.update()
        except Exception: pass

    page.add(ft.Container(bgcolor=T["BASE"], expand=True,
        content=ft.Column([
            update_banner,
            ft.Container(expand=True),
            ft.Column([
                ft.ProgressRing(color=T["GREEN"], bgcolor="transparent",
                                 stroke_width=2, width=32, height=32),
                ft.Container(height=12),
                ft.Text("Laczenie...", size=12, color=T["GRAY"], text_align="center"),
            ], horizontal_alignment="center"),
            ft.Container(expand=True),
        ], horizontal_alignment="center", expand=True)))
    page.update()

    def boot_with_update():
        threading.Thread(target=check_update_ui, daemon=True).start()
        boot()

    threading.Thread(target=boot_with_update, daemon=True).start()


if __name__ == "__main__":
    ft.app(target=main)