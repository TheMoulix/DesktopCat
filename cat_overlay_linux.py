"""
Desktop Cat Widget - Always-on-top animated desktop companion for Linux
Developed with GTK 3, Cairo, Pillow, and AppIndicator3.
"""

import os
import sys
import json
import time
import signal
import threading
import subprocess
from collections import deque
from PIL import Image, ImageSequence

# Ensure X11/XWayland backend for reliable positioning & transparency on Wayland compositors
if "GDK_BACKEND" not in os.environ and os.environ.get("DISPLAY"):
    os.environ["GDK_BACKEND"] = "x11"

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
import cairo

try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3
    HAVE_APPINDICATOR = True
except Exception:
    HAVE_APPINDICATOR = False

# Paths & Directories
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

GIF_DIR = os.path.join(APP_DIR, "gif")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
LOCK_FILE = os.path.join(APP_DIR, ".cat_instance.lock")
ICON_PNG = os.path.join(APP_DIR, "app_icon.png")
ICON_ICO = os.path.join(APP_DIR, "app_icon.ico")
START_SH = os.path.join(APP_DIR, "start.sh")

AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
AUTOSTART_DESKTOP = os.path.join(AUTOSTART_DIR, "DesktopCat.desktop")

# Default friendly names for iconic GIFs
KNOWN_CATS = {
    "ca6c744333366d89b3824449cb844c2e.gif": "🐱 Dancing Cat (Happy)",
    "30c210344bbbcde4d5542c02a0cb908b.gif": "🐱 Maxwell Cat",
    "644b88254ec38a97c422ce861ddcaea2.gif": "🐱 Pop Cat",
    "e241a7e78b9d769eceda182dfe42f92f.gif": "🐱 Clapping Cat (Oiia)",
    "51cc28f22e434cdc530912ee0f116f22.gif": "🐱 Chipi Cat",
}


def ensure_png_icon():
    """Ensure a PNG icon exists for the Linux system tray and desktop launcher."""
    if not os.path.exists(ICON_PNG) and os.path.exists(ICON_ICO):
        try:
            im = Image.open(ICON_ICO)
            im.save(ICON_PNG)
        except Exception:
            pass


