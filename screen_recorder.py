"""
Lightweight Screen Recorder & Screenshot Tool
================================================
A small floating on-screen icon that lets you:
  - Record the full screen to video (no audio)
  - Take instant screenshots
  - Auto-save everything to a folder you pick, with timestamped filenames

Dependencies (install once):
    pip install mss numpy opencv-python

Run:
    python screen_recorder.py

Platform notes:
  - Windows & macOS: works out of the box.
  - macOS: grant "Screen Recording" permission to your Terminal/Python app
    in System Settings > Privacy & Security > Screen Recording, or you'll
    get black frames.
  - Linux: screen capture works on X11. Plain Wayland sessions block this
    kind of capture for security reasons - run under X11/XWayland instead.
"""

import os
import sys
import time
import threading
import datetime
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    import mss
    import mss.tools
    import numpy as np
    import cv2
except ImportError as e:
    print("Missing dependency:", e)
    print("Install with:  pip install mss numpy opencv-python")
    sys.exit(1)

# ----------------------------------------------------------------------
# Settings you can tweak
# ----------------------------------------------------------------------
FPS = 12                # lower = smaller files & less CPU, higher = smoother video
SCALE = 1.0              # 1.0 = full resolution, 0.75 = 75% size (smaller files)
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".screenrec_config.txt")
DEFAULT_FOLDER = os.path.join(os.path.expanduser("~"), "Videos", "ScreenCapture")


# ----------------------------------------------------------------------
# Remembers the last folder you chose, between runs
# ----------------------------------------------------------------------
def load_save_folder():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                path = f.read().strip()
            if path and os.path.isdir(path):
                return path
        except OSError:
            pass
    os.makedirs(DEFAULT_FOLDER, exist_ok=True)
    return DEFAULT_FOLDER


def save_folder_config(path):
    try:
        with open(CONFIG_FILE, "w") as f:
            f.write(path)
    except OSError:
        pass


# ----------------------------------------------------------------------
# Recording engine (runs capture loop on a background thread)
# ----------------------------------------------------------------------
class ScreenRecorder:
    def __init__(self, save_folder, fps=FPS, scale=SCALE):
        self.save_folder = save_folder
        self.fps = fps
        self.scale = scale
        self.recording = False
        self.writer = None
        self.thread = None
        self.filename = None
        self.monitor = None
        self.out_size = None
        self._stop_flag = threading.Event()

    def _build_writer(self, base_path, width, height):
        """Try mp4 first; fall back to avi if this OpenCV build can't write mp4."""
        mp4_path = base_path + ".mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(mp4_path, fourcc, self.fps, (width, height))
        if writer.isOpened():
            return writer, mp4_path
        writer.release()
        avi_path = base_path + ".avi"
        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        writer = cv2.VideoWriter(avi_path, fourcc, self.fps, (width, height))
        return writer, avi_path

    def start(self):
        if self.recording:
            return None
        os.makedirs(self.save_folder, exist_ok=True)
        with mss.mss() as sct:
            monitor = sct.monitors[0]  # full virtual screen (all monitors combined)

        width = int(monitor["width"] * self.scale)
        height = int(monitor["height"] * self.scale)
        width -= width % 2    # even dimensions avoid codec issues
        height -= height % 2

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base_path = os.path.join(self.save_folder, f"Recording_{timestamp}")
        self.writer, self.filename = self._build_writer(base_path, width, height)

        if not self.writer.isOpened():
            return None

        self.monitor = monitor
        self.out_size = (width, height)
        self.recording = True
        self._stop_flag.clear()
        self.thread = threading.Thread(target=self._record_loop, daemon=True)
        self.thread.start()
        return self.filename

    def _record_loop(self):
        frame_interval = 1.0 / self.fps
        with mss.mss() as sct:
            while not self._stop_flag.is_set():
                loop_start = time.time()
                raw = np.array(sct.grab(self.monitor))
                frame = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
                if (frame.shape[1], frame.shape[0]) != self.out_size:
                    frame = cv2.resize(frame, self.out_size, interpolation=cv2.INTER_AREA)
                self.writer.write(frame)
                elapsed = time.time() - loop_start
                remaining = frame_interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)

    def stop(self):
        if not self.recording:
            return
        self._stop_flag.set()
        if self.thread:
            self.thread.join(timeout=3)
        if self.writer:
            self.writer.release()
            self.writer = None
        self.recording = False


