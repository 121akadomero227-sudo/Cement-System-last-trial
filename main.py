"""URMC KAJJANSI - Truck Offloaders' Payment System (Kivy / Android).

Launch sequence: logo -> "Welcome to URMC KAJJANSI" -> dashboard.
"""
import os
import re
import json
import shutil
import difflib
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.animation import Animation
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition, NoTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform

import Urmc
import assets_data
from io import BytesIO
from base64 import b64decode
from kivy.core.image import Image as CoreImage

Window.clearcolor = (1, 1, 1, 1)   # white from the very first frame
Window.softinput_mode = "below_target"

DEFAULT_PRICE_PER_BAG = 150

# ---------------------------------------------------------------- theme
RED = (0.89, 0.15, 0.17, 1)
YELLOW = (1.0, 0.83, 0.0, 1)
HEADER = (0.075, 0.078, 0.09, 1)
BG = (0.95, 0.955, 0.965, 1)
WHITE = (1, 1, 1, 1)
TEXT = (0.10, 0.11, 0.13, 1)
MUTED = (0.42, 0.45, 0.50, 1)
LINE = (0.86, 0.87, 0.90, 1)
GREEN = (0.10, 0.60, 0.34, 1)
SOFT_RED = (1.0, 0.91, 0.91, 1)
LIGHT = (0.92, 0.93, 0.95, 1)

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
LOGO = os.path.join(ASSET_DIR, "logo.png")

APP = None          # set by AppMain
OPEN_MODALS = []    # currently open pop-ups (for the Android back key)

PROTECTED = {"finalize", "price", "password"}


_TEX = {}


def _texture(key, b64):
    if key not in _TEX:
        _TEX[key] = CoreImage(BytesIO(b64decode(b64)), ext="png").texture
    return _TEX[key]


def icon_tex(name):
    return _texture("i_" + name, assets_data.ICONS[name])


def logo_tex():
    return _texture("logo", assets_data.LOGO_PNG)


# ---------------------------------------------------------- data helpers
def _number(value):
    try:
        v = float(value)
        return int(v) if v == int(v) else v
    except (TypeError, ValueError):
        return DEFAULT_PRICE_PER_BAG


def get_price(data, truck=None):
    """Price that applies to a truck (its own saved price, else the system one)."""
    if truck and truck.get("price_per_bag") is not None:
        return _number(truck.get("price_per_bag"))
    if data.get("price_per_bag") is not None:
        return _number(data.get("price_per_bag"))
    return _number(getattr(Urmc, "PRICE_PER_BAG", DEFAULT_PRICE_PER_BAG))


def truck_revenue(data, truck):
    return int(round(truck.get("bags", 0) * get_price(data, truck)))


def ensure_price_setting(data):
    """Make sure the system price exists and every truck carries its own price.

    Old records without a stored price are stamped with the current price once,
    so later price changes can never rewrite them or their receipts.
    """
    changed = False
    if data.get("price_per_bag") is None:
        data["price_per_bag"] = _number(
            getattr(Urmc, "PRICE_PER_BAG", DEFAULT_PRICE_PER_BAG))
        changed = True
    for t in data.get("trucks", []):
        if t.get("price_per_bag") is None:
            t["price_per_bag"] = data["price_per_bag"]
            changed = True
    if changed:
        Urmc.save_data(data)
    Urmc.PRICE_PER_BAG = data["price_per_bag"]
    return data["price_per_bag"]


def load():
    d = Urmc.load_data()
    ensure_price_setting(d)
    return d


def find_truck(data, record_no):
    return next((t for t in data.get("trucks", [])
                 if t.get("system_record_number") == record_no), None)


def delete_truck(record_no):
    d = load()
    t = find_truck(d, record_no)
    if t is None:
        raise ValueError("Record not found.")
    if t.get("finalized"):
        raise ValueError("Paid trucks cannot be deleted.")
    idx = d["trucks"].index(t)
    d["trucks"].pop(idx)
    if not Urmc.save_data(d):
        raise RuntimeError("The record could not be deleted (save failed).")


def restore_latest_backup():
    """Replace a damaged database with the newest backup that passes checks."""
    files = sorted(
        (os.path.join(Urmc.BACKUP_FOLDER, f)
         for f in os.listdir(Urmc.BACKUP_FOLDER) if f.endswith(".json")),
        key=os.path.getmtime, reverse=True)
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                candidate = json.load(fh)
        except (OSError, ValueError):
            continue
        if Urmc.validate_database(candidate):
            if os.path.exists(Urmc.DATA_FILE):
                shutil.copyfile(
                    Urmc.DATA_FILE,
                    Urmc.DATA_FILE + ".damaged-"
                    + datetime.now().strftime("%Y%m%d-%H%M%S"))
            shutil.copyfile(path, Urmc.DATA_FILE)
            return os.path.basename(path)
    return None


# ---- worker-name helpers (kept from the original app) -----------------
def normalize_name(name):
    name = " ".join(str(name).strip().split())
    if not name:
        return ""
    return Urmc.clean_name(name)


def _worker_base_name(name):
    """Separate a worker name from an optional number/Roman numeral."""
    s = " ".join(str(name).strip().split())
    m = re.match(r"^(.*?)(?:\s+([0-9]+|[ivxlcdm]+))?$", s, re.IGNORECASE)
    if not m:
        return s, ""
    return m.group(1).strip(), (m.group(2) or "").lower()


def _name_key(name):
    base, suffix = _worker_base_name(name)
    key = re.sub(r"[^a-z0-9]", "", base.casefold())
    return key, suffix


def _name_similarity(a, b):
    ak, asuffix = _name_key(a)
    bk, bsuffix = _name_key(b)

    # James and James II are deliberately different people.
    if asuffix != bsuffix or not ak or not bk:
        return 0.0

    ratio = difflib.SequenceMatcher(None, ak, bk).ratio()

    # Catch a single omitted/added character in longer names such as
    # Jeremiah / Jeremaih, while avoiding aggressive merging of short names.
    longest = max(len(ak), len(bk))
    if longest <= 4:
        threshold = 0.90
    elif longest <= 7:
        threshold = 0.84
    else:
        threshold = 0.80

    return ratio if ratio >= threshold else 0.0


def known_worker_names(data):
    names = []
    seen = set()
    for t in data.get("trucks", []):
        for raw in t.get("workers", []):
            name = normalize_name(raw)
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                names.append(name)
    return names


def possible_worker_match(name, known):
    matches = []
    for existing in known:
        score = _name_similarity(name, existing)
        if score:
            matches.append((score, existing))
    matches.sort(reverse=True)
    return matches[0] if matches else None




def _canonicalize_worker_names(names):
    """Create a display mapping for obvious spelling mistakes.

    Numbered/Roman-numeral variants such as James and James II remain separate.
    """
    clean_names = []
    for raw in names:
        name = normalize_name(raw)
        if name and name.casefold() not in {x.casefold() for x in clean_names}:
            clean_names.append(name)

    canonical = []
    mapping = {}

    for name in clean_names:
        found = None
        best_ratio = 0.0
        for existing in canonical:
            ratio = _name_similarity(name, existing)
            if ratio > best_ratio:
                found = existing
                best_ratio = ratio
        if found is None:
            canonical.append(name)

    for raw in names:
        name = normalize_name(raw)
        if not name:
            continue
        found = None
        best_ratio = 0.0
        for existing in canonical:
            ratio = _name_similarity(name, existing)
            if ratio > best_ratio:
                found = existing
                best_ratio = ratio
        mapping[name] = found or name

    return mapping





def launch_next(manager, name):
    """Switch without any transition, so no black frame appears."""
    manager.transition = NoTransition()
    manager.current = name
    manager.transition = SlideTransition(duration=0.22)


def go_back_slide(manager, name):
    manager.transition.direction = "right"
    manager.current = name
    Clock.schedule_once(
        lambda dt: setattr(manager.transition, "direction", "left"), 0.4)