class DesktopCatAppLinux:
    def __init__(self):
        self.lock_file = LOCK_FILE
        self._check_single_instance()

        ensure_png_icon()

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
        self.load_token = 0
        self.animation_cache = {}

        # Dragging state
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.win_start_x = 0
        self.win_start_y = 0
        self.is_dragging = False

        # Setup GTK Window
        self.win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.win.set_title("Desktop Cat Overlay")
        self.win.set_role("DesktopCatOverlay")
        self.win.set_decorated(False)
        self.win.set_keep_above(True)
        self.win.set_skip_taskbar_hint(True)
        self.win.set_skip_pager_hint(True)
        self.win.set_app_paintable(True)
        self.win.connect("delete-event", self.quit_app)

        # Set transparent visual
        screen = self.win.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.win.set_visual(visual)

        # CSS transparency
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"window, drawingarea { background-color: transparent; }")
        Gtk.StyleContext.add_provider_for_screen(
            screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # DrawingArea for rendering frames and capturing events
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.SMOOTH_SCROLL_MASK
        )
        self.drawing_area.connect("draw", self.on_draw)
        self.drawing_area.connect("button-press-event", self.on_button_press)
        self.drawing_area.connect("button-release-event", self.on_button_release)
        self.drawing_area.connect("motion-notify-event", self.on_motion_notify)
        self.drawing_area.connect("scroll-event", self.on_scroll)
        self.win.add(self.drawing_area)

        # Periodic check to ensure window stays topmost
        GLib.timeout_add(1500, self.ensure_topmost)

        # Setup tray
        self.tray_indicator = None
        self.setup_tray()

        # Load first cat animation
        self.load_cat(self.current_gif, initial=True)
        self.save_config()

        # Show window
        self.win.show_all()

    def _check_single_instance(self):
        """Cleanly terminate older instance if running, to ensure fresh instance always opens."""
        try:
            if os.path.exists(self.lock_file):
                with open(self.lock_file, "r") as f:
                    old_pid = int(f.read().strip())
                if old_pid != os.getpid():
                    try:
                        os.kill(old_pid, signal.SIGTERM)
                        time.sleep(0.2)
                    except (ProcessLookupError, PermissionError):
                        pass
        except Exception:
            pass

        try:
            with open(self.lock_file, "w") as f:
                f.write(str(os.getpid()))
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
            for fname in sorted(os.listdir(GIF_DIR)):
                if fname.lower().endswith(".gif"):
                    label = KNOWN_CATS.get(fname, f"🐱 {fname}")
                    gifs.append((fname, label))
        return gifs

    def get_work_area(self):
        """Retrieve screen working area excluding panels / taskbars."""
        display = Gdk.Display.get_default()
        if display:
            seat = display.get_default_seat()
            pointer = seat.get_pointer() if seat else None
            mon = None
            if pointer:
                _, px, py = pointer.get_position()
                mon = display.get_monitor_at_point(px, py)
            if not mon:
                mon = display.get_primary_monitor() or display.get_monitor(0)
            if mon:
                work = mon.get_workarea()
                if work.width > 0 and work.height > 0:
                    return work.x, work.y, work.x + work.width, work.y + work.height
                geom = mon.get_geometry()
                return geom.x, geom.y, geom.x + geom.width, geom.y + geom.height
        return 0, 0, 1920, 1080

    # --- Loading & Animation Processing ---
    def load_cat(self, gif_filename, initial=False):
        gif_path = os.path.join(GIF_DIR, gif_filename)
        if not os.path.exists(gif_path):
            avail = self.get_available_gifs()
            if avail:
                gif_filename = avail[0][0]
                gif_path = os.path.join(GIF_DIR, gif_filename)
            else:
                return

        self.current_gif = gif_filename
        self.load_token += 1
        current_token = self.load_token

        if self.anim_job:
            GLib.source_remove(self.anim_job)
            self.anim_job = None

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

        # Prepare first frame synchronously for instant responsiveness
        try:
            sample_im.seek(0)
            quick_surf = self._process_frame(sample_im, w, h, self.cutout)
            self.frames = [quick_surf]
            self.durations = [sample_im.info.get("duration", 50) or 50]
            self.frame_index = 0
            self._update_display(w, h, initial=initial)
        except Exception:
            pass

        # Decode remaining frames asynchronously in background
        def background_worker():
            try:
                full_im = Image.open(gif_path)
                bg_frames = []
                bg_durations = []

                for frame in ImageSequence.Iterator(full_im):
                    if self.load_token != current_token:
                        return
                    processed_surf = self._process_frame(frame, w, h, self.cutout)
                    bg_frames.append(processed_surf)
                    dur = frame.info.get("duration", 50)
                    if not dur or dur < 20:
                        dur = 50
                    bg_durations.append(dur)

                if self.load_token == current_token and bg_frames:
                    GLib.idle_add(
                        self._apply_loaded_frames,
                        current_token,
                        bg_frames,
                        bg_durations,
                        w,
                        h,
                        cache_key,
                    )
            except Exception as e:
                print(f"Error loading frames: {e}")

        t = threading.Thread(target=background_worker, daemon=True)
        t.start()

    def _smart_cutout(self, f, w, h):
        """Intelligently removes white/black backgrounds, compression artifacts, and dust specks."""
        pix = f.load()

        # 1. Native transparency check
        alpha_zeros = sum(1 for y in range(0, h, 4) for x in range(0, w, 4) if pix[x, y][3] == 0)
        total_samples = (h // 4 + 1) * (w // 4 + 1)
        if total_samples > 0 and (alpha_zeros / total_samples) > 0.15:
            return f

        # 2. Determine background brightness
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
                return p[0] > 185 and p[1] > 185 and p[2] > 185
            else:
                return max(p[:3]) < 120 or sum(p[:3]) < 260

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

        raw = f.tobytes()
        gbytes = GLib.Bytes.new(raw)
        pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
            gbytes, GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4
        )
        return Gdk.cairo_surface_create_from_pixbuf(pixbuf, 0, None)

    def _apply_loaded_frames(self, token, bg_surfaces, durations, w, h, cache_key):
        if self.load_token != token:
            return
        self.frames = bg_surfaces
        self.durations = durations
        if cache_key:
            if len(self.animation_cache) > 12:
                self.animation_cache.clear()
            self.animation_cache[cache_key] = (self.frames, self.durations)
        self.frame_index = 0
        self.drawing_area.queue_draw()
        if not self.anim_job:
            self.animate_step()

    def _update_display(self, w, h, initial=False):
        self.current_w = w
        self.current_h = h
        self.drawing_area.set_size_request(w, h)
        self.win.resize(w, h)

        wl, wt, wr, wb = self.get_work_area()
        if self.saved_pos and len(self.saved_pos) == 2:
            cur_x, cur_y = self.saved_pos
            if not initial:
                old_w, old_h = self.win.get_size()
                if old_h > 1:
                    cur_y = cur_y + old_h - h
            cur_x = max(wl, min(cur_x, wr - w))
            cur_y = max(wt, min(cur_y, wb - h))
        else:
            cur_x = wr - w - 15
            cur_y = wb - h

        self.win.move(cur_x, cur_y)
        self.win.set_keep_above(True)
        self.drawing_area.queue_draw()

        if not self.anim_job and len(self.frames) > 0:
            self.animate_step()

    def on_draw(self, widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()

        if self.frames and self.frame_index < len(self.frames):
            surf = self.frames[self.frame_index]
            if surf:
                cr.set_operator(cairo.OPERATOR_OVER)
                cr.set_source_surface(surf, 0, 0)
                cr.paint()
        return False

    def animate_step(self):
        if not self.frames:
            return False
        self.frame_index = (self.frame_index + 1) % len(self.frames)
        self.drawing_area.queue_draw()
        dur = self.durations[self.frame_index] if self.frame_index < len(self.durations) else 50
        self.anim_job = GLib.timeout_add(dur, self.animate_step)
        return False

    # --- Mouse & Interaction Handlers ---
    def on_button_press(self, widget, event):
        double_click_type = getattr(Gdk.EventType, "2BUTTON_PRESS", 5)
        if event.type == double_click_type and event.button == 1:
            self.snap_to_corner()
            return True

        if event.button == 1:
            if not self.locked:
                self.is_dragging = True
                self.drag_start_x = event.x_root
                self.drag_start_y = event.y_root
                cur_x, cur_y = self.win.get_position()
                self.win_start_x = cur_x
                self.win_start_y = cur_y
            return True
        elif event.button == 3:
            self.show_context_menu(event)
            return True
        return False

    def on_motion_notify(self, widget, event):
        if self.is_dragging and not self.locked:
            dx = int(event.x_root - self.drag_start_x)
            dy = int(event.y_root - self.drag_start_y)
            self.win.move(self.win_start_x + dx, self.win_start_y + dy)
        return True

    def on_button_release(self, widget, event):
        if event.button == 1 and self.is_dragging:
            self.is_dragging = False
            cur_x, cur_y = self.win.get_position()
            self.saved_pos = [cur_x, cur_y]
            self.save_config()
        return True

    def on_scroll(self, widget, event):
        if event.direction == Gdk.ScrollDirection.UP:
            new_scale = min(3.0, self.scale + 0.1)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            new_scale = max(0.4, self.scale - 0.1)
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            _, dy = event.get_scroll_deltas()
            if dy < 0:
                new_scale = min(3.0, self.scale + 0.1)
            else:
                new_scale = max(0.4, self.scale - 0.1)
        else:
            return False

        if abs(new_scale - self.scale) > 0.01:
            self.set_scale(round(new_scale, 2))
        return True

    def snap_to_corner(self):
        """Positions cat directly above taskbar in the bottom-right corner."""
        wl, wt, wr, wb = self.get_work_area()
        new_x = wr - self.current_w - 15
        new_y = wb - self.current_h
        self.saved_pos = None
        self.save_config()
        self.win.move(new_x, new_y)
        self.win.set_keep_above(True)

    def set_scale(self, new_scale):
        self.scale = new_scale
        self.load_cat(self.current_gif)
        self.save_config()
        self.update_tray_menu()

    def set_cutout(self, val):
        if self.cutout != val:
            self.cutout = val
            self.load_cat(self.current_gif)
            self.save_config()
            self.update_tray_menu()

    def set_locked(self, val):
        self.locked = val
        self.save_config()
        self.update_tray_menu()

    def switch_cat(self, gif_filename):
        self.load_cat(gif_filename)
        self.save_config()
        self.update_tray_menu()

    def open_gif_folder(self):
        os.makedirs(GIF_DIR, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", GIF_DIR])
        except Exception:
            pass

    def ensure_topmost(self):
        try:
            self.win.set_keep_above(True)
        except Exception:
            pass
        return True

    # --- Autostart ---
    def is_autostart_enabled(self):
        return os.path.exists(AUTOSTART_DESKTOP)

    def set_autostart(self, enabled):
        if enabled:
            os.makedirs(AUTOSTART_DIR, exist_ok=True)
            desktop_content = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=DesktopCat
Comment=Always-on-top animated desktop companion
Exec="{START_SH}"
Icon={ICON_PNG}
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
"""
            try:
                with open(AUTOSTART_DESKTOP, "w", encoding="utf-8") as f:
                    f.write(desktop_content)
                os.chmod(AUTOSTART_DESKTOP, 0o755)
            except Exception as e:
                print(f"Error enabling autostart: {e}")
        else:
            try:
                if os.path.exists(AUTOSTART_DESKTOP):
                    os.remove(AUTOSTART_DESKTOP)
            except Exception as e:
                print(f"Error disabling autostart: {e}")
        self.update_tray_menu()

    # --- Menus & Tray ---
    def build_menu(self, is_tray=False):
        menu = Gtk.Menu()

        # 1. Select Cat submenu
        cats_submenu = Gtk.Menu()
        for fname, label in self.get_available_gifs():
            prefix = "✓ " if fname == self.current_gif else "   "
            item = Gtk.MenuItem(label=f"{prefix}{label}")
            item.connect("activate", lambda w, fn=fname: self.switch_cat(fn))
            cats_submenu.append(item)
        cats_item = Gtk.MenuItem(label="🐱 Select Cat")
        cats_item.set_submenu(cats_submenu)
        menu.append(cats_item)

        # 2. Size submenu
        scale_submenu = Gtk.Menu()
        for s_label, s_val in [
            ("50%  (Mini)", 0.5),
            ("75%  (Small)", 0.75),
            ("100% (Normal)", 1.0),
            ("125% (Medium)", 1.25),
            ("150% (Large)", 1.5),
            ("200% (Max)", 2.0),
        ]:
            prefix = "✓ " if abs(self.scale - s_val) < 0.05 else "   "
            item = Gtk.MenuItem(label=f"{prefix}{s_label}")
            item.connect("activate", lambda w, val=s_val: self.set_scale(val))
            scale_submenu.append(item)
        scale_item = Gtk.MenuItem(label="📏 Size")
        scale_item.set_submenu(scale_submenu)
        menu.append(scale_item)

        # 3. Transparent Background
        cutout_item = Gtk.CheckMenuItem(label="✨ Transparent Background (Cutout)")
        cutout_item.set_active(self.cutout)
        cutout_item.connect("toggled", lambda w: self.set_cutout(w.get_active()))
        menu.append(cutout_item)

        # 4. Snap to Corner
        snap_item = Gtk.MenuItem(label="📍 Snap to Bottom-Right Corner")
        snap_item.connect("activate", lambda w: self.snap_to_corner())
        menu.append(snap_item)

        # 5. Lock in Place
        lock_item = Gtk.CheckMenuItem(label="🔒 Lock in Place (Fix position)")
        lock_item.set_active(self.locked)
        lock_item.connect("toggled", lambda w: self.set_locked(w.get_active()))
        menu.append(lock_item)

        # 6. Autostart
        autostart_item = Gtk.CheckMenuItem(label="🚀 Start with System")
        autostart_item.set_active(self.is_autostart_enabled())
        autostart_item.connect("toggled", lambda w: self.set_autostart(w.get_active()))
        menu.append(autostart_item)

        menu.append(Gtk.SeparatorMenuItem())

        # 7. Open GIF Folder
        folder_item = Gtk.MenuItem(label="📂 Open GIF Folder...")
        folder_item.connect("activate", lambda w: self.open_gif_folder())
        menu.append(folder_item)

        # 8. Exit
        exit_item = Gtk.MenuItem(label="❌ Exit")
        exit_item.connect("activate", self.quit_app)
        menu.append(exit_item)

        return menu

    def show_context_menu(self, event):
        menu = self.build_menu(is_tray=False)
        menu.show_all()
        if hasattr(menu, "popup_at_pointer"):
            menu.popup_at_pointer(event)
        else:
            menu.popup(None, None, None, None, event.button, event.time)

    def setup_tray(self):
        if not HAVE_APPINDICATOR:
            return
        try:
            self.tray_indicator = AppIndicator3.Indicator.new(
                "DesktopCat",
                ICON_PNG if os.path.exists(ICON_PNG) else "applications-games",
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            )
            self.tray_indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self.update_tray_menu()
        except Exception as e:
            print(f"Tray indicator error: {e}")

    def update_tray_menu(self):
        if not hasattr(self, "tray_indicator") or not self.tray_indicator:
            return
        tray_menu = self.build_menu(is_tray=True)
        tray_menu.show_all()
        self.tray_indicator.set_menu(tray_menu)

    def quit_app(self, *args):
        if self.anim_job:
            GLib.source_remove(self.anim_job)
            self.anim_job = None
        if hasattr(self, "tray_indicator") and self.tray_indicator:
            self.tray_indicator.set_status(AppIndicator3.IndicatorStatus.PASSIVE)
        try:
            if os.path.exists(self.lock_file):
                os.remove(self.lock_file)
        except Exception:
            pass
        if Gtk.main_level() > 0:
            Gtk.main_quit()
        sys.exit(0)

    def run(self):
        Gtk.main()


if __name__ == "__main__":
    app = DesktopCatAppLinux()
    app.run()
