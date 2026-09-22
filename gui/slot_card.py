from __future__ import annotations
from typing import Callable
import customtkinter as ctk

class SlotCard(ctk.CTkFrame):
    def __init__(
        self,
        master,
        slot_key: str,
        empty_label: str,
        on_test: Callable[[str], None],
        on_change: Callable[[str], None],
        on_remove: Callable[[str], None],
        on_volume_change: Callable[[str, int], None],
        **kwargs,
    ):
        super().__init__(master, corner_radius=16, height=118, **kwargs)
        # Lock the card to a fixed height regardless of content (grid
        # normally auto-sizes a frame to its tallest child, which would
        # make a card with a long, wrapped filename taller than an empty
        # one next to it - grid_propagate(False) is what actually pins
        # the size point 6 asked for; height=96 alone isn't enough).
        self.grid_propagate(False)

        self.slot_key = slot_key
        self.empty_label = empty_label
        self._on_test = on_test
        self._on_change = on_change
        self._on_remove = on_remove
        self._on_volume_change = on_volume_change

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # The clickable body: a plain frame + label (not a CTkButton - it
        # doesn't support wraplength) so long filenames wrap instead of
        # overflowing the card. Left-click = change/add, right-click =
        # remove; both are bound on the frame AND the label so clicking
        # anywhere in the body works, matching "press the box or the name".
        self.body = ctk.CTkFrame(self, fg_color="transparent", corner_radius=8, cursor="hand2")
        self.body.grid(row=0, column=0, padx=(8, 4), pady=(10, 4), sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)

        self.name_label = ctk.CTkLabel(
            self.body, text=empty_label, anchor="w", justify="left",
            text_color=("gray45", "gray60"), font=ctk.CTkFont(size=15),
            wraplength=360, cursor="hand2",
        )
        self.name_label.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        for widget in (self.body, self.name_label):
            widget.bind("<Button-1>", self._handle_change_event)
            widget.bind("<Button-3>", self._handle_remove_event)

        self.play_btn = ctk.CTkButton(
            self, text="\u25b6", width=36, height=48, corner_radius=36,
            font=ctk.CTkFont(size=24), command=self._handle_test,
        )
        self.play_btn.grid(row=0, column=1, padx=(0, 10), pady=(10, 5))

        # Always present (even when empty) so the card is the same size
        # whether or not a sound is assigned.
        self.volume_slider = ctk.CTkSlider(
            self, from_=0, to=100, number_of_steps=100, height=16,
            command=self._on_slider_move,
        )
        self.volume_slider.grid(row=1, column=0, columnspan=2, padx=8, pady=(0, 10), sticky="ew")

        self.set_empty()

    # ---- widget event handlers ----

    def _handle_test(self) -> None:
        self._on_test(self.slot_key)

    def _handle_change_event(self, event=None) -> None:
        self._on_change(self.slot_key)

    def _handle_remove_event(self, event=None) -> None:
        self._on_remove(self.slot_key)

    def _on_slider_move(self, value) -> None:
        self._on_volume_change(self.slot_key, int(round(value)))

    # ---- display states (size never changes between these) ----

    def set_empty(self) -> None:
        self.name_label.configure(text=self.empty_label, text_color=("gray45", "gray60"))
        self.volume_slider.set(100)  # DEFAULT_SLOT_VOLUME - otherwise an
        # untouched CTkSlider sits at its own arbitrary default position,
        # not a meaningful one.
        self.play_btn.configure(state="disabled")

    def set_missing(self, display_name: str, volume: int = 100) -> None:
        self.name_label.configure(text=f"{display_name}  [MISSING]", text_color="#D9822B")
        self.volume_slider.set(volume)  # the stored volume is still meaningful even though the file is gone
        self.play_btn.configure(state="disabled")

    def set_assigned(self, display_name: str, volume: int) -> None:
        self.name_label.configure(text=display_name, text_color=("gray10", "gray95"))
        self.volume_slider.set(volume)
        self.play_btn.configure(state="normal")