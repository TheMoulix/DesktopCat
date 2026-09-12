"""
Desktop Cat Widget - Always-on-top animated desktop companion
Developed for Windows with Tkinter, Pillow, and pystray
"""

import os
import sys
import json
import time
import ctypes
from ctypes import wintypes
import threading
from collections import deque
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk, ImageSequence, ImageDraw
import pystray
import winreg

REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_RUN_NAME = "DesktopCat"

# --- Paths & Constants ---
if getattr(sys, "frozen", False):
    EXE_DIR = os.path.dirname(sys.executable)
    APP_DIR = EXE_DIR
    if os.path.isdir(os.path.join(EXE_DIR, "gif")):
        GIF_DIR = os.path.join(EXE_DIR, "gif")
    elif os.path.isdir(os.path.join(os.path.dirname(EXE_DIR), "gif")):
        GIF_DIR = os.path.join(os.path.dirname(EXE_DIR), "gif")
    elif hasattr(sys, "_MEIPASS") and os.path.isdir(os.path.join(sys._MEIPASS, "gif")):
        GIF_DIR = os.path.join(sys._MEIPASS, "gif")
    else:
        GIF_DIR = os.path.join(EXE_DIR, "gif")
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    GIF_DIR = os.path.join(APP_DIR, "gif")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
try:
    os.chdir(APP_DIR)
except Exception:
    pass

STARTUP_DIR = os.path.join(
    os.environ.get("APPDATA", ""),
    r"Microsoft\Windows\Start Menu\Programs\Startup"
)
STARTUP_LINK = os.path.join(STARTUP_DIR, "DesktopCat.vbs")

COLOR_KEY = "#000001"  # Windows colorkey for transparency
COLOR_KEY_RGB = (0, 0, 1)

# Win32 Constants
SPI_GETWORKAREA = 0x0030
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010

# Win32 Structures & API
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

user32 = ctypes.windll.user32
try:
    hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if hdesk:
        user32.SetThreadDesktop(hdesk)
except Exception:
    pass

SetWindowLongPtr = user32.SetWindowLongPtrW
SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
SetWindowLongPtr.restype = ctypes.c_ssize_t

GetWindowLongPtr = user32.GetWindowLongPtrW
GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
GetWindowLongPtr.restype = ctypes.c_ssize_t

SetWindowPos = user32.SetWindowPos
SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT
]

# Friendly names for default GIF collection
KNOWN_CATS = {
    "ca6c744333366d89b3824449cb844c2e.gif": "🐱 Dancing Cat (Happy)",
    "30c210344bbbcde4d5542c02a0cb908b.gif": "🐱 Maxwell Cat",
    "644b88254ec38a97c422ce861ddcaea2.gif": "🐱 Pop Cat",
    "e241a7e78b9d769eceda182dfe42f92f.gif": "🐱 Clapping Cat (Oiia)",
    "51cc28f22e434cdc530912ee0f116f22.gif": "🐱 Chipi Cat",
}


def get_work_area():
    """Retrieve desktop working area excluding the Windows taskbar, with fallback for early boot."""
    rect = RECT()
    success = user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    if not success or rect.right <= rect.left or rect.bottom <= rect.top:
        sw = user32.GetSystemMetrics(0) or 1920
        sh = user32.GetSystemMetrics(1) or 1080
        return 0, 0, sw, sh
    return rect.left, rect.top, rect.right, rect.bottom