def take_screenshot(save_folder):
    os.makedirs(save_folder, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = os.path.join(save_folder, f"Screenshot_{timestamp}.png")
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        img = sct.grab(monitor)
        mss.tools.to_png(img.rgb, img.size, output=filename)
    return filename


# ----------------------------------------------------------------------
# Floating on-screen widget (small draggable icon, click for menu)
# ----------------------------------------------------------------------
class FloatingWidget:
    SIZE = 42

    def __init__(self):
        self.save_folder = load_save_folder()
        self.recorder = ScreenRecorder(self.save_folder)
        self._blink_on = True
        self.menu = None

        self.root = tk.Tk()
        self.root.title("Screen Recorder")
        self.root.overrideredirect(True)          # no title bar - just the icon
        self.root.attributes("-topmost", True)     # always on top
        try:
            self.root.attributes("-alpha", 0.94)    # slight transparency
        except tk.TclError:
            pass
        self.root.configure(bg="#1e1e1e")

        screen_w = self.root.winfo_screenwidth()
        self.root.geometry(f"{self.SIZE}x{self.SIZE}+{screen_w - 90}+40")

        self.canvas = tk.Canvas(self.root, width=self.SIZE, height=self.SIZE,
                                 bg="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.draw_icon()

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self._drag_info = {"x": 0, "y": 0, "moved": False}

        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

    # -- drawing ---------------------------------------------------------
    def draw_icon(self):
        self.canvas.delete("all")
        color = "#e03131" if self.recorder.recording else "#3a3a3a"
        self.canvas.create_oval(3, 3, self.SIZE - 3, self.SIZE - 3,
                                 fill=color, outline="#999", width=1, tags="dot")
        symbol = "\u25a0" if self.recorder.recording else "\u25cf"  # ■ or ●
        self.canvas.create_text(self.SIZE / 2, self.SIZE / 2, text=symbol,
                                 fill="white", font=("Segoe UI", 13))

    def _blink(self):
        if self.recorder.recording:
            self._blink_on = not self._blink_on
            color = "#ff5252" if self._blink_on else "#a01818"
            self.canvas.itemconfig("dot", fill=color)
            self.root.after(600, self._blink)

    def show_toast(self, text, duration=1800):
        """Small non-blocking notification near the icon, auto-closes."""
        x, y = self.root.winfo_x(), self.root.winfo_y()
        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg="#1e1e1e")
        tk.Label(toast, text=text, bg="#1e1e1e", fg="white", font=("Segoe UI", 9),
                  padx=10, pady=6, justify="left").pack()
        toast.update_idletasks()
        w = toast.winfo_width()
        toast.geometry(f"+{max(x - w + self.SIZE, 0)}+{y + self.SIZE + 6}")
        toast.after(duration, toast.destroy)

    # -- dragging vs. clicking --------------------------------------------
    def _press(self, event):
        self._drag_info = {"x": event.x, "y": event.y, "moved": False}

    def _drag(self, event):
        dx = event.x - self._drag_info["x"]
        dy = event.y - self._drag_info["y"]
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag_info["moved"] = True
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")

    def _release(self, event):
        if not self._drag_info["moved"]:
            self.toggle_menu()

    # -- popup menu --------------------------------------------------------
    def toggle_menu(self):
        if self.menu and self.menu.winfo_exists():
            self.close_menu()
            return
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self.menu = tk.Toplevel(self.root)
        self.menu.overrideredirect(True)
        self.menu.attributes("-topmost", True)
        self.menu.configure(bg="#1e1e1e")
        self.menu.geometry(f"190x175+{x - 150}+{y}")

        def btn(text, cmd):
            b = tk.Button(self.menu, text=text, command=cmd, bg="#2b2b2b", fg="white",
                          activebackground="#3a3a3a", activeforeground="white",
                          relief="flat", anchor="w", padx=10, font=("Segoe UI", 10), bd=0)
            b.pack(fill="x", pady=1, padx=4)

        btn("Stop Recording" if self.recorder.recording else "Start Recording",
            self.toggle_recording)
        btn("Take Screenshot", self.do_screenshot)
        btn("Choose Save Folder", self.choose_folder)
        btn("Open Save Folder", self.open_folder)
        btn("Quit", self.quit_app)

    def close_menu(self):
        if self.menu and self.menu.winfo_exists():
            self.menu.destroy()
        self.menu = None

    # -- actions -----------------------------------------------------------
    def toggle_recording(self):
        self.close_menu()
        if self.recorder.recording:
            self.recorder.stop()
            self.draw_icon()
            self.show_toast(f"Saved:\n{os.path.basename(self.recorder.filename)}")
        else:
            self.recorder.save_folder = self.save_folder
            result = self.recorder.start()
            if result is None:
                messagebox.showerror("Recording failed",
                                      "Could not start the video writer.\n"
                                      "Check that the save folder is writable.")
                return
            self.draw_icon()
            self._blink()

    def do_screenshot(self):
        self.close_menu()
        self.root.withdraw()   # hide the icon so it doesn't appear in the shot
        self.root.update()
        time.sleep(0.15)       # give the window manager time to actually hide it
        filename = take_screenshot(self.save_folder)
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.show_toast(f"Saved:\n{os.path.basename(filename)}")

    def choose_folder(self):
        self.close_menu()
        folder = filedialog.askdirectory(initialdir=self.save_folder)
        if folder:
            self.save_folder = folder
            self.recorder.save_folder = folder
            save_folder_config(folder)

    def open_folder(self):
        self.close_menu()
        if sys.platform.startswith("win"):
            os.startfile(self.save_folder)
        elif sys.platform == "darwin":
            os.system(f'open "{self.save_folder}"')
        else:
            os.system(f'xdg-open "{self.save_folder}"')

    def quit_app(self):
        if self.recorder.recording:
            self.recorder.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    FloatingWidget().run()
