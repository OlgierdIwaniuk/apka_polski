"""Run with Python 3. Listening uses gTTS and pygame (internet required)."""
import json
import random
import re
import threading
import tkinter as tk
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from tkinter import messagebox, ttk

LEVELS = ("A1", "A2", "B1", "B2")
MODES = ("Vocabulary", "Cases", "Verb Tenses", "Mixed Grammar", "Listening")
PROGRESS = Path.home() / "PolishTrainerProgress.json"

# Each row contains the prompt, accepted answers and feedback in English.
CONTENT = {
    "A1": (
        """a book|książka|This is a feminine noun.
a dog|pies|The plural is psy.
today|dzisiaj / dziś|Both forms mean today.
good morning / good day|dzień dobry|A polite greeting.""",
        """Mam na imię Anna.|Mam na imię Anna.|My name is Anna.
To jest mój dom.|To jest mój dom.|This is my house.
Lubię kawę.|Lubię kawę.|I like coffee.""",
    ),
    "A2": (
        """a train station|dworzec kolejowy|Dworzec can also refer to a bus station.
a receipt (from a shop)|paragon|You can ask: Czy mogę prosić o paragon?
to make an appointment (e.g. with a doctor)|umówić się na wizytę / umawiać się na wizytę|Umówić się is perfective. Umawiać się is imperfective.""",
        """Gdzie mogę kupić bilet?|Gdzie mogę kupić bilet?|Where can I buy a ticket?
Wczoraj wróciłam późno do domu.|Wczoraj wróciłam późno do domu.|I came home late yesterday.
Jutro spotkam się z koleżanką.|Jutro spotkam się z koleżanką.|Tomorrow I will meet a friend.""",
    ),
    "B1": (
        """to take part in something|brać udział w czymś / wziąć udział w czymś|W is followed by the locative in this expression.
to make a decision|podjąć decyzję / podejmować decyzję|Podjąć is perfective and podejmować is imperfective.
an advantage (a positive feature)|zaleta / atut|Both can describe a positive feature.""",
        """Mimo deszczu poszliśmy na spacer.|Mimo deszczu poszliśmy na spacer.|We went for a walk despite the rain.
Gdybym miał czas, pomógłbym ci.|Gdybym miał czas, pomógłbym ci.|If I had time, I would help you.
Nie wiedziałam, że zmienili termin spotkania.|Nie wiedziałam, że zmienili termin spotkania.|I didn't know they had changed the meeting date.""",
    ),
    "B2": (
        """to draw conclusions|wyciągać wnioski / wyciągnąć wnioski|Both aspect forms are accepted.
to take something into account|brać coś pod uwagę / wziąć coś pod uwagę / uwzględniać coś / uwzględnić coś|Both expressions convey taking something into account.
justification / rationale|uzasadnienie|Uzasadnienie explains the grounds for a decision.""",
        """Wbrew oczekiwaniom wyniki okazały się obiecujące.|Wbrew oczekiwaniom wyniki okazały się obiecujące.|Contrary to expectations, the results turned out to be promising.
Biorąc pod uwagę koszty, zdecydowaliśmy się zmienić plan.|Biorąc pod uwagę koszty, zdecydowaliśmy się zmienić plan.|Taking costs into account, we decided to change the plan.
Gdybyśmy wcześniej przeanalizowali dane, uniknęlibyśmy tego błędu.|Gdybyśmy wcześniej przeanalizowali dane, uniknęlibyśmy tego błędu.|If we had analysed the data earlier, we would have avoided this mistake.""",
    ),
}


@dataclass(frozen=True)
class Exercise:
    key: str
    mode: str
    prompt: str
    answers: tuple[str, ...]
    note: str


DATA_DIR = Path(__file__).resolve().parent
GRAMMAR_FILES = {
    "Cases": "grammar_cases.json",
    "Verb Tenses": "grammar_verb_tenses.json",
    "Mixed Grammar": "grammar_mixed.json",
}


@lru_cache(maxsize=None)
def grammar_data(filename):
    return json.loads((DATA_DIR / filename).read_text(encoding="utf-8-sig"))


def exercises(level):
    for mode, filename in GRAMMAR_FILES.items():
        for row in grammar_data(filename)[level]:
            prompt = row["prompt"]
            yield Exercise(f"{level}/{mode}/{prompt}", mode, prompt,
                           tuple(row["answers"]), row["explanation"])
    for mode, rows in zip(("Vocabulary", "Listening"), CONTENT[level]):
        for row in rows.splitlines():
            prompt, answers, note = row.split("|")
            yield Exercise(f"{level}/{mode}/{prompt}", mode, prompt,
                           tuple(answers.split(" / ")), note)


VOCABULARY_PATH = DATA_DIR / "vocabulary.json"


