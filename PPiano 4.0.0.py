import tkinter as tk
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageTk
import keyboard
from pynput.keyboard import Controller, Key
from threading import Lock, Event
import time, re, random, os, base64
from io import BytesIO
import tempfile, logging, concurrent.futures, collections

logging.basicConfig(level=logging.WARNING, format='%(levelname)s - %(name)s: %(message)s')
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
        '$': 'F#2', '5': 'G2',  '%': 'G#2', '6': 'A2',  '^': 'A#2', '7': 'B2', # O trema foi removido daqui!
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
    def get_true_midi(self, char_str):
        """Retorna o MIDI real. Se tiver CTRL (\x11), desce 1 oitava (-12)."""
        if char_str.startswith('\x11'):
            base_char = char_str[1:]
            # Se no seu jogo o CTRL desce 2 oitavas em vez de 1, mude -12 para -24!
            return self.char_to_midi.get(base_char, 64) - 12
        return self.char_to_midi.get(char_str, 64)

    def get_char_from_midi(self, midi):
        """Transforma um número MIDI no caractere certo, botando o CTRL se for muito grave."""
        # Se for uma nota normal do teclado
        if midi in self.midi_to_char:
            return self.midi_to_char[midi]
        
        # Se a nota for EXTREMAMENTE grave (fora do mapa padrão),
        # ele sobe 1 oitava para achar a letra, e bota o '\x11' (CTRL) na frente!
        if midi + 12 in self.midi_to_char:
            return '\x11' + self.midi_to_char[midi + 12]
            
        return ""

    def __init__(self):
        self.note_name_to_midi = {f"{note}{octave}": 12 * (octave + 1) + i 
                                  for octave in range(-1, 9) for i, note in enumerate(self.NOTE_NAMES)}
        self.char_to_midi = {char: self.note_name_to_midi[name] 
                             for char, name in self.KEY_TO_NOTE_NAME.items() if name in self.note_name_to_midi}
        self.midi_to_char = {midi: char for char, midi in self.char_to_midi.items()}
        self.midi_range = (self.char_to_midi.get('1', 0), self.char_to_midi.get('m', 127))

