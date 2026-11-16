"""Assignment dialog at brief export: sets only what the AI cannot clarify from the scene itself – assignment in
one sentence, hints for this export, "discuss only", look pre-stage, focus on the selection. Scope of the round,
kinds of work, bindingness, tools and way of working are clarified by the AI in the first round from the notes
(brief.CLARIFY). Stored in scene.brief_task (brief.task_clean)."""
import html
import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QScrollArea, QWidget)

from . import brief, brief_v4
from .i18n import tr

def autoprompt(name, folder, task):
    """Sentence for the AI chat after the export – the same for every model (comparison), with Mule tools
    (MCP) if the AI has them."""
    # Blind test Glider 003: "say it briefly" and "the images" turned the first round into a short chat – 6 of ~60
    # images opened, no units and work list. That is why the sentence refers to the first round in the core.
    from . import review_round
    if (task or {}).get("kind") != "discuss" and review_round.is_brief((task or {}).get("based_on")):  # review round
        return tr("Review-Runde {0} zu „{1}“ liegt in {2}. Das ist kein neuer Brief und kein neuer Lauf, sondern Feedback für unsere laufende Arbeit: Lies dort review.md ganz und öffne alle Bilder, die sie nennt. Lass das Review in Entscheidungen, Einheiten und Arbeitsliste einfließen, nenn mir, wo es etwas Etabliertes ändert, frag nur, was offen bleibt, und arbeite dann weiter wie bisher – gleiche Regeln, gleiche Stufe.").format(
            review_round.round_number(folder or ""), name, os.path.normpath(folder) if folder else folder)
    if (task or {}).get("kind") != "discuss":  # build brief with working-method package v4 (hooks, roles, levels)
        text = tr("Diese Sitzung muss im Brief-Ordner {1} laufen, nur dort greifen die Hooks. Läuft sie in einem anderen Ordner, mach nichts weiter und sag mir, dass ich eine neue Sitzung in genau diesem Ordner starten soll. Beginne deine erste Nachricht mit dem Block „GATE STATUS“ aus dem Start-Hook, wörtlich zitiert. Fehlt er, mach nichts weiter und sag es mir. Prüfe und besprich den Sketch Brief „{0}“ ({1}). Lies conductor.md, project.md und brief.md und mach die erste Runde, wie sie in conductor.md steht: zuerst die echten Fragen mit markierten Bildern, dann eine Tabelle mit allem Zweifelsfreien, dann die Einheiten mit Abhängigkeiten und Spuren, ganz unten die aktuelle Stufe und wie ich sie ändere. Ich darf per Ausnahme antworten. Nach meinen Antworten kommt dein kurzer Zielvorschlag; gebaut wird erst nach meiner Bestätigung. Hast du die Mule-Werkzeuge, schlag für Referenzbilder ohne Unterschrift je einen Satz vor und speichere, was ich bestätige, mit set_image_captions; das Geklärte der ersten Runde schreibst du mit write_clarified zurück.").format(name, os.path.normpath(folder) if folder else folder)
        if brief.TASK_LOOK in (task or {}).get("parts", []):
            text += tr(" Vor dem Bauen: je Hero-Kamera einen Bild-Prompt mit mir abstimmen (set_hero_prompt), Bilder erzeugen lassen, ich wähle aus.")
        return text
    text = (tr("Prüfe und besprich den Sketch Brief „{0}“ ({1}): Lies brief.md und mach die erste Runde, wie sie im Core steht – zuerst alle Hero-Bilder, ganzen Bretter und Abschnittsbilder aus dem Ordner, auch die von Teilen, die diese Runde nicht baut; dann die Antworten auf die Klärungsfragen, die du selbst aus Notizen und genannten Dateien beantwortest, nur die wirklich offenen Fragen, und – wenn gebaut wird – Prüfeinheiten und Arbeitsliste, alles in einer Nachricht. Hast du die Mule-Werkzeuge, sieh dir zusätzlich die Szene mit scene_brief an (live) und schreib das Geklärte am Ende mit write_clarified zurück. Referenzbilder ohne Unterschrift (image_captions): schlag je Bild einen Satz vor – wofür es steht und worauf es dabei ankommt (keine Nacherzählung des Bilds; sagt das Brett es schon, nur darauf verweisen) – und zu welchen Teilen (IDs) es gehört, und speichere, was ich bestätige, mit set_image_captions.").format(name, folder))
    if brief.TASK_LOOK in (task or {}).get("parts", []):
        text += (tr(" Schreib danach je Hero-Kamera einen guten Bild-Prompt aus dem Brief (Form wie im Hero-Bild, Materialien, Licht, Stimmung, Kamera, Stil), stimm ihn mit mir ab und speichere ihn mit set_hero_prompt."))
    return text