# ---------------------------------------------------------- UI widgets
def paint(widget, color, radius=0):
    """Give a widget a (rounded) background. Returns the Color so it can change."""
    with widget.canvas.before:
        col = Color(*color)
        rect = RoundedRectangle(pos=widget.pos, size=widget.size,
                                radius=[dp(radius)])

    def upd(*_):
        rect.pos = widget.pos
        rect.size = widget.size

    widget.bind(pos=upd, size=upd)
    return col


class Lbl(Label):
    """Single-line label that fills its box and truncates instead of overflowing."""

    def __init__(self, text="", fs=15, color=TEXT, bold=False,
                 halign="left", h=None, **kw):
        super().__init__(text=text, font_size=sp(fs), color=color, bold=bold,
                         halign=halign, valign="middle", shorten=True,
                         shorten_from="right", **kw)
        if h:
            self.size_hint_y = None
            self.height = dp(h)
        self.bind(size=lambda *_: setattr(self, "text_size", self.size))


class Txt(Label):
    """Wrapping label whose height follows its text."""

    def __init__(self, text="", fs=15, color=TEXT, bold=False,
                 halign="left", **kw):
        super().__init__(text=text, font_size=sp(fs), color=color, bold=bold,
                         halign=halign, valign="top", size_hint_y=None,
                         height=dp(20), **kw)
        self.bind(
            width=lambda *_: setattr(self, "text_size", (self.width, None)),
            texture_size=lambda *_: setattr(self, "height",
                                            self.texture_size[1]))


class Card(BoxLayout):
    def __init__(self, bg=WHITE, border=LINE, radius=14, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            self._bcol = Color(*border)
            self._outer = RoundedRectangle(radius=[dp(radius)])
            Color(*bg)
            self._inner = RoundedRectangle(radius=[dp(max(radius - 1, 0))])
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._outer.pos = self.pos
        self._outer.size = self.size
        self._inner.pos = (self.x + dp(1), self.y + dp(1))
        self._inner.size = (max(self.width - dp(2), 0),
                            max(self.height - dp(2), 0))

    def set_border(self, color):
        self._bcol.rgba = color


def auto_height(widget):
    widget.size_hint_y = None
    widget.bind(minimum_height=widget.setter("height"))
    return widget


class Btn(ButtonBehavior, BoxLayout):
    def __init__(self, text="", icon=None, bg=RED, fg=WHITE, h=52, fs=16,
                 radius=12, **kw):
        kw.setdefault("size_hint_y", None)
        super().__init__(orientation="horizontal", height=dp(h),
                         padding=[dp(10), 0], spacing=dp(8), **kw)
        self._bg = bg
        self._col = paint(self, bg, radius)
        self.add_widget(Widget())
        if icon:
            self.add_widget(Image(
                texture=icon_tex(icon), size_hint=(None, None),
                size=(dp(h * 0.42), dp(h * 0.42)),
                pos_hint={"center_y": .5}, color=fg))
        if text:
            self.lbl = Label(text=text, bold=True, font_size=sp(fs),
                             color=fg, size_hint_x=None)
            self.lbl.bind(texture_size=lambda i, v: setattr(i, "width", v[0]))
            self.add_widget(self.lbl)
        self.add_widget(Widget())
        self.bind(state=self._on_state)

    def _on_state(self, *_):
        if self.state == "down":
            self._col.rgba = tuple(c * 0.80 for c in self._bg[:3]) + (1,)
        else:
            self._col.rgba = self._bg

    def set_bg(self, color):
        self._bg = color
        self._col.rgba = color


class IconBtn(ButtonBehavior, BoxLayout):
    def __init__(self, icon, size=46, tint=WHITE, bg=(1, 1, 1, .12), **kw):
        super().__init__(size_hint=(None, None), size=(dp(size), dp(size)),
                         padding=dp(size * 0.24), pos_hint={"center_y": .5},
                         **kw)
        paint(self, bg, size / 2)
        self.add_widget(Image(texture=icon_tex(icon), color=tint))
        self.bind(state=lambda *_: setattr(
            self, "opacity", .6 if self.state == "down" else 1))


class Tile(ButtonBehavior, Card):
    def __init__(self, text, icon, accent=RED, icon_color=WHITE, **kw):
        super().__init__(orientation="vertical", size_hint_y=None,
                         height=dp(118), padding=[dp(8), dp(12), dp(8), dp(8)],
                         spacing=dp(8), **kw)
        circle = BoxLayout(size_hint=(None, None), size=(dp(50), dp(50)),
                           pos_hint={"center_x": .5}, padding=dp(12))
        paint(circle, accent, 25)
        circle.add_widget(Image(texture=icon_tex(icon), color=icon_color))
        self.add_widget(circle)
        self.add_widget(Lbl(text, fs=14, bold=True, halign="center"))
        self.bind(state=lambda *_: setattr(
            self, "opacity", .7 if self.state == "down" else 1))


class Field(Card):
    """Labelled, rounded text box. The TextInput is `.input`."""

    def __init__(self, hint="", text="", h=54, multiline=False, filt=None,
                 input_type="text", password=False, **kw):
        super().__init__(orientation="horizontal", size_hint_y=None,
                         height=dp(h), padding=dp(3), radius=12,
                         border=(0.78, 0.80, 0.84, 1), **kw)
        self.input = TextInput(
            hint_text=hint, text=text, multiline=multiline,
            input_filter=filt, input_type=input_type, password=password,
            background_normal="", background_active="",
            background_color=(0, 0, 0, 0), foreground_color=TEXT,
            hint_text_color=(0.58, 0.61, 0.66, 1), cursor_color=RED,
            font_size=sp(17), write_tab=False,
            padding=[dp(10), dp(14), dp(10), dp(8)])
        self.input.bind(focus=lambda i, f: self.set_border(RED if f else (
            0.78, 0.80, 0.84, 1)))
        self.add_widget(self.input)


def chip(text, color):
    c = Label(text=text, bold=True, font_size=sp(12), color=WHITE,
              size_hint=(None, None), size=(dp(84), dp(26)),
              pos_hint={"center_y": .5})
    paint(c, color, 13)
    return c


def section_label(text):
    return Lbl(text, fs=13, color=MUTED, bold=True, h=26)


def scroll_list(spacing=10):
    sv = ScrollView(do_scroll_x=False, bar_width=dp(3),
                    scroll_type=["bars", "content"])
    grid = GridLayout(cols=1, spacing=dp(spacing), size_hint_y=None,
                      padding=[0, 0, 0, dp(8)])
    grid.bind(minimum_height=grid.setter("height"))
    sv.add_widget(grid)
    return sv, grid


def note_card(text, color=MUTED):
    card = Card(orientation="vertical", size_hint_y=None, padding=dp(16))
    card.bind(minimum_height=card.setter("height"))
    card.add_widget(Txt(text, fs=15, color=color, halign="center"))
    return card


def info_card(title, rows, accent=RED):
    """Titled card with label/value rows."""
    card = Card(orientation="vertical", size_hint_y=None, padding=dp(14),
                spacing=dp(4))
    card.bind(minimum_height=card.setter("height"))
    card.add_widget(Lbl(title, fs=17, bold=True, color=accent, h=30))
    for k, v in rows:
        row = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(8))
        row.add_widget(Lbl(k, fs=14, color=MUTED, size_hint_x=.52))
        row.add_widget(Lbl(v, fs=15, bold=True, halign="right",
                           size_hint_x=.48))
        card.add_widget(row)
    return card


