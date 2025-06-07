import tkinter as tk
from tkinter import filedialog, font
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageTk
import keyboard
from pynput.keyboard import Controller, Key
from threading import Lock, Thread, Event
import time
import re
import random
import os
import base64
from io import BytesIO
import tempfile
import threading
import logging
from images import ICON_BASE64, BACKGROUND_IMAGE, BRAZIL_FLAG_BASE64, UK_FLAG_BASE64
import concurrent.futures

logger = logging.getLogger(__name__)

class Metadata:
    def __init__(self):
        self.version = "2.5.0"
        self.creator = "Gustavo R. Lima"
        self.comments = "An advanced piano simulator for keyboard."
        self.product_name = "PPiano"
        self.language = "en-US" 

class KeyboardSimulatorApp:
    SHIFT_MAP = {
        '1': '!', '2': '@', '3': '#', '4': '$', '5': '%',
        '6': '^', '7': '&', '8': '*', '9': '(', '0': ')',
        '-': '_', '=': '+', '[': '{', ']': '}', '\\': '|',
        ';': ':', "'": '"', ',': '<', '.': '>', '/': '?',
        '`': '~'
    }
    
    def __init__(self, master):
        self.master = master 
        self.metadata = Metadata()
        self.master.title(f"{self.metadata.product_name} v{self.metadata.version}")
        
        self.is_inverted = False  # Flag para controle de direção   
        self.original_text = ""
        self.current_display_text = ""

        self.master.geometry("600x400")
        self.master.resizable(False, False)

        self.imperfect_perfect_chord_chance = 0.05 # Chance de tocar acorde perfeito mesmo em imperfect_mode (era 0.15, ajustei para o valor do seu código)
        self.initial_max_imperfect_delay = 0.089   # O valor máximo inicial para o delay aleatório
        self.delay_reduction_percentage_per_key = 0.15 # Ex: 15% de redução do teto do delay a cada tecla
        self.min_imperfect_delay_cap = 0.020       # O teto mínimo para o delay, não reduz abaixo disso

        self.forbidden_chars = {
            ',', '-', '+','´',';','ç','[',']','{','}',
            '`','~','/','\'','_','|','=','<','>',':','"','.'
        }

        self.setup_icon()
        self.setup_background()

        self.language = 'en-US'
        self.setup_language_button()
        self.texts = self.get_texts()

        self.create_widgets()
        self.setup_text_tags()

        ### HOTKEY CONFIGURATION TO PRESS KEYS ###
        
        
        self.hotkey1 = 'num -' #Default: Numeric -
        self.hotkey2 = '+' #Default: +
        self.hotkey3 = 'num *' #Default: Numeric *
        ##########################################
        # Unified key state tracking
        self.control_keys = {
        'hotkey1': {
            'pressed': False, 
            'current_element': None, 
            'active_keys': set(),
            'key_timestamps': {}
        },
        'hotkey2': {
            'pressed': False, 
            'current_element': None, 
            'active_keys': set(),
            'key_timestamps': {}
        },
        'hotkey3': {
            'pressed': False, 
            'current_element': None, 
            'active_keys': set(),
            'key_timestamps': {}
        }
        }
        
        self.last_press_time = 0
        self.min_press_interval = 0.005  # 50ms minimum between presses by default
        
        self.keyboard_controller = Controller()
        self.lock = Lock()
        self.running = False
        self.imperfect_mode = False
        self.file_selection_mode = False
        self.current_file = None
        
        # Release handling
        self.release_threads = {key: {} for key in self.control_keys}
        self.release_events = {key: {} for key in self.control_keys}
        
        # Special key mappings
        self.shift_keys = {
            '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
            '^': '6', '&': '7', '*': '8', '(': '9', ')': '0'
        }
        
        self.key_stack = []
        self.stack_pointer = 0

        # Set up end key monitoring
        self.setup_end_key_monitoring()

        # Thread pool for multitasking keypress/release
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)

    def setup_icon(self):
        icon_data = base64.b64decode(ICON_BASE64)
        icon_file = self.create_temp_icon_file(icon_data)
        self.master.iconbitmap(icon_file)
        # Delete the temporary file
        os.remove(icon_file)

    def create_temp_icon_file(self, icon_data):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ico') as icon_file:
            icon_file.write(icon_data)
            return icon_file.name

    def setup_background(self):
        # Decode the base64 image
        image_data = base64.b64decode(BACKGROUND_IMAGE)
        bg_image = Image.open(BytesIO(image_data))
        bg_image = bg_image.resize((600, 400), Image.LANCZOS)
        
        # Semi-transparent overlay
        overlay = Image.new('RGBA', bg_image.size, (0, 0, 0, 128))
        bg_image = Image.alpha_composite(bg_image.convert('RGBA'), overlay)
        
        self.bg_photo = ImageTk.PhotoImage(bg_image)

        # Create a canvas and put the image on it
        self.canvas = tk.Canvas(self.master, width=600, height=400)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.bg_photo, anchor="nw")

    def setup_language_button(self):
        # Load and resize flag images
        brazil_flag = self.load_and_resize_image(BRAZIL_FLAG_BASE64, (20, 15))
        uk_flag = self.load_and_resize_image(UK_FLAG_BASE64, (20, 15))

        self.flag_images = {
            'pt-BR': ImageTk.PhotoImage(brazil_flag),
            'en-US': ImageTk.PhotoImage(uk_flag)
        }

        self.language_button = tk.Button(self.master, image=self.flag_images['en-US'], 
                                         command=self.toggle_language, 
                                         bd=0, highlightthickness=0)
        self.language_button.place(x=10, y=10)

    def load_and_resize_image(self, base64_string, size):
        image_data = base64.b64decode(base64_string)
        image = Image.open(BytesIO(image_data))
        return image.resize(size, Image.LANCZOS)

    def update_text(self):
        self.load_button.config(text=self.texts[self.language]['load_button'])
        self.always_on_top_check.config(text=self.texts[self.language]['always_on_top'])
        self.imperfect_mode_check.config(text=self.texts[self.language]['imperfect_mode'])
        self.status_label.config(text=self.texts[self.language]['status_label'])

    def toggle_language(self):
        self.language = 'pt-BR' if self.language == 'en-US' else 'en-US'
        self.language_button.config(image=self.flag_images[self.language])
        self.update_text()

    def get_texts(self):
        return {
            'pt-BR': {
                'load_button': "Carregar Arquivo",
                'always_on_top': "Fixar Janela",
                'imperfect_mode': "Modo Imperfeito",
                'status_label': "Pressione '-' para simular a tecla | ',' para reiniciar o progresso"
            },
            'en-US': {
                'load_button': "Load File",
                'always_on_top': "Pin Window",
                'imperfect_mode': "Imperfect mode",
                'status_label': "- + *  simulates a keypress | ',' to reset progress"
            }
        }
        
    def create_widgets(self):
        custom_font = font.Font(family="Roboto", size=10, weight="bold")

        # Text display
        self.text_display = ScrolledText(self.master, wrap=tk.WORD, width=50, height=10, font=custom_font, fg="white", bg="#1a1a1a")
        self.text_display.place(relx=0.5, rely=0.4, anchor="center")
        # Nova associação para clique do mouse
        self.text_display.bind("<Button-1>", self.on_text_click)

        # File list
        self.file_list = tk.Listbox(self.master, font=custom_font, fg="white", bg="#1a1a1a")
        self.file_list.place(relx=0.5, rely=0.4, anchor="center")
        self.file_list.bind('<Double-1>', self.on_file_select)
        self.file_list.bind('<Return>', self.on_file_select)
        self.file_list.place_forget()  # Initially hidden

        # Toggle button for file selection
        self.toggle_button = tk.Button(self.master, text="📁", command=self.toggle_file_selection, font=custom_font, fg="white", bg="#333333", width=3, height=2)
        self.toggle_button.place(relx=0.9, rely=0.4, anchor="center")

        # Control frame
        control_frame = tk.Frame(self.master, bg="#1a1a1a")
        control_frame.place(relx=0.5, rely=0.85, anchor="center")

        def create_rounded_button(parent, text, command):
            return tk.Button(parent, text=text, command=command, font=custom_font, fg="white", bg="#333333", bd=0, highlightthickness=0, relief="flat", padx=10, pady=5, activebackground="#444444", activeforeground="white")

        self.load_button = create_rounded_button(control_frame, self.texts[self.language]['load_button'], self.load_file)
        self.load_button.grid(row=0, column=0, padx=5, pady=5)

        self.always_on_top = tk.BooleanVar()
        self.always_on_top_check = tk.Checkbutton(control_frame, text=self.texts[self.language]['always_on_top'], 
                                                  variable=self.always_on_top,
                                                  command=self.toggle_always_on_top, font=custom_font,
                                                  fg="white", bg="#1a1a1a", selectcolor="#555555",
                                                  activebackground="#1a1a1a", activeforeground="white")
        self.always_on_top_check.grid(row=0, column=1, padx=5, pady=5)

        self.imperfect_mode_var = tk.BooleanVar()
        self.imperfect_mode_check = tk.Checkbutton(control_frame, text=self.texts[self.language]['imperfect_mode'], 
                                                   variable=self.imperfect_mode_var,
                                                   command=self.toggle_imperfect_mode, font=custom_font,
                                                   fg="white", bg="#1a1a1a", selectcolor="#555555",
                                                   activebackground="#1a1a1a", activeforeground="white")
        self.imperfect_mode_check.grid(row=0, column=2, padx=5, pady=5)

        self.invert_button = create_rounded_button(control_frame, "↕", self.toggle_invert_direction)
        self.invert_button.grid(row=0, column=3, padx=5, pady=5)

        self.status_label = tk.Label(control_frame, text=self.texts[self.language]['status_label'], 
                                     font=custom_font, fg="white", bg="#1a1a1a")
        self.status_label.grid(row=1, column=0, columnspan=3, pady=5)

        

    def toggle_file_selection(self):
        self.file_selection_mode = not self.file_selection_mode
        if self.file_selection_mode:
            self.text_display.place_forget()
            self.file_list.place(relx=0.5, rely=0.4, anchor="center")
            self.load_txt_files()
            self.file_list.focus_set()  # Adicionado foco na lista
        else:
            self.file_list.place_forget()
            self.text_display.place(relx=0.5, rely=0.4, anchor="center")
            self.text_display.focus_set()  # Retorna foco para o texto

    def load_txt_files(self):
        self.file_list.delete(0, tk.END)
        for file in os.listdir('.'):
            if file.endswith('.txt'):
                self.file_list.insert(tk.END, file)

    def load_file_content(self, filename):
        with open(filename, 'r', encoding='utf-8') as file:
            content = file.read()
        
        # Desativa inversão temporariamente
        original_state = self.is_inverted
        if self.is_inverted:
            self.toggle_invert_direction()  # Desliga inversor

        # Armazena original e limpa cache invertido
        self.original_text = content
        self.current_file = os.path.basename(filename)
        
        # Aplica inversão imediatamente se necessário
        self.current_display_text = self.original_text #always load non inverted first
        
        self.reset_simulator(self.current_display_text)
        self.scroll_to_current_position(initial=True)
        self.master.title(f"PPiano - {self.current_file[:-4]}")

        # Restaura estado original da inversão
        if original_state:
            self.toggle_invert_direction() #Liga o inversor se estava ligado antes

    def on_file_select(self, event):
        #On file select loads content inside .txt
        selection = self.file_list.curselection()
        if selection:
            filename = self.file_list.get(selection[0])
            self.load_file_content(filename)  # Usa a função corrigida
            self.current_file = os.path.basename(filename)
            self.master.title(f"PPiano - {self.current_file[:-4]}")
            self.toggle_file_selection()

    def scroll_to_current_position(self, initial=False):
        """Scroll automático garantido com atualização forçada"""
        self.text_display.update_idletasks()  # Força atualização do layout
        
        if not self.key_stack:
            return
        
        total_elements = len(self.key_stack)
        index = total_elements - 1 - self.stack_pointer if self.is_inverted else self.stack_pointer
        
        try:
            element, pos = self.key_stack[index]
            end_pos = pos + len(element)
            
            # Converte posições para índices do texto
            start_index = f"1.0 + {pos} chars"
            end_index = f"1.0 + {end_pos} chars"
            
            # Scroll inicial para posição correta
            if initial:
                if self.is_inverted:
                    # Scroll para final com margem
                    self.text_display.see(end_index)
                    self.text_display.yview_moveto(1.0)  # Garante fim absoluto
                    self.master.after(50, lambda: self.text_display.see(end_index))  # Dupla verificação
                else:
                    # Scroll para início
                    self.text_display.see(start_index)
                    self.text_display.yview_moveto(0.0)
                return
            
            # Scroll dinâmico durante execução
            bbox = self.text_display.bbox(start_index)
            if not bbox:  # Se elemento não está visível
                self.text_display.see(start_index)
                # Ajuste fino baseado na direção
                if self.is_inverted:
                    self.text_display.yview("scroll", -1, "pages")  # Sobe um pouco
                else:
                    self.text_display.yview("scroll", 1, "pages")  # Desce um pouco

        except Exception as e:
            print(f"Debug - Erro no scroll: {e}")
            print(f"Index: {index}, Total: {total_elements}")

    def toggle_invert_direction(self):
        """Alterna a direção com scroll automático inicial"""
        self.is_inverted = not self.is_inverted
        self.stack_pointer = 0
        
        # Atualiza aparência do botão
        self.invert_button.config(
            relief='sunken' if self.is_inverted else 'raised',
            bg='#555555' if self.is_inverted else '#333333'
        )
        
        # Scroll inicial para posição correta
        self.scroll_to_current_position(initial=True)
        self.highlight_current_element()

    def reset_simulator(self, content):
        self.text_display.config(state=tk.NORMAL)
        self.text_display.delete(1.0, tk.END)
        self.text_display.insert(tk.END, content)
        self.text_display.config(state=tk.DISABLED)
        
        self.key_stack = self.parse_text_to_stack(content)
        self.stack_pointer = 0
        self.highlight_current_element()
        self.start_monitoring()
    def setup_text_tags(self):
        self.text_display.tag_configure("highlight", background="purple")
        
    # Novo método: converte índice de text widget ("linha.coluna") em offset absoluto
    def index_to_offset(self, index_str):
        line, col = map(int, index_str.split('.'))
        content = self.text_display.get("1.0", tk.END)
        lines = content.splitlines(keepends=True)
        offset = sum(len(lines[i]) for i in range(line-1)) + col
        return offset

    # Modificado: método on_text_click para atualizar o scroll automaticamente ao clicar
    def on_text_click(self, event):
        index_clicked = self.text_display.index(f"@{event.x},{event.y}")
        click_offset = self.index_to_offset(index_clicked)
        for i, (element, pos) in enumerate(self.key_stack):
            end_pos = pos + len(element)
            if pos <= click_offset < end_pos:
                if element.startswith('[') and element.endswith(']'):
                    new_element = element[1:-1]  # remove os colchetes
                    new_pos = pos + 1             # posição ajustada para o conteúdo interno
                    self.key_stack[i] = (new_element, new_pos)
                if self.is_inverted:
                    self.stack_pointer = len(self.key_stack) - 1 - i
                else:
                    self.stack_pointer = i
                self.highlight_current_element()
                self.scroll_to_current_position(initial=True)
                # Força o scroll para o início do elemento clicado
                start_index = self.text_display.index(f"1.0 + {pos} chars")
                self.text_display.see(start_index)
                break

    def setup_end_key_monitoring(self):
        """Set up monitoring for the End key"""
        keyboard.on_press_key('end', self.handle_end_key)
    
    def get_all_txt_files(self):
        """Get all .txt files from current directory and Sheets subdirectory"""
        txt_files = []
        
        # Get files from current directory
        txt_files.extend([f for f in os.listdir('.') if f.endswith('.txt')])
        
        # Get files from Sheets subdirectory if it exists
        sheets_dir = os.path.join('.', 'Sheets')
        if os.path.exists(sheets_dir) and os.path.isdir(sheets_dir):
            sheet_files = [os.path.join('Sheets', f) for f in os.listdir(sheets_dir) if f.endswith('.txt')]
            txt_files.extend(sheet_files)
        
        return txt_files
    
    def handle_end_key(self, e):
        """Handles End key press by loading a random txt file (current dir or ./Sheets/ folder)"""
        txt_files = self.get_all_txt_files()
        
        if not txt_files:
            self.show_no_files_message()
            return
        
        random_file = random.choice(txt_files)
        self.load_file_content(random_file)
        self.current_file = os.path.basename(random_file)
        self.master.title(f"PPiano - {self.current_file[:-4]}")
        
        # Flash the window title briefly to indicate file change
        self.flash_title()

    def flash_title(self):
        """Flash the window title to indicate file change"""
        original_title = self.master.title()
        self.master.title("File Changed!")
        self.master.after(500, lambda: self.master.title(original_title))
    
    def load_file(self):
        filename = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if filename:
            self.current_file = os.path.basename(filename)
            self.master.title(f"PPiano - {self.current_file[:-4]}")
            self.load_file_content(filename)

    def get_key_variants(self, key: str) -> set:
        """Return all possible variants of a key (lowercase, uppercase, shifted)."""
        variants = {key, self.get_opposite_case(key)}
        shifted = self.SHIFT_MAP.get(key.lower())
        if shifted:
            variants.add(shifted)
        return variants
    
    def highlight_current_element(self):
        self.text_display.tag_remove("highlight", "1.0", tk.END)
        if self.key_stack:
            total = len(self.key_stack)
            index = total - 1 - self.stack_pointer if self.is_inverted else self.stack_pointer
            
            if index < total:
                element, pos = self.key_stack[index]
                end_pos = pos + len(element)
                start = self.text_display.index(f"1.0 + {pos} chars")
                end = self.text_display.index(f"1.0 + {end_pos} chars")
                self.text_display.tag_add("highlight", start, end)

    def toggle_always_on_top(self):
        self.master.attributes('-topmost', self.always_on_top.get())

    def toggle_imperfect_mode(self):
        self.imperfect_mode = self.imperfect_mode_var.get()

    def parse_text_to_stack(self, text):
        stack = []
        pattern = r'\[([^\]]+)\]|(\S)'
        
        for match in re.finditer(pattern, text):
            element = None
            start_pos = match.start()
            
            if match.group(1):  # Grupo entre colchetes
                group_content = match.group(1)
                # Verifica se contém caracteres proibidos
                if not any(c in self.forbidden_chars for c in group_content):
                    element = (f'[{group_content}]', start_pos)
            else:  # Caractere simples
                char = match.group(2)
                if char not in self.forbidden_chars:
                    element = (char, start_pos)
            
            if element:
                stack.append(element)
        
        return stack
    
    def introduce_error(self, element):
        """Introduz erros mantendo a validade dos caracteres"""
        # Lista de caracteres permitidos (excluindo proibidos)
        valid_chars = [c for c in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789']
        
        new_element = []
        for c in element:
            if random.random() < 0.001:  # 5% chance de erro
                new_char = random.choice(valid_chars)
                new_element.append(new_char)
            else:
                new_element.append(c)
        return ''.join(new_element)

    def process_element(self, element):
        """Processa um elemento aplicando filtros e modo imperfeito"""
        # Filtra caracteres proibidos
        filtered = ''.join([c for c in element if c not in self.forbidden_chars])
        
        # Aplica modo imperfeito se necessário
        if self.imperfect_mode:
            return self.introduce_error(filtered)
        return filtered
    
    def process_next(self, control_key):
        with self.lock:
            total = len(self.key_stack)
            if self.stack_pointer < total:
                index = total - 1 - self.stack_pointer if self.is_inverted else self.stack_pointer
                element, pos = self.key_stack[index]
                
                processed_element = self.process_element(element)
                self.stack_pointer += 1
                
                self.highlight_current_element()
                self.scroll_to_current_position()
                return processed_element
        return None

    def simulate_keypress(self, key: str, press: bool = True, release: bool = False, control_key: str = None) -> None:
        """Simulate pressing or releasing a key with appropriate modifiers."""
        try:
            if key in self.shift_keys:
                with self.keyboard_controller.pressed(Key.shift):
                    self._handle_key_action(self.shift_keys[key], press, release, control_key)
            elif key.isupper() or key in self.SHIFT_MAP.values():
                with self.keyboard_controller.pressed(Key.shift):
                    self._handle_key_action(key.lower(), press, release, control_key)
            else:
                self._handle_key_action(key, press, release, control_key)
        except Exception as e:
            logger.exception("Error simulating keypress")

    def key_monitoring_thread(self) -> None:
        """Monitor hotkey states and trigger corresponding actions."""
        POLL_INTERVAL = 0.001
        while self.running:
            current_time = time.monotonic()
            # Process each hotkey
            for control_key in ['hotkey1', 'hotkey2', 'hotkey3']:
                self._process_hotkey_state(control_key, current_time)
            # Handle reset key
            if keyboard.is_pressed(',') and (current_time - self.last_press_time) >= self.min_press_interval:
                with self.lock:
                    self.reset_scroll()
                    self.last_press_time = current_time
            time.sleep(POLL_INTERVAL)

    def _process_hotkey_state(self, control_key: str, current_time: float) -> None:
        """Processa hotkey com verificação de modo virtual"""
        key_to_check = getattr(self, control_key)
        
        # Verificação direta do estado físico
        is_pressed = keyboard.is_pressed(key_to_check)
        state = self.control_keys[control_key]['pressed']
        
        if is_pressed != state:
            with self.lock:
                self.control_keys[control_key]['pressed'] = is_pressed
            # Release lock before further processing
            if is_pressed and (current_time - self.last_press_time) >= self.min_press_interval:
                # Força liberação imediata da tecla hotkey no modo virtual
                keyboard.release(key_to_check)
                # Offload to thread pool for multitasking
                self.executor.submit(self.handle_key_press, control_key)
                self.last_press_time = current_time
            elif not is_pressed:
                self.executor.submit(self.handle_key_release, control_key)

    def delayed_keypress(self, key: str, control_key: str, delay: float) -> None:
        """ Waits for delay, then simulates key press if conditions allow. """
        try:
            if delay > 0.001: # Only sleep if delay is significant
                 time.sleep(delay)

            # Minimize lock duration
            with self.lock:
                # Double-check: Is the controlling hotkey still considered pressed?
                if not self.control_keys[control_key]['pressed']:
                     logger.debug(f"Skipping delayed press of '{key}': Hotkey {control_key} released before press.")
                     return

                self.simulate_keypress(key, press=True, release=False, control_key=control_key)

                # Update state *after* successful simulation
                self.control_keys[control_key]['active_keys'].add(key)
                self.control_keys[control_key]['key_timestamps'][key] = time.time() # Record press time

        except Exception as e:
            logger.exception(f"Error in delayed key press for '{key}' by {control_key}")

    def handle_key_release(self, control_key):
        """ Processes a hotkey release: schedules delayed releases for keys pressed by this hotkey. """
        # Copy current_element to avoid holding lock during scheduling
        with self.lock: # Protect access to shared state
            current_element = self.control_keys[control_key]['current_element']
            if not current_element:
                #logger.debug(f"Handle Release '{control_key}': No current element to release.")
                return # Nothing was being pressed by this key

            logger.debug(f"Handle Release '{control_key}': Element='{current_element}'")

            # Clear previous pending releases *for this control key* only if needed?
            # No, the cancellation in handle_key_press should cover overlaps.
            # Just schedule new releases for the element that was just being played.

            keys_to_release = list(current_element)  # Copy for thread safety
            self.control_keys[control_key]['current_element'] = None

        for key_char in keys_to_release:
            with self.lock:
                 # Only schedule release if the key is still considered active *by this control key*
                 # (It might have been force-released or cancelled already)
                 if key_char in self.control_keys[control_key]['active_keys']:

                     # Determine release delay
                     if self.imperfect_mode:
                         # Slightly longer max delay for releases than presses
                         delay = random.uniform(0.00, 0.150)
                     else: # Perfect mode
                         delay = 0.00 # Effectively immediate release

                     # Check if key is held by *another* active hotkey
                     key_variants = self.get_key_variants(key_char)
                     held_by_other = any(
                         variant in self.control_keys[other_key]['active_keys']
                         for other_key in self.control_keys
                         if other_key != control_key and self.control_keys[other_key]['pressed'] # Check if other key is *currently* pressed
                         for variant in key_variants
                     )

                     if held_by_other:
                         logger.debug(f"  Skipping release schedule for '{key_char}': Held by another active hotkey.")
                         # We still need to remove it from *this* control_key's active set
                         self.control_keys[control_key]['active_keys'].discard(key_char)
                         if key_char in self.control_keys[control_key]['key_timestamps']:
                             del self.control_keys[control_key]['key_timestamps'][key_char]
                         # Do NOT schedule a release thread
                     else:
                         # Schedule the delayed release
                         #logger.debug(f"  Scheduling release for '{key_char}' with delay {delay:.4f}s")
                         event = threading.Event()
                         thread = threading.Thread(target=self.delayed_keyrelease, args=(key_char, control_key, delay, event), daemon=True)

                         # Store thread and event for potential cancellation
                         self.release_events[control_key][key_char] = event
                         self.release_threads[control_key][key_char] = thread
                         # Offload to thread pool for multitasking
                         self.executor.submit(self.delayed_keyrelease, key_char, control_key, delay, event)
                 else:
                      logger.debug(f"  Skipping release schedule for '{key_char}': Not active for {control_key} (likely already released or cancelled).")


    def delayed_keyrelease(self, key: str, control_key: str, delay: float, event: Event) -> None:
        """ Waits for delay, then simulates key release unless cancelled by event. """
        cancelled = False
        try:
            if event:
                # Wait for the delay, returns True if event is set during wait
                cancelled = event.wait(timeout=delay)
            # else: No event provided? Should not happen with current logic.

        except Exception as e:
            logger.error(f"Error waiting for release event for '{key}': {e}")
            cancelled = True # Treat error as cancellation for safety

        with self.lock: # Protect state updates

            # --- Cleanup regardless of cancellation ---
            # Remove from release tracking first
            if control_key in self.release_events and key in self.release_events[control_key]:
                 del self.release_events[control_key][key]
            if control_key in self.release_threads and key in self.release_threads[control_key]:
                 del self.release_threads[control_key][key]

            # Check if key is still marked active for this control key
            # (It might have been removed by a forced release or another cancellation)
            if key not in self.control_keys[control_key]['active_keys']:
                 # If cancelled, log it. If not cancelled, it means something else already handled it.
                 if cancelled: logger.debug(f"Release cancelled for '{key}' (scheduled by {control_key}). State already cleaned up.")
                 else: logger.debug(f"Release for '{key}' (scheduled by {control_key}) aborted: Key no longer active.")
                 return # Nothing more to do

            # --- If Cancelled ---
            if cancelled:
                logger.debug(f"Release cancelled for '{key}' (scheduled by {control_key}). Cleaning up state.")
                # Only remove from active_keys and timestamp, DO NOT simulate release
                self.control_keys[control_key]['active_keys'].discard(key)
                if key in self.control_keys[control_key]['key_timestamps']:
                    del self.control_keys[control_key]['key_timestamps'][key]
                return

            # --- If Not Cancelled ---
            # Proceed with release simulation and state cleanup
            try:
                 # Check again if held by another active key right before releasing
                 key_variants = self.get_key_variants(key)
                 held_by_other_now = any(
                     variant in self.control_keys[other_key]['active_keys']
                     for other_key in self.control_keys
                     if other_key != control_key and self.control_keys[other_key]['pressed']
                     for variant in key_variants
                 )

                 if held_by_other_now:
                     logger.debug(f"Final check: Aborting release of '{key}' by {control_key}: Now held by another active key.")
                     # Still clean up this control key's state
                     self.control_keys[control_key]['active_keys'].discard(key)
                     if key in self.control_keys[control_key]['key_timestamps']:
                         del self.control_keys[control_key]['key_timestamps'][key]
                     return

                 # Simulate the release
                 #logger.debug(f"Executing delayed release: '{key}' by {control_key} after delay {delay:.3f}s")
                 self.simulate_keypress(key, press=False, release=True, control_key=control_key)

                 # Clean up state *after* successful simulation
                 self.control_keys[control_key]['active_keys'].discard(key)
                 if key in self.control_keys[control_key]['key_timestamps']:
                     del self.control_keys[control_key]['key_timestamps'][key]

            except Exception as e:
                 logger.exception(f"Error during delayed key release simulation for '{key}'")
                 # Attempt cleanup even on error
                 self.control_keys[control_key]['active_keys'].discard(key)
                 if key in self.control_keys[control_key]['key_timestamps']:
                     del self.control_keys[control_key]['key_timestamps'][key]

    def handle_key_press(self, control_key):
        """Processes a hotkey press: gets next element, cancels conflicting releases, schedules presses."""
        keys_to_press = self.process_next(control_key)
        if not keys_to_press:
            logger.info(f"Handle Press '{control_key}': No more elements to process or error.")
            return # End of stack or error

        with self.lock: # Ensure atomic operations on shared state
            current_time = time.time()

            # --- FIX: Cancel pending releases for the *same* keys ---
            for key_char_to_press in keys_to_press:
                variants_to_cancel = self.get_key_variants(key_char_to_press)
                #logger.debug(f"  Pressing '{key_char_to_press}'. Variants to check/cancel for release: {variants_to_cancel}")

                for other_ctrl_key in list(self.control_keys.keys()): # Iterate over copy of keys
                    if other_ctrl_key in self.release_events:
                        # Iterate over copy as we might modify the dict implicitly via event.set() -> delayed_release cleanup
                        for released_key, event in list(self.release_events[other_ctrl_key].items()):
                            if released_key in variants_to_cancel and event and not event.is_set():
                                logger.info(f"  Interrupting pending release of '{released_key}' (scheduled by {other_ctrl_key}) due to new press of '{key_char_to_press}' by {control_key}.")
                                event.set() # Signal the delayed_keyrelease thread to cancel

            conflict_timeout = 0.1 # seconds
            other_active_control_keys = [k for k in self.control_keys.keys() if k != control_key and k in self.control_keys] # Ensure k exists
            for key_char_to_press in keys_to_press:
                 key_variants = self.get_key_variants(key_char_to_press)
                 for other_ctrl_key in other_active_control_keys:
                     # Check if other_ctrl_key still has an entry (it might have been cleaned up)
                     if other_ctrl_key not in self.control_keys or 'active_keys' not in self.control_keys[other_ctrl_key]:
                         continue
                     for variant in key_variants:
                         if variant in self.control_keys[other_ctrl_key]['active_keys']:
                             other_timestamp = self.control_keys[other_ctrl_key]['key_timestamps'].get(variant, 0)
                             if current_time - other_timestamp > conflict_timeout:
                                 logger.warning(f"  Force releasing '{variant}' held by {other_ctrl_key} for >{conflict_timeout}s due to new press by {control_key}.")
                                 event = self.release_events.get(other_ctrl_key, {}).get(variant)
                                 if event: event.set()
                                 self.simulate_keypress(variant, press=False, release=True, control_key=other_ctrl_key)
                                 self.control_keys[other_ctrl_key]['active_keys'].discard(variant)
                                 if variant in self.control_keys[other_ctrl_key]['key_timestamps']:
                                     del self.control_keys[other_ctrl_key]['key_timestamps'][variant]

            # --- Schedule the key presses ---
            delays = {}
            # Convert keys_to_press (string) to a list to maintain order
            ordered_keys_to_press = list(keys_to_press)

            if len(ordered_keys_to_press) == 1 or not self.imperfect_mode:
                # Single key or perfect mode: all keys press simultaneously (delay 0)
                for key_char in ordered_keys_to_press:
                    delays[key_char] = 0.0
            else: # Imperfect mode for chords (multiple keys)
                if random.random() < self.imperfect_perfect_chord_chance:
                    # Chance to play chord perfectly even in imperfect mode
                    logger.debug(f"  Imperfect mode for '{keys_to_press}', but got lucky: playing perfectly.")
                    for key_char in ordered_keys_to_press:
                        delays[key_char] = 0.0
                else:
                    # --- NEW LOGIC for progressive delay reduction ---
                    logger.debug(f"  Imperfect mode for '{keys_to_press}': applying progressive delays.")
                    current_max_delay_cap = self.initial_max_imperfect_delay

                    for i, key_char in enumerate(ordered_keys_to_press):
                        if i == 0:
                            # First key is always instant
                            delays[key_char] = 0.0
                            logger.debug(f"    Key '{key_char}' (1st): delay 0.0s")
                        else:
                            # For subsequent keys, calculate delay based on current_max_delay_cap
                            actual_delay = random.uniform(0.0, current_max_delay_cap)
                            delays[key_char] = actual_delay
                            logger.debug(f"    Key '{key_char}' ({i+1}th): delay {actual_delay:.4f}s (cap {current_max_delay_cap:.4f}s)")

                            # Reduce the max delay cap for the *next* key
                            next_max_delay_cap = current_max_delay_cap * (1 - self.delay_reduction_percentage_per_key)
                            current_max_delay_cap = max(next_max_delay_cap, self.min_imperfect_delay_cap)
                            logger.debug(f"      Next max delay cap will be: {current_max_delay_cap:.4f}s")
            
            # Store the element being processed *before* starting threads
            # Ensure control_key entry exists (it should have been created by process_next or earlier)
            if control_key not in self.control_keys:
                 self.control_keys[control_key] = {'active_keys': set(), 'key_timestamps': {}, 'current_element': None}
            self.control_keys[control_key]['current_element'] = keys_to_press

            # Start a thread for each key press
            for key_char in ordered_keys_to_press: # Iterate in order for logging consistency
                press_delay = delays.get(key_char, 0.0)
                logger.debug(f"  Scheduling press for '{key_char}' with calculated delay {press_delay:.4f}s")
                thread = threading.Thread(target=self.delayed_keypress, args=(key_char, control_key, press_delay), daemon=True)
                thread.start()
                # Timestamp is updated *inside* delayed_keypress after actual press simulation

    def _handle_key_action(self, key, press, release, control_key):
        """Execute key actions unconditionally."""
        if press:
            self.keyboard_controller.press(key)
        if release:
            self.keyboard_controller.release(key)
        # No virtual mode branch; always simulate physical key actions

    def get_opposite_case(self, key):
        if key in self.shift_keys:
            return self.shift_keys[key]
        elif key in '~!@#$%^&(_+{}|:"<>?':
            return key
        return key.lower() if key.isupper() else key.upper()

    def stop_monitoring(self):
        """
        Stop monitoring and clean up resources
        """
        self.running = False
        
        # Cancel all pending release threads
        for control_key in self.release_events:
            for event in self.release_events[control_key].values():
                if event:
                    event.set()
        
        # Wait for monitoring thread to finish
        if hasattr(self, 'monitoring_thread') and self.monitoring_thread:
            self.monitoring_thread.join(timeout=1.0)  # Add timeout to prevent hanging
            
        # Release any stuck keys
        for control_key in self.control_keys:
            for key in self.control_keys[control_key]['active_keys'].copy():
                try:
                    self.simulate_keypress(key, press=False, release=True, control_key=control_key)
                except Exception as e:
                    print(f"Error releasing stuck key {key}: {e}")
        
        # Clear all states
        for control_key in self.control_keys:
            self.control_keys[control_key]['active_keys'].clear()
            self.control_keys[control_key]['current_element'] = None
        
        # Clear threads and event dictionaries
        self.release_threads.clear()
        self.release_events.clear()

        # Shutdown thread pool
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)

    def reset_scroll(self):
        #Goes all way up inside the current text location
        self.stack_pointer = 0
        self.highlight_current_element()
        self.text_display.see("1.0")
        self.text_display.update()
        self.scroll_to_current_position(initial=True)


    def start_monitoring(self):
        if not self.running:
            self.running = True
            self.monitoring_thread = Thread(target=self.key_monitoring_thread)
            self.monitoring_thread.start()

    def on_closing(self):
        """Clean up resources when closing the application"""
        self.stop_monitoring()
        # Unregister all
        keyboard.unhook_all()
        self.master.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = KeyboardSimulatorApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()