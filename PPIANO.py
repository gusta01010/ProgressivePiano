import keyboard
import os
from pynput.keyboard import Controller, Key
from threading import Lock, Thread
import time
import re
import random

text_set = []
set_index = 0
keyboard_controller = Controller()
lock = Lock()
current_element = None
running = True
return_to_menu = False
imperfect_mode = False

def list_txt_files():
    return [f for f in os.listdir() if f.endswith('.txt')]

def display_menu(files):
    print("\nAvailable sheets (.txt):")
    for i, file in enumerate(files, 1):
        print(f"{i}. {file}")
    print("\nEnter the file number or ‘i’ to enable/disable imperfect mode")

def read_file(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            content = file.read()
        return content
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")
        return ""
    except Exception as e:
        print(f"Error reading the file: {e}")
        return ""

def parse_text_to_set(text):
    pattern = r'\[([^\]]+)\]|(\S)'
    forbidden_chars = set([',', '-', '.', '|'])
    
    def filter_element(element):
        if len(element) > 1:  # Para conjuntos como [abc]
            return ''.join(char for char in element if char not in forbidden_chars)
        else:  # Para caracteres individuais
            return element if element not in forbidden_chars else None
    
    return [filtered for match in re.findall(pattern, text)
            for element in match if element
            for filtered in [filter_element(element)] if filtered]


def simulate_keypress(key, press=True, release=False):
    global set_index
    shift_keys = {'!': '1', '@': '2', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8', '(': '9'}
    
    if key in shift_keys:
        with keyboard_controller.pressed(Key.shift):
            if press:
                keyboard_controller.press(shift_keys[key])
            if release:
                keyboard_controller.release(shift_keys[key])
    elif key.isupper():
        with keyboard_controller.pressed(Key.shift):
            if press:
                keyboard_controller.press(key.lower())
            if release:
                keyboard_controller.release(key.lower())
    else:
        if press:
            keyboard_controller.press(key)
        if release:
            keyboard_controller.release(key)

def generate_random_char():
    forbidden_chars = set([',', '-', '+','\\','´',';','ç','[',']','{','}','`','~','/','\'','_','|','=','<','>',':','\"','?','.'])
    while True:
        new_char = chr(random.randint(33, 126))
        if new_char not in forbidden_chars:
            return new_char
        
#Imperfect mode
def introduce_error(element):
    if len(element) > 1:  # For note sets like [abc]
        if random.random() < 0.05: #5%
            index = random.randint(0, len(element) - 1)
            new_char = generate_random_char()
            return element[:index] + new_char + element[index+1:]
    else:  # For single notes
        if random.random() < 0.05: #5%
            return generate_random_char()
    return element

#Processes next note
def process_next():
    global set_index, current_element
    with lock:
        if set_index < len(text_set):
            current_element = text_set[set_index]
            if imperfect_mode:
                current_element = introduce_error(current_element)
            set_index += 1
            return True
        return False

def key_monitoring_thread():
    global running, current_element, return_to_menu, set_index
    minus_pressed = False
    while running:
        if keyboard.is_pressed('-'):
            if not minus_pressed:
                minus_pressed = True
                if process_next() and current_element:
                    for key in current_element:
                        simulate_keypress(key, press=True, release=False)
        else:
            if minus_pressed:
                minus_pressed = False
                if current_element:
                    for key in current_element:
                        simulate_keypress(key, press=False, release=True)
                current_element = None

        if keyboard.is_pressed(','):
            set_index = 0
        if keyboard.is_pressed('+'):
            return_to_menu = True
            running = False
        if keyboard.is_pressed('esc'):
            running = False
        
        time.sleep(0.01)  # Small delay to prevent excessive CPU usage

def run_program(filename):
    global text_set, running, return_to_menu, set_index, imperfect_mode

    text_content = read_file(filename)
    if text_content:
        text_set = parse_text_to_set(text_content)
    else:
        return

    print(f"\nFile '{filename}' loaded and transformed into a set.")
    print("Resulting set:", text_set)
    print("Press and hold '-' to simulate typing the next element.")
    print("Press ',' to reset.")
    print("Press '+' to return to the main menu.")
    print("Release '-' to free the keys and move to the next element.")
    print("Press 'Esc' to exit.")
    print(f"Imperfect mode: {'Enabled' if imperfect_mode else 'Disabled'}")
    running = True
    return_to_menu = False
    set_index = 0

    monitoring_thread = Thread(target=key_monitoring_thread)
    monitoring_thread.start()

    while running:
        time.sleep(0.1)

    monitoring_thread.join()

def main():
    global imperfect_mode
    while True:
        files = list_txt_files()
        if not files:
            print("No .txt file found inside the current directory.\nDid you insert at the same folder where PPiano is installed?")
            input("Press the [ENTER] key to continue.")
            return

        display_menu(files)
        choice = input("Enter your option (or 'q' to quit): ")
        
        if choice.lower() == 'q':
            break
        elif choice.lower() == 'i':
            imperfect_mode = not imperfect_mode
            print(f"Imperfect Mode: {'ON' if imperfect_mode else 'OFF'}.")
            continue

        try:
            file_index = int(choice) - 1
            if 0 <= file_index < len(files):
                filename = files[file_index]
                run_program(filename)
                if not return_to_menu:
                    break
            else:
                print("Invalid option. Please, try again.")
        except ValueError:
            print("Invalid value. Please, enter a valid value.")

    print("Program ended.")

if __name__ == "__main__":
    main()