class MusicTheory:
    """Handles Auto-Bass, Counter-Melody, Voice Leading and Ornaments."""
    MAJOR_KEY_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
    MINOR_KEY_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
    
    MAJOR_SCALE_STEPS = [0, 2, 4, 5, 7, 9, 11]
    MINOR_SCALE_STEPS = [0, 2, 3, 5, 7, 8, 10]

    def __init__(self, mapper: NoteMapper):
        self.mapper = mapper
        self.root_midi = 0
        self.is_major = True
        self.last_harmony_midi = None  # Memória para o Voice Leading

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

    def _calc_diatonic_interval(self, midi, step_shift):
        """Calcula uma nota N graus acima ou abaixo na escala atual."""
        scale = self.MAJOR_SCALE_STEPS if self.is_major else self.MINOR_SCALE_STEPS
        pitch_class = midi % 12
        octave = midi // 12
        relative_pitch = (pitch_class - self.root_midi + 12) % 12
        
        try: scale_idx = scale.index(relative_pitch)
        except ValueError: scale_idx = max([i for i, s in enumerate(scale) if s < relative_pitch], default=0)

        target_idx = (scale_idx + step_shift) % 7
        octave_shift = (scale_idx + step_shift) // 7
        target_relative_pitch = scale[target_idx]
        
        return (octave + octave_shift) * 12 + self.root_midi + target_relative_pitch

    def get_counter_melody(self, note_char, mode="Voice Leading"):
        base_char = note_char[1:] if note_char.startswith('\x11') else note_char
        if base_char not in self.mapper.char_to_midi:
            return ""

        midi = self.mapper.get_true_midi(note_char)
        if midi is None:
            return ""

        target_midi = None

        if mode == "Off":
            return ""
        elif mode == "Parallel Octave Below":
            target_midi = midi - 12
        elif mode == "Parallel Octave Above":
            target_midi = midi + 12
        elif mode == "Third Below":
            target_midi = self._calc_diatonic_interval(midi, -2)
        elif mode == "Third Above":
            target_midi = self._calc_diatonic_interval(midi, 2)
        elif mode == "Sixth Below":
            target_midi = self._calc_diatonic_interval(midi, -5)
        elif mode == "Sixth Above":
            target_midi = self._calc_diatonic_interval(midi, 5)
        elif mode == "Voice Leading":
            if self.last_harmony_midi is None:
                target_midi = self._calc_diatonic_interval(midi, -2)
            else:
                candidates = [
                    self._calc_diatonic_interval(midi, -2),
                    self._calc_diatonic_interval(midi, -4),
                    self._calc_diatonic_interval(midi, -5),
                ]
                target_midi = min(candidates, key=lambda x: abs(x - self.last_harmony_midi))
        else:
            return ""

        if target_midi is None or target_midi == midi:
            return ""

        self.last_harmony_midi = target_midi
        return self.mapper.get_char_from_midi(target_midi)

    def get_appoggiatura(self, note_char):
        """Gera a nota de enfeite APENAS para a melodia, com proteção contra dissonância."""
        if note_char not in self.mapper.char_to_midi: return None
        midi = self.mapper.char_to_midi[note_char]
        
        # REGRA 1: Apojatura APENAS na mão direita/melodia (Notas acima de C4 / MIDI 60).
        # Enfeitar os graves (como o 'q' ou '8' da partitura de Omori) estraga a música.
        if midi < 60: return None
        
        # Calcula 1 grau abaixo na escala
        app_midi = self._calc_diatonic_interval(midi, -1)
        
        # REGRA 2: A Proteção de Ouro.
        # Se a música mudou de tom e a nota caiu muito longe (mais de 2 semitons),
        # soará horrivelmente desafinado. Nós forçamos a ser exatamente 1 semitom (meio tom abaixo),
        # que é o clássico "Slide" de piano cromático que sempre soa lindo.
        distance = midi - app_midi
        if distance > 2 or distance < 1:
            app_midi = midi - 1
            
        return self.mapper.midi_to_char.get(app_midi)

    def get_bass_note(self, note_char, mode_var, transpose_var, range_bounds, pattern="Single", counter=0, root_midi=None):
        # Support CTRL-prefixed chars (e.g. '\x11q') — strip prefix for char lookup,
        # but use the TRUE sounding MIDI (one octave lower) for all calculations.
        base_char = note_char[1:] if note_char.startswith('\x11') else note_char
        if base_char not in self.mapper.char_to_midi: return ""
        melody_midi = self.mapper.get_true_midi(note_char)  # honours the \x11 octave shift
        mode = mode_var.get()
        
        base_midi = None
        if mode == "Smart Octave":
            base_midi = melody_midi + int(transpose_var.get())
            while base_midi > melody_midi - 7: base_midi -= 12
        elif mode == "Force to Low Range" and range_bounds:
            base_midi = 36 + (melody_midi % 12)
            if base_midi < range_bounds[0]: base_midi += 12
            if melody_midi > 72 and base_midi + 12 <= range_bounds[1]: base_midi += 12
        
        if base_midi is None: return ""
        if root_midi is None: root_midi = self.root_midi
        
        result_midis =[]
        
        # --- A MÁGICA DIATÔNICA (Para o baixo nunca mais desafinar!) ---
        # 0 = Tônica, 2 = Terça diatônica, 4 = Quinta diatônica, 5 = Sexta, 7 = Oitava
        
        if pattern == "Single": 
            result_midis.append(base_midi)
        elif pattern == "Octave": 
            result_midis.extend([base_midi, base_midi + 12])
        elif pattern == "Power": 
            # Root + Quinta Diatônica (Garante que a 5ª se encaixe na escala)
            result_midis.extend([base_midi, self._calc_diatonic_interval(base_midi, 4)])
        elif pattern == "Root-5th": 
            # Alterna Tônica e Quinta Diatônica
            target_step = 0 if counter % 2 == 0 else 4
            result_midis.append(self._calc_diatonic_interval(base_midi, target_step))
        elif pattern == "Alberti": 
            # Tônica -> Quinta -> Terça -> Quinta (100% dentro do tom da música)
            steps =[0, 4, 2, 4]
            result_midis.append(self._calc_diatonic_interval(base_midi, steps[counter % 4]))
        elif pattern == "Walking": 
            # Tônica -> Terça -> Quinta -> Sexta
            steps =[0, 2, 4, 5]
            result_midis.append(self._calc_diatonic_interval(base_midi, steps[counter % 4]))
        elif pattern == "Arpeggio": 
            # Tônica -> Terça -> Quinta -> Oitava
            steps =[0, 2, 4, 7]
            result_midis.append(self._calc_diatonic_interval(base_midi, steps[counter % 4]))
        elif pattern == "Boogie": 
            # Tônica -> Quinta -> Sexta -> Quinta
            steps = [0, 4, 5, 4]
            result_midis.append(self._calc_diatonic_interval(base_midi, steps[counter % 4]))
        elif pattern == "Pedal":
            pedal_midi = base_midi - (base_midi % 12) + root_midi
            if pedal_midi > base_midi + 5: pedal_midi -= 12
            if pedal_midi < base_midi - 7: pedal_midi += 12
            result_midis.append(pedal_midi)
            
        elif pattern == "Pump":
            # Root -> Root -> Fifth -> Root (estilo rock/punk)
            steps = [0, 0, 4, 0]
            result_midis.append(self._calc_diatonic_interval(base_midi, steps[counter % 4]))
        elif pattern == "Stride":
            # Alterna baixo grave e acorde (estilo ragtime/stride piano)
            if counter % 2 == 0:
                result_midis.append(base_midi)  # Nota grave no tempo forte
            else:
                # Acorde no contratempo (terça + quinta)
                result_midis.append(self._calc_diatonic_interval(base_midi + 12, 2))
                result_midis.append(self._calc_diatonic_interval(base_midi + 12, 4))
        # Convert to Valid Chars with Foldback Anti-Crash
        result = ""
        for m in result_midis:
            folded_m = m
            while folded_m < range_bounds[0]: folded_m += 12
            while folded_m > range_bounds[1]: folded_m -= 12
            # Safety: bass must sit at least a minor 3rd (3 semitones) below the melody.
            # Diatonic snapping can push a note up to within 1 semitone of the melody;
            # this loop folds it down one more octave if it's too close.
            while melody_midi - folded_m < 3:
                if folded_m - 12 >= range_bounds[0]:
                    folded_m -= 12
                else:
                    folded_m = -1
                    break
            if folded_m < 0:
                continue
            c = self.mapper.midi_to_char.get(folded_m)
            if c and c != base_char and c not in result:
                result += c
                
        return result

