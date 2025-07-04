# --- bot.py (Version with Coordinate Fix and Admin Check) ---

import time
import threading
import cv2
import numpy as np
import pyautogui

# GUI and Windows API libraries
import customtkinter as ctk
import win32gui
import win32api
import win32con
import ctypes

# --- Part 1: Core Bot Utilities (find_and_click is UPDATED) ---

def is_admin():
    """Checks if the script is running with administrative privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def take_screenshot():
    screenshot = pyautogui.screenshot()
    return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

def find_image(template_path, screenshot, threshold=0.8):
    template = cv2.imread(template_path, cv2.IMREAD_UNCHANGED)
    if template is None:
        print(f"Error: Template image not found at {template_path}")
        return None
    if template.shape[2] == 4:
        template = template[:,:,:3]
        
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        template_h, template_w = template.shape[:2]
        center_x = max_loc[0] + template_w // 2
        center_y = max_loc[1] + template_h // 2
        return (center_x, center_y)
    return None

def background_click(hwnd, x, y):
    lParam = win32api.MAKELONG(x, y)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
    time.sleep(0.1)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lParam)

# --- THIS FUNCTION IS THE KEY FIX ---
def find_and_click_background(hwnd, template_path, screenshot, threshold=0.8):
    """
    Finds an image, translates coordinates, and sends a background click.
    """
    # Find the image on the screen
    screen_location = find_image(template_path, screenshot, threshold)
    
    if screen_location:
        # Get the position of the BlueStacks window on the screen
        window_rect = win32gui.GetWindowRect(hwnd)
        window_x, window_y = window_rect[0], window_rect[1]
        
        # Translate the screen coordinates to window-relative coordinates
        relative_x = screen_location[0] - window_x
        relative_y = screen_location[1] - window_y
        
        print(f"Found {template_path} at screen:{screen_location}. Clicking window coords:({relative_x}, {relative_y})")
        background_click(hwnd, relative_x, relative_y)
        return True
        
    return False

# --- Part 2: The Bot's Main Logic (Unchanged from previous version) ---
class ClashBot:
    def __init__(self, status_callback):
        self.bot_running = False
        self.thread = None
        self.status_callback = status_callback
        self.templates = {'attack': 'templates/attack_button.png'}
        self.hwnd = 0

    def start(self):
        if not self.bot_running:
            self.bot_running = True
            self.thread = threading.Thread(target=self.run_full_bot_logic, daemon=True)
            self.thread.start()
            self.status_callback("Full automation started.")

    def stop(self):
        if self.bot_running:
            self.bot_running = False
            self.status_callback("Stopping... bot will halt after current action.")

    def run_test_click_attack(self):
        self.status_callback("Running single test: Find & Click Attack...")
        threading.Thread(target=self._test_attack_action, daemon=True).start()

    def _get_bluestacks_hwnd(self):
        if self.hwnd != 0 and win32gui.IsWindow(self.hwnd):
            return self.hwnd
        # IMPORTANT: Make sure this window title is EXACTLY correct!
        self.hwnd = win32gui.FindWindow(None, "BlueStacks App Player")
        if self.hwnd == 0:
            self.status_callback("Error: BlueStacks window not found.")
            return 0
        return self.hwnd

    def _test_attack_action(self):
        hwnd = self._get_bluestacks_hwnd()
        if not hwnd: return

        screen = take_screenshot()
        if find_and_click_background(hwnd, self.templates['attack'], screen):
            self.status_callback("Test successful: Click sent to the game.")
        else:
            self.status_callback("Test failed: Attack button not found on screen.")

    def run_full_bot_logic(self):
        hwnd = self._get_bluestacks_hwnd()
        if not hwnd: 
            self.bot_running = False
            return
        
        self.status_callback(f"BlueStacks found! Starting main loop...")
        
        while self.bot_running:
            try:
                self.status_callback("Looking for Attack button...")
                screen = take_screenshot()
                if find_and_click_background(hwnd, self.templates['attack'], screen):
                    self.status_callback("Attack button clicked. Waiting 10s...")
                    time.sleep(10)
                else:
                    self.status_callback("Attack button not found. Waiting 10s...")
                    time.sleep(10)
            except Exception as e:
                self.status_callback(f"An error occurred: {e}")
                time.sleep(10)
        self.status_callback("Bot stopped.")

# --- Part 3: The GUI Application (Now with Admin status check) ---
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Clash of Clans Bot")
        self.geometry("450x280")
        self.grid_columnconfigure(0, weight=1)
        
        self.bot = ClashBot(self.update_status)

        self.title_label = ctk.CTkLabel(self, text="CoC Bot Control Panel", font=ctk.CTkFont(size=20, weight="bold"))
        self.title_label.grid(row=0, column=0, columnspan=2, padx=20, pady=(10, 5))

        # Admin status warning
        admin_text = "Status: Running as Admin" if is_admin() else "Warning: Not running as Admin"
        admin_color = "green" if is_admin() else "orange"
        self.admin_label = ctk.CTkLabel(self, text=admin_text, text_color=admin_color, font=ctk.CTkFont(size=12, weight="bold"))
        self.admin_label.grid(row=1, column=0, columnspan=2, padx=20, pady=0)
        
        self.test_button = ctk.CTkButton(self, text="Test: Find & Click Attack", command=self.bot.run_test_click_attack)
        self.test_button.grid(row=2, column=0, columnspan=2, padx=20, pady=10, sticky="ew")

        self.start_button = ctk.CTkButton(self, text="Start Full Automation", command=self.bot.start)
        self.start_button.grid(row=3, column=0, padx=(20, 5), pady=10, sticky="ew")

        self.stop_button = ctk.CTkButton(self, text="Stop", command=self.bot.stop, fg_color="darkred")
        self.stop_button.grid(row=3, column=1, padx=(5, 20), pady=10, sticky="ew")

        self.status_label = ctk.CTkLabel(self, text="Status: Ready", wraplength=400)
        self.status_label.grid(row=4, column=0, columnspan=2, padx=20, pady=(10, 20))
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def update_status(self, message):
        self.status_label.configure(text=f"Status: {message}")

    def on_closing(self):
        self.bot.stop()
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()