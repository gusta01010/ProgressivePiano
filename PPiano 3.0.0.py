import tkinter as tk
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageTk
import keyboard
from pynput.keyboard import Controller, Key
from threading import Lock
import time, re, random, os, base64
from io import BytesIO
import tempfile, logging, concurrent.futures, collections

logger = logging.getLogger(__name__)

try:
    from images import ICON_BASE64, BACKGROUND_IMAGE
except ImportError:
    ICON_BASE64 = BACKGROUND_IMAGE = ""

class NoteMapper:
    """Handles Char to MIDI and Shift Logic."""
    SHIFT_MAP = {
        '1': '!', '2': '@', '3': '#', '4': '$', '5': '%',
        '6': '^', '7': '&', '8': '*', '9': '(', '0': ')',
        '-': '_', '=': '+', '[': '{', ']': '}', '\\': '|',
        ';': ':', "'": '"', ',': '<', '.': '>', '/': '?', '`': '~'
    }
    REVERSE_SHIFT_MAP = {v: k for k, v in SHIFT_MAP.items()}
    NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    KEY_TO_NOTE_NAME = {
        '1': 'C2',  '!': 'C#2', '2': 'D2',  '@': 'D#2', '3': 'E2',  '4': 'F2',
        '$': 'F#2', '5': 'G2',  '%': 'G#2', '6': 'A2',  '^': 'A#2', '¨': 'A#2', '7': 'B2',
        '8': 'C3',  '*': 'C#3', '9': 'D3',  '(': 'D#3', '0': 'E3',  'q': 'F3',
        'Q': 'F#3', 'w': 'G3',  'W': 'G#3', 'e': 'A3',  'E': 'A#3', 'r': 'B3',
        't': 'C4',  'T': 'C#4', 'y': 'D4',  'Y': 'D#4', 'u': 'E4',  'i': 'F4',
        'I': 'F#4', 'o': 'G4',  'O': 'G#4', 'p': 'A4',  'P': 'A#4', 'a': 'B4',
        's': 'C5',  'S': 'C#5', 'd': 'D5',  'D': 'D#5', 'f': 'E5',  'g': 'F5',
        'G': 'F#5', 'h': 'G5',  'H': 'G#5', 'j': 'A5',  'J': 'A#5', 'k': 'B5',
        'l': 'C6',  'L': 'C#6', 'z': 'D6',  'Z': 'D#6', 'x': 'E6',  'c': 'F6',
        'C': 'F#6', 'v': 'G6',  'V': 'G#6', 'b': 'A6',  'B': 'A#6', 'n': 'B6',
        'm': 'C7'
    }

    def __init__(self):
        self.note_name_to_midi = {f"{note}{octave}": 12 * (octave + 1) + i 
                                  for octave in range(-1, 9) for i, note in enumerate(self.NOTE_NAMES)}
        self.char_to_midi = {char: self.note_name_to_midi[name] 
                             for char, name in self.KEY_TO_NOTE_NAME.items() if name in self.note_name_to_midi}
        self.midi_to_char = {midi: char for char, midi in self.char_to_midi.items()}
        self.midi_range = (self.char_to_midi.get('1', 0), self.char_to_midi.get('m', 127))

