### `screen_recorder.py`
"""
Lightweight Screen Recorder & Screenshot Tool
================================================
A floating on-screen toolbar for fast screen recording and screenshots.

Dependencies:
    pip install mss numpy opencv-python pyinstaller
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
    sys.exit(1)

# ---------------------------------------------------------------
# Configuration Constants
# ------------------------------------------------------------
FPS = 12
SCALE = 1.0
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".screenrec_config.txt")
DEFAULT_FOLDER = os.path.join(os.path.expanduser("~"), "Videos", "ScreenCapture")


# ----------------------------------------------------------------
# Helper Functions
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


# -------------------------------------------------------------------
# Recording & Capture Engine
# -----------------------------------------------------------------
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
            monitor = sct.monitors[0]

        width = int(monitor["width"] * self.scale)
        height = int(monitor["height"] * self.scale)
        width -= width % 2
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


# -----------------------------------------------------------------
# Floating UI Widget
# ----------------------------------------------------------------------
class FloatingWidget:
    def __init__(self):
        self.save_folder = load_save_folder()
        self.recorder = ScreenRecorder(self.save_folder)
        self._blink_on = True
        self.menu = None

        self.root = tk.Tk()
        self.root.title("Screen Recorder")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#1a1a1a")

        screen_w = self.root.winfo_screenwidth()
        self.root.geometry(f"120x40+{screen_w - 150}+40")

        self.btn_rec = tk.Label(self.root, text="⏺", bg="#1a1a1a", fg="#ff4d4d", font=("Segoe UI", 16))
        self.btn_rec.place(x=0, y=0, width=40, height=40)

        self.btn_shot = tk.Label(self.root, text="📷", bg="#1a1a1a", fg="white", font=("Segoe UI", 13))
        self.btn_shot.place(x=40, y=0, width=40, height=40)

        self.btn_more = tk.Label(self.root, text="⋮", bg="#1a1a1a", fg="white", font=("Segoe UI", 16))
        self.btn_more.place(x=80, y=0, width=40, height=40)

        self._drag_info = {"x": 0, "y": 0, "moved": False}
        for w in (self.root, self.btn_rec, self.btn_shot, self.btn_more):
            w.bind("<ButtonPress-1>", self._press)
            w.bind("<B1-Motion>", self._drag)

        self.btn_rec.bind("<ButtonRelease-1>", lambda e: self._click_action(self.toggle_recording))
        self.btn_shot.bind("<ButtonRelease-1>", lambda e: self._click_action(self.do_screenshot))
        self.btn_more.bind("<ButtonRelease-1>", lambda e: self._click_action(self.toggle_menu))

    def _press(self, event):
        self._drag_info = {"x": event.x_root, "y": event.y_root, "moved": False}
        self._start_x = self.root.winfo_x()
        self._start_y = self.root.winfo_y()

    def _drag(self, event):
        dx = event.x_root - self._drag_info["x"]
        dy = event.y_root - self._drag_info["y"]
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag_info["moved"] = True
            self.root.geometry(f"+{self._start_x + dx}+{self._start_y + dy}")

    def _click_action(self, action):
        if not self._drag_info["moved"]:
            action()

    def _blink(self):
        if self.recorder.recording:
            self._blink_on = not self._blink_on
            color = "#ff4d4d" if self._blink_on else "#802626"
            self.btn_rec.configure(fg=color, text="⏹")
            self.root.after(600, self._blink)
        else:
            self.btn_rec.configure(fg="#ff4d4d", text="⏺")

    def show_toast(self, text, duration=1800):
        x, y = self.root.winfo_x(), self.root.winfo_y()
        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg="#1a1a1a")
        tk.Label(toast, text=text, bg="#1a1a1a", fg="white", font=("Segoe UI", 9), padx=10, pady=6).pack()
        toast.update_idletasks()
        w = toast.winfo_width()
        toast.geometry(f"+{x + 60 - (w // 2)}+{y + 45}")
        toast.after(duration, toast.destroy)

    def toggle_menu(self):
        if self.menu and self.menu.winfo_exists():
            self.close_menu()
            return
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self.menu = tk.Toplevel(self.root)
        self.menu.overrideredirect(True)
        self.menu.attributes("-topmost", True)
        self.menu.configure(bg="#1a1a1a")
        self.menu.geometry(f"160x85+{x - 40}+{y + 45}")

        def btn(text, cmd):
            b = tk.Button(self.menu, text=text, command=cmd, bg="#262626", fg="white",
                          activebackground="#333", activeforeground="white",
                          relief="flat", anchor="w", padx=10, font=("Segoe UI", 9), bd=0)
            b.pack(fill="x", pady=1, padx=4)

        btn("Choose Save Folder", self.choose_folder)
        btn("Open Save Folder", self.open_folder)
        btn("Quit", self.quit_app)

    def close_menu(self):
        if self.menu and self.menu.winfo_exists():
            self.menu.destroy()
        self.menu = None

    def toggle_recording(self):
        self.close_menu()
        if self.recorder.recording:
            self.recorder.stop()
            self._blink()
            self.show_toast("Saved Video")
        else:
            self.recorder.save_folder = self.save_folder
            if self.recorder.start() is None:
                messagebox.showerror("Error", "Could not start recording.")
                return
            self._blink()

    def do_screenshot(self):
        self.close_menu()
        self.root.withdraw()
        self.root.update()
        time.sleep(0.15)
        take_screenshot(self.save_folder)
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.show_toast("Saved Screenshot")

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
