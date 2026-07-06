from pynput import keyboard

# macOS virtual keycodes for number row (top of keyboard)
# These are stable regardless of modifier keys held
_VK_MAP = {
    29: 0,   # 0
    18: 1,   # 1
    19: 2,   # 2
    20: 3,   # 3
    21: 4,   # 4
    23: 5,   # 5
    22: 6,   # 6
    26: 7,   # 7
}


class GhostKeyListener:
    def __init__(self, on_document_switch, on_back, on_quit, on_ctrl_toggle=None):
        self._on_document_switch = on_document_switch
        self._on_back = on_back
        self._on_quit = on_quit
        self._on_ctrl_toggle = on_ctrl_toggle  # called with True/False when Ctrl is pressed/released
        self._ctrl_pressed = False
        self._shift_pressed = False
        self._listener = None

    def start(self):
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _on_press(self, key):
        # Track modifier state
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
            self._ctrl_pressed = True
            if self._on_ctrl_toggle:
                self._on_ctrl_toggle(True)
            return
        if key in (keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.shift):
            self._shift_pressed = True
            return

        # Escape -> go back to document list (only with Ctrl to avoid accidental triggers)
        if self._ctrl_pressed and key == keyboard.Key.esc:
            self._on_back()
            return

        # Ctrl + Shift + Q -> quit Ghost
        if self._ctrl_pressed and self._shift_pressed:
            if hasattr(key, "char") and key.char in ("q", "Q"):
                self._on_quit()
                return
            # Also check vk for 'q' (macOS vk=12)
            if hasattr(key, "vk") and key.vk == 12:
                self._on_quit()
                return

        # Ctrl + number -> switch document (using virtual keycodes for reliability)
        if self._ctrl_pressed and hasattr(key, "vk") and key.vk is not None:
            number = _VK_MAP.get(key.vk)
            if number is not None:
                if 1 <= number <= 7:
                    self._on_document_switch(number)
                    return
                if number == 0:
                    self._on_back()
                    return

        # Fallback: also check key.char in case vk is not available
        if self._ctrl_pressed and hasattr(key, "char") and key.char is not None:
            if key.char in "1234567":
                self._on_document_switch(int(key.char))
                return
            if key.char == "0":
                self._on_back()
                return

    def _on_release(self, key):
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
            self._ctrl_pressed = False
            if self._on_ctrl_toggle:
                self._on_ctrl_toggle(False)
        if key in (keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.shift):
            self._shift_pressed = False