def load_exercises(path=VOCABULARY_PATH):
    catalog = {level: list(exercises(level)) for level in LEVELS}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Expected the Polish Trainer vocabulary format (version 1).")
    groups = data.get("levels")
    if not isinstance(groups, dict):
        raise ValueError("Missing vocabulary levels.")
    for level, items in catalog.items():
        rows = groups.get(level)
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"Missing vocabulary for {level}.")
        notes = {item.key: item.note for item in items if item.mode == "Vocabulary"}
        vocabulary = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"Invalid vocabulary entry in {level}.")
            prompt = row.get("english")
            answers = row.get("polish")
            if (
                not isinstance(prompt, str) or not prompt.strip()
                or not isinstance(answers, list) or not answers
                or any(not isinstance(answer, str) or not normalize(answer) for answer in answers)
            ):
                raise ValueError(f"Invalid vocabulary entry in {level}.")
            prompt = prompt.strip()
            key = f"{level}/Vocabulary/{prompt}"
            if key in vocabulary:
                raise ValueError(f"Duplicate vocabulary prompt in {level}: {prompt}")
            vocabulary[key] = Exercise(key, "Vocabulary", prompt, tuple(answers), notes.get(key, ""))
        catalog[level] = [*vocabulary.values(), *(item for item in items if item.mode != "Vocabulary")]
    return catalog


def normalize(value):
    value = unicodedata.normalize("NFC", value).casefold()
    return " ".join(re.sub(r"[.,!?;:…]+", " ", value).split())


def play_polish(sentence):
    from gtts import gTTS
    from pygame import mixer

    sound = BytesIO()
    gTTS(sentence, lang="pl", timeout=10).write_to_fp(sound)
    sound.seek(0)
    if not mixer.get_init():
        mixer.init()
    mixer.music.load(sound, "mp3")
    mixer.music.play()