class MusicTheory:
    """Handles Auto-Bass and Auto-Chord logic."""
    MAJOR_SCALE_CHORDS = {0: [4, 7], 2: [3, 7], 4: [3, 7], 5: [4, 7], 7: [4, 7], 9: [3, 7], 11: [3, 6]}
    MINOR_SCALE_CHORDS = {0: [3, 7], 2: [3, 6], 3: [4, 7], 5: [3, 7], 7: [3, 7], 8: [4, 7], 10: [4, 7]}
    MAJOR_KEY_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
    MINOR_KEY_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

    def __init__(self, mapper: NoteMapper):
        self.mapper = mapper
        self.root_midi = 0
        self.is_major = True

    def infer_key(self, key_stack):
        pitch_counts = collections.defaultdict(int)
        for element, _ in key_stack:
            clean = element.strip("[]")
            for char in clean:
                if char in self.mapper.char_to_midi:
                    pitch_counts[self.mapper.char_to_midi[char] % 12] += 1
        if not pitch_counts: return
        total = sum(pitch_counts.values())
        profile = [pitch_counts[i] / total for i in range(12)]
        best_corr = -1
        for root in range(12):
            corr_maj = sum(profile[i] * self.MAJOR_KEY_PROFILE[(i - root) % 12] for i in range(12))
            if corr_maj > best_corr: best_corr, self.root_midi, self.is_major = corr_maj, root, True
            corr_min = sum(profile[i] * self.MINOR_KEY_PROFILE[(i - root) % 12] for i in range(12))
            if corr_min > best_corr: best_corr, self.root_midi, self.is_major = corr_min, root, False

    def get_chord_notes(self, note_char):
        if note_char not in self.mapper.char_to_midi: return ""
        midi = self.mapper.char_to_midi[note_char]
        pitch_class = midi % 12
        scale_degree = (pitch_class - self.root_midi + 12) % 12
        chord_map = self.MAJOR_SCALE_CHORDS if self.is_major else self.MINOR_SCALE_CHORDS
        intervals = chord_map.get(scale_degree, [4, 7])
        return "".join([self.mapper.midi_to_char.get(midi + i, "") for i in intervals])

    def get_bass_note(self, note_char, mode_var, transpose_var, range_bounds):
        if note_char not in self.mapper.char_to_midi: return None
        midi = self.mapper.char_to_midi[note_char]
        mode = mode_var.get()
        final_midi = None
        if mode == "Smart Octave":
            final_midi = midi + int(transpose_var.get())
        elif mode == "Force to Low Range" and range_bounds:
            low, high = range_bounds
            pitch_class = midi % 12
            final_midi = low + pitch_class
            if final_midi > high: final_midi = low + (final_midi - low) % (high - low + 1)
            elif final_midi < low: final_midi = low + (final_midi - low) % (high - low + 1)
        return self.mapper.midi_to_char.get(final_midi)