class DesktopCatApp:
    def __init__(self):
        # Prevent multiple duplicate instances cleanly
        self.lock_file = os.path.join(APP_DIR, ".cat_instance.lock")
        self._check_single_instance()

        # If autostart was previously enabled, ensure registry points to current path
        self._sync_autostart_path()

        self.root = tk.Tk()
        self.root.title("Desktop Cat Overlay")
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", COLOR_KEY)
        self.root.config(bg=COLOR_KEY)

        # Settings
        self.config = self.load_config()
        self.scale = self.config.get("scale", 1.0)
        self.cutout = self.config.get("cutout", True)
        self.locked = self.config.get("locked", False)
        self.current_gif = self.config.get("current_cat", "ca6c744333366d89b3824449cb844c2e.gif")
        self.saved_pos = self.config.get("position", None)
        self.current_w = 180
        self.current_h = 180

        # State
        self.frames = []
        self.durations = []
        self.frame_index = 0
        self.anim_job = None
        self.is_loading = False
        self.load_token = 0
        self.animation_cache = {}

        # Dragging state
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.is_dragging = False

        # Canvas for rendering
        self.canvas = tk.Canvas(self.root, bg=COLOR_KEY, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas_image_id = None

        # Bind events
        self.canvas.bind("<ButtonPress-1>", self.on_drag_start)
        self.canvas.bind("<B1-Motion>", self.on_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_drag_release)
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.canvas.bind("<Button-3>", self.show_context_menu)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)

        # Build context menu
        self.build_context_menu()

        # Load first cat animation
        self.load_cat(self.current_gif, initial=True)
        self.save_config()

        # Periodic check to ensure window stays topmost
        self.ensure_topmost()

        # Setup system tray icon
        self.tray_icon = None
        self.setup_tray()

    def _check_single_instance(self):
        """Cleanly terminate older instance if running, to ensure fresh instance always opens."""
        try:
            if os.path.exists(self.lock_file):
                with open(self.lock_file, "r") as f:
                    old_pid = int(f.read().strip())
                if old_pid != os.getpid():
                    try:
                        import signal
                        os.kill(old_pid, signal.SIGTERM)
                        time.sleep(0.2)
                    except Exception:
                        pass
        except Exception:
            pass

        # Write current PID to lock file
        try:
            with open(self.lock_file, "w") as f:
                f.write(str(os.getpid()))
        except Exception:
            pass

    def _sync_autostart_path(self):
        """If autostart is enabled, ensure the command points to the current executable path."""
        try:
            if self.is_autostart_enabled():
                current_cmd = self.get_autostart_command()
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_READ)
                val, _ = winreg.QueryValueEx(key, REG_RUN_NAME)
                winreg.CloseKey(key)
                if val != current_cmd:
                    wkey = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_SET_VALUE)
                    winreg.SetValueEx(wkey, REG_RUN_NAME, 0, winreg.REG_SZ, current_cmd)
                    winreg.CloseKey(wkey)
        except Exception:
            pass

        # Always remove any legacy DesktopCat.vbs if found in Startup folder
        try:
            if os.path.exists(STARTUP_LINK):
                os.remove(STARTUP_LINK)
        except Exception:
            pass

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_config(self):
        data = {
            "current_cat": self.current_gif,
            "scale": round(self.scale, 2),
            "cutout": self.cutout,
            "locked": self.locked,
            "position": self.saved_pos,
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get_available_gifs(self):
        """List all available GIF files in the gif directory."""
        gifs = []
        if os.path.isdir(GIF_DIR):
            for fname in os.listdir(GIF_DIR):
                if fname.lower().endswith(".gif"):
                    label = KNOWN_CATS.get(fname, f"🐱 {fname}")
                    gifs.append((fname, label))
        return gifs

    def build_context_menu(self):
        self.context_menu = tk.Menu(self.root, tearoff=0)

        # 1. Cats submenu
        self.cats_menu = tk.Menu(self.context_menu, tearoff=0)
        self.context_menu.add_cascade(label="🐱 Select Cat", menu=self.cats_menu)

        # 2. Scale submenu
        self.scale_menu = tk.Menu(self.context_menu, tearoff=0)
        for s_label, s_val in [
            ("50%  (Mini)", 0.5),
            ("75%  (Small)", 0.75),
            ("100% (Normal)", 1.0),
            ("125% (Medium)", 1.25),
            ("150% (Large)", 1.5),
            ("200% (Max)", 2.0),
        ]:
            self.scale_menu.add_command(
                label=s_label,
                command=lambda v=s_val: self.set_scale(v)
            )
        self.context_menu.add_cascade(label="📏 Size", menu=self.scale_menu)

        # 3. Cutout toggle
        self.cutout_var = tk.BooleanVar(value=self.cutout)
        self.context_menu.add_checkbutton(
            label="✨ Transparent Background (Cutout)",
            variable=self.cutout_var,
            command=self.toggle_cutout
        )

        # 4. Snap back to bottom-right
        self.context_menu.add_command(
            label="📍 Snap to Bottom-Right Corner",
            command=self.snap_to_corner
        )

        # 5. Lock position
        self.locked_var = tk.BooleanVar(value=self.locked)
        self.context_menu.add_checkbutton(
            label="🔒 Lock in Place (Fix position)",
            variable=self.locked_var,
            command=self.toggle_lock
        )

        # 6. Autostart toggle
        self.autostart_var = tk.BooleanVar(value=self.is_autostart_enabled())
        self.context_menu.add_checkbutton(
            label="🚀 Start with Windows",
            variable=self.autostart_var,
            command=self.toggle_autostart
        )

        self.context_menu.add_separator()

        # 7. Open GIF folder
        self.context_menu.add_command(
            label="📂 Open GIF Folder...",
            command=self.open_gif_folder
        )

        # 8. Exit
        self.context_menu.add_command(
            label="❌ Exit",
            command=self.quit_app
        )

    def refresh_cats_menu(self):
        """Populate the cats submenu with currently available gifs."""
        self.cats_menu.delete(0, tk.END)
        for fname, label in self.get_available_gifs():
            prefix = "✓ " if fname == self.current_gif else "   "
            self.cats_menu.add_command(
                label=f"{prefix}{label}",
                command=lambda fn=fname: self.switch_cat(fn)
            )

    def show_context_menu(self, event):
        self.refresh_cats_menu()
        self.cutout_var.set(self.cutout)
        self.locked_var.set(self.locked)
        self.autostart_var.set(self.is_autostart_enabled())
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    # --- Loading & Animation Processing ---
    def load_cat(self, gif_filename, initial=False):
        gif_path = os.path.join(GIF_DIR, gif_filename)
        if not os.path.exists(gif_path):
            # fallback to first available gif
            avail = self.get_available_gifs()
            if avail:
                gif_filename = avail[0][0]
                gif_path = os.path.join(GIF_DIR, gif_filename)
            else:
                return

        self.current_gif = gif_filename
        self.load_token += 1
        current_token = self.load_token

        # Stop existing animation
        if self.anim_job:
            self.root.after_cancel(self.anim_job)
            self.anim_job = None

        # Calculate dimensions (base height is 180px)
        base_h = int(180 * self.scale)
        try:
            sample_im = Image.open(gif_path)
            orig_w, orig_h = sample_im.size
            aspect = orig_w / orig_h
            w = max(40, int(base_h * aspect))
            h = max(40, base_h)
        except Exception:
            return

        cache_key = (self.current_gif, w, h, self.cutout)
        if cache_key in self.animation_cache:
            cached_frames, cached_durations = self.animation_cache[cache_key]
            self.frames = cached_frames
            self.durations = cached_durations
            self.frame_index = 0
            self._update_display(w, h, initial=initial)
            return

        # Prepare first frame quickly on main thread for instant feedback
        try:
            sample_im.seek(0)
            quick_frame = self._process_frame(sample_im, w, h, self.cutout)
            tk_quick = ImageTk.PhotoImage(quick_frame)
            self.frames = [tk_quick]
            self.durations = [sample_im.info.get("duration", 50) or 50]
            self.frame_index = 0
            self._update_display(w, h, initial=initial)
        except Exception:
            try:
                sample_im.seek(0)
                raw_frame = sample_im.convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
                bg = Image.new("RGBA", (w, h), COLOR_KEY_RGB + (255,))
                comp = Image.alpha_composite(bg, raw_frame).convert("RGB")
                tk_raw = ImageTk.PhotoImage(comp)
                self.frames = [tk_raw]
                self.durations = [50]
                self.frame_index = 0
                self._update_display(w, h, initial=initial)
            except Exception:
                pass

        # Load remaining frames in background thread
        def background_worker():
            try:
                full_im = Image.open(gif_path)
                bg_frames = []
                bg_durations = []

                for frame in ImageSequence.Iterator(full_im):
                    if self.load_token != current_token:
                        return
                    processed = self._process_frame(frame, w, h, self.cutout)
                    bg_frames.append(processed)
                    dur = frame.info.get("duration", 50)
                    if not dur or dur < 20:
                        dur = 50
                    bg_durations.append(dur)

                if self.load_token == current_token and bg_frames:
                    self.root.after(0, lambda: self._apply_loaded_frames(current_token, bg_frames, bg_durations, w, h, cache_key))
            except Exception as e:
                print(f"Error loading frames: {e}")

        t = threading.Thread(target=background_worker, daemon=True)
        t.start()

    def _smart_cutout(self, f, w, h):
        """Intelligently removes white/black backgrounds, compression artifacts, and dust."""
        pix = f.load()

        # 1. Native transparency check
        alpha_zeros = sum(1 for y in range(0, h, 4) for x in range(0, w, 4) if pix[x, y][3] == 0)
        total_samples = (h // 4 + 1) * (w // 4 + 1)
        if total_samples > 0 and (alpha_zeros / total_samples) > 0.15:
            return f

        # 2. Determine background type (Light vs Dark)
        border_samples = []
        for x in range(0, w, 4):
            border_samples.append(pix[x, 0][:3])
            border_samples.append(pix[x, min(h - 1, 10)][:3])
        for y in range(0, h, 4):
            border_samples.append(pix[0, y][:3])
            border_samples.append(pix[w - 1, y][:3])

        avg_brightness = sum(sum(p) for p in border_samples) / (len(border_samples) * 3)
        is_light_bg = avg_brightness > 135

        is_popcat = "644b" in self.current_gif
        max_y = h - 2 if is_popcat else h

        visited_bg = [False] * (w * h)
        queue = deque()

        def is_bg_pixel(p):
            if is_light_bg:
                # White, off-white, light gray compression artifacts
                return p[0] > 185 and p[1] > 185 and p[2] > 185
            else:
                # Dark background / dark vignette
                return max(p[:3]) < 120 or sum(p[:3]) < 260

        # Seed outer borders
        for x in range(w):
            for y in (0, max_y - 1):
                idx = y * w + x
                if not visited_bg[idx] and is_bg_pixel(pix[x, y]):
                    visited_bg[idx] = True
                    queue.append((x, y))
        for y in range(max_y):
            for x in (0, w - 1):
                idx = y * w + x
                if not visited_bg[idx] and is_bg_pixel(pix[x, y]):
                    visited_bg[idx] = True
                    queue.append((x, y))

        while queue:
            cx, cy = queue.popleft()
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                if 0 <= nx < w and 0 <= ny < max_y:
                    nidx = ny * w + nx
                    if not visited_bg[nidx] and is_bg_pixel(pix[nx, ny]):
                        visited_bg[nidx] = True
                        queue.append((nx, ny))

        # Filter out background and tiny film dust/specks
        island_visited = [False] * (w * h)
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out_pix = out.load()

        for y in range(max_y):
            for x in range(w):
                idx = y * w + x
                if not visited_bg[idx] and not island_visited[idx]:
                    island = []
                    island_visited[idx] = True
                    iq = deque([(x, y)])
                    while iq:
                        ix, iy = iq.popleft()
                        island.append((ix, iy))
                        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                            jx, jy = ix + dx, iy + dy
                            if 0 <= jx < w and 0 <= jy < max_y:
                                jidx = jy * w + jx
                                if not visited_bg[jidx] and not island_visited[jidx]:
                                    island_visited[jidx] = True
                                    iq.append((jx, jy))
                    # Keep islands >= 30 pixels (cat body, paws, hands)
                    if len(island) >= 30:
                        for ix, iy in island:
                            out_pix[ix, iy] = pix[ix, iy]

        return out

    def _process_frame(self, frame, w, h, cutout):
        f = frame.convert("RGBA")
        f = f.resize((w, h), Image.Resampling.LANCZOS)

        if cutout:
            try:
                f = self._smart_cutout(f, w, h)
            except Exception as e:
                print(f"Cutout error: {e}")

        # Composite onto colorkey (0, 0, 1)
        bg = Image.new("RGBA", (w, h), COLOR_KEY_RGB + (255,))
        comp = Image.alpha_composite(bg, f)
        return comp.convert("RGB")

    def _apply_loaded_frames(self, token, pil_frames, durations, w, h, cache_key=None):
        if self.load_token != token:
            return
        self.frames = [ImageTk.PhotoImage(img) for img in pil_frames]
        self.durations = durations
        if cache_key:
            if len(self.animation_cache) > 12:
                self.animation_cache.clear()
            self.animation_cache[cache_key] = (self.frames, self.durations)
        self.frame_index = 0
        if self.frames and self.canvas_image_id is not None:
            self.canvas.itemconfig(self.canvas_image_id, image=self.frames[0])
            self.canvas.image = self.frames[0]
        if not self.anim_job:
            self.animate_step()

    def _update_display(self, w, h, initial=False):
        self.current_w = w
        self.current_h = h
        self.canvas.config(width=w, height=h)
        if self.canvas_image_id is None:
            self.canvas_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.frames[0])
        else:
            self.canvas.itemconfig(self.canvas_image_id, image=self.frames[0])
        self.canvas.image = self.frames[0]

        # Position window
        wl, wt, wr, wb = get_work_area()
        if self.saved_pos and len(self.saved_pos) == 2:
            cur_x, cur_y = self.saved_pos
            if not initial:
                old_h = self.root.winfo_height()
                if old_h > 1:
                    cur_y = cur_y + old_h - h
            # Boundary guard: ensure window is always visible inside work area
            cur_x = max(wl, min(cur_x, wr - w))
            cur_y = max(wt, min(cur_y, wb - h))
        else:
            cur_x = wr - w - 15
            cur_y = wb - h

        self.root.geometry(f"{w}x{h}+{cur_x}+{cur_y}")
        try:
            hwnd = self.root.winfo_id()
            SetWindowPos(hwnd, HWND_TOPMOST, cur_x, cur_y, w, h, SWP_NOACTIVATE)
        except Exception:
            pass
        self.root.lift()

        if not self.anim_job and len(self.frames) > 0:
            self.animate_step()

    def animate_step(self):
        if not self.frames:
            return
        self.frame_index = (self.frame_index + 1) % len(self.frames)
        self.canvas.itemconfig(self.canvas_image_id, image=self.frames[self.frame_index])
        self.canvas.image = self.frames[self.frame_index]
        dur = self.durations[self.frame_index] if self.frame_index < len(self.durations) else 50
        self.anim_job = self.root.after(dur, self.animate_step)

    # --- Interaction Handlers ---
    def on_drag_start(self, event):
        if self.locked:
            return
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.is_dragging = True

    def on_drag_motion(self, event):
        if self.locked or not self.is_dragging:
            return
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y
        new_x = self.root.winfo_x() + dx
        new_y = self.root.winfo_y() + dy
        self.root.geometry(f"+{new_x}+{new_y}")

    def on_drag_release(self, event):
        if self.locked or not self.is_dragging:
            return
        self.is_dragging = False
        self.saved_pos = [self.root.winfo_x(), self.root.winfo_y()]
        self.save_config()

    def on_double_click(self, event):
        """Double click resets cat back to bottom-right corner."""
        self.snap_to_corner()

    def on_mouse_wheel(self, event):
        """Scroll wheel zooms cat in / out smoothly."""
        if event.delta > 0:
            new_scale = min(3.0, self.scale + 0.1)
        else:
            new_scale = max(0.4, self.scale - 0.1)
        if abs(new_scale - self.scale) > 0.01:
            self.set_scale(round(new_scale, 2))

    def snap_to_corner(self):
        """Positions cat directly above taskbar in the bottom-right corner."""
        wl, wt, wr, wb = get_work_area()
        new_x = wr - self.current_w - 15
        new_y = wb - self.current_h
        self.saved_pos = None  # None means keep locked to corner
        self.save_config()
        self.root.geometry(f"{self.current_w}x{self.current_h}+{new_x}+{new_y}")
        try:
            hwnd = self.root.winfo_id()
            SetWindowPos(hwnd, HWND_TOPMOST, new_x, new_y, self.current_w, self.current_h, SWP_NOACTIVATE)
        except Exception:
            pass
        self.root.lift()

    def toggle_lock(self):
        self.locked = not self.locked
        self.save_config()
        if hasattr(self, "locked_var"):
            self.locked_var.set(self.locked)

    def switch_cat(self, gif_filename):
        self.load_cat(gif_filename)
        self.save_config()

    def set_scale(self, new_scale):
        self.scale = new_scale
        self.load_cat(self.current_gif)
        self.save_config()

    def toggle_cutout(self):
        self.cutout = not self.cutout
        self.load_cat(self.current_gif)
        self.save_config()

    def get_autostart_command(self):
        """Returns the appropriate command string to launch DesktopCat on startup."""
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        else:
            pyw_exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if not os.path.exists(pyw_exe):
                pyw_exe = sys.executable
            return f'"{pyw_exe}" "{os.path.abspath(__file__)}"'

    def is_autostart_enabled(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, REG_RUN_NAME)
            winreg.CloseKey(key)
            return True
        except Exception:
            return False

    def toggle_autostart(self):
        enabled = not self.is_autostart_enabled()
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_SET_VALUE)
            if enabled:
                cmd = self.get_autostart_command()
                winreg.SetValueEx(key, REG_RUN_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, REG_RUN_NAME)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            pass

        # Clean up any legacy DesktopCat.vbs in Startup folder
        try:
            if os.path.exists(STARTUP_LINK):
                os.remove(STARTUP_LINK)
        except Exception:
            pass

        if hasattr(self, "autostart_var"):
            self.autostart_var.set(self.is_autostart_enabled())

    def open_gif_folder(self):
        os.makedirs(GIF_DIR, exist_ok=True)
        os.startfile(GIF_DIR)

    def ensure_topmost(self):
        """Keep the window topmost over newly opened windows."""
        try:
            hwnd = self.root.winfo_id()
            SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass
        self.root.after(1500, self.ensure_topmost)

    # --- System Tray Integration ---
    def setup_tray(self):
        def tray_worker():
            # Generate cute cat tray icon
            icon_img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(icon_img)
            # Draw cute cat face
            draw.ellipse((8, 14, 56, 58), fill=(255, 170, 80, 255), outline=(220, 130, 40, 255), width=2)
            draw.polygon([(12, 22), (20, 6), (28, 16)], fill=(255, 170, 80, 255))
            draw.polygon([(52, 22), (44, 6), (36, 16)], fill=(255, 170, 80, 255))
            # Eyes & nose
            draw.ellipse((20, 28, 26, 36), fill=(40, 40, 40, 255))
            draw.ellipse((38, 28, 44, 36), fill=(40, 40, 40, 255))
            draw.polygon([(30, 38), (34, 38), (32, 42)], fill=(255, 100, 120, 255))

            def make_tray_menu():
                cat_items = []
                for fname, label in self.get_available_gifs():
                    def switch_action(f_name):
                        return lambda icon, item: self.root.after(0, lambda: self.switch_cat(f_name))
                    cat_items.append(
                        pystray.MenuItem(
                            label,
                            switch_action(fname),
                            checked=lambda item, fn=fname: fn == self.current_gif
                        )
                    )

                scale_items = []
                for s_label, s_val in [
                    ("50%", 0.5), ("75%", 0.75), ("100%", 1.0),
                    ("125%", 1.25), ("150%", 1.5), ("200%", 2.0)
                ]:
                    def scale_action(val):
                        return lambda icon, item: self.root.after(0, lambda: self.set_scale(val))
                    scale_items.append(
                        pystray.MenuItem(
                            s_label,
                            scale_action(s_val),
                            checked=lambda item, v=s_val: abs(self.scale - v) < 0.05
                        )
                    )

                return pystray.Menu(
                    pystray.MenuItem("🐱 Select Cat", pystray.Menu(*cat_items)),
                    pystray.MenuItem("📏 Size", pystray.Menu(*scale_items)),
                    pystray.MenuItem(
                        "✨ Transparent Background",
                        lambda icon, item: self.root.after(0, self.toggle_cutout),
                        checked=lambda item: self.cutout
                    ),
                    pystray.MenuItem(
                        "📍 Snap to Corner",
                        lambda icon, item: self.root.after(0, self.snap_to_corner)
                    ),
                    pystray.MenuItem(
                        "🔒 Lock in Place",
                        lambda icon, item: self.root.after(0, self.toggle_lock),
                        checked=lambda item: self.locked
                    ),
                    pystray.MenuItem(
                        "🚀 Start with Windows",
                        lambda icon, item: self.root.after(0, self.toggle_autostart),
                        checked=lambda item: self.is_autostart_enabled()
                    ),
                    pystray.MenuItem(
                        "📂 Open GIF Folder",
                        lambda icon, item: self.root.after(0, self.open_gif_folder)
                    ),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        "❌ Exit",
                        lambda icon, item: self.root.after(0, self.quit_app)
                    ),
                )

            self.tray_icon = pystray.Icon(
                "DesktopCat",
                icon_img,
                "Desktop Cat",
                menu=make_tray_menu()
            )
            for _ in range(5):
                try:
                    self.tray_icon.run()
                    break
                except Exception:
                    time.sleep(2)

        t = threading.Thread(target=tray_worker, daemon=True)
        t.start()

    def quit_app(self):
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        try:
            if os.path.exists(self.lock_file):
                os.remove(self.lock_file)
        except Exception:
            pass
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()


DesktopCatAppWindows = DesktopCatApp


if __name__ == "__main__":
    app = DesktopCatApp()
    app.run()