def truck_card(d, t, on_edit=None, on_delete=None):
    paid = bool(t.get("finalized"))
    card = Card(orientation="vertical", size_hint_y=None, padding=dp(14),
                spacing=dp(6))
    card.bind(minimum_height=card.setter("height"))

    top = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(8))
    top.add_widget(Lbl(t.get("actual_truck_number") or "(no truck number)",
                       fs=18, bold=True))
    top.add_widget(chip("PAID" if paid else "UNPAID", GREEN if paid else RED))
    card.add_widget(top)

    card.add_widget(Lbl(
        f"Record #{t['system_record_number']}   •   {t['offloading_date']}",
        fs=14, color=MUTED, h=22))

    money_row = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(8))
    money_row.add_widget(Lbl(
        f"{t['bags']:,} bags × {Urmc.money(get_price(d, t))}", fs=15,
        size_hint_x=.5))
    money_row.add_widget(Lbl(Urmc.money(truck_revenue(d, t)), fs=20,
                             bold=True, color=RED, halign="right",
                             size_hint_x=.5))
    card.add_widget(money_row)

    workers = t.get("workers", [])
    card.add_widget(Txt(f"Workers ({len(workers)}): " + ", ".join(workers),
                        fs=14, color=MUTED))
    if paid and t.get("payment_batch_id"):
        card.add_widget(Txt(
            f"Paid {t.get('payment_date', '')} • {t['payment_batch_id']}",
            fs=13, color=GREEN))
    if t.get("edited_at") and not paid:
        card.add_widget(Txt(f"Edited {t['edited_at']}", fs=12, color=MUTED))

    if (on_edit or on_delete) and not paid:
        actions = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        if on_edit:
            actions.add_widget(Btn("EDIT", "edit", bg=YELLOW, fg=TEXT, h=46,
                                   fs=15, on_release=lambda *_: on_edit()))
        if on_delete:
            actions.add_widget(Btn("DELETE", "trash", bg=SOFT_RED, fg=RED,
                                   h=46, fs=15,
                                   on_release=lambda *_: on_delete()))
        card.add_widget(actions)
    return card


# ------------------------------------------------------------- pop-ups
class Modal(ModalView):
    """Styled pop-up. buttons = [(text, bg, fg, callback_or_None), ...]"""

    def __init__(self, title, body="", buttons=None, accent=RED,
                 content=None, **kw):
        super().__init__(size_hint=(.92, None), auto_dismiss=False,
                         background="", background_color=(0, 0, 0, 0),
                         overlay_color=(0, 0, 0, .55), **kw)
        card = Card(orientation="vertical", size_hint=(1, None),
                    padding=dp(18), spacing=dp(12), radius=18)
        card.bind(minimum_height=card.setter("height"))
        card.bind(height=lambda *_: setattr(self, "height", card.height))

        card.add_widget(Txt(title, fs=19, bold=True, color=accent))

        if body:
            txt = Txt(body, fs=15)
            sv = ScrollView(size_hint_y=None, do_scroll_x=False,
                            bar_width=dp(3))

            def fit(*_):
                sv.height = min(txt.height, Window.height * 0.5)

            txt.bind(height=fit)
            sv.add_widget(txt)
            card.add_widget(sv)
        if content is not None:
            card.add_widget(content)

        buttons = buttons or [("OK", RED, WHITE, None)]
        stacked = len(buttons) > 2
        row = BoxLayout(
            orientation="vertical" if stacked else "horizontal",
            size_hint_y=None, spacing=dp(10))
        if stacked:
            row.bind(minimum_height=row.setter("height"))
        else:
            row.height = dp(50)
        for text, bg, fg, cb in buttons:
            row.add_widget(Btn(text, bg=bg, fg=fg, h=50, fs=15,
                               on_release=lambda *_, c=cb: self._press(c)))
        card.add_widget(row)
        self.add_widget(card)
        self.bind(on_open=lambda *_: OPEN_MODALS.append(self),
                  on_dismiss=lambda *_: OPEN_MODALS.remove(self)
                  if self in OPEN_MODALS else None)

    def _press(self, cb):
        self.dismiss()
        if cb:
            Clock.schedule_once(lambda dt: cb(), 0.05)


def info(title, message, kind="info", on_ok=None):
    accent = {"ok": GREEN, "error": RED}.get(kind, TEXT)
    Modal(title, message, [("OK", accent if kind != "info" else RED, WHITE,
                            on_ok)], accent=accent).open()


def confirm(title, message, yes_text, on_yes, danger=True, yes_color=None):
    Modal(title, message, [
        ("CANCEL", LIGHT, TEXT, None),
        (yes_text, yes_color or (RED if danger else GREEN), WHITE, on_yes),
    ]).open()


# --------------------------------------------------------------- pages
class Page(Screen):
    """Screen with a branded header and an inset-safe body."""
    title = ""
    subtitle = ""
    show_back = True

    def __init__(self, **kw):
        super().__init__(**kw)
        app = APP
        root = BoxLayout(orientation="vertical")
        paint(root, BG)

        header = BoxLayout(orientation="vertical", size_hint_y=None)
        header.bind(minimum_height=header.setter("height"))
        paint(header, HEADER)
        self.top_gap = Widget(size_hint_y=None, height=app.inset_top)
        header.add_widget(self.top_gap)

        self.bar = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(12),
                             padding=[dp(10), dp(6)])
        if self.show_back:
            self.bar.add_widget(IconBtn(
                "back", on_release=lambda *_: self.go_back()))
        else:
            logo_box = BoxLayout(size_hint=(None, None),
                                 size=(dp(84), dp(46)), padding=dp(3),
                                 pos_hint={"center_y": .5})
            paint(logo_box, WHITE, 8)
            logo_box.add_widget(Image(texture=logo_tex()))
            self.bar.add_widget(logo_box)

        titles = BoxLayout(orientation="vertical")
        self.title_label = Lbl(self.title, fs=19, bold=True, color=WHITE)
        titles.add_widget(self.title_label)
        if self.subtitle:
            titles.add_widget(Lbl(self.subtitle, fs=12, color=YELLOW,
                                  size_hint_y=None, height=dp(18)))
        self.bar.add_widget(titles)
        header.add_widget(self.bar)

        stripe = BoxLayout(size_hint_y=None, height=dp(4))
        for c in (RED, YELLOW):
            w = Widget()
            paint(w, c)
            stripe.add_widget(w)
        header.add_widget(stripe)
        root.add_widget(header)

        self.body = BoxLayout(orientation="vertical", spacing=dp(10))
        root.add_widget(self.body)
        self.add_widget(root)

        self._apply_insets()
        app.bind(inset_left=self._apply_insets, inset_top=self._apply_insets,
                 inset_right=self._apply_insets,
                 inset_bottom=self._apply_insets)

    def _apply_insets(self, *_):
        a = APP
        self.top_gap.height = a.inset_top
        self.bar.padding = [dp(10) + a.inset_left, dp(6),
                            dp(10) + a.inset_right, dp(6)]
        self.body.padding = [dp(16) + a.inset_left, dp(12),
                             dp(16) + a.inset_right,
                             dp(12) + a.inset_bottom]

    def back_target(self):
        return "dashboard"

    def go_back(self):
        go_back_slide(self.manager, self.back_target())


