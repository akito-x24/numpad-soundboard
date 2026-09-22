"""Small modal that captures the next physical keypress for rebinding CE/Panic."""
from __future__ import annotations

from typing import Callable

import customtkinter as ctk


class RebindDialog(ctk.CTkToplevel):
    def __init__(self, master, current_label: str, on_cancel: Callable[[], None]):
        super().__init__(master)
        self.title("Rebind Panic Key")
        self.geometry("400x200")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self._on_cancel = on_cancel
        self._conflict_label = None

        ctk.CTkLabel(
            self, text="Press the key you want to use\nfor PANIC / STOP ALL AUDIO",
            font=ctk.CTkFont(size=14, weight="bold"), justify="center",
        ).pack(pady=(24, 8))
        ctk.CTkLabel(
            self, text=f"Currently: {current_label}", text_color=("gray40", "gray65")
        ).pack(pady=(0, 12))
        ctk.CTkButton(self, text="Cancel", width=100, command=self._cancel).pack(pady=4)

        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _cancel(self) -> None:
        self._on_cancel()
        self.destroy()

    def show_conflict(self, message: str) -> None:
        if self._conflict_label is None:
            self._conflict_label = ctk.CTkLabel(self, text="", text_color="#D9822B", wraplength=340)
            self._conflict_label.pack(pady=(0, 8))
        self._conflict_label.configure(text=message)
