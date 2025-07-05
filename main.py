# --- key_automator.py (Final Version with Dynamic "Next" Button Wait) ---

import customtkinter as ctk
import pyautogui
import threading
import time
import cv2  # OpenCV for advanced image searching
import numpy as np
import os

# --- Main Automation Logic Class ---

class KeyBot:
    def __init__(self, status_callback):
        self.running = False
        self.thread = None
        self.status_callback = status_callback
        
        # --- THE FINAL, DYNAMIC ACTION SEQUENCE ---
        self.sequence = [
            ('press', 'f'),
            ('press', '4'),
            # --- THIS IS THE MODIFIED ACTION ---
            ('wait_for_image', 'templates/next.png', 20),
            # --- END OF MODIFICATION ---
            ('hold', 's', 2),
            ('hold', 'down', 3),
            ('press', 'e'), ('press', '1'), ('press', '2'), ('press', '3'), ('press', '4'),
            ('press', '5'), ('press', '6'), ('press', '7'), ('press', '8'), ('press', '9'),
            ('press', '0'), ('press', '1'), ('press', '3'), ('press', '5'), ('press', '6'),
            ('press', '7'), ('press', '8'), ('press', '0'), ('press', 'r'), ('press', '1'),
            ('press', 't'), ('press', '1'), ('press', 'y'), ('press', '5'), ('press', 'u'),
            ('press', '1'), ('press', 'u'), ('press', 'i'), ('press', '0'), ('press', 'y'),
            ('press', 'o'), ('press', 'z'), ('press', 'x'), ('press', 'c'),
            ('wait', 15),
            ('press', 'v'), ('press', 'b'), ('press', 'n'),
            ('wait_for_image', 'templates/return.png', 180), 
            ('press', 'g')
        ]

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self.run_loop, daemon=True)
            self.thread.start()
            self.status_callback("Automation started. Waiting to begin first loop...")

    def stop(self):
        if self.running:
            self.running = False
            self.status_callback("Stop signal received! Finishing current action...")

    def find_image_multi_scale(self, template_path, confidence=0.7):
        if not os.path.exists(template_path):
            self.status_callback(f"Error: Template not found at {template_path}")
            return False
        template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        screenshot = pyautogui.screenshot()
        screenshot_gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
        scales = np.linspace(0.8, 1.2, 20)
        for scale in scales:
            w, h = int(template.shape[1] * scale), int(template.shape[0] * scale)
            if w == 0 or h == 0: continue
            resized_template = cv2.resize(template, (w, h))
            res = cv2.matchTemplate(screenshot_gray, resized_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val >= confidence:
                return True
        return False

    def run_loop(self):
        while self.running:
            try:
                self.status_callback("Starting new loop in 10 seconds...")
                for i in range(10, 0, -1):
                    if not self.running: break
                    self.status_callback(f"Starting new loop in {i}s...")
                    time.sleep(1)

                if not self.running: break

                for action_tuple in self.sequence:
                    if not self.running: break
                    action_type = action_tuple[0]
                    
                    if action_type == 'press':
                        key = action_tuple[1]
                        self.status_callback(f"Pressing key: '{key}'")
                        pyautogui.press(key)
                        
                    elif action_type == 'hold':
                        key, duration = action_tuple[1], action_tuple[2]
                        self.status_callback(f"Holding key '{key}' for {duration}s...")
                        pyautogui.keyDown(key)
                        for _ in range(duration):
                            if not self.running: break
                            time.sleep(1)
                        pyautogui.keyUp(key)
                        
                    elif action_type == 'wait':
                        duration = action_tuple[1]
                        self.status_callback(f"Waiting for {duration}s...")
                        for _ in range(duration):
                            if not self.running: break
                            time.sleep(1)

                    elif action_type == 'wait_for_image':
                        image_path, timeout = action_tuple[1], action_tuple[2]
                        self.status_callback(f"Searching for '{os.path.basename(image_path)}' (max {timeout}s)...")
                        start_time = time.time()
                        image_found = False
                        
                        while time.time() - start_time < timeout:
                            if not self.running: break
                            elapsed = int(time.time() - start_time)
                            self.status_callback(f"Searching for '{os.path.basename(image_path)}' ({elapsed}/{timeout}s)...")
                            if self.find_image_multi_scale(image_path):
                                self.status_callback(f"Image '{os.path.basename(image_path)}' FOUND!")
                                image_found = True
                                break
                            time.sleep(2)
                        
                        if not image_found and self.running:
                            self.status_callback(f"Timeout! Image not found after {timeout}s.")
                    
                    time.sleep(0.1)

            except Exception as e:
                self.status_callback(f"An error occurred: {e}")
                self.running = False
        
        self.status_callback("Automation has stopped. Ready to start again.")


# --- GUI Application Class (Unchanged) ---
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Keyboard Automator")
        self.geometry("500x300")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.bot = KeyBot(self.update_status)
        self.title_label = ctk.CTkLabel(self, text="Keyboard Automator", font=ctk.CTkFont(size=24, weight="bold"))
        self.title_label.grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 10))
        self.start_button = ctk.CTkButton(self, text="Start Automation", command=self.bot.start, height=40, font=ctk.CTkFont(size=14, weight="bold"))
        self.start_button.grid(row=1, column=0, padx=(20, 5), pady=20, sticky="ew")
        self.stop_button = ctk.CTkButton(self, text="Stop Automation", command=self.bot.stop, height=40, fg_color="#D35400", hover_color="#B84300", font=ctk.CTkFont(size=14, weight="bold"))
        self.stop_button.grid(row=1, column=1, padx=(5, 20), pady=20, sticky="ew")
        self.status_frame = ctk.CTkFrame(self, corner_radius=10)
        self.status_frame.grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 20), sticky="nsew")
        self.status_frame.grid_rowconfigure(0, weight=1)
        self.status_frame.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(self.status_frame, text="Status: Ready", font=ctk.CTkFont(size=16), wraplength=400)
        self.status_label.grid(row=0, column=0, padx=15, pady=15)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def update_status(self, message):
        self.status_label.configure(text=message)

    def on_closing(self):
        self.bot.stop()
        self.destroy()

# --- Main Entry Point ---
if __name__ == "__main__":
    app = App()
    app.mainloop()