# ------------------------------------------------- launch sequence screens
class LaunchScreen(Screen):
    """Logo alone (3 s) -> cross-fade to the welcome message -> dashboard."""

    FADE_SECONDS = 2.8
    WELCOME_SECONDS = 2.4

    def __init__(self, **kw):
        super().__init__(**kw)
        root = FloatLayout()
        paint(root, WHITE)

        # layer 1: the logo, alone
        self.logo = Image(texture=logo_tex(), size_hint=(.82, .4),
                          pos_hint={"center_x": .5, "center_y": .5})
        root.add_widget(self.logo)

        # layer 2: welcome message, fully transparent until it fades in
        self.welcome = FloatLayout(opacity=0)
        paint(self.welcome, HEADER)

        content = BoxLayout(
            orientation="vertical", size_hint=(.88, None), height=dp(300),
            pos_hint={"center_x": .5, "center_y": .52}, spacing=dp(18))

        badge = BoxLayout(size_hint=(None, None), size=(dp(92), dp(92)),
                          padding=dp(22), pos_hint={"center_x": .5})
        paint(badge, YELLOW, 46)
        badge.add_widget(Image(texture=icon_tex("truck"), color=HEADER))
        content.add_widget(badge)

        msg = Label(
            text=("[size=24sp]Welcome to[/size]\n"
                  "[size=34sp][b][color=ffd400]URMC KAJJANSI[/color][/b]"
                  "[/size]"),
            markup=True, color=WHITE, halign="center", valign="middle",
            size_hint_y=None, height=dp(100))
        msg.bind(size=lambda *_: setattr(msg, "text_size", msg.size))
        content.add_widget(msg)

        stripe = BoxLayout(size_hint=(None, None), size=(dp(150), dp(5)),
                           pos_hint={"center_x": .5})
        for c in (RED, YELLOW):
            w = Widget()
            paint(w, c)
            stripe.add_widget(w)
        content.add_widget(stripe)

        content.add_widget(Lbl(
            "Universal Readymix Concrete Ltd", fs=14,
            color=(0.80, 0.82, 0.86, 1), halign="center", h=24))

        self.welcome.add_widget(content)
        root.add_widget(self.welcome)
        self.add_widget(root)
        self._events = []

    def on_enter(self, *_):
        self._t = 0.0
        self._phase = "fade"
        self._ticker = Clock.schedule_interval(self._tick, 0)

    def _tick(self, dt):
        # Heavy start-up work happens here, one piece per frame, while the
        # fade plays. Time is counted in capped frame steps so a slow frame
        # can never make the fade or the welcome message be skipped.
        APP.build_next()
        self._t += min(dt, 0.05)
        if self._phase == "fade":
            p = min(self._t / self.FADE_SECONDS, 1.0)
            self.welcome.opacity = p * p * (3 - 2 * p)
            if p >= 1.0:
                self._phase = "hold"
                self._t = 0.0
        elif self._t >= self.WELCOME_SECONDS and APP.ready:
            self._ticker.cancel()
            launch_next(self.manager, "dashboard")

    def on_leave(self, *_):
        t = getattr(self, "_ticker", None)
        if t:
            t.cancel()