class KeyboardSimulatorApp:
    # ── Timing and probability constants ──────────────────────────────────────
    GRACE_NOTE_CHANCE    = 0.20   # Probability of a grace note (appoggiatura)
    GRACE_NOTE_DURATION  = 0.04   # Seconds the grace note is held
    KEY_SETTLE_TIME      = 0.004  # Seconds for OS to register a modifier change
    # ──────────────────────────────────────────────────────────────────────────

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
        self.ctrl_needed_count = 0
        self.control_keys_state = {}
        # Per-trigger cancellation: lets us interrupt imperfect press timing immediately on key-up.
        # (Important for large sets like [abcdefghijklm] where press timing can span 100ms+.)
        self._press_cancel_events = {}

        self.setup_variables()
        self.setup_ui_assets()
        self.create_widgets()
        self.setup_input_hooks()

    def setup_metadata(self):
        self.version = "4.0.0"
        self.product_name = "PPiano"
        self.master.title(f"{self.product_name} v{self.version}")

    def setup_window(self):
        self.master.geometry("720x520")
        self.master.resizable(False, False)
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_variables(self):
        self.always_on_top = tk.BooleanVar(value=False)
        self.imperfect_mode_var = tk.BooleanVar(value=False)
        self.imperfect_type = tk.StringVar(value="New")
        
        self.imperfect_perfect_chord_chance = 0.1
        self.initial_max_imperfect_delay = 0.07
        self.delay_reduction_percentage_per_key = 0.1
        self.min_imperfect_delay_cap = 0.000
        
        self.old_imperfect_perfect_chord_chance = 0.05
        self.old_initial_max_imperfect_delay = 0.109
        self.old_delay_reduction_percentage_per_key = 0.55
        self.old_min_imperfect_delay_cap = 0.00

        # Imperfect release feel (timing between releasing individual notes in a chord).
        # Keep small to avoid the old "keeps going toward Z after release" feeling.
        # Values are milliseconds.
        self.imperfect_release_jitter_ms = (0, 92)
        self.old_imperfect_release_jitter_ms = (0, 40)
        
        # Physical hand simulation for "New" imperfect mode
        self.hand_left_midi_pos = 48.0  # Bass side (approx C3)
        self.hand_right_midi_pos = 72.0 # Treble side (approx C5)
        self.hand_travel_speed = 0.0006  # Faster travel speed

        self.smart_release_enabled = tk.BooleanVar(value=False)
        self.conflict_release_enabled = tk.BooleanVar(value=True)
        self.bass_mode_enabled = tk.BooleanVar(value=False)
        self.bass_mode = tk.StringVar(value="Smart Octave")
        self.bass_transpose_level = tk.IntVar(value=-12)
        self.transpose_display_var = tk.StringVar(value="-12 semitones")
        self.bass_note_interval = tk.IntVar(value=1)
        
        self.harmony_enabled = tk.BooleanVar(value=False)
        self.harmony_mode = tk.StringVar(value="Voice Leading")  # Padrão: Voice Leading

        self.shift_physically_pressed = False
        self.ctrl_physically_pressed = False

        self.strum_enabled = tk.BooleanVar(value=False)
        self.appoggiatura_enabled = tk.BooleanVar(value=False)

        # Enhanced bass mode options
        self.bass_pattern = tk.StringVar(value="Single")
        self.bass_pattern_counter = 0  # For alternating patterns
        
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

        # --- CONTAINER UNIFICADO: MUSICAL FEATURES ---
        g_features = ttk.LabelFrame(panel, text="Musical Features")
        g_features.pack(side="left", padx=5, fill="y")
        
        # 1. Harmonia / Contra Canto
        self.chk_harmony = ttk.Checkbutton(g_features, text="Enable Harmony", variable=self.harmony_enabled, command=self.update_check_styles)
        self.chk_harmony.pack(anchor="w", padx=5, pady=(5, 0))
        
        # Dropdown da Harmonia (com recuo de 22px para alinhar com o texto do checkbox)
        harmony_combo = ttk.Combobox(g_features, textvariable=self.harmony_mode, 
                                     values=["Voice Leading", "Third Below", "Third Above", "Sixth Below", "Sixth Above", "Parallel Octave Below", "Parallel Octave Above"], 
                                     state="readonly", width=19)
        harmony_combo.pack(anchor="w", padx=22, pady=(0, 8))
                     
        # 2. Ornamentos e Articulações
        ttk.Checkbutton(g_features, text="Strumming (Harpejar)", variable=self.strum_enabled).pack(anchor="w", padx=5, pady=(0, 2))
        ttk.Checkbutton(g_features, text="Grace Notes (Apojatura)", variable=self.appoggiatura_enabled).pack(anchor="w", padx=5, pady=(0, 5))
        
        # 3. Dica Visual
        ttk.Label(g_features, text="F5 = Magic Harpejo", foreground="#ffb347", font=('Roboto', 8, 'italic')).pack(anchor="w", padx=5, pady=(2, 5))
        # ----------------------------------------------
        g_bass = ttk.LabelFrame(panel, text="Auto Bass")
        g_bass.pack(side="left", padx=5, fill="y")
        self.chk_bass = ttk.Checkbutton(g_bass, text="Enable", variable=self.bass_mode_enabled, command=self.update_check_styles)
        self.chk_bass.pack(anchor="w")
        ttk.Radiobutton(g_bass, text="Smart Octave", variable=self.bass_mode, value="Smart Octave").pack(anchor="w")
        ttk.Radiobutton(g_bass, text="Force Low", variable=self.bass_mode, value="Force to Low Range").pack(anchor="w")
        
        # Bass pattern selection
        pattern_frame = ttk.Frame(g_bass)
        pattern_frame.pack(fill="x", pady=2)
        ttk.Label(pattern_frame, text="Pattern:").pack(side="left")
        bass_pattern_combo = ttk.Combobox(pattern_frame, textvariable=self.bass_pattern, 
                                          values=["Single", "Octave", "Power", "Root-5th", 
                                                  "Walking", "Arpeggio", "Boogie", "Pedal", 
                                                  "Pump", "Stride", "Alberti"], 
                                          state="readonly", width=10)
        bass_pattern_combo.pack(side="right")
        
        t_frame = ttk.Frame(g_bass)
        t_frame.pack(fill="x", pady=2)
        ttk.Label(t_frame, text="Transpose:").pack(side="left")
        ttk.Label(t_frame, textvariable=self.transpose_display_var).pack(side="right")
        ttk.Scale(g_bass, from_=-24, to=-0, variable=self.bass_transpose_level, command=self.update_transpose_lbl).pack(fill="x")

        self.toggle_button = ttk.Button(self.master, text="📁", command=self.toggle_file_view, width=3)
        self.toggle_button.place(relx=0.88, rely=0.4, anchor="w")
        self.status_lbl = ttk.Label(self.master, text="Ready │ F1-F4/Num=Play  F5=Gliss  PgUp=Bass  Pause=SmRls  ,=Reset  End=Random", font=('Roboto', 8))
        self.status_lbl.place(relx=0.5, rely=0.2, anchor="center")
        self.update_check_styles()

    def update_check_styles(self):
        for var, widget in [(self.harmony_enabled, self.chk_harmony), (self.bass_mode_enabled, self.chk_bass)]:
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
            keyboard.on_press_key('page up', self.toggle_bass_hotkey)
            keyboard.on_press_key('page down', self.toggle_harmony_hotkey)
            keyboard.on_press_key('f5', self.on_glissando_press)

            self.running = True
        except Exception as e: logger.error(f"Failed to setup hooks: {e}")

    def on_hotkey_press(self, event):
        if not self.running or not self.key_stack: return
        key_name = event.name.lower()
        if self.control_keys_state.get(key_name, False): return
        self.control_keys_state[key_name] = True
        self.executor.submit(self.process_keypress_logic, key_name)

    def on_hotkey_release(self, event):
        key_name = event.name.lower()
        self.control_keys_state[key_name] = False
        # Cancel any in-flight imperfect press timing for this trigger immediately.
        try:
            with self.lock:
                ev = self._press_cancel_events.get(key_name)
                if ev:
                    ev.set()
        except Exception:
            pass
        self.executor.submit(self.process_keyrelease_logic, key_name)

    def process_keypress_logic(self, trigger_key):
        final_sequence = ""
        release_after_press = False
        cancel_event = None
        prev_notes_to_release_immediately = ""

        try:
            with self.lock:
                prev = self._press_cancel_events.get(trigger_key)
                if prev: prev.set()
                cancel_event = Event()
                self._press_cancel_events[trigger_key] = cancel_event

                self.ensure_valid_pointer()
                if self.stack_pointer >= len(self.key_stack): return

                index = self.get_current_stack_index()
                raw_element, _ = self.key_stack[index]

                notes_to_play, advance_stack = self._get_next_payload(index, raw_element, trigger_key)

                if not notes_to_play:
                    if advance_stack:
                        self.stack_pointer += 1
                        self.ensure_valid_pointer()
                        self.schedule_ui_update()
                    return

                if self.smart_release_enabled.get():
                    smart_release_chars = self._compute_smart_releases(notes_to_play)
                else:
                    smart_release_chars = []

                is_primary = (index not in self.sub_pointer_map) or (self.sub_pointer_map[index] == 0)
                harmony_notes = self._calculate_harmony(notes_to_play) if is_primary else[]
                final_sequence = notes_to_play + harmony_notes

                if advance_stack:
                    self.stack_pointer += 1
                    if index in self.sub_pointer_map: del self.sub_pointer_map[index]
                    self.ensure_valid_pointer()

                self.schedule_ui_update()

                prev_notes_to_release_immediately = self.active_notes_by_source.pop(trigger_key,[])

                if self.conflict_release_enabled.get():
                    for other_key, active_notes in list(self.active_notes_by_source.items()):
                        if other_key == trigger_key: continue
                        conflicting =[c for c in active_notes if c in final_sequence]
                        if conflicting:
                            new_notes =[c for c in active_notes if c not in conflicting]
                            self.active_notes_by_source[other_key] = new_notes
                            for c in conflicting: self._release_single_note_logic(c)

                self.active_notes_by_source[trigger_key] =[]
                release_after_press = not self.control_keys_state.get(trigger_key, False)

            for char in smart_release_chars:
                with self.lock:
                    self._release_single_note_logic(char)
            
            if prev_notes_to_release_immediately:
                self._release_chars(prev_notes_to_release_immediately, apply_imperfect_jitter=False)

            # --- APOJATURA (GRACE NOTE) ---
            if self.appoggiatura_enabled.get() and final_sequence:
                # Pega a nota mais aguda (a melodia) para enfeitar, nunca o baixo!
                highest_char = max(final_sequence, key=lambda c: self.mapper.char_to_midi.get(c[1:] if c.startswith('\x11') else c, 0))
                char_lookup = highest_char[1:] if highest_char.startswith('\x11') else highest_char
                
                # GRACE_NOTE_CHANCE% de chance para surpreender o ouvido
                if random.random() < self.GRACE_NOTE_CHANCE:
                    app_char = self.theory.get_appoggiatura(char_lookup)
                    if app_char and app_char not in final_sequence:
                        def play_grace():
                            # Toca a nota de enfeite simultaneamente sem travar o teclado
                            base_k, shift, _ = self._get_key_info(app_char)
                            if shift: self.keyboard_controller.press(Key.shift)
                            self.keyboard_controller.press(base_k)
                            time.sleep(self.GRACE_NOTE_DURATION)
                            self.keyboard_controller.release(base_k)
                            if shift: self.keyboard_controller.release(Key.shift)
                        
                        self.executor.submit(play_grace)
            # ----------------------------------------

            # CORREÇÃO DAS NOTAS: O 'elif final_sequence' voltou para tocar os blocos [2up] !
            if harmony_notes:
                self._press_notes_ref_counted(notes_to_play, harmony_notes, trigger_key, cancel_event)
            elif final_sequence:
                self._press_notes_ref_counted(final_sequence,[], trigger_key, cancel_event)

            if release_after_press or (not self.control_keys_state.get(trigger_key, False)):
                self.process_keyrelease_logic(trigger_key)
        finally:
            try:
                with self.lock:
                    ev = self._press_cancel_events.get(trigger_key)
                    if ev is cancel_event:
                        self._press_cancel_events.pop(trigger_key, None)
            except Exception: pass

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
        
        parsed_notes = []
        in_ctrl = False
        for c in content:
            if c == ':': in_ctrl = True
            elif c == "'": in_ctrl = False
            elif c not in self.forbidden_chars:
                parsed_notes.append('\x11' + c if in_ctrl else c)
        
        if not parsed_notes: return None, True

        sub_idx = self.sub_pointer_map.get(index, 0)

        if trigger_key in self.f_keys and is_group and len(parsed_notes) > 1:
            if sub_idx >= len(parsed_notes): return None, True
            
            char = parsed_notes[sub_idx]
            next_sub = sub_idx + 1
            if next_sub >= len(parsed_notes): return [char], True 
            else:
                self.sub_pointer_map[index] = next_sub
                return [char], False 
        
        return parsed_notes[sub_idx:], True

    def _calculate_harmony(self, melody_notes):
        if not melody_notes:
            return []
        extras = []

        # Para BAIXO: usa a nota mais grave do acorde (raiz real da harmonia)
        primary_char = min(
            melody_notes,
            key=lambda c: self.mapper.char_to_midi.get(c[1:] if c.startswith('\x11') else c, 999)
        )
        uses_ctrl = primary_char.startswith('\x11')
        primary_char_lookup = primary_char[1:] if uses_ctrl else primary_char

        # Para HARMONIA: usa a nota MAIS AGUDA (a melodia real)
        melody_char = max(
            melody_notes,
            key=lambda c: self.mapper.char_to_midi.get(
                c[1:] if c.startswith('\x11') else c, 0
            )
        )
        melody_uses_ctrl = melody_char.startswith('\x11')

        # 1. Baixo (usa a primeira nota, como antes)
        if self.bass_mode_enabled.get():
            if self.bass_note_interval.get() <= 1 or (self.stack_pointer % self.bass_note_interval.get() == 0):
                # Pass the full primary_char (including any '\x11' prefix) so get_bass_note
                # can use the TRUE sounding MIDI for its calculations.  Do NOT re-apply the
                # CTRL prefix to the returned bass chars — they are already the correct
                # playable keys and adding '\x11' would shift them down yet another octave.
                bass = self.theory.get_bass_note(
                    primary_char, self.bass_mode, self.bass_transpose_level,
                    self.mapper.midi_range, self.bass_pattern.get(),
                    self.bass_pattern_counter, self.theory.root_midi
                )
                if bass:
                    for b in bass:
                        extras.append(b)  # never propagate CTRL to bass notes
                self.bass_pattern_counter += 1

        # 2. Contra Canto — aplicado à nota mais AGUDA (melodia)
        if self.harmony_enabled.get() and self.harmony_mode.get() != "Off":
            counter_note = self.theory.get_counter_melody(
                melody_char,  # ← COM prefixo \x11 se existir!
                self.harmony_mode.get()
            )
            if counter_note:
                if counter_note not in extras and counter_note != melody_char:
                    extras.append(counter_note)

        return extras
    
    def on_glissando_press(self, event):
        """Ativado pelo F5. Dispara um harpejo glorioso."""
        if not self.running: return
        self.executor.submit(self._play_glissando_fill)

    def _play_glissando_fill(self):
        """Toca um harpejo mágico (Pentatônico) com dinâmica de tempo humana."""
        # A mágica de Genshin/Zelda vem das escalas Pentatônicas!
        major_penta = [0, 2, 4, 7, 9]
        minor_penta = [0, 3, 5, 7, 10]
        penta_steps = major_penta if self.theory.is_major else minor_penta
        
        root = self.theory.root_midi
        start_midi = 48 + root # Começa nos graves
        
        notes_to_play = []
        
        # Constrói o harpejo subindo 3 oitavas completas
        for octave in range(3):
            for step in penta_steps:
                midi = start_midi + step + (octave * 12)
                char = self.mapper.midi_to_char.get(midi)
                if char and char not in notes_to_play:
                    notes_to_play.append(char)
                    
        if not notes_to_play: return
        
        # Toca as notas com "Curva de Expressão" (Rubato)
        total_notes = len(notes_to_play)
        for i, char in enumerate(notes_to_play):
            if not self.running: break
            
            base_key, needs_shift, _ = self._get_key_info(char)
            
            if needs_shift: self.keyboard_controller.press(Key.shift)
            self.keyboard_controller.press(base_key)
            
            # Dinâmica de tempo: O dedilhar acelera no meio e flutua no fim
            progress = i / total_notes
            if progress < 0.2: delay = 0.035       # Começa cadenciado
            elif progress < 0.8: delay = 0.015     # Acelera no meio do varrido
            else: delay = 0.045                    # Suaviza nas notas mais agudas
            
            time.sleep(delay)
            
            self.keyboard_controller.release(base_key)
            if needs_shift: self.keyboard_controller.release(Key.shift)

    def _precise_wait(self, duration, cancel_event=None):
        if duration <= 0: return False
        if duration > 0.02 or cancel_event:
            if cancel_event: return cancel_event.wait(duration)
            time.sleep(duration); return False
        end = time.perf_counter() + duration
        while time.perf_counter() < end: pass
        return False
    
    def _sort_by_modifier_group(self, chars):
        """Agrupa notas pelo modificador para evitar vazamento.
        Ordem: sem modificador → Ctrl → Shift → Ctrl+Shift
        Shift vem por ÚLTIMO para ficar seguro durante o acorde."""
        
        groups = {'none': [], 'ctrl': [], 'shift': [], 'both': []}
        
        for c in chars:
            _, needs_shift, needs_ctrl = self._get_key_info(c)
            if needs_shift and needs_ctrl:
                groups['both'].append(c)
            elif needs_ctrl:
                groups['ctrl'].append(c)
            elif needs_shift:
                groups['shift'].append(c)
            else:
                groups['none'].append(c)
        
        # Dentro de cada grupo, ordena por MIDI para consistência
        midi_key = lambda c: self.mapper.char_to_midi.get(
            c[1:] if c.startswith('\x11') else c, 999)
        
        for g in groups.values():
            g.sort(key=midi_key)
    
        return groups['none'] + groups['ctrl'] + groups['shift'] + groups['both']

    def _press_notes_ref_counted(self, melody_chars, harmony_chars, trigger_key, cancel_event=None):
        delays = {} 
        chars = melody_chars + harmony_chars
        
        # --- LÓGICA DE STRUMMING (Acordes Rolados) HUMANIZADA ---
        if self.strum_enabled.get() and len(chars) > 1:
            sorted_chars = sorted(chars, key=lambda c: self.mapper.char_to_midi.get(
                c[1:] if c.startswith('\x11') else c, 999))
            accum = 0.0
            for i, c in enumerate(sorted_chars):
                delays[c] = accum
                # Se for um acorde enorme [qetuo], passa o dedo rápido (20ms). 
                # Se for [IS], dedilha suave e devagar (35ms).
                base_delay = 0.035 if len(chars) <= 3 else 0.020
                
                # Efeito de Emoção: A última nota do acorde demora um instante a mais para cair
                if i == len(sorted_chars) - 2:
                    accum += base_delay + 0.015
                else:
                    accum += base_delay
                    
        elif self.imperfect_mode_var.get() and len(chars) > 1 and self.imperfect_type.get() == "New":
            # TWO-HANDED Physical Simulation: Left Hand (<= 70 MIDI) and Right Hand (> 70 MIDI)
            left_notes = []
            right_notes = []
            
            for c in melody_chars:
                char_lookup = c[1:] if c.startswith('\x11') else c
                midi = self.mapper.char_to_midi.get(char_lookup, 64)
                if midi <= 70: left_notes.append({'char': c, 'midi': midi, 'is_harmony': False})
                else: right_notes.append({'char': c, 'midi': midi, 'is_harmony': False})
            
            for c in harmony_chars:
                char_lookup = c[1:] if c.startswith('\x11') else c
                midi = self.mapper.char_to_midi.get(char_lookup, 64)
                if midi <= 70: left_notes.append({'char': c, 'midi': midi, 'is_harmony': True})
                else: right_notes.append({'char': c, 'midi': midi, 'is_harmony': True})

            with self.lock:
                total_active = sum(self.sim_key_counts.values())
            congestion = 1.0 + (total_active * 0.05)

            def calc_hand_delays(hand_notes, current_hand_pos):
                if not hand_notes: return {}, current_hand_pos
                
                # Priority: Harmony notes are calculated as starting at t=0
                # Melody notes are sorted by proximity to the hand
                res = {}
                
                # Split hand notes into harmony and melody
                h_notes = [n for n in hand_notes if n['is_harmony']]
                m_notes = [n for n in hand_notes if not n['is_harmony']]
                
                # Harmony notes hit instantly (t=0)
                for hn in h_notes:
                    res[hn['char']] = 0.0
                
                # Melody notes follow the physical simulation
                if m_notes:
                    m_notes.sort(key=lambda x: abs(x['midi'] - current_hand_pos))
                    accum = 0.0
                    prev_m = current_hand_pos
                    for i, data in enumerate(m_notes):
                        delta = abs(data['midi'] - prev_m)
                        if i == 0:
                            # Distance from hand to first melody note
                            accum = (delta * self.hand_travel_speed) * congestion
                        else:
                            # Staggering: significantly faster now for tight chords
                            stagger = (delta * 0.001) + random.uniform(0.001, 0.004)
                            accum += stagger * congestion
                        res[data['char']] = max(0, accum + random.uniform(-0.001, 0.002))
                        prev_m = data['midi']
                
                # New hand pos is avg of ALL notes played by this hand
                new_pos = sum(x['midi'] for x in hand_notes) / len(hand_notes)
                return res, new_pos

            # Calculate independent delays for both hands
            ld, new_l_pos = calc_hand_delays(left_notes, self.hand_left_midi_pos)
            rd, new_r_pos = calc_hand_delays(right_notes, self.hand_right_midi_pos)
            
            delays.update(ld)
            delays.update(rd)
            
            with self.lock:
                self.hand_left_midi_pos = (self.hand_left_midi_pos * 0.2) + (new_l_pos * 0.8)
                self.hand_right_midi_pos = (self.hand_right_midi_pos * 0.2) + (new_r_pos * 0.8)
            
            # Exec order is now by absolute time, allowing both hands to start simultaneously
            sorted_chars = sorted(delays.keys(), key=lambda c: delays[c])

        elif self.imperfect_mode_var.get() and len(chars) > 1:
            # Robotic/Old logic...
            sorted_chars = self._sort_by_modifier_group(chars)  
            if self.imperfect_type.get() == "Old":
                if random.random() < self.old_imperfect_perfect_chord_chance:
                    for c in sorted_chars: delays[c] = 0.0
                else:
                    current_max_delay_cap = self.old_initial_max_imperfect_delay
                    for i, c in enumerate(sorted_chars):
                        if i == 0: delays[c] = 0.0
                        else:
                            delays[c] = random.uniform(0.0, current_max_delay_cap)
                            current_max_delay_cap = max(
                                current_max_delay_cap * (1 - self.old_delay_reduction_percentage_per_key),
                                self.old_min_imperfect_delay_cap
                            )
        else:
            sorted_chars = self._sort_by_modifier_group(chars)  # ← MUDOU
            for c in sorted_chars:
                delays[c] = 0

        # Press Execution (Now waits for the DELTA between scheduled times)
        last_delay = 0.0
        for char in sorted_chars:
            d = delays.get(char, 0)
            wait_time = d - last_delay

            if wait_time > 0:
                if not self.control_keys_state.get(trigger_key, False):
                    break
                if self._precise_wait(wait_time, cancel_event):
                    break

            if not self.control_keys_state.get(trigger_key, False):
                break

            last_delay = d
            base_key, needs_shift, needs_ctrl = self._get_key_info(char)

            with self.lock:
                # ── SHIFT: mudar estado físico SOMENTE quando necessário ──
                if needs_shift and not self.shift_physically_pressed:
                    self.keyboard_controller.press(Key.shift)
                    self.shift_physically_pressed = True
                    time.sleep(self.KEY_SETTLE_TIME)  # Dar tempo ao SO para registrar
                elif not needs_shift and self.shift_physically_pressed:
                    self.keyboard_controller.release(Key.shift)
                    self.shift_physically_pressed = False
                    time.sleep(self.KEY_SETTLE_TIME)

                if needs_shift:
                    self.shift_needed_count += 1

                # ── CTRL: mesma lógica ──
                if needs_ctrl and not self.ctrl_physically_pressed:
                    self.keyboard_controller.press(Key.ctrl)
                    self.ctrl_physically_pressed = True
                    time.sleep(self.KEY_SETTLE_TIME)
                elif not needs_ctrl and self.ctrl_physically_pressed:
                    self.keyboard_controller.release(Key.ctrl)
                    self.ctrl_physically_pressed = False
                    time.sleep(self.KEY_SETTLE_TIME)

                if needs_ctrl:
                    self.ctrl_needed_count += 1

                # ── Pressionar a nota ──
                if self.sim_key_counts[base_key] > 0:
                    self.keyboard_controller.release(base_key)
                self.keyboard_controller.press(base_key)
                self.sim_key_counts[base_key] += 1

                if trigger_key not in self.active_notes_by_source:
                    self.active_notes_by_source[trigger_key] = []
                self.active_notes_by_source[trigger_key].append(char)

    def process_keyrelease_logic(self, trigger_key):
        # Pop state under lock, then perform any timing outside lock so key-up never blocks input.
        chars = []
        with self.lock:
            ev = self._press_cancel_events.get(trigger_key)
            if ev:
                ev.set()
            chars = self.active_notes_by_source.pop(trigger_key, [])
        if chars:
            self._release_chars(chars, apply_imperfect_jitter=True)

    def _release_single_note_logic(self, char):
        """Libera UMA nota. NÃO re-pressiona modificadores."""
        base_key, needs_shift, needs_ctrl = self._get_key_info(char)

        # 1. Liberar a tecla da nota
        self.sim_key_counts[base_key] -= 1
        if self.sim_key_counts[base_key] <= 0:
            self.sim_key_counts[base_key] = 0
            self.keyboard_controller.release(base_key)

        # 2. Decrementar Shift — só libera fisicamente quando NINGUÉM mais precisa
        if needs_shift:
            self.shift_needed_count = max(0, self.shift_needed_count - 1)
            if self.shift_needed_count == 0 and self.shift_physically_pressed:
                self.keyboard_controller.release(Key.shift)
                self.shift_physically_pressed = False

        # 3. Decrementar Ctrl — mesma lógica
        if needs_ctrl:
            self.ctrl_needed_count = max(0, self.ctrl_needed_count - 1)
            if self.ctrl_needed_count == 0 and self.ctrl_physically_pressed:
                self.keyboard_controller.release(Key.ctrl)
                self.ctrl_physically_pressed = False

    def _release_chars(self, chars, apply_imperfect_jitter: bool):
        """Release a string of note-chars.

        If apply_imperfect_jitter is True, imperfect mode may:
        - randomize release order (New imperfect)
        - add a small delay (0-40ms by default) between releasing notes

        Implementation detail:
        - Sleeps happen OUTSIDE the global lock so releases never stall other input.
        - Each actual release updates shared ref-count state under the lock.
        """
        if not chars:
            return

        chars_list = list(chars)

        # Optional: imperfect release order randomization (New type).
        if apply_imperfect_jitter and self.imperfect_mode_var.get() and len(chars_list) > 1:
            if self.imperfect_type.get() == "New":
                if random.random() < 0.6:
                    random.shuffle(chars_list)

        for i, char in enumerate(chars_list):
            with self.lock:
                self._release_single_note_logic(char)

            # Optional per-note release timing (small stagger).
            if (
                apply_imperfect_jitter
                and self.imperfect_mode_var.get()
                and len(chars_list) > 1
                and i < len(chars_list) - 1
            ):
                if self.imperfect_type.get() == "New":
                    lo, hi = getattr(self, 'imperfect_release_jitter_ms', (0, 80))
                else:
                    lo, hi = getattr(self, 'old_imperfect_release_jitter_ms', (0, 80))
                delay = random.uniform(float(lo), float(hi)) / 1000.0
                self._precise_wait(delay)

    def _get_key_info(self, char):
        needs_ctrl = False
        if char.startswith('\x11'):
            needs_ctrl = True
            char = char[1:]
            
        if char in self.mapper.REVERSE_SHIFT_MAP:
            return self.mapper.REVERSE_SHIFT_MAP[char], True, needs_ctrl
        elif char.isupper():
            return char.lower(), True, needs_ctrl
        return char, False, needs_ctrl

    def _compute_smart_releases(self, incoming_notes):
        """
        APENAS CALCULA quais notas devem ser liberadas.
        NÃO toca no teclado. NÃO faz I/O.
        Deve ser chamada DENTRO do lock.
        Retorna lista de chars para liberar.
        """
        if not incoming_notes:
            return []

        # 1. MIDI das notas que vão entrar
        incoming_midis = []
        for c in incoming_notes:
            char_lookup = c[1:] if c.startswith('\x11') else c
            if char_lookup in self.mapper.char_to_midi:
                incoming_midis.append(self.mapper.char_to_midi[char_lookup])

        if not incoming_midis:
            return []

        dissonant_intervals = {1, 2, 6, 10, 11}
        chars_to_release = []
        keys_to_clean = []

        # 2. Varrer notas ativas e decidir quais soltar
        for t_key, notes in self.active_notes_by_source.items():
            notes_to_release = []
            for n in notes:
                char_lookup = n[1:] if n.startswith('\x11') else n
                held_midi = self.mapper.char_to_midi.get(char_lookup, -1)
                if held_midi == -1:
                    continue
                for in_midi in incoming_midis:
                    interval = abs(held_midi - in_midi) % 12
                    distance = abs(held_midi - in_midi)
                    if interval in dissonant_intervals or (0 < distance <= 2):
                        notes_to_release.append(n)
                        break

            # Atualizar a lista de notas ativas (isso é só dados, não I/O)
            if notes_to_release:
                remaining = [n for n in notes if n not in notes_to_release]
                self.active_notes_by_source[t_key] = remaining
                if not remaining:
                    keys_to_clean.append(t_key)
                chars_to_release.extend(notes_to_release)

        for k in keys_to_clean:
            self.active_notes_by_source.pop(k, None)

        return chars_to_release

    def get_current_stack_index(self):
        if not self.key_stack: return 0
        return len(self.key_stack) - 1 - self.stack_pointer if self.is_inverted else self.stack_pointer

    def schedule_ui_update(self): self.master.after_idle(self.update_text_highlight)

    def update_text_highlight(self):
        self.text_display.tag_remove("highlight", "1.0", tk.END)
        total = len(self.key_stack)
        if self.stack_pointer >= total:
            self.status_lbl.config(text="✓ End of sheet")
            return
        idx = self.get_current_stack_index()
        if 0 <= idx < total:
            _, pos = self.key_stack[idx]
            raw_text = self.key_stack[idx][0]
            self.text_display.tag_add("highlight", f"1.0 + {pos} chars", f"1.0 + {pos + len(raw_text)} chars")

            # Update status label with current position
            direction = "▲" if self.is_inverted else "▼"
            self.status_lbl.config(text=f"{direction} Note {self.stack_pointer + 1} / {total}  [{raw_text}]")

            # scroll to show more context - look ahead a few lines
            current_index = self.text_display.index(f"1.0 + {pos} chars")
            line_num = int(current_index.split('.')[0])
            lookahead_line = line_num + 3
            self.text_display.see(f"{lookahead_line}.0")
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
            for match in re.compile(r'(\[[^\]]+\])|([:\']?[^ \n\t])').finditer(content):
                self.key_stack.append((match.group(), match.start()))
            self.stack_pointer = 0
            self.sub_pointer_map.clear()
            self.active_notes_by_source.clear()
            self.sim_key_counts.clear()
            self.shift_needed_count = 0
            self.ctrl_needed_count = 0
            self.theory.infer_key(self.key_stack)
            # Full physical-state reset on new file load (clears any stuck keys)
            self.bass_pattern_counter = 0
            self.theory.last_harmony_midi = None
            self.shift_needed_count = 0
            self.ctrl_needed_count = 0
            self.shift_physically_pressed = False
            self.ctrl_physically_pressed = False
            self.keyboard_controller.release(Key.shift)
            self.keyboard_controller.release(Key.ctrl)
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
            self.ctrl_needed_count = 0
            self.shift_physically_pressed = False
            self.ctrl_physically_pressed = False
            self.keyboard_controller.release(Key.shift)
            self.keyboard_controller.release(Key.ctrl)
            self.bass_pattern_counter = 0
            self.theory.last_harmony_midi = None
            self.ensure_valid_pointer()
        self.schedule_ui_update()  # After lock: only schedules a read-only UI repaint

    def on_end_press(self, e):
        files = [f for f in os.listdir('.') if f.endswith('.txt')]
        if os.path.exists('Sheets'): files += [os.path.join('Sheets', f) for f in os.listdir('Sheets') if f.endswith('.txt')]
        if files: 
            target = random.choice(files)
            self.master.after(0, lambda: self.process_file_load(target))

    def toggle_bass_hotkey(self, e):
        """Page Up hotkey: toggle Auto-Bass on/off."""
        val = not self.bass_mode_enabled.get()
        self.bass_mode_enabled.set(val)
        self.update_check_styles()

    def toggle_harmony_hotkey(self, e):
        """Page Up hotkey: toggle Auto-Bass on/off."""
        val = not self.harmony_enabled.get()
        self.harmony_enabled.set(val)
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
        try:
            with self.lock:
                for ev in self._press_cancel_events.values():
                    ev.set()
                self._press_cancel_events.clear()
        except Exception:
            pass
        self.executor.shutdown(wait=False)
        self.master.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = KeyboardSimulatorApp(root)
    root.mainloop()