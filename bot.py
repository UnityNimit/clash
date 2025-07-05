# --- bot.py (The Definitive "Always On" Version) ---

import time
import threading
import pyautogui

# GUI and Keyboard Listener libraries
import customtkinter as ctk
import ctypes
import keyboard

# --- Part 1: Core Bot Utilities ---

def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin()
    except: return False

# The robust hybrid clicker for the single Attack button.
def find_and_click_single(template_path, task_name, status_callback, confidence=0.8):
    status_callback(f"Scanning for {task_name} button...")
    location = None
    try:
        location = pyautogui.locateOnScreen(template_path, confidence=confidence)
    except pyautogui.PyAutoGUIException:
        status_callback(f"Skipping: {task_name} button not found.")
        return False
        
    if location:
        status_callback(f"{task_name} button found! Performing click...")
        original_pos = pyautogui.position()
        center = pyautogui.center(location)
        pyautogui.moveTo(center, duration=0.15)
        pyautogui.click()
        time.sleep(0.3)
        pyautogui.moveTo(original_pos, duration=0.15)
        return True
    
    status_callback(f"Skipping: {task_name} button not found.")
    return False

# The fast resource clicker for collecting one resource at a time.
def find_and_click_one_resource(template_path, task_name, confidence=0.8):
    location = None
    try:
        location = pyautogui.locateOnScreen(template_path, confidence=confidence)
    except pyautogui.PyAutoGUIException:
        return False
    
    if location:
        original_pos = pyautogui.position()
        center = pyautogui.center(location)
        pyautogui.moveTo(center, duration=0.1)
        pyautogui.click()
        time.sleep(0.2)
        pyautogui.moveTo(original_pos, duration=0.1)
        return True
    return False

# --- Part 2: The Bot's Main Logic ---
class ClashBot:
    def __init__(self, status_callback):
        self.is_collecting = False
        self.collection_thread = None
        self.status_callback = status_callback
        self.templates = {
            'attack': 'templates/attack_button.png',
            'gold': 'templates/gold.png',
            'elixir': 'templates/elixir.png',
            'dark_elixir': 'templates/darkelixir.png'
        }

    def start_resource_collection(self):
        if not self.is_collecting:
            self.is_collecting = True
            self.collection_thread = threading.Thread(target=self.run_collection_loop, daemon=True)
            self.collection_thread.start()
            self.status_callback("Resource collection has started. Press ESC to stop.")

    def stop_collection(self):
        if self.is_collecting:
            self.is_collecting = False
            self.status_callback("Stop signal received! Halting collection loop...")

    def run_single_attack(self):
        self.status_callback("Preparing to launch a single attack...")
        attack_thread = threading.Thread(target=self._attack_action, daemon=True)
        attack_thread.start()

    def _attack_action(self):
        for i in range(3, 0, -1):
            self.status_callback(f"Attacking in {i}...")
            time.sleep(1)
        
        find_and_click_single(self.templates['attack'], "Attack", self.status_callback, confidence=0.7)
        self.status_callback("Attack action complete. Returning to idle.")

    # --- THIS IS THE NEW "ALWAYS ON" COLLECTION LOOP ---
    def run_collection_loop(self):
        while self.is_collecting:
            try:
                action_taken = False
                
                # We check each resource type one by one.
                # If we find one, we click it and immediately restart the loop.
                self.status_callback("Scanning for resources...")
                
                if find_and_click_one_resource(self.templates['dark_elixir'], "Dark Elixir"):
                    self.status_callback("Collected Dark Elixir.")
                    action_taken = True
                
                if not action_taken and find_and_click_one_resource(self.templates['gold'], "Gold"):
                    self.status_callback("Collected Gold.")
                    action_taken = True
                
                if not action_taken and find_and_click_one_resource(self.templates['elixir'], "Elixir"):
                    self.status_callback("Collected Elixir.")
                    action_taken = True

                # After checking all resources, decide what to do next.
                if action_taken:
                    # If we did something, wait just a moment before re-scanning.
                    time.sleep(1)
                else:
                    # If we did nothing, the village is idle. Wait and show a countdown.
                    for i in range(5, 0, -1):
                        if not self.is_collecting: break # Allow stopping during idle
                        self.status_callback(f"Village is idle. Re-scanning in {i}s...")
                        time.sleep(1)

            except Exception as e:
                self.status_callback(f"An error occurred in collection loop: {e}")
                self.is_collecting = False
        
        self.status_callback("Resource collection has stopped.")

# --- Part 3: The GUI Application ---
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Clash of Clans Bot")
        self.geometry("450x320")
        self.grid_columnconfigure((0, 1), weight=1)
        self.bot = ClashBot(self.update_status)
        self.title_label = ctk.CTkLabel(self, text="CoC Bot Control Panel", font=ctk.CTkFont(size=20, weight="bold"))
        self.title_label.grid(row=0, column=0, columnspan=2, padx=20, pady=(10, 5))
        admin_text = "Status: Running as Admin" if is_admin() else "Warning: Not running as Admin"
        admin_color = "green" if is_admin() else "orange"
        self.admin_label = ctk.CTkLabel(self, text=admin_text, text_color=admin_color, font=ctk.CTkFont(size=12, weight="bold"))
        self.admin_label.grid(row=1, column=0, columnspan=2, padx=20, pady=0)
        self.start_button = ctk.CTkButton(self, text="Start Resource Collection", command=self.bot.start_resource_collection)
        self.start_button.grid(row=2, column=0, padx=(20, 5), pady=10, sticky="ew")
        self.stop_button = ctk.CTkButton(self, text="Stop Collection", command=self.bot.stop_collection, fg_color="darkred")
        self.stop_button.grid(row=2, column=1, padx=(5, 20), pady=10, sticky="ew")
        self.attack_button = ctk.CTkButton(self, text="Perform Single Attack", command=self.bot.run_single_attack, fg_color="#005B96")
        self.attack_button.grid(row=3, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        self.status_label = ctk.CTkLabel(self, text="Status: Ready. Press ESC to stop collection anytime.", wraplength=400)
        self.status_label.grid(row=4, column=0, columnspan=2, padx=20, pady=(10, 20))
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.setup_hotkeys()

    def update_status(self, message):
        self.status_label.configure(text=f"Status: {message}")

    def on_closing(self):
        self.bot.stop_collection()
        self.destroy()

    def setup_hotkeys(self):
        hotkey_thread = threading.Thread(target=self._hotkey_listener, daemon=True)
        hotkey_thread.start()

    def _hotkey_listener(self):
        keyboard.add_hotkey('esc', self.bot.stop_collection)
        keyboard.wait()

if __name__ == "__main__":
    app = App()
    app.mainloop()