# ----------------------------------------------------------- dashboard
class Dashboard(Page):
    title = "URMC KAJJANSI"
    subtitle = "Truck Offloaders' Payment System"
    show_back = False

    def __init__(self, **kw):
        super().__init__(**kw)
        sv = ScrollView(do_scroll_x=False, bar_width=dp(3),
                        scroll_type=["bars", "content"])
        self.col = BoxLayout(orientation="vertical", size_hint_y=None,
                             spacing=dp(14), padding=[0, 0, 0, dp(10)])
        self.col.bind(minimum_height=self.col.setter("height"))
        sv.add_widget(self.col)
        self.body.add_widget(sv)

        # filled on every visit
        self.alert_box = BoxLayout(orientation="vertical", size_hint_y=None,
                                   spacing=dp(10))
        auto_height(self.alert_box)
        self.col.add_widget(self.alert_box)

        hero = Card(bg=HEADER, border=HEADER, orientation="vertical",
                    size_hint_y=None, height=dp(130), padding=dp(16),
                    spacing=dp(2), radius=18)
        hero.add_widget(Lbl("UNPAID MONEY", fs=13, bold=True,
                            color=(0.75, 0.77, 0.82, 1), h=22))
        self.amount = Lbl("", fs=32, bold=True, color=YELLOW, h=52)
        hero.add_widget(self.amount)
        self.detail = Lbl("", fs=14, color=WHITE, h=24)
        hero.add_widget(self.detail)
        self.col.add_widget(hero)

        self.col.add_widget(section_label("MENU"))
        grid = GridLayout(cols=2, spacing=dp(12), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        tiles = [
            ("Record Truck", "plus", "record_new", RED, WHITE),
            ("Unpaid Trucks", "truck", "unpaid", YELLOW, HEADER),
            ("Finalize Payments", "check", "finalize", GREEN, WHITE),
            ("Payment History", "history", "history", HEADER, WHITE),
            ("Search Truck", "search", "search", YELLOW, HEADER),
            ("Worker Earnings", "users", "worker", RED, WHITE),
            ("System Summary", "chart", "summary", HEADER, WHITE),
            ("Statements", "doc", "statements", YELLOW, HEADER),
            ("Offloading Price", "tag", "price", RED, WHITE),
            ("Change Password", "lock", "password", HEADER, WHITE),
        ]
        for text, icon, target, accent, ic in tiles:
            grid.add_widget(Tile(
                text, icon, accent, ic,
                on_release=lambda *_, t=target: APP.go(t)))
        self.col.add_widget(grid)

        foot = Card(orientation="horizontal", size_hint_y=None,
                    height=dp(64), padding=[dp(12), dp(8)], spacing=dp(10))
        foot.add_widget(Image(texture=icon_tex("shield"), color=GREEN,
                              size_hint=(None, None),
                              size=(dp(30), dp(30)),
                              pos_hint={"center_y": .5}))
        txts = BoxLayout(orientation="vertical")
        txts.add_widget(Lbl("Auto-backup is ON", fs=14, bold=True,
                            color=GREEN))
        self.backup_lbl = Lbl("", fs=12, color=MUTED)
        txts.add_widget(self.backup_lbl)
        foot.add_widget(txts)
        foot.add_widget(Btn("LOCK", "power", bg=LIGHT, fg=TEXT, h=44, fs=13,
                            size_hint_x=None, width=dp(104),
                            pos_hint={"center_y": .5},
                            on_release=lambda *_: APP.lock()))
        self.col.add_widget(foot)

    def on_pre_enter(self, *_):
        self.alert_box.clear_widgets()
        if APP.db_error:
            card = Card(bg=SOFT_RED, border=RED, orientation="vertical",
                        size_hint_y=None, padding=dp(14), spacing=dp(8))
            card.bind(minimum_height=card.setter("height"))
            card.add_widget(Txt("DATABASE PROBLEM", fs=16, bold=True,
                                color=RED))
            card.add_widget(Txt(APP.db_error, fs=14))
            card.add_widget(Btn("RESTORE FROM LATEST BACKUP", "shield", h=48,
                                fs=14, on_release=lambda *_: self.restore()))
            self.alert_box.add_widget(card)
        try:
            d = load()
            unpaid = Urmc.unpaid_trucks(d)
            money = sum(truck_revenue(d, t) for t in unpaid)
            self.amount.text = Urmc.money(money)
            self.detail.text = (f"{len(unpaid)} truck(s) awaiting payment  •  "
                                f"{Urmc.money(get_price(d))}/bag")
        except Exception:
            self.amount.text = "—"
            self.detail.text = "Records unavailable"
        self.backup_lbl.text = Urmc.last_backup_text().split(" (")[0]

    def restore(self):
        def do():
            try:
                name = restore_latest_backup()
                if not name:
                    info("Restore failed", "No valid backup was found.",
                         "error")
                    return
                APP.db_error = ""
                info("Restored", f"Records restored from:\n{name}", "ok",
                     on_ok=lambda: self.on_pre_enter())
            except Exception as e:
                info("Restore failed", str(e), "error")
        confirm("Restore backup?",
                "The damaged database will be replaced by the newest valid "
                "backup. A copy of the damaged file is kept.",
                "RESTORE", do)


# -------------------------------------------------------- record / edit
class Record(Page):
    title = "Record Truck"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.edit_id = None
        self.return_to = "dashboard"

        sv = ScrollView(do_scroll_x=False, bar_width=dp(3))
        col = BoxLayout(orientation="vertical", size_hint_y=None,
                        spacing=dp(8), padding=[0, 0, 0, dp(12)])
        col.bind(minimum_height=col.setter("height"))
        sv.add_widget(col)

        self.banner = Card(bg=(1, 0.97, 0.80, 1), border=YELLOW,
                           orientation="vertical", size_hint_y=None,
                           padding=dp(12))
        self.banner.bind(minimum_height=self.banner.setter("height"))
        self.banner_txt = Txt("", fs=14)
        self.banner.add_widget(self.banner_txt)

        self.f_truck = Field("e.g. UBA 123X", input_type="text")
        self.f_date = Field("DD/MM/YYYY")
        self.f_bags = Field("e.g. 600", filt="int", input_type="number")
        self.f_workers = Field("One name per line", h=170, multiline=True)

        self.banner_holder = BoxLayout(orientation="vertical",
                                       size_hint_y=None)
        auto_height(self.banner_holder)
        col.add_widget(self.banner_holder)

        for label, fld in (("TRUCK NUMBER", self.f_truck),
                           ("OFFLOADING DATE", self.f_date),
                           ("NUMBER OF BAGS", self.f_bags),
                           ("WORKERS (ONE NAME PER LINE)", self.f_workers)):
            col.add_widget(section_label(label))
            col.add_widget(fld)

        col.add_widget(Widget(size_hint_y=None, height=dp(4)))
        self.save_btn = Btn("SAVE RECORD", "tick", bg=RED, h=58,
                            on_release=lambda *_: self.save())
        col.add_widget(self.save_btn)
        self.body.add_widget(sv)

    # ---- navigation
    def back_target(self):
        return self.return_to if self.edit_id is not None else "dashboard"

    def on_pre_enter(self, *_):
        self.banner_holder.clear_widgets()
        if self.edit_id is not None:
            self.title_label.text = "Edit Truck Record"
            self.save_btn.lbl.text = "SAVE CHANGES"
            try:
                t = find_truck(load(), self.edit_id)
                if t is None or t.get("finalized"):
                    raise ValueError("This record can no longer be edited.")
                self.f_truck.input.text = t.get("actual_truck_number", "")
                self.f_date.input.text = t.get("offloading_date", "")
                self.f_bags.input.text = str(t.get("bags", ""))
                self.f_workers.input.text = "\n".join(t.get("workers", []))
                self.banner_txt.text = (
                    f"Editing record #{self.edit_id}. The price per bag saved "
                    f"on this record ({Urmc.money(get_price(load(), t))}) "
                    "stays the same.")
                self.banner_holder.add_widget(self.banner)
            except Exception as e:
                info("Cannot edit", str(e), "error",
                     on_ok=lambda: setattr(self.manager, "current",
                                           self.return_to))
        else:
            self.title_label.text = "Record Truck"
            self.save_btn.lbl.text = "SAVE RECORD"
            self._clear()

    def on_leave(self, *_):
        self.edit_id = None

    def _clear(self):
        self.f_truck.input.text = ""
        self.f_date.input.text = Urmc.now_date()
        self.f_bags.input.text = ""
        self.f_workers.input.text = ""

    # ---- validation + save
    def save(self):
        try:
            data = load()
            actual = " ".join(self.f_truck.input.text.strip().split())

            date_txt = self.f_date.input.text.strip()
            if date_txt:
                try:
                    date = datetime.strptime(date_txt, "%d/%m/%Y").strftime(
                        "%d/%m/%Y")
                except ValueError:
                    raise ValueError(
                        "Date must look like 25/12/2026 (DD/MM/YYYY).")
            else:
                date = Urmc.now_date()

            bags_txt = self.f_bags.input.text.strip()
            if not bags_txt.isdigit() or int(bags_txt) <= 0:
                raise ValueError("Enter the number of bags (more than 0).")
            bags = int(bags_txt)

            workers, seen = [], set()
            for raw in self.f_workers.input.text.splitlines():
                name = normalize_name(raw)
                if name and name.casefold() not in seen:
                    seen.add(name.casefold())
                    workers.append(name)
            if not workers:
                raise ValueError("Enter at least one worker.")

            # Same truck may return on another date; only same truck + same
            # date is a duplicate (the record being edited is ignored).
            if actual:
                dup = next((
                    t for t in data.get("trucks", [])
                    if t.get("system_record_number") != self.edit_id
                    and " ".join(str(t.get("actual_truck_number", ""))
                                 .strip().split()).upper() == actual.upper()
                    and str(t.get("offloading_date", "")).strip() == date),
                    None)
                if dup:
                    info("Duplicate truck on same date",
                         f"Truck {actual} already has a record for {date} "
                         f"(record #{dup['system_record_number']}).\n\n"
                         "The same truck can be recorded again on a "
                         "different date.", "error")
                    return

            known = known_worker_names(data)
            corrections = []
            for name in workers:
                m = possible_worker_match(name, known)
                if m and m[1].casefold() != name.casefold():
                    corrections.append((name, m[1]))
            if corrections:
                self._ask_names(actual, date, bags, workers, corrections)
                return

            self._commit(actual, date, bags, workers)
        except Exception as e:
            info("Could not save", str(e), "error")

    def _ask_names(self, actual, date, bags, workers, corrections):
        lines = ["A worker name is very similar to a name already used. "
                 "This prevents one person being saved twice because of a "
                 "typing mistake.\n"]
        for typed, existing in corrections:
            lines.append(f"Typed:  {typed}\nExisting:  {existing}\n")

        def corrected():
            result = list(workers)
            for typed, existing in corrections:
                result = [existing if n.casefold() == typed.casefold() else n
                          for n in result]
            return list(dict.fromkeys(result))

        Modal("Possible name typo", "\n".join(lines), [
            ("USE EXISTING NAME", GREEN, WHITE,
             lambda: self._commit(actual, date, bags, corrected())),
            ("KEEP WHAT I TYPED", YELLOW, TEXT,
             lambda: self._commit(actual, date, bags, workers)),
            ("CANCEL", LIGHT, TEXT, None),
        ]).open()

    def _commit(self, actual, date, bags, workers):
        try:
            if self.edit_id is not None:
                self._apply_edit(actual, date, bags, workers)
            else:
                self._apply_new(actual, date, bags, workers)
        except Exception as e:
            info("Could not save", str(e), "error")

    def _apply_new(self, actual, date, bags, workers):
        data = load()
        record_no = Urmc.get_next_record_number(data)
        price = get_price(data)
        truck = {
            "system_record_number": record_no,
            "actual_truck_number": actual,
            "offloading_date": date,
            "bags": bags,
            "price_per_bag": price,
            "workers": workers,
            "finalized": False,
            "created_at": Urmc.now_timestamp(),
        }
        data["trucks"].append(truck)
        if not Urmc.save_data(data):
            raise RuntimeError("The record could not be saved.")

        revenue = truck_revenue(data, truck)
        shares = Urmc.worker_shares(revenue, len(workers))
        details = "\n".join(f"{n}: {Urmc.money(s)}"
                            for n, s in zip(workers, shares))
        info("Record saved",
             f"Record #{record_no}\nTruck: {actual or '(not supplied)'}\n"
             f"Bags: {bags:,}\nPrice per bag: {Urmc.money(price)}\n"
             f"Revenue: {Urmc.money(revenue)}\n\nWorker shares:\n{details}\n\n"
             "Made a mistake? Open Unpaid Trucks and tap EDIT.", "ok")
        self._clear()

    def _apply_edit(self, actual, date, bags, workers):
        data = load()
        t = find_truck(data, self.edit_id)
        if t is None:
            raise ValueError("Record not found.")
        if t.get("finalized"):
            raise ValueError("This truck is already PAID and cannot be edited.")
        backup = dict(t)
        t.update({
            "actual_truck_number": actual,
            "offloading_date": date,
            "bags": bags,
            "workers": workers,
            "edited_at": Urmc.now_timestamp(),
        })
        if not Urmc.save_data(data):
            t.clear()
            t.update(backup)
            raise RuntimeError("Changes could not be saved.")

        revenue = truck_revenue(data, t)
        info("Changes saved",
             f"Record #{self.edit_id} updated.\n\n"
             f"Truck: {actual or '(not supplied)'}\nDate: {date}\n"
             f"Bags: {bags:,}\nRevenue: {Urmc.money(revenue)}\n"
             f"Workers: {', '.join(workers)}", "ok",
             on_ok=lambda: setattr(self.manager, "current", self.return_to))


# ------------------------------------------------------ truck list pages
def card_with_actions(d, t, page_name, refresh):
    """Truck card whose EDIT / DELETE buttons work for unpaid trucks."""
    no = t["system_record_number"]

    def do_delete():
        try:
            delete_truck(no)
            refresh()
        except Exception as e:
            info("Could not delete", str(e), "error")

    def ask_delete():
        confirm("Delete this record?",
                f"Record #{no}\nTruck: "
                f"{t.get('actual_truck_number') or '(no truck number)'}\n"
                f"{t['bags']:,} bags • {t['offloading_date']}\n\n"
                "This removes the record permanently.",
                "YES, DELETE", do_delete)

    return truck_card(d, t,
                      on_edit=lambda: APP.edit_truck(no, page_name),
                      on_delete=ask_delete)


class UnpaidPage(Page):
    title = "Unpaid Trucks"

    def __init__(self, **kw):
        super().__init__(**kw)
        sv, self.grid = scroll_list()
        self.body.add_widget(sv)

    def on_pre_enter(self, *_):
        self.refresh()

    def refresh(self):
        self.grid.clear_widgets()
        try:
            d = load()
            ts = sorted(Urmc.unpaid_trucks(d),
                        key=lambda x: x["system_record_number"], reverse=True)
            total = sum(truck_revenue(d, t) for t in ts)
            self.grid.add_widget(info_card(
                "Awaiting payment",
                [("Trucks", str(len(ts))), ("Total", Urmc.money(total))],
                accent=RED))
            if not ts:
                self.grid.add_widget(note_card("No unpaid trucks."))
            for t in ts:
                self.grid.add_widget(
                    card_with_actions(d, t, "unpaid", self.refresh))
        except Exception as e:
            self.grid.add_widget(note_card(str(e), RED))


class HistoryPage(Page):
    title = "Payment History"
    LIMIT = 100

    def __init__(self, **kw):
        super().__init__(**kw)
        sv, self.grid = scroll_list()
        self.body.add_widget(sv)

    def on_pre_enter(self, *_):
        self.grid.clear_widgets()
        try:
            d = load()
            ts = sorted(Urmc.paid_trucks(d),
                        key=lambda x: x["system_record_number"], reverse=True)
            total = sum(truck_revenue(d, t) for t in ts)
            self.grid.add_widget(info_card(
                "Paid records",
                [("Trucks", str(len(ts))), ("Total paid", Urmc.money(total))],
                accent=GREEN))
            if not ts:
                self.grid.add_widget(note_card("No payments made yet."))
            for t in ts[:self.LIMIT]:
                self.grid.add_widget(truck_card(d, t))
            if len(ts) > self.LIMIT:
                self.grid.add_widget(note_card(
                    f"Showing the latest {self.LIMIT} of {len(ts)} paid "
                    "trucks. Use Search Truck to find older ones."))
        except Exception as e:
            self.grid.add_widget(note_card(str(e), RED))


class SearchPage(Page):
    title = "Search Truck"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.field = Field("Truck number or record #")
        self.field.input.bind(on_text_validate=lambda *_: self.search())
        self.body.add_widget(self.field)
        self.body.add_widget(Btn("SEARCH", "search", h=52,
                                 on_release=lambda *_: self.search()))
        sv, self.grid = scroll_list()
        self.body.add_widget(sv)

    def on_pre_enter(self, *_):
        if self.field.input.text.strip():
            self.search()

    def search(self):
        self.grid.clear_widgets()
        q = self.field.input.text.strip().upper().lstrip("#")
        if not q:
            self.grid.add_widget(note_card("Type a truck number to search."))
            return
        try:
            d = load()
            found = [t for t in d.get("trucks", [])
                     if q in str(t.get("actual_truck_number", "")).upper()
                     or q == str(t["system_record_number"])]
            if not found:
                self.grid.add_widget(note_card("No matching truck records."))
                return
            found.sort(key=lambda x: x["system_record_number"], reverse=True)
            for t in found:
                self.grid.add_widget(
                    card_with_actions(d, t, "search", self.search))
        except Exception as e:
            self.grid.add_widget(note_card(str(e), RED))


# ------------------------------------------------------------- finalize
class SelectCard(ButtonBehavior, Card):
    def __init__(self, d, t, on_change, **kw):
        super().__init__(orientation="horizontal", size_hint_y=None,
                         height=dp(100), padding=dp(12), spacing=dp(12), **kw)
        self.no = t["system_record_number"]
        self.on_change = on_change
        self.checked = False

        self.box = BoxLayout(size_hint=(None, None), size=(dp(32), dp(32)),
                             padding=dp(5), pos_hint={"center_y": .5})
        self._boxcol = paint(self.box, (0.84, 0.86, 0.89, 1), 9)
        self.tick = Image(texture=icon_tex("tick"), color=WHITE, opacity=0)
        self.box.add_widget(self.tick)
        self.add_widget(self.box)

        mid = BoxLayout(orientation="vertical")
        mid.add_widget(Lbl(t.get("actual_truck_number") or "(no truck number)",
                           fs=17, bold=True))
        mid.add_widget(Lbl(
            f"#{self.no} • {t['offloading_date']} • {t['bags']:,} bags",
            fs=13, color=MUTED))
        mid.add_widget(Lbl(", ".join(t.get("workers", [])), fs=13,
                           color=MUTED))
        self.add_widget(mid)

        self.add_widget(Lbl(Urmc.money(truck_revenue(d, t)), fs=16,
                            bold=True, color=RED, halign="right",
                            size_hint_x=None, width=dp(108)))
        self.bind(on_release=lambda *_: self.set_checked(not self.checked))

    def set_checked(self, value, notify=True):
        self.checked = value
        self._boxcol.rgba = GREEN if value else (0.84, 0.86, 0.89, 1)
        self.tick.opacity = 1 if value else 0
        self.set_border(GREEN if value else LINE)
        if notify:
            self.on_change()


class FinalizePage(Page):
    title = "Finalize Payments"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rows = []
        self.data = None

        top = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        top.add_widget(Btn("SELECT ALL", "check", bg=YELLOW, fg=TEXT, h=46,
                           fs=14, on_release=lambda *_: self.select_all(True)))
        top.add_widget(Btn("CLEAR", bg=LIGHT, fg=TEXT, h=46, fs=14,
                           on_release=lambda *_: self.select_all(False)))
        self.body.add_widget(top)
        self.body.add_widget(Lbl("Tap the trucks you want to pay.", fs=13,
                                 color=MUTED, h=22))

        sv, self.grid = scroll_list()
        self.body.add_widget(sv)

        bar = Card(bg=HEADER, border=HEADER, orientation="horizontal",
                   size_hint_y=None, height=dp(76), padding=[dp(14), dp(8)],
                   spacing=dp(10), radius=16)
        txt = BoxLayout(orientation="vertical")
        self.sel_lbl = Lbl("0 selected", fs=13, color=(0.80, 0.82, 0.86, 1))
        self.sel_total = Lbl("Shs 0", fs=21, bold=True, color=YELLOW)
        txt.add_widget(self.sel_lbl)
        txt.add_widget(self.sel_total)
        bar.add_widget(txt)
        self.pay_btn = Btn("REVIEW & PAY", bg=GREEN, h=54, fs=15,
                           size_hint_x=None, width=dp(160),
                           pos_hint={"center_y": .5},
                           on_release=lambda *_: self.review())
        bar.add_widget(self.pay_btn)
        self.body.add_widget(bar)

    def on_pre_enter(self, *_):
        self.reload()

    def reload(self):
        self.grid.clear_widgets()
        self.rows = []
        try:
            self.data = load()
            ts = sorted(Urmc.unpaid_trucks(self.data),
                        key=lambda x: x["system_record_number"])
            if not ts:
                self.grid.add_widget(note_card("No unpaid trucks to finalize."))
            for t in ts:
                row = SelectCard(self.data, t, self.update_total)
                self.rows.append(row)
                self.grid.add_widget(row)
        except Exception as e:
            self.grid.add_widget(note_card(str(e), RED))
        self.update_total()

    def selected(self):
        return [r.no for r in self.rows if r.checked]

    def select_all(self, value):
        for r in self.rows:
            r.set_checked(value, notify=False)
        self.update_total()

    def update_total(self):
        ids = set(self.selected())
        total = sum(truck_revenue(self.data, t)
                    for t in self.data.get("trucks", [])
                    if t["system_record_number"] in ids) if self.data else 0
        self.sel_lbl.text = f"{len(ids)} truck(s) selected"
        self.sel_total.text = Urmc.money(total)
        self.pay_btn.set_bg(GREEN if ids else (0.45, 0.47, 0.50, 1))

    def review(self):
        ids = self.selected()
        if not ids:
            info("Nothing selected",
                 "Tap one or more trucks in the list first.", "error")
            return
        d = load()
        chosen = sorted((t for t in Urmc.unpaid_trucks(d)
                         if t["system_record_number"] in set(ids)),
                        key=lambda x: x["system_record_number"])
        total = sum(truck_revenue(d, t) for t in chosen)
        payouts = {}
        lines = [f"Trucks: {len(chosen)}", f"TOTAL: {Urmc.money(total)}", ""]
        for t in chosen:
            lines.append(
                f"#{t['system_record_number']}  "
                f"{t.get('actual_truck_number') or '(no number)'}  •  "
                f"{t['bags']:,} bags  •  {Urmc.money(truck_revenue(d, t))}")
            shares = Urmc.worker_shares(truck_revenue(d, t),
                                        len(t.get("workers", [])))
            for w, s in zip(t.get("workers", []), shares):
                payouts[w] = payouts.get(w, 0) + s
        lines += ["", "WORKER TOTALS:"]
        lines += [f"{w}: {Urmc.money(v)}"
                  for w, v in sorted(payouts.items(),
                                     key=lambda x: x[0].casefold())]
        lines += ["", "Check everything carefully. Paid trucks can no "
                      "longer be edited."]
        Modal("Confirm payment", "\n".join(lines), [
            ("CANCEL", LIGHT, TEXT, None),
            ("CONFIRM & PAY", GREEN, WHITE, lambda: self.pay(ids)),
        ], accent=GREEN).open()

    def pay(self, ids):
        try:
            data = load()
            wanted = set(ids)
            chosen = sorted((t for t in Urmc.unpaid_trucks(data)
                             if t["system_record_number"] in wanted),
                            key=lambda x: x["system_record_number"])
            if len(chosen) != len(wanted):
                raise RuntimeError(
                    "The list changed since the review. Nothing was paid. "
                    "Please select again.")
            total = sum(truck_revenue(data, t) for t in chosen)
            payment_id = Urmc.finalize_payment_records(data, chosen)
            if not payment_id:
                raise RuntimeError("Payment could not be finalized.")
            info("PAYMENT SUCCESSFUL",
                 f"Batch: {payment_id}\n\nTrucks paid: {len(chosen)}\n"
                 f"Total: {Urmc.money(total)}\n\nA receipt was saved under "
                 "Statements.", "ok", on_ok=self.reload)
        except Exception as e:
            info("PAYMENT NOT COMPLETED",
                 f"Nothing was marked as paid.\n\n{e}", "error")


# -------------------------------------------------------------- reports
class ReportPage(Page):
    def __init__(self, **kw):
        super().__init__(**kw)
        sv, self.grid = scroll_list()
        self.body.add_widget(sv)

    def make(self, d):
        return []

    def on_pre_enter(self, *_):
        self.grid.clear_widgets()
        try:
            for w in self.make(load()):
                self.grid.add_widget(w)
        except Exception as e:
            self.grid.add_widget(note_card(str(e), RED))


class SummaryPage(ReportPage):
    title = "System Summary"

    def make(self, d):
        all_t = d.get("trucks", [])
        paid = Urmc.paid_trucks(d)
        unpaid = Urmc.unpaid_trucks(d)
        value = lambda ts: Urmc.money(sum(truck_revenue(d, t) for t in ts))
        return [
            info_card("Trucks", [
                ("Total records", str(len(all_t))),
                ("Paid", str(len(paid))),
                ("Unpaid", str(len(unpaid))),
                ("Total bags", f"{sum(t.get('bags', 0) for t in all_t):,}"),
            ]),
            info_card("Money", [
                ("Recorded value", value(all_t)),
                ("Paid", value(paid)),
                ("Unpaid", value(unpaid)),
            ], accent=GREEN),
            info_card("Settings", [
                ("Price per bag (new records)", Urmc.money(get_price(d))),
            ], accent=HEADER),
        ]


class WorkerPage(ReportPage):
    title = "Worker Earnings"

    def make(self, d):
        names = []
        for t in d.get("trucks", []):
            names.extend(t.get("workers", []))
        mapping = _canonicalize_worker_names(names)
        totals = {}
        for t in d.get("trucks", []):
            shares = Urmc.worker_shares(truck_revenue(d, t),
                                        len(t.get("workers", [])))
            for name, share in zip(t.get("workers", []), shares):
                clean = normalize_name(name)
                disp = mapping.get(clean, clean)
                totals.setdefault(disp, [0, 0])
                totals[disp][0 if t.get("finalized") else 1] += share
        if not totals:
            return [note_card("No worker records yet.")]
        return [
            info_card(n, [("Paid", Urmc.money(v[0])),
                          ("Unpaid", Urmc.money(v[1]))])
            for n, v in sorted(totals.items(), key=lambda x: x[0].casefold())
        ]


class StatementsPage(Page):
    title = "Payment Statements"

    def __init__(self, **kw):
        super().__init__(**kw)
        sv, self.grid = scroll_list()
        self.body.add_widget(sv)

    def on_pre_enter(self, *_):
        self.grid.clear_widgets()
        try:
            folder = Urmc.STATEMENT_FOLDER
            files = []
            if os.path.isdir(folder):
                files = sorted((f for f in os.listdir(folder)
                                if f.lower().endswith(".txt")), reverse=True)
            if not files:
                self.grid.add_widget(note_card("No payment statements yet."))
            for f in files:
                self.grid.add_widget(self._row(f))
        except Exception as e:
            self.grid.add_widget(note_card(str(e), RED))

    def _row(self, fname):
        path = os.path.join(Urmc.STATEMENT_FOLDER, fname)
        label = fname.replace("_Payment_Statement.txt", "")

        class Row(ButtonBehavior, Card):
            pass

        row = Row(orientation="horizontal", size_hint_y=None, height=dp(64),
                  padding=[dp(14), dp(8)], spacing=dp(10))
        row.add_widget(Image(texture=icon_tex("doc"), color=RED,
                             size_hint=(None, None), size=(dp(28), dp(28)),
                             pos_hint={"center_y": .5}))
        row.add_widget(Lbl(label, fs=15, bold=True))
        row.bind(on_release=lambda *_: self.show(path, label))
        return row

    def show(self, path, label):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read()
            lines = []
            for ln in raw.splitlines():
                s = ln.strip()
                if s and set(s) <= set("=-"):
                    lines.append("-" * 32)
                else:
                    lines.append(ln.rstrip())
            Modal(label, "\n".join(lines), [("CLOSE", RED, WHITE, None)],
                  accent=TEXT).open()
        except Exception as e:
            info("Cannot open statement", str(e), "error")


# ------------------------------------------------------------- settings
class PricePage(Page):
    title = "Offloading Price"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.body.add_widget(Txt(
            "The amount charged per bag for NEW trucks. Trucks already "
            "recorded keep the price they were saved with.", fs=14,
            color=MUTED))
        self.body.add_widget(section_label("PRICE PER BAG (SHS)"))
        self.field = Field("e.g. 150", filt="float", input_type="number")
        self.body.add_widget(self.field)
        self.body.add_widget(Btn("SAVE PRICE", "tick", h=56,
                                 on_release=lambda *_: self.save()))
        self.body.add_widget(Widget())

    def on_pre_enter(self, *_):
        try:
            self.field.input.text = str(get_price(load()))
        except Exception as e:
            info("Error", str(e), "error")

    def save(self):
        try:
            value = _number(self.field.input.text.strip())
            if self.field.input.text.strip() == "" or value <= 0:
                raise ValueError("Price per bag must be more than zero.")
            d = load()
            old = d.get("price_per_bag")
            d["price_per_bag"] = value
            if not Urmc.save_data(d):
                d["price_per_bag"] = old
                raise RuntimeError("Price was not changed (save failed).")
            Urmc.PRICE_PER_BAG = value
            info("Price updated",
                 f"New price: {Urmc.money(value)} per bag.\n\n"
                 "Applies to NEW trucks only.", "ok")
        except Exception as e:
            info("Price not updated", str(e), "error")


class PasswordPage(Page):
    title = "Change Password"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.cur = Field("Current password", password=True)
        self.new = Field("New password (8+ characters)", password=True)
        self.conf = Field("Confirm new password", password=True)
        for lbl, f in (("CURRENT PASSWORD", self.cur),
                       ("NEW PASSWORD", self.new),
                       ("CONFIRM NEW PASSWORD", self.conf)):
            self.body.add_widget(section_label(lbl))
            self.body.add_widget(f)
        self.body.add_widget(Btn("CHANGE PASSWORD", "lock", h=56,
                                 on_release=lambda *_: self.change()))
        self.body.add_widget(Widget())

    def on_pre_enter(self, *_):
        for f in (self.cur, self.new, self.conf):
            f.input.text = ""

    def change(self):
        try:
            d = Urmc.load_data()
            if not Urmc.verify_password(self.cur.input.text,
                                        d["password_salt"],
                                        d["password_hash"]):
                raise ValueError("Current password is incorrect.")
            if len(self.new.input.text) < 8:
                raise ValueError("New password needs at least 8 characters.")
            if self.new.input.text != self.conf.input.text:
                raise ValueError("The new passwords do not match.")
            salt, h = Urmc.make_password_hash(self.new.input.text)
            old = (d["password_salt"], d["password_hash"])
            d["password_salt"], d["password_hash"] = salt, h
            if not Urmc.save_data(d):
                d["password_salt"], d["password_hash"] = old
                raise RuntimeError("Password not changed (save failed).")
            info("Success", "Password changed.", "ok")
            self.on_pre_enter()
        except Exception as e:
            info("Password not changed", str(e), "error")


# ------------------------------------------------------------------ app
def read_android_insets():
    """(left, top, right, bottom, drawn_behind_bars) in pixels, or None."""
    if platform != "android":
        return None
    try:
        from jnius import autoclass
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        decor = activity.getWindow().getDecorView()
        wi = decor.getRootWindowInsets()
        if wi is None:
            return None
        sdk = autoclass("android.os.Build$VERSION").SDK_INT
        if sdk >= 30:
            T = autoclass("android.view.WindowInsets$Type")
            ins = wi.getInsets(T.systemBars() | T.displayCutout())
            vals = (ins.left, ins.top, ins.right, ins.bottom)
        else:
            vals = (wi.getSystemWindowInsetLeft(),
                    wi.getSystemWindowInsetTop(),
                    wi.getSystemWindowInsetRight(),
                    wi.getSystemWindowInsetBottom())
        dm = autoclass("android.util.DisplayMetrics")()
        activity.getWindowManager().getDefaultDisplay().getRealMetrics(dm)
        behind = Window.height >= dm.heightPixels - 4
        return vals + (behind,)
    except Exception:
        return None


class AppMain(App):
    inset_left = NumericProperty(0)
    inset_top = NumericProperty(0)
    inset_right = NumericProperty(0)
    inset_bottom = NumericProperty(0)

    def __init__(self, **kw):
        global APP
        super().__init__(**kw)
        APP = self
        self.unlocked = False
        self.db_error = ""
        self.inset_top = dp(30)
        self.inset_bottom = dp(24)

    # ---- start-up
    PAGES = [
        ("dashboard", "Dashboard"), ("record", "Record"),
        ("unpaid", "UnpaidPage"), ("finalize", "FinalizePage"),
        ("history", "HistoryPage"), ("search", "SearchPage"),
        ("worker", "WorkerPage"), ("summary", "SummaryPage"),
        ("statements", "StatementsPage"), ("price", "PricePage"),
        ("password", "PasswordPage"),
    ]

    def build(self):
        self.title = "URMC KAJJANSI"
        Window.clearcolor = WHITE
        self.update_insets()
        for delay in (0.3, 1.0, 2.5):
            Clock.schedule_once(self.update_insets, delay)
        Window.bind(size=lambda *_: Clock.schedule_once(
            self.update_insets, 0.2))
        Window.bind(on_keyboard=self.on_key)

        # Only the launch screen is created now so the first frame appears
        # immediately. Everything else is built behind it (see build_next).
        sm = ScreenManager(transition=SlideTransition(duration=0.22))
        sm.add_widget(LaunchScreen(name="splash"))
        self.sm = sm
        self.pending = list(self.PAGES)
        self.init_done = False
        self.ready = False
        return sm

    def build_next(self):
        """One piece of start-up work per call (called once per frame)."""
        if not self.init_done:
            self.init_done = True
            try:
                Urmc.set_storage_dir(self.user_data_dir)
                load()                      # creates the database on 1st run
                Urmc.auto_backup("start")   # automatic backup every launch
            except Exception as e:
                self.db_error = str(e)
            for name in assets_data.ICONS:  # decode all icons up front
                icon_tex(name)
            return
        if self.pending:
            name, cls = self.pending.pop(0)
            self.sm.add_widget(globals()[cls](name=name))
        if not self.pending:
            self.ready = True

    # ---- keep content clear of status bar / gesture bar / notch
    def update_insets(self, *_):
        r = read_android_insets()
        if r is None:
            left = right = 0
            top, bottom = dp(30), dp(24)
        else:
            left, top, right, bottom, behind = r
            if behind:
                top = max(top, dp(24))
                bottom = max(bottom, dp(16)) + dp(4)
            else:   # system already keeps the window clear of the bars
                left = right = 0
                top, bottom = dp(2), dp(8)
        self.inset_left, self.inset_right = left, right
        self.inset_top, self.inset_bottom = top, bottom

    # ---- navigation
    def go(self, name):
        if name == "record_new":
            rec = self.sm.get_screen("record")
            rec.edit_id = None
            name = "record"
        if name in PROTECTED and not self.unlocked:
            self.ask_password(lambda: self._open(name))
            return
        self.sm.current = name

    def _open(self, name):
        self.sm.current = name

    def edit_truck(self, record_no, return_to):
        rec = self.sm.get_screen("record")
        rec.edit_id = record_no
        rec.return_to = return_to
        self.sm.current = "record"

    def lock(self):
        was_open = self.unlocked
        self.unlocked = False
        info("Locked" if was_open else "Already locked",
             "Finalize Payments, Offloading Price and Change Password will "
             "ask for the password.\n\nThis button does not affect backups: "
             "backups are always automatic.", "ok")

    def ask_password(self, then):
        fld = Field("Administrator password", password=True)

        def check():
            try:
                d = Urmc.load_data()
                if Urmc.verify_password(fld.input.text, d["password_salt"],
                                        d["password_hash"]):
                    self.unlocked = True
                    then()
                else:
                    info("Access denied", "Incorrect password.", "error")
            except Exception as e:
                info("Error", str(e), "error")

        Modal("Administrator password",
              "Enter the password to open this section.",
              [("CANCEL", LIGHT, TEXT, None), ("UNLOCK", RED, WHITE, check)],
              content=fld).open()

    def on_key(self, window, key, *args):
        if key != 27:               # Android back button / Esc
            return False
        if OPEN_MODALS:
            return True
        cur = self.sm.current
        if cur in ("splash", "welcome"):
            return True
        if cur == "dashboard":
            return False            # let the system close the app
        go_back_slide(self.sm, self.sm.current_screen.back_target())
        return True

    def on_pause(self):
        return True

    def on_resume(self):
        self.unlocked = False       # re-lock sensitive sections


if __name__ == "__main__":
    AppMain().run()
