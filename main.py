# --- key_automator.py (Final Version with GUI Reps Input) ---

import customtkinter as ctk
import pyautogui
import threading
import time
import cv2
import numpy as np
import os
try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r'C:\Nimit\tesseractOCR\tesseract.exe'
except ImportError:
    print("Pytesseract not found. OCR features will not work.")
    pytesseract = None

# --- Main Automation Logic Class ---

class KeyBot:
    def __init__(self, status_callback):
        self.running = False
        self.thread = None
        self.status_callback = status_callback
        self.current_loop_target = None
        self.attack_reps = 10  # Default value

        # --- SEQUENCE DEFINITIONS ---
        self.main_attack_sequence = [
            ('press', 'f'), ('press', '4'), ('wait_for_image', 'templates/next.png', 20),
            ('hold', 's', 2), ('hold', 'down', 3), ('press', 'e'), ('press', '1'),
            ('press', '2'), ('press', '3'), ('press', '4'), ('press', '5'), ('press', '6'),
            ('press', '7'), ('press', '8'), ('press', '9'), ('press', '0'), ('press', '1'),
            ('press', '3'), ('press', '5'), ('press', '6'), ('press', '7'), ('press', '8'),
            ('press', '0'), ('press', 'r'), ('press', '1'), ('press', 't'), ('press', '1'),
            ('press', 'y'), ('press', '5'), ('press', 'u'), ('press', '1'), ('press', 'u'),
            ('press', 'i'), ('press', '0'), ('press', 'y'), ('press', 'o'), ('press', 'z'),
            ('press', 'x'), ('press', 'c'), ('wait', 15), ('press', 'v'), ('press', 'b'),
            ('press', 'n'), ('wait_for_image', 'templates/return.png', 180), ('press', 'g')
        ]
        
        self.wall_upgrade_sequence_1 = [
            ('click_image', 'templates/builder.png', 20),
            ('wait', 1), 
            # ### MODIFIED DURATION ###
            ('hold', 's', 12), 
            ('wait', 1),
            ('click_text', 'Wall', 12), ('wait', 2),
            ('click_image', 'templates/builder.png', 20),
            ('press', 'q'), ('press', 'p')
        ]
        
        self.wall_upgrade_sequence_2 = [
            ('wait', 2),
            ('click_image', 'templates/builder.png', 20),
            ('wait', 1), 
            # ### MODIFIED DURATION ###
            ('hold', 's', 12), 
            ('wait', 3),
            ('click_text', 'Wall', 12), ('wait', 2),
            ('click_image', 'templates/builder.png', 20),
            ('press', 'm'), ('press', 'p')
        ]

    def start(self, loop_type, reps=10):
        if not self.running:
            self.running = True
            self.current_loop_target = loop_type
            if loop_type == 'normal':
                self.attack_reps = reps
            
            self.thread = threading.Thread(target=self.run_automation, daemon=True)
            self.thread.start()
            self.status_callback(f"Automation '{loop_type}' started. Waiting to begin first loop...")

    def stop(self):
        if self.running:
            self.running = False
            self.status_callback("Stop signal received! Finishing current action...")

    def find_image_multi_scale(self, template_path, confidence=0.7):
        if not os.path.exists(template_path):
            self.status_callback(f"Error: Template not found at {template_path}")
            return None
        template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        if template is None:
            self.status_callback(f"Error: Could not read template at {template_path}")
            return None
        screenshot = pyautogui.screenshot()
        screenshot_gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
        scales = np.linspace(0.8, 1.2, 20)
        for scale in scales:
            w, h = int(template.shape[1] * scale), int(template.shape[0] * scale)
            if w == 0 or h == 0: continue
            resized_template = cv2.resize(template, (w, h))
            res = cv2.matchTemplate(screenshot_gray, resized_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val >= confidence:
                return (max_loc[0] + w // 2, max_loc[1] + h // 2)
        return False

    def find_and_click_text(self, target_text, timeout):
        self.status_callback(f"Searching for text '{target_text}' (max {timeout}s)...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not self.running: return False
            screenshot = pyautogui.screenshot()
            data = pytesseract.image_to_data(screenshot, output_type=pytesseract.Output.DICT)
            num_boxes = len(data['level'])
            for i in range(num_boxes):
                if target_text.lower() in data['text'][i].lower() and int(data['conf'][i]) > 60:
                    x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                    center_x, center_y = x + w // 2, y + h // 2
                    self.status_callback(f"Text '{target_text}' FOUND! Clicking at ({center_x}, {center_y}).")
                    pyautogui.click(center_x, center_y)
                    return True
            elapsed = int(time.time() - start_time)
            self.status_callback(f"Searching for text '{target_text}' ({elapsed}/{timeout}s)...")
            time.sleep(2)
        self.status_callback(f"Timeout! Text '{target_text}' not found after {timeout}s.")
        return False

    def _execute_action(self, action_tuple):
        if not self.running: return False
        action_type = action_tuple[0]
        if action_type == 'press':
            key = action_tuple[1]
            self.status_callback(f"Pressing key: '{key}'")
            pyautogui.press(key)
        elif action_type == 'hold':
            key, duration = action_tuple[1], action_tuple[2]
            self.status_callback(f"Holding key '{key}' for {duration}s...")
            pyautogui.keyDown(key)
            for i in range(duration):
                if not self.running: break
                time.sleep(1)
            pyautogui.keyUp(key)
        elif action_type == 'wait':
            duration = action_tuple[1]
            self.status_callback(f"Waiting for {duration}s...")
            for i in range(duration):
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
        elif action_type == 'click_image':
            image_path, timeout = action_tuple[1], action_tuple[2]
            self.status_callback(f"Searching for '{os.path.basename(image_path)}' to click (max {timeout}s)...")
            start_time = time.time()
            clicked = False
            while time.time() - start_time < timeout:
                if not self.running: break
                coords = self.find_image_multi_scale(image_path)
                if coords:
                    self.status_callback(f"Image '{os.path.basename(image_path)}' found. Clicking...")
                    pyautogui.click(coords)
                    clicked = True
                    break
                elapsed = int(time.time() - start_time)
                self.status_callback(f"Searching to click '{os.path.basename(image_path)}' ({elapsed}/{timeout}s)...")
                time.sleep(1)
            if not clicked and self.running:
                self.status_callback(f"Timeout! Could not find '{os.path.basename(image_path)}' to click.")
        elif action_type == 'click_text':
            text, timeout = action_tuple[1], action_tuple[2]
            self.find_and_click_text(text, timeout)
        time.sleep(0.1)
        return True

    def _wait_before_loop(self):
        self.status_callback("Starting new loop in 10 seconds...")
        for i in range(10, 0, -1):
            if not self.running: return False
            self.status_callback(f"Starting new loop in {i}s...")
            time.sleep(1)
        return self.running

    def run_automation(self):
        try:
            if self.current_loop_target == 'normal':
                self.normal_attack_loop()
            elif self.current_loop_target == 'builder':
                self.builder_attack_loop()
        except Exception as e:
            self.status_callback(f"An error occurred: {e}")
            self.running = False
        self.status_callback("Automation has stopped. Ready to start again.")

    def normal_attack_loop(self):
        while self.running:
            for i in range(self.attack_reps):
                if not self.running: break
                self.status_callback(f"--- Starting Main Attack Loop {i + 1}/{self.attack_reps} ---")
                if not self._wait_before_loop(): break

                for action_tuple in self.main_attack_sequence:
                    if not self.running: break
                    self._execute_action(action_tuple)
            
            if not self.running: break

            self.status_callback("--- Starting Wall Upgrade Sequence (Part 1) ---")
            for action_tuple in self.wall_upgrade_sequence_1:
                if not self.running: break
                self._execute_action(action_tuple)
            if not self.running: break

            self.status_callback("--- Starting Wall Upgrade Sequence (Part 2) ---")
            for action_tuple in self.wall_upgrade_sequence_2:
                if not self.running: break
                self._execute_action(action_tuple)

    def builder_attack_loop(self):
        while self.running:
            if not self._wait_before_loop(): break
            actions = [
                ('press', 'f'), ('press', '4'), ('wait_for_image', 'templates/battle_machine_1.png', 10),
                ('hold', 's', 2), ('hold', 'down', 2), ('press', 'e'), ('press', '1'),
                ('press', 'r'), ('press', '1'), ('press', '1'), ('press', '1'), ('press', '1'),
                ('press', '1'), ('press', 'o'), ('press', '1')
            ]
            for action in actions:
                if not self.running: break
                self._execute_action(action)
            if not self.running: break
            self.status_callback("Searching for Super Pekka card...")
            pekka_found = False
            while not pekka_found and self.running:
                if self.find_image_multi_scale('templates/super_pekka_card.png'):
                    self.status_callback("Super Pekka card FOUND!")
                    pekka_found = True
                else:
                    self.status_callback("Pekka not found, pressing 'o' and waiting 24s...")
                    pyautogui.press('o')
                    time.sleep(24)
            if not self.running: break
            actions_part_2 = [
                ('hold', 's', 2), ('hold', 'down', 2), ('press', 'e'), ('press', '1'),
                ('press', 'r'), ('press', '1'), ('press', 't'), ('press', '1'),
                ('press', 'y'), ('press', '1'), ('press', 'u'), ('press', '1'),
                ('press', 'i'), ('press', '1'), ('press', 'o'), ('press', '1'),
                ('press', 'p'), ('press', '1'), ('press', 'leftbracket'), ('press', '1'),
                ('wait_for_image', 'templates/return.png', 150), ('press', 'g')
            ]
            for action in actions_part_2:
                if not self.running: break
                self._execute_action(action)

# --- GUI Application Class ---
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Keyboard Automator")
        self.geometry("550x420")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        self.grid_columnconfigure((0, 1), weight=1)
        self.grid_rowconfigure(3, weight=1)
        
        self.bot = KeyBot(self.update_status)
        
        self.title_label = ctk.CTkLabel(self, text="Keyboard Automator", font=ctk.CTkFont(size=24, weight="bold"))
        self.title_label.grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 10))

        self.normal_attack_frame = ctk.CTkFrame(self)
        self.normal_attack_frame.grid(row=1, column=0, padx=(20, 10), pady=10, sticky="ew")
        self.normal_attack_frame.grid_columnconfigure(1, weight=1)
        
        self.reps_label = ctk.CTkLabel(self.normal_attack_frame, text="Attack Reps:", font=ctk.CTkFont(size=14))
        self.reps_label.grid(row=0, column=0, padx=(10, 5), pady=10)
        
        self.reps_entry = ctk.CTkEntry(self.normal_attack_frame)
        self.reps_entry.grid(row=0, column=1, padx=(0, 10), pady=10, sticky="ew")
        self.reps_entry.insert(0, "10")

        self.start_normal_button = ctk.CTkButton(self.normal_attack_frame, text="Start Normal Attack", command=self.start_normal_attack_from_gui, height=40, font=ctk.CTkFont(size=14, weight="bold"))
        self.start_normal_button.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")

        self.builder_attack_frame = ctk.CTkFrame(self)
        self.builder_attack_frame.grid(row=1, column=1, padx=(10, 20), pady=10, sticky="nsew")
        self.builder_attack_frame.grid_rowconfigure(0, weight=1)
        self.builder_attack_frame.grid_columnconfigure(0, weight=1)
        self.start_builder_button = ctk.CTkButton(self.builder_attack_frame, text="Start Builder Attack", command=lambda: self.bot.start('builder'), height=40, font=ctk.CTkFont(size=14, weight="bold"), fg_color="#1F618D", hover_color="#2980B9")
        self.start_builder_button.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.stop_button = ctk.CTkButton(self, text="Stop Automation", command=self.bot.stop, height=40, fg_color="#D35400", hover_color="#B84300", font=ctk.CTkFont(size=14, weight="bold"))
        self.stop_button.grid(row=2, column=0, columnspan=2, padx=20, pady=10, sticky="ew")

        self.status_frame = ctk.CTkFrame(self, corner_radius=10)
        self.status_frame.grid(row=3, column=0, columnspan=2, padx=20, pady=(0, 20), sticky="nsew")
        self.status_frame.grid_rowconfigure(0, weight=1)
        self.status_frame.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(self.status_frame, text="Status: Ready", font=ctk.CTkFont(size=16), wraplength=450)
        self.status_label.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def start_normal_attack_from_gui(self):
        reps_str = self.reps_entry.get()
        try:
            reps = int(reps_str)
            if reps <= 0:
                reps = 10
                self.update_status("Reps must be positive. Defaulting to 10.")
        except ValueError:
            reps = 10
            self.update_status("Invalid input for reps. Defaulting to 10.")
        
        self.bot.start('normal', reps=reps)

    def update_status(self, message):
        self.status_label.configure(text=message)

    def on_closing(self):
        self.bot.stop()
        self.destroy()

if __name__ == "__main__":
    if not os.path.exists("templates"):
        os.makedirs("templates")
        print("Created 'templates' directory. Please place your images there.")
    app = App()
    app.mainloop()