class BriefDialog(QDialog):
    def __init__(self, parent=None, task=None, selected=0, checks=None, name="skizze", folder="", clarified=None,
                 timing_interp=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Sketch Brief – Auftrag"))
        self.setMinimumWidth(600)
        task = brief.task_clean(task)
        self.checks = checks or {}  # brief.precheck: open items from the scene, text for the keyword hints
        form = QFormLayout(self)

        self.task = QLineEdit(task.get("task", ""))
        self.task.setPlaceholderText(tr("Ziel dieses Exports – ein Satz"))
        form.addRow(tr("Auftrag in einem Satz:"), self.task)
        self.notes = QPlainTextEdit(task.get("notes", ""))
        self.notes.setPlaceholderText(tr("Nur für diesen Export, Vorrang vor Notizen: Prioritäten, was wegbleibt, Änderungen"))
        self.notes.setFixedHeight(self.notes.fontMetrics().lineSpacing() * 3 + 12)
        form.addRow(tr("Hinweise zu diesem Export:"), self.notes)
        # review round: feedback for the running chat of an earlier brief (review_round.py) – no folder to choose
        self.folder = folder  # proposed folder of this export (also for the autoprompt)
        self.based_on = QLineEdit(task.get("based_on", ""))
        self.based_on.setReadOnly(True)
        self.based_on.setPlaceholderText(tr("nichts – normaler Export, ein neuer Brief"))
        pick = QPushButton(tr("Wählen …"))
        pick.setToolTip(tr("Brief-Ordner, in dem der laufende Chat arbeitet – dieser Export wird eine Review-Runde darin"))
        pick.clicked.connect(self._pick_based_on)
        unpick = QPushButton("×")
        unpick.setToolTip(tr("Keine Review-Runde – normaler Export"))
        unpick.setFixedWidth(unpick.fontMetrics().horizontalAdvance("×") + 20)
        unpick.clicked.connect(lambda: self.based_on.setText(""))
        brow = QWidget()
        blay = QHBoxLayout(brow)
        blay.setContentsMargins(0, 0, 0, 0)
        blay.addWidget(self.based_on, 1)
        blay.addWidget(pick)
        blay.addWidget(unpick)
        self.based_on_row = brow
        form.addRow(tr("Baut auf:"), brow)
        self.based_on_info = QLabel()
        self.based_on_info.setWordWrap(True)
        self.based_on_info.setStyleSheet("color: gray")
        form.addRow("", self.based_on_info)
        self.based_on.textChanged.connect(self._sync)
        self.discuss = QCheckBox(tr("Nur besprechen – nichts bauen"))
        self.discuss.setChecked(task.get("kind") == "discuss")
        self.discuss.toggled.connect(self._sync)
        form.addRow(tr("Art:"), self.discuss)
        self.look = QCheckBox(tr("Look-Vorstufe: erst Bilder aus den Hero-Kameras generieren, dann bauen"))
        self.look.setChecked(brief.TASK_LOOK in task.get("parts", []))
        self.look.toggled.connect(self._sync)
        form.addRow("", self.look)

        # timing cameras (only if there are any): stepped as in Mule or linear between the poses
        self.timing_combo = QComboBox()
        self.timing_combo.addItem(tr("gestuft – wie in Mule (jede Stellung hält bis zur nächsten)"), "step")
        self.timing_combo.addItem(tr("linear zwischen den Stellungen (weich machst du danach im 3D-Programm)"), "linear")
        self.timing_combo.setCurrentIndex(1 if timing_interp == "linear" else 0)
        form.addRow(tr("Shot-Kameras:"), self.timing_combo)
        form.setRowVisible(self.timing_combo, timing_interp is not None)

        self.focus = QCheckBox(tr("nur die Auswahl bauen ({0} Objekt(e)) – der Rest der Szene ist Kontext").format(selected))
        form.addRow(tr("Umfang:"), self.focus)
        form.setRowVisible(self.focus, bool(selected))
        info = QLabel(tr("Umfang der Runde, Arbeitsarten, Verbindlichkeit, Werkzeuge und Arbeitsweise klärt die KI in der ersten Runde aus deinen Notizen und fragt nach, was offen bleibt."))
        info.setWordWrap(True)
        info.setStyleSheet("color: gray")
        form.addRow(info)

        # what was clarified with the AI (MCP write_clarified): is in every export – view or delete (only at export)
        self.clarified, self.clear_clarified = clarified or {}, False
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        n = len(self.clarified.get("answers", []))
        self.clarified_label = QLabel(tr("{0} Punkt{1}").format(n, 'e' if n != 1 else '')
                                      + (tr(" und eine Zusammenfassung") if self.clarified.get("summary") else "")
                                      + tr(" – stehen in jedem Export")
                                      + (tr(" (+{0} im Verlauf)").format(len(self.clarified['history']))
                                         if self.clarified.get("history") else ""))
        show = QPushButton(tr("Ansehen"))
        show.clicked.connect(self._show_clarified)
        self.clarified_drop = QPushButton(tr("Löschen"))
        self.clarified_drop.setCheckable(True)
        self.clarified_drop.toggled.connect(self._drop_clarified)
        lay.addWidget(self.clarified_label, 1)
        lay.addWidget(show)
        lay.addWidget(self.clarified_drop)
        form.addRow(tr("Geklärt mit der KI:"), row)
        form.setRowVisible(row, bool(self.clarified))
        # check before export: what is open in the scene and which details are missing for the ticked parts –
        # fix in the scene, not here (the export is always possible)
        self.hints = QLabel()
        self.hints.setWordWrap(True)
        self.hints.setTextFormat(Qt.RichText)
        scroll = QScrollArea()
        scroll.setWidget(self.hints)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(150)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self.hints_box = scroll
        form.addRow(scroll)
        self.task.textChanged.connect(self._sync)
        self.notes.textChanged.connect(self._sync)

        # autoprompt: sentence for the AI chat, in the clipboard after the export; follows the settings until the user
        # changes it themselves
        self.name = name
        self.copy_prompt = QCheckBox(tr("Autoprompt – nach dem Export in der Zwischenablage (im Chat Strg+V)"))
        self.copy_prompt.setChecked(QSettings("SketchMachine", "SketchMachine").value("brief_copy_prompt", True)
                                    in (True, "true"))
        form.addRow(self.copy_prompt)
        self.prompt = QPlainTextEdit()
        self.prompt.setFixedHeight(self.prompt.fontMetrics().lineSpacing() * 4 + 12)
        self.prompt.setToolTip(tr("Wird aus den Einstellungen erzeugt; eigene Änderungen bleiben"))
        self._prompt_auto = True  # False as soon as the user writes themselves
        self._filling = False
        self.prompt.textChanged.connect(self._prompt_edited)
        self.copy_prompt.toggled.connect(self.prompt.setVisible)
        self.prompt.setVisible(self.copy_prompt.isChecked())
        form.addRow(self.prompt)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.addButton(tr("Exportieren"), QDialogButtonBox.AcceptRole)
        clear = QPushButton(tr("Leeren"))
        clear.setToolTip(tr("Alles auf „nicht angegeben“ – der Brief enthält dann keinen Auftrag"))
        clear.clicked.connect(self._clear)
        buttons.addButton(clear, QDialogButtonBox.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._sync()

    def _sync(self):
        """Look pre-stage only when building; hints before export and autoprompt follow the settings."""
        self.look.setEnabled(not self.discuss.isChecked())
        if hasattr(self, "based_on_info"):
            self.based_on_row.setEnabled(not self.discuss.isChecked())
            self.based_on_info.setText(self.based_on_text())
            self.layout().setRowVisible(self.based_on_info, bool(self.based_on_info.text()))
        if not hasattr(self, "hints"):
            return  # still under construction
        hints = brief.part_hints(self.values(), self.checks.get("text", ""), self.checks.get("images", False))             + self.checks.get("points", [])
        if not self.discuss.isChecked():  # build brief: the gate hooks need these programs on this machine
            if not hasattr(self, "_hook_missing"):
                self._hook_missing = brief_v4.hook_programs()[2]
            if self._hook_missing:
                hints.append(tr("Für die Hooks des Bau-Briefs fehlt auf diesem Rechner: {0} – ohne sie gelten die "
                                "Regeln nur im Chat").format(", ".join(self._hook_missing)))
        self.hints.setText(tr("<b>Vor dem Export prüfen ({0}):</b><br>").format(len(hints)) + "<br>".join(
            "• " + html.escape(h) for h in hints) if hints else "")
        self.hints_box.setVisible(bool(hints))
        self.layout().setRowVisible(self.hints_box, bool(hints))  # empty: no gap in the dialog
        if getattr(self, "_prompt_auto", False):
            self._filling = True
            self.prompt.setPlainText(autoprompt(self.name, self.round_folder() or self.folder, self.values()))
            self._filling = False

    def round_folder(self):
        """Folder of the review round when "Builds on" points to a brief (and it is being built), otherwise None."""
        from . import review_round
        b = self.based_on.text().strip()
        if not b or self.discuss.isChecked() or not review_round.is_brief(b):
            return None
        return review_round.next_folder(b)

    def based_on_text(self):
        """Where the review round goes – or why none."""
        from . import review_round
        b = self.based_on.text().strip()
        if not b:
            return ""
        if not review_round.is_brief(b):
            return tr("Dort liegt kein Sketch Brief (brief.json) – wähl den Brief-Ordner, in dem der laufende Chat arbeitet.")
        target = review_round.next_folder(b)
        return tr("Review-Runde {0} – geht ohne Ordnerwahl nach {1}. Keine neuen Regeln, Hooks oder Arbeitsordner: drin steht nur, was sich an den Notizen seit dem letzten Export geändert hat, dazu der aktuelle Stand. Den Satz fügst du im laufenden Chat ein.").format(
            review_round.round_number(target), os.path.normpath(target))

    def _pick_based_on(self):
        from PySide6.QtWidgets import QFileDialog
        start = self.based_on.text() or os.path.dirname(self.folder or "")
        d = QFileDialog.getExistingDirectory(self, tr("Brief-Ordner des laufenden Chats wählen"), start)
        if d:
            from . import review_round
            self.based_on.setText(os.path.normpath(review_round.base_of(d)))

    def clarified_text(self):
        """What was clarified, for reading (summary, then question → answer)."""
        c = self.clarified
        parts = [c["summary"], ""] if c.get("summary") else []
        parts += [f"• {a['question']} → " + (tr("entscheidet die KI") if a["answer"] == "decide" else a["answer"])
                  for a in c.get("answers", [])]
        if c.get("history"):
            parts += ["", tr("Verlauf (gilt nicht mehr):"), *[f"• {a['question']} → {a['answer']}" for a in c["history"]]]
        return "\n".join(parts).strip()

    def _show_clarified(self):
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(QMessageBox.NoIcon, tr("Geklärt mit der KI"), self.clarified_text(), QMessageBox.Close, self)
        box.exec()

    def _drop_clarified(self, on):
        self.clear_clarified = on
        self.clarified_drop.setText(tr("Behalten") if on else tr("Löschen"))
        self.clarified_label.setEnabled(not on)
        self.clarified_label.setToolTip(tr("Wird beim Exportieren gelöscht") if on else "")

    def _prompt_edited(self):
        if not self._filling:
            self._prompt_auto = False

    def prompt_text(self, folder=None):
        """Autoprompt for the chat; folder: actual folder (replaces the proposed one)."""
        text = self.prompt.toPlainText().strip()
        if not (folder and self.folder):
            return text
        # the sentence names the folder normalized (autoprompt); replace in both spellings
        return text.replace(os.path.normpath(self.folder), os.path.normpath(folder)).replace(self.folder, folder)

    def _clear(self):
        self.task.clear()
        self.notes.clear()
        self.discuss.setChecked(False)
        self.look.setChecked(False)
        self.based_on.setText("")
        self._sync()

    def timing_interp(self):
        return self.timing_combo.currentData()

    def values(self):
        """Assignment as stored (only what was specified)."""
        return brief.task_clean({
            "task": self.task.text(), "notes": self.notes.toPlainText(),
            "kind": "discuss" if self.discuss.isChecked() else None,
            "parts": [brief.TASK_LOOK] if self.look.isChecked() else [],
            "based_on": self.based_on.text()})  # unused when discussing only, but remembered