class Trainer:
    def __init__(self, root):
        self.root = root
        self.level = tk.StringVar(value="A1")
        self.audio_running = False
        try:
            for filename in GRAMMAR_FILES.values():
                grammar_data(filename)
        except (OSError, ValueError) as error:
            messagebox.showerror(
                "Grammar files",
                f"Could not load the grammar files: {error}\n\n"
                "Extract all files into the same folder and run Polish Trainer again.",
                parent=root,
            )
            root.destroy()
            return
        try:
            self.catalog = load_exercises()
        except (OSError, ValueError) as error:
            self.catalog = {level: list(exercises(level)) for level in LEVELS}
            messagebox.showwarning(
                "Vocabulary",
                f"Could not load vocabulary.json: {error}\n\n"
                "Place the Polish vocabulary.json next to polish_trainer.py. "
                "The starter vocabulary will be used for now.",
                parent=root,
            )
        try:
            self.progress = json.loads(PROGRESS.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.progress = {}
        except (OSError, ValueError) as error:
            messagebox.showerror("Progress", str(error))
            raise
        self.panel = ttk.Frame(root, padding=24)
        self.panel.pack(fill="both", expand=True)
        self.menu()

    def clear(self):
        self.root.unbind("<Return>")
        for child in self.panel.winfo_children():
            child.destroy()

    def menu(self):
        self.clear()
        ttk.Label(self.panel, text="Polish Trainer", font=("TkDefaultFont", 22)).pack()
        ttk.Label(self.panel, text="Choose your level").pack(pady=(12, 3))
        ttk.Combobox(self.panel, textvariable=self.level, values=LEVELS,
                     state="readonly", width=8).pack(pady=(0, 12))
        ttk.Button(self.panel, text="Learn Vocabulary", width=25,
                   command=self.start_learning).pack(pady=3)
        ttk.Button(self.panel, text="Grammar Tutorial", width=25,
                   command=self.show_grammar_tutorial).pack(pady=3)
        for mode in (*MODES, "Review My Mistakes"):
            ttk.Button(self.panel, text=mode, width=25,
                       command=lambda mode=mode: self.start(mode)).pack(pady=3)
        ttk.Button(self.panel, text="Statistics", command=self.statistics).pack(pady=8)

    def show_grammar_tutorial(self):
        level = self.level.get()
        try:
            tutorial = grammar_data("grammar_tutorial.json")
            lessons = [*tutorial[level], *tutorial.get("reference", [])]
        except (OSError, ValueError, KeyError) as error:
            messagebox.showerror("Grammar Tutorial", f"Could not load the tutorial: {error}")
            return
        self.clear()
        ttk.Button(self.panel, text="Back to Menu", command=self.menu).pack(anchor="w")
        ttk.Label(self.panel, text=f"{level} · Grammar Tutorial").pack(pady=(4, 8))
        selector = ttk.Combobox(self.panel, state="readonly", width=44,
                                values=[lesson["title"] for lesson in lessons])
        selector.pack(pady=(0, 8))
        body = ttk.Frame(self.panel)
        body.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        page = tk.Text(body, wrap="word", padx=12, pady=12, yscrollcommand=scroll.set)
        page.pack(side="left", fill="both", expand=True)
        scroll.configure(command=page.yview)
        page.tag_configure("focus", underline=True)

        def display_lesson(_event=None):
            lesson = lessons[selector.current()]
            page.configure(state="normal")
            page.delete("1.0", "end")
            page.insert("end", lesson["rule"] + "\n\n")
            for table in lesson.get("tables", []):
                page.insert("end", table["title"] + "\n", ("focus",))
                for row in table["rows"]:
                    page.insert("end", row[0] + "\n")
                    for label, value in zip(table["headers"][1:], row[1:]):
                        page.insert("end", f"    {label}: {value}\n")
                page.insert("end", "\n")
            for example in lesson["examples"]:
                for index, part in enumerate(example["polish"].split("**")):
                    page.insert("end", part, ("focus",) if index % 2 else ())
                page.insert("end", "\n" + example["english"] + "\n\n")
            page.yview_moveto(0)
            page.configure(state="disabled")

        selector.bind("<<ComboboxSelected>>", display_lesson)
        selector.current(0)
        display_lesson()

    def start_learning(self):
        level = self.level.get()
        self.learning_items = [item for item in self.catalog[level] if item.mode == "Vocabulary"]
        random.shuffle(self.learning_items)
        self.learning_offset = 0
        self.show_learning_set()

    def next_learning_set(self):
        self.learning_offset += 10
        if self.learning_offset >= len(self.learning_items):
            self.start_learning()
        else:
            self.show_learning_set()

    def show_learning_set(self):
        self.clear()
        self.audio_error = tk.StringVar()
        ttk.Button(self.panel, text="Back to Menu", command=self.menu).pack(anchor="w")
        ttk.Label(self.panel, text=f"{self.level.get()} · Learn Vocabulary").pack(pady=(4, 6))
        table = ttk.Frame(self.panel)
        table.pack(fill="x")
        table.columnconfigure(0, weight=1)
        table.columnconfigure(1, weight=2)
        ttk.Label(table, text="Polish").grid(row=0, column=0, sticky="w")
        ttk.Label(table, text="English").grid(row=0, column=1, sticky="w")
        items = self.learning_items[self.learning_offset:self.learning_offset + 10]
        for row, item in enumerate(items, start=1):
            word = item.answers[0]
            ttk.Label(table, text=word, wraplength=205).grid(
                row=row, column=0, sticky="w", padx=(0, 8))
            ttk.Label(table, text=item.prompt, wraplength=300).grid(
                row=row, column=1, sticky="w", padx=(0, 8))
            ttk.Button(table, text="Listen", command=lambda word=word: self.listen(word)).grid(
                row=row, column=2, sticky="e")
        ttk.Label(self.panel, textvariable=self.audio_error, wraplength=570).pack()
        ttk.Button(self.panel, text="Next Set", command=self.next_learning_set).pack(pady=6)

    def statistics(self):
        rows = ["Level    Correct / Attempts    To review"]
        for level in LEVELS:
            records = [self.progress.get(item.key, [0, 0, False]) for item in self.catalog[level]]
            correct = sum(row[0] for row in records)
            total = sum(row[1] for row in records)
            pending = sum(row[2] for row in records)
            rows.append(f"{level}         {correct} / {total}                      {pending}")
        messagebox.showinfo("Statistics", "\n".join(rows))

    def start(self, mode):
        self.mode = mode
        pool = self.catalog[self.level.get()]
        if mode == "Review My Mistakes":
            self.queue = [item for item in pool if self.progress.get(item.key, [0, 0, False])[2]]
        else:
            self.queue = [item for item in pool if item.mode == mode]
        if not self.queue:
            messagebox.showinfo(mode, "There are no mistakes to review at this level.")
            return
        random.shuffle(self.queue)
        if mode == "Vocabulary":
            self.queue = self.queue[:40]
        self.position = 0
        self.score = 0
        self.question()

    def question(self):
        self.clear()
        self.item = self.queue[self.position]
        self.checked = False
        self.overridable = False
        self.audio_error = tk.StringVar()
        ttk.Button(self.panel, text="Back to Menu", command=self.menu).pack(anchor="w")
        ttk.Label(self.panel, text=f"{self.level.get()} · {self.mode} · "
                  f"{self.position + 1}/{len(self.queue)}").pack(pady=14)
        instructions = {
            "Listening": "Listen and type the sentence in Polish.",
            "Vocabulary": "Translate into Polish.",
        }
        ttk.Label(self.panel, text=instructions.get(self.item.mode, "Complete the sentence.")).pack()
        if self.item.mode == "Listening":
            ttk.Button(self.panel, text="Play Polish Audio", command=lambda: self.listen(self.item.prompt)).pack(pady=8)
            ttk.Label(self.panel, textvariable=self.audio_error, wraplength=570).pack()
        else:
            ttk.Label(self.panel, text=self.item.prompt, wraplength=570,
                      font=("TkDefaultFont", 13)).pack(pady=12)
        self.entry = ttk.Entry(self.panel, width=55)
        self.entry.pack(pady=8)
        self.entry.focus_set()
        accents = ttk.Frame(self.panel)
        accents.pack()
        for letter in "ąćęłńóśźż":
            ttk.Button(accents, text=letter, width=3,
                       command=lambda letter=letter: self.insert(letter)).pack(side="left")
        self.feedback = tk.StringVar()
        ttk.Label(self.panel, textvariable=self.feedback, wraplength=570).pack(pady=12)
        actions = ttk.Frame(self.panel)
        actions.pack()
        self.check_button = ttk.Button(actions, text="Check", command=self.check)
        self.check_button.pack(side="left", padx=4)
        self.override_button = ttk.Button(actions, text="My Answer Is Correct",
                                          command=self.override, state="disabled")
        self.override_button.pack(side="left", padx=4)
        self.next_button = ttk.Button(actions, text="Next", command=self.advance, state="disabled")
        self.next_button.pack(side="left", padx=4)
        self.root.bind("<Return>", self.enter)

    def insert(self, letter):
        if not self.checked:
            self.entry.insert(tk.INSERT, letter)
            self.entry.focus_set()

    def listen(self, sentence):
        if self.audio_running:
            return
        self.audio_running = True
        status = self.audio_error
        status.set("Loading audio…")

        def finish(error):
            self.audio_running = False
            status.set(error)

        def worker():
            try:
                play_polish(sentence)
                error = ""
            except ImportError:
                error = "Install audio support with: python -m pip install gTTS pygame"
            except Exception:
                error = "Audio could not play. Check your internet connection and audio output."
            self.root.after(0, finish, error)

        threading.Thread(target=worker, daemon=True).start()

    def accepted_answers(self):
        record = self.progress.get(self.item.key, [])
        saved = record[3] if self.item.mode == "Vocabulary" and len(record) > 3 else []
        return (*self.item.answers, *saved)

    def record(self, correct, new_attempt, accepted_variant=None):
        record = self.progress.get(self.item.key, [0, 0, False])
        old_correct, old_total = record[:2]
        updated_record = [old_correct + int(correct), old_total + int(new_attempt), not correct]
        if accepted_variant is not None:
            saved = record[3] if len(record) > 3 else []
            updated_record.append([*saved, accepted_variant])
        else:
            updated_record.extend(record[3:])
        updated = {**self.progress, self.item.key: updated_record}
        temporary = PROGRESS.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(updated, ensure_ascii=False), encoding="utf-8")
            temporary.replace(PROGRESS)
        except OSError as error:
            messagebox.showerror("Could not save progress", str(error))
            return False
        self.progress = updated
        return True

    def check(self):
        answer = normalize(self.entry.get())
        if self.checked or not answer:
            return
        accepted = self.accepted_answers()
        correct = answer in {normalize(value) for value in accepted}
        if not self.record(correct, new_attempt=True):
            return
        self.checked = True
        self.score += int(correct)
        self.overridable = not correct
        self.entry.configure(state="readonly")
        self.check_button.configure(state="disabled")
        self.next_button.configure(state="normal")
        if self.overridable:
            self.override_button.configure(state="normal")
        heading = "Correct!" if correct else "Accepted answers: " + " / ".join(accepted)
        self.feedback.set(f"{heading}\n{self.item.note}")

    def override(self):
        if not self.overridable:
            return
        variant = self.entry.get().strip() if self.item.mode == "Vocabulary" else None
        if self.record(True, new_attempt=False, accepted_variant=variant):
            self.score += 1
            self.overridable = False
            self.override_button.configure(state="disabled")
            heading = (
                "Marked correct and saved as an accepted answer for this question."
                if variant is not None else "Marked correct for this attempt."
            )
            self.feedback.set(f"{heading}\n{self.item.note}")

    def enter(self, _event):
        if self.checked:
            self.advance()
        else:
            self.check()
        return "break"

    def advance(self):
        self.position += 1
        if self.position == len(self.queue):
            messagebox.showinfo("Session complete", f"Score: {self.score}/{len(self.queue)}")
            self.menu()
        else:
            self.question()


if __name__ == "__main__":
    app = tk.Tk()
    app.title("Polish Trainer · A1–B2")
    app.minsize(640, 480)
    Trainer(app)
    app.mainloop()
