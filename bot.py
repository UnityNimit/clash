# --- bot.py (Version with Dynamic Child Window Finder) ---

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

# --- Part 1: Core Bot Utilities (Unchanged) ---

def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin()
    except: return False

# THIS IS THE NEW, CORRECTED VERSION
def take_screenshot():
    screenshot = pyautogui.screenshot()
    # The fix is changing COLOR_RGB_BGR to COLOR_RGB2BGR
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
        h, w = template.shape[:2]
        return (max_loc[0] + w // 2, max_loc[1] + h // 2)
    return None

def find_and_click_background(hwnd, template_path, screenshot, threshold=0.8):
    screen_location = find_image(template_path, screenshot, threshold)
    if screen_location:
        client_rect = win32gui.GetClientRect(hwnd)
        client_x, client_y = win32gui.ClientToScreen(hwnd, (client_rect[0], client_rect[1]))
        border_width = client_x - win32gui.GetWindowRect(hwnd)[0]
        title_bar_height = client_y - win32gui.GetWindowRect(hwnd)[1]
        relative_x = screen_location[0] - (client_x - border_width)
        relative_y = screen_location[1] - (client_y - title_bar_height)
        
        print(f"Found {template_path}. Clicking relative coords: ({relative_x}, {relative_y}) on HWND:{hwnd}")
        
        lParam = win32api.MAKELONG(relative_x, relative_y)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
        time.sleep(0.1)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lParam)
        return True
    return False

# --- THIS IS THE NEW CORE FUNCTION ---
def find_best_child_hwnd(parent_hwnd):
    """
    Enumerates all child windows of a parent and returns the handle to the one
    with the largest area.
    """
    child_windows = []
    def enum_child_callback(hwnd, lParam):
        child_windows.append(hwnd)
        return True
    
    win32gui.EnumChildWindows(parent_hwnd, enum_child_callback, None)
    
    max_area = 0
    best_hwnd = None
    
    for hwnd in child_windows:
        try:
            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            area = width * height
            if area > max_area:
                max_area = area
                best_hwnd = hwnd
        except Exception:
            # Some windows may not be accessible, just skip them
            continue
            
    return best_hwnd

# --- Part 2: The Bot's Main Logic (UPDATED) ---
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

    # UPDATED to use the new finding logic
    def _get_bluestacks_hwnd(self):
        # Find the main parent window
        parent_hwnd = win32gui.FindWindow(None, "BlueStacks App Player")
        if parent_hwnd == 0:
            self.status_callback("Error: Main BlueStacks window not found.")
            return 0
        
        # Find the largest child window within the parent
        self.hwnd = find_best_child_hwnd(parent_hwnd)
        if self.hwnd is None:
            self.status_callback(f"Error: Could not find a suitable child window. Is the game running?")
            return 0
            
        return self.hwnd

    def _test_attack_action(self):
        hwnd = self._get_bluestacks_hwnd()
        if not hwnd: 
            self.status_callback("Test failed: Could not get BlueStacks window handle.")
            return

        self.status_callback(f"Target window found! Handle (HWND): {hwnd}. Now searching for button...")
        screen = take_screenshot()
        if find_and_click_background(hwnd, self.templates['attack'], screen):
            self.status_callback("Test successful: Click sent to the game.")
        else:
            self.status_callback("Test failed: Attack button not found on screen.")

    def run_full_bot_logic(self):
        # This function can be expanded later
        self._test_attack_action()
        self.status_callback("Full automation task finished.")
        self.bot_running = False

# --- Part 3: The GUI Application (Unchanged) ---
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Clash of Clans Bot")
        self.geometry("450x280")
        self.grid_columnconfigure(0, weight=1)
        self.bot = ClashBot(self.update_status)
        self.title_label = ctk.CTkLabel(self, text="CoC Bot Control Panel", font=ctk.CTkFont(size=20, weight="bold"))
        self.title_label.grid(row=0, column=0, columnspan=2, padx=20, pady=(10, 5))
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
    def update_status(self, message): self.status_label.configure(text=f"Status: {message}")
    def on_closing(self): self.bot.stop(); self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()