class KeyboardSimulatorApp:
    def __init__(self, master):
        self.master = master
        self.setup_metadata()
        self.setup_window()
        
        self.mapper = NoteMapper()
        self.theory = MusicTheory(self.mapper)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=20)
        self.keyboard_controller = Controller()
        
        self.running = False
        self.lock = Lock()
        self.key_stack = []
        self.stack_pointer = 0
        self.sub_pointer_map = {} 
        self.is_inverted = False
        
        self.active_notes_by_source = {} 
        self.sim_key_counts = collections.defaultdict(int)
        self.shift_needed_count = 0
        self.control_keys_state = {}
        self.processing_lock = False 

        self.setup_variables()
        self.setup_ui_assets()
        self.create_widgets()
        self.setup_input_hooks()

    def setup_metadata(self):
        self.version = "3.0.0"
        self.product_name = "PPiano"
        self.master.title(f"{self.product_name} v{self.version}")

    def setup_window(self):
        self.master.geometry("600x520")
        self.master.resizable(False, False)
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_variables(self):
        self.always_on_top = tk.BooleanVar(value=False)
        self.imperfect_mode_var = tk.BooleanVar(value=False)
        self.imperfect_type = tk.StringVar(value="New")
        
        self.imperfect_perfect_chord_chance = 0.1
        self.initial_max_imperfect_delay = 0.05
        self.delay_reduction_percentage_per_key = 0.1
        self.min_imperfect_delay_cap = 0.005
        
        self.old_imperfect_perfect_chord_chance = 0.05
        self.old_initial_max_imperfect_delay = 0.109
        self.old_delay_reduction_percentage_per_key = 0.55
        self.old_min_imperfect_delay_cap = 0.020

        self.smart_release_enabled = tk.BooleanVar(value=False)
        self.conflict_release_enabled = tk.BooleanVar(value=True)
        self.chord_mode_enabled = tk.BooleanVar(value=False)
        self.bass_mode_enabled = tk.BooleanVar(value=False)
        self.bass_mode = tk.StringVar(value="Smart Octave")
        self.bass_transpose_level = tk.IntVar(value=-12)
        self.transpose_display_var = tk.StringVar(value="-12 semitones")
        self.bass_note_interval = tk.IntVar(value=1)
        self.chord_type = tk.StringVar(value="Major")
        
        self.f_keys = {'f1', 'f2', 'f3', 'f4'}
        self.std_keys = {'-', '+', 'num *'}
        self.control_keys = self.f_keys.union(self.std_keys)
        
        self.forbidden_chars = {',', '-', '+', '.', '<', '>', '{', '}', ';', '/', ':', "'", '"', '`', '~', '_', '|', '=', '?', '\\', '[', ']'}
        self.releasable_chars = {chr(c) for c in range(ord('e'), ord('z') + 1)}

    def setup_ui_assets(self):
        if BACKGROUND_IMAGE:
            try:
                img_data = base64.b64decode(BACKGROUND_IMAGE)
                bg_img = Image.open(BytesIO(img_data)).resize((800, 600), Image.LANCZOS)
                overlay = Image.new('RGBA', bg_img.size, (0, 0, 0, 160))
                bg_img = Image.alpha_composite(bg_img.convert('RGBA'), overlay)
                self.bg_photo = ImageTk.PhotoImage(bg_img)
                self.canvas = tk.Canvas(self.master, width=800, height=600)
                self.canvas.pack(fill="both", expand=True)
                self.canvas.create_image(0, 0, image=self.bg_photo, anchor="nw")
            except Exception: self.master.configure(bg="#1a1a1a")
        else: self.master.configure(bg="#1a1a1a")
        
        if ICON_BASE64:
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.ico') as tmp:
                    tmp.write(base64.b64decode(ICON_BASE64))
                    tmp.close()
                    self.master.iconbitmap(tmp.name)
                    os.unlink(tmp.name)
            except: pass

    def create_widgets(self):
        style = ttk.Style()
        style.theme_use('clam')
        bg_dark, fg_white = "#1a1a1a", "white"
        style.configure('.', background=bg_dark, foreground=fg_white, font=('Roboto', 10))
        style.configure('TFrame', background=bg_dark)
        style.configure('TButton', background="#333", foreground="white", borderwidth=1)
        style.map('TButton', background=[('active', '#444')])
        style.configure("Green.TCheckbutton", background=bg_dark, foreground="#4dff4d")
        style.configure("Red.TCheckbutton", background=bg_dark, foreground="#ff4d4d")

        self.text_display = ScrolledText(self.master, wrap=tk.WORD, width=50, height=10, 
                                         font=('Roboto', 10, 'bold'), bg=bg_dark, fg=fg_white, 
                                         insertbackground="white", selectbackground="#550055",
                                         state='disabled', cursor="arrow")
        self.text_display.place(relx=0.5, rely=0.4, anchor="center")
        self.text_display.bind("<Button-1>", self.on_text_click)
        self.text_display.tag_configure("highlight", background="#770077")

        self.file_list = tk.Listbox(self.master, bg=bg_dark, fg=fg_white, selectbackground="#550055")
        self.file_list.bind('<Double-1>', self.on_file_select)
        
        panel = ttk.Frame(self.master)
        panel.place(relx=0.5, rely=0.82, anchor="center")
        
        g_gen = ttk.LabelFrame(panel, text="General")
        g_gen.pack(side="left", padx=5, fill="y")
        ttk.Button(g_gen, text="Load File", command=self.load_file).pack(fill="x", padx=2, pady=2)
        ttk.Checkbutton(g_gen, text="Always on Top", variable=self.always_on_top, command=self.toggle_top).pack(anchor="w")
        
        imperfect_frame = ttk.Frame(g_gen)
        imperfect_frame.pack(anchor="w")
        ttk.Checkbutton(imperfect_frame, text="Imperfect Mode", variable=self.imperfect_mode_var).pack(side="left")
        ttk.Radiobutton(imperfect_frame, text="New", variable=self.imperfect_type, value="New").pack(side="left", padx=5)
        ttk.Radiobutton(imperfect_frame, text="Old", variable=self.imperfect_type, value="Old").pack(side="left", padx=5)
        
        ttk.Checkbutton(g_gen, text="Smart Release", variable=self.smart_release_enabled, command=self.update_check_styles).pack(anchor="w")
        ttk.Checkbutton(g_gen, text="Conflict Release", variable=self.conflict_release_enabled).pack(anchor="w")
        ttk.Button(g_gen, text="Invert Direction", command=self.toggle_invert).pack(fill="x", padx=2, pady=2)

        g_chord = ttk.LabelFrame(panel, text="Auto Chord")
        g_chord.pack(side="left", padx=5, fill="y")
        self.chk_chord = ttk.Checkbutton(g_chord, text="Enable", variable=self.chord_mode_enabled, command=self.update_check_styles)
        self.chk_chord.pack(anchor="w")
        ttk.Radiobutton(g_chord, text="Major", variable=self.chord_type, value="Major").pack(anchor="w")
        ttk.Radiobutton(g_chord, text="Minor", variable=self.chord_type, value="Minor").pack(anchor="w")

        g_bass = ttk.LabelFrame(panel, text="Auto Bass")
        g_bass.pack(side="left", padx=5, fill="y")
        self.chk_bass = ttk.Checkbutton(g_bass, text="Enable", variable=self.bass_mode_enabled, command=self.update_check_styles)
        self.chk_bass.pack(anchor="w")
        ttk.Radiobutton(g_bass, text="Smart Octave", variable=self.bass_mode, value="Smart Octave").pack(anchor="w")
        ttk.Radiobutton(g_bass, text="Force Low", variable=self.bass_mode, value="Force to Low Range").pack(anchor="w")
        
        t_frame = ttk.Frame(g_bass)
        t_frame.pack(fill="x", pady=5)
        ttk.Label(t_frame, text="Transpose:").pack(side="left")
        ttk.Label(t_frame, textvariable=self.transpose_display_var).pack(side="right")
        ttk.Scale(g_bass, from_=-24, to=-1, variable=self.bass_transpose_level, command=self.update_transpose_lbl).pack(fill="x")

        self.toggle_button = ttk.Button(self.master, text="📁", command=self.toggle_file_view, width=3)
        self.toggle_button.place(relx=0.88, rely=0.4, anchor="w")
        self.status_lbl = ttk.Label(self.master, text="Ready. Press F1-F4 or Numpad keys.", font=('Roboto', 9))
        self.status_lbl.place(relx=0.5, rely=0.2, anchor="center")
        self.update_check_styles()

    def update_check_styles(self):
        for var, widget in [(self.chord_mode_enabled, self.chk_chord), (self.bass_mode_enabled, self.chk_bass)]:
            widget.config(style="Green.TCheckbutton" if var.get() else "Red.TCheckbutton")

    def update_transpose_lbl(self, val):
        self.transpose_display_var.set(f"{int(float(val))} semitones")

    def setup_input_hooks(self):
        try:
            keyboard.unhook_all()
            for k in self.control_keys:
                keyboard.on_press_key(k, self.on_hotkey_press)
                keyboard.on_release_key(k, self.on_hotkey_release)
            keyboard.on_press_key('end', self.on_end_press)
            keyboard.on_press_key('pause', lambda e: self.smart_release_enabled.set(not self.smart_release_enabled.get()))
            keyboard.on_press_key(',', self.on_reset_press)
            keyboard.on_press_key('page up', self.toggle_harmony_hotkey)
            self.running = True
        except Exception as e: logger.error(f"Failed to setup hooks: {e}")

    def on_hotkey_press(self, event):
        if not self.running or not self.key_stack: return
        key_name = event.name.lower()
        if self.control_keys_state.get(key_name, False): return
        if self.processing_lock: return
        self.control_keys_state[key_name] = True
        self.executor.submit(self.process_keypress_logic, key_name)

    def on_hotkey_release(self, event):
        key_name = event.name.lower()
        self.control_keys_state[key_name] = False
        self.executor.submit(self.process_keyrelease_logic, key_name)

    def process_keypress_logic(self, trigger_key):
        with self.lock:
            self.processing_lock = True
            
            self.ensure_valid_pointer()

            if self.stack_pointer >= len(self.key_stack):
                if hasattr(self, 'current_file_index') and self.file_list.size() > 0:
                    next_index = (self.current_file_index + 1) % self.file_list.size()
                    self.current_file_index = next_index
                    self.file_list.selection_clear(0, tk.END)
                    self.file_list.selection_set(self.current_file_index)
                    self.file_list.activate(self.current_file_index)
                    self.load_selected_file()
                    self.status_lbl.config(text=f"Auto-advanced to: {os.path.basename(self.file_list.get(self.current_file_index))}")
                self.processing_lock = False
                return

            index = self.get_current_stack_index()
            raw_element, _ = self.key_stack[index]

            notes_to_play, advance_stack = self._get_next_payload(index, raw_element, trigger_key)

            if not notes_to_play:
                if advance_stack:
                    self.stack_pointer += 1
                    self.ensure_valid_pointer()
                    self.schedule_ui_update()
                return

            if self.smart_release_enabled.get(): self._handle_smart_release()

            is_primary = (index not in self.sub_pointer_map) or (self.sub_pointer_map[index] == 0)
            final_sequence = notes_to_play
            if is_primary: final_sequence += self._calculate_harmony(notes_to_play)

            if advance_stack:
                self.stack_pointer += 1
                if index in self.sub_pointer_map: del self.sub_pointer_map[index]
                self.ensure_valid_pointer()
            
            self.schedule_ui_update()
            
            if trigger_key in self.active_notes_by_source:
                self._release_source(trigger_key)
            
            if self.conflict_release_enabled.get():
                for other_key, active_notes in list(self.active_notes_by_source.items()):
                    if other_key == trigger_key: continue
                    
                    conflicting = [c for c in active_notes if c in final_sequence]
                    if conflicting:
                        new_notes = "".join([c for c in active_notes if c not in conflicting])
                        self.active_notes_by_source[other_key] = new_notes
                        
                        for c in conflicting:
                            self._release_single_note_logic(c)

            self.active_notes_by_source[trigger_key] = ""
            
            self._press_notes_ref_counted(final_sequence, trigger_key)
            
            if not self.control_keys_state.get(trigger_key, False):
                self._release_source(trigger_key)
            
            self.processing_lock = False

    def ensure_valid_pointer(self):
        """
        Advances stack_pointer until it sits on an element that contains at least one valid note char.
        """
        while self.stack_pointer < len(self.key_stack):
            idx = self.get_current_stack_index()
            raw_element, _ = self.key_stack[idx]
            
            is_group = raw_element.startswith('[')
            content = raw_element.strip('[]') if is_group else raw_element
            
            has_valid = any(c for c in content if c not in self.forbidden_chars)
            
            if has_valid:
                return
            
            self.stack_pointer += 1

    def _get_next_payload(self, index, raw_element, trigger_key):
        is_group = raw_element.startswith('[')
        content = raw_element.strip('[]') if is_group else raw_element
        valid_content = ''.join([c for c in content if c not in self.forbidden_chars])
        
        if not valid_content: return None, True

        sub_idx = self.sub_pointer_map.get(index, 0)

        if trigger_key in self.f_keys and is_group and len(valid_content) > 1:
            if sub_idx >= len(valid_content): return None, True
            
            char = valid_content[sub_idx]
            next_sub = sub_idx + 1
            if next_sub >= len(valid_content): return char, True 
            else:
                self.sub_pointer_map[index] = next_sub
                return char, False 
        
        return valid_content[sub_idx:], True

    def _calculate_harmony(self, melody_notes):
        if not melody_notes: return ""
        extras, primary_char = "", melody_notes[0]
        if self.bass_mode_enabled.get():
            if self.bass_note_interval.get() <= 1 or (self.stack_pointer % self.bass_note_interval.get() == 0):
                 bass = self.theory.get_bass_note(primary_char, self.bass_mode, self.bass_transpose_level, self.mapper.midi_range)
                 if bass and bass != primary_char: extras += bass
        if self.chord_mode_enabled.get(): extras += self.theory.get_chord_notes(primary_char)
        return extras

    def _press_notes_ref_counted(self, chars, trigger_key):
        sorted_chars = sorted(chars, key=lambda c: self.mapper.char_to_midi.get(c, 999))
        delays = {}
        if self.imperfect_mode_var.get() and len(sorted_chars) > 1:
            if self.imperfect_type.get() == "New":
                base_delay = random.uniform(0.000, 0.013)
                for i, c in enumerate(sorted_chars):
                    jitter = random.uniform(-0.005, 0.012)
                    delays[c] = max(0, i * base_delay + jitter)
                
                if random.random() < 0.15 and len(sorted_chars) >= 3:
                    idx = random.randint(0, len(sorted_chars) - 2)
                    sorted_chars[idx], sorted_chars[idx + 1] = sorted_chars[idx + 1], sorted_chars[idx]
            else:
                if random.random() < self.old_imperfect_perfect_chord_chance:
                    for c in sorted_chars:
                        delays[c] = 0.0
                else:
                    current_max_delay_cap = self.old_initial_max_imperfect_delay
                    
                    for i, c in enumerate(sorted_chars):
                        if i == 0:
                            delays[c] = 0.0
                        else:
                            delays[c] = random.uniform(0.0, current_max_delay_cap)
                            current_max_delay_cap = max(
                                current_max_delay_cap * (1 - self.old_delay_reduction_percentage_per_key),
                                self.old_min_imperfect_delay_cap
                            )
        else:
            for c in sorted_chars: delays[c] = 0

        for char in sorted_chars:
            d = delays[char]
            if d > 0:
                if not self.control_keys_state.get(trigger_key, False):
                    break
                time.sleep(d)
            
            if not self.control_keys_state.get(trigger_key, False):
                break
            
            base_key, needs_shift = self._get_key_info(char)
            if needs_shift:
                self.keyboard_controller.press(Key.shift)
                self.shift_needed_count += 1
            else:
                self.keyboard_controller.release(Key.shift)

            current_count = self.sim_key_counts[base_key]
            if current_count > 0:
                self.keyboard_controller.release(base_key)
                time.sleep(0.005) 
                self.keyboard_controller.press(base_key)
            else:
                self.keyboard_controller.press(base_key)
            
            self.sim_key_counts[base_key] += 1
            
            if trigger_key not in self.active_notes_by_source:
                self.active_notes_by_source[trigger_key] = ""
            self.active_notes_by_source[trigger_key] += char

    def process_keyrelease_logic(self, trigger_key):
        with self.lock:
            self._release_source(trigger_key)

    def _release_single_note_logic(self, char):
        base_key, needs_shift = self._get_key_info(char)
        
        if needs_shift:
            self.keyboard_controller.press(Key.shift)
            self.shift_needed_count -= 1
        else:
            self.keyboard_controller.release(Key.shift)

        self.sim_key_counts[base_key] -= 1
        if self.sim_key_counts[base_key] <= 0:
            self.sim_key_counts[base_key] = 0
            self.keyboard_controller.release(base_key)
        
        if needs_shift:
            self.keyboard_controller.release(Key.shift)

    def _release_source(self, source_key):
        chars = self.active_notes_by_source.pop(source_key, None)
        if not chars: return
        
        chars_list = list(chars)
        if self.imperfect_mode_var.get() and len(chars_list) > 1:
            if self.imperfect_type.get() == "New":
                if random.random() < 0.2:
                    random.shuffle(chars_list)
        
        for i, char in enumerate(chars_list):
            if self.imperfect_mode_var.get() and i > 0 and len(chars_list) > 1:
                if self.imperfect_type.get() == "New":
                    delay = random.uniform(0.000, 0.018)
                else:
                    jitter_range = getattr(self, 'human_release_jitter_ms', (5, 25))
                    delay = random.uniform(jitter_range[0], jitter_range[1]) / 1000.0
                time.sleep(delay)
            
            self._release_single_note_logic(char)

    def _get_key_info(self, char):
        if char in self.mapper.REVERSE_SHIFT_MAP:
            return self.mapper.REVERSE_SHIFT_MAP[char], True
        elif char.isupper():
            return char.lower(), True
        return char, False

    def _handle_smart_release(self):
        keys_to_clean = []
        for t_key, notes in self.active_notes_by_source.items():
            high_notes = [n for n in notes if n.lower() in self.releasable_chars and self.mapper.char_to_midi.get(n, 0) >= 60]
            if high_notes:
                remaining = "".join([n for n in notes if n not in high_notes])
                self.active_notes_by_source[t_key] = remaining
                if not remaining: keys_to_clean.append(t_key)
                
                for char in high_notes:
                    self._release_single_note_logic(char)
        for k in keys_to_clean:
            if k in self.active_notes_by_source: del self.active_notes_by_source[k]

    def get_current_stack_index(self):
        if not self.key_stack: return 0
        return len(self.key_stack) - 1 - self.stack_pointer if self.is_inverted else self.stack_pointer

    def schedule_ui_update(self): self.master.after_idle(self.update_text_highlight)

    def update_text_highlight(self):
        self.text_display.tag_remove("highlight", "1.0", tk.END)
        if self.stack_pointer >= len(self.key_stack): return
        idx = self.get_current_stack_index()
        if 0 <= idx < len(self.key_stack):
            _, pos = self.key_stack[idx]
            raw_text = self.key_stack[idx][0]
            self.text_display.tag_add("highlight", f"1.0 + {pos} chars", f"1.0 + {pos + len(raw_text)} chars")
            self.text_display.see(f"1.0 + {pos} chars")

    def load_file(self):
        fname = filedialog.askopenfilename(filetypes=[("Text", "*.txt")])
        if fname: self.process_file_load(fname)

    def process_file_load(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f: content = f.read()
            self.current_file = os.path.basename(filepath)
            self.master.title(f"{self.product_name} - {self.current_file}")
            self.text_display.configure(state='normal')
            self.text_display.delete(1.0, tk.END)
            self.text_display.insert(tk.END, content)
            self.text_display.configure(state='disabled')
            self.key_stack = []
            for match in re.compile(r'(\[[^\]]+\])|([^ \n\t])').finditer(content):
                self.key_stack.append((match.group(), match.start()))
            self.stack_pointer = 0
            self.sub_pointer_map.clear()
            self.active_notes_by_source.clear()
            self.sim_key_counts.clear()
            self.shift_needed_count = 0
            self.theory.infer_key(self.key_stack)
            self.ensure_valid_pointer()
            self.update_text_highlight()
        except Exception as e: logger.error(f"Load error: {e}")

    def toggle_file_view(self):
        if self.file_list.winfo_ismapped():
            self.file_list.place_forget()
            self.text_display.place(relx=0.5, rely=0.4, anchor="center")
        else:
            self.text_display.place_forget()
            self.file_list.place(relx=0.5, rely=0.4, anchor="center", width=420, height=170)
            self.refresh_file_list()

    def refresh_file_list(self):
        self.file_list.delete(0, tk.END)
        files = [f for f in os.listdir('.') if f.endswith('.txt')]
        if os.path.exists('Sheets'): files += [os.path.join('Sheets', f) for f in os.listdir('Sheets') if f.endswith('.txt')]
        for f in files: self.file_list.insert(tk.END, f)

    def on_file_select(self, event):
        sel = self.file_list.curselection()
        if sel:
            self.process_file_load(self.file_list.get(sel[0]))
            self.toggle_file_view()

    def toggle_invert(self):
        self.is_inverted = not self.is_inverted
        self.stack_pointer = 0
        self.ensure_valid_pointer()
        self.schedule_ui_update()

    def toggle_top(self): self.master.attributes('-topmost', self.always_on_top.get())
    
    def on_reset_press(self, e):
        with self.lock:
            self.stack_pointer = 0
            self.sub_pointer_map.clear()
            self.active_notes_by_source.clear()
            self.sim_key_counts.clear()
            self.shift_needed_count = 0
            self.ensure_valid_pointer()
            self.schedule_ui_update()

    def on_end_press(self, e):
        files = [f for f in os.listdir('.') if f.endswith('.txt')]
        if os.path.exists('Sheets'): files += [os.path.join('Sheets', f) for f in os.listdir('Sheets') if f.endswith('.txt')]
        if files: 
            target = random.choice(files)
            self.master.after(0, lambda: self.process_file_load(target))

    def toggle_harmony_hotkey(self, e):
        val = not self.bass_mode_enabled.get()
        self.bass_mode_enabled.set(val)
        self.update_check_styles()
        
    def on_text_click(self, event):
        try:
            click_index = self.text_display.index(f"@{event.x},{event.y}")
            click_offset_tuple = self.text_display.count("1.0", click_index, "chars")
            click_offset = click_offset_tuple[0] if click_offset_tuple else 0
            with self.lock:
                found_idx = 0
                for i, (element, start_pos) in enumerate(self.key_stack):
                    if start_pos > click_offset: break
                    found_idx = i 
                if self.is_inverted: self.stack_pointer = len(self.key_stack) - 1 - found_idx
                else: self.stack_pointer = found_idx
                self.sub_pointer_map.clear()
                self.ensure_valid_pointer()
                self.schedule_ui_update()
        except Exception: pass

    def on_closing(self):
        self.running = False
        keyboard.unhook_all()
        self.executor.shutdown(wait=False)
        self.master.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = KeyboardSimulatorApp(root)
    root.mainloop()