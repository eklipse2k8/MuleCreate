"""Assignment dialog at brief export: sets only what the AI cannot clarify from the scene itself – assignment in
one sentence, hints for this export, "discuss only", look pre-stage, focus on the selection. Scope of the round,
kinds of work, bindingness, tools and way of working are clarified by the AI in the first round from the notes
(brief.CLARIFY). Stored in scene.brief_task (brief.task_clean). "Brief-Recipe" picks the brief recipe of a build brief
(recipes.py): Mule's own or one of the user's / the community's – a review round keeps the recipe of its brief."""
import html
import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QPlainTextEdit, QPushButton, QScrollArea, QToolButton, QWidget)

from . import brief, brief_v4, recipes
from .i18n import tr

def autoprompt(name, folder, task):
    """Sentence for the AI chat after the export – the same for every model (comparison), with Mule tools
    (MCP) if the AI has them."""
    # Blind test Glider 003: "say it briefly" and "the images" turned the first round into a short chat – 6 of ~60
    # images opened, no units and work list. That is why the sentence refers to the first round in the core.
    from . import i18n, recipes, review_round
    if (task or {}).get("kind") != "discuss" and review_round.is_brief((task or {}).get("based_on")):  # review round
        recipe = brief_v4.recipe_of(review_round.base_of(task["based_on"])) or recipes.default()
        text = recipe.render("review_start", {"round": review_round.round_number(folder or ""), "project_name": name,
                                              "round_dir": os.path.normpath(folder) if folder else ""}, i18n.LANG)
        return (text or tr("Review-Runde {0} zu „{1}“ liegt in {2}. Lies dort review.md ganz und arbeite weiter.").format(
            review_round.round_number(folder or ""), name, os.path.normpath(folder) if folder else folder)).strip()
    if (task or {}).get("kind") != "discuss":  # build brief: the sentence comes with the recipe
        recipe = recipes.get((task or {}).get("recipe"))
        return recipe.render("start", {"project_name": name, "brief_dir": os.path.normpath(folder) if folder else "",
                                       "look": brief.TASK_LOOK in (task or {}).get("parts", []),
                                       "recipe": {"id": recipe.id, "name": recipe.name, "version": recipe.version}},
                             i18n.LANG).strip()
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

        # brief recipe (recipes.py): the whole way of working of a build brief – rules, roles, hooks, agents, texts
        self.recipe_combo = QComboBox()
        self.recipe_combo.setToolTip(tr("Recipe des Bau-Briefs: die ganze Arbeitsweise – Regeln, Rollen, Hooks, Agenten und der Satz für den Chat"))
        more = QToolButton()
        more.setText("…")
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        menu.addAction(tr("Neues Recipe …"), self._new_recipe)
        menu.addAction(tr("Als eigenes Recipe kopieren …"), self._copy_recipe)
        menu.addSeparator()
        menu.addAction(tr("Recipe importieren (.zip) …"), self._import_recipe)
        menu.addAction(tr("Recipe aus Ordner importieren …"), self._import_recipe_folder)
        menu.addSeparator()
        menu.addAction(tr("Inhalt ansehen …"), self._show_recipe)
        menu.addAction(tr("Recipe-Ordner öffnen"), self._open_recipe_dir)
        menu.addAction(tr("Neu einlesen"), lambda: self._fill_recipes(self.recipe_combo.currentData()))
        more.setMenu(menu)
        rrow = QWidget()
        rlay = QHBoxLayout(rrow)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.addWidget(self.recipe_combo, 1)
        rlay.addWidget(more)
        self.recipe_row = rrow
        form.addRow(tr("Brief-Recipe:"), rrow)
        self.recipe_info = QLabel()
        self.recipe_info.setWordWrap(True)
        self.recipe_info.setStyleSheet("color: gray")
        form.addRow("", self.recipe_info)
        self._recipes = {}
        self._fill_recipes(task.get("recipe") or recipes.DEFAULT_ID)
        self.recipe_combo.currentIndexChanged.connect(self._sync)

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
        if hasattr(self, "recipe_info"):
            self.recipe_row.setEnabled(not self.discuss.isChecked() and self.round_folder() is None)
            self.recipe_info.setText(self.recipe_text())
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

    # ---- brief recipe

    def _fill_recipes(self, wanted):
        """Recipes into the list; broken ones are shown but cannot be chosen. A wanted recipe that is missing falls
        back to Mule's own (the info line says so)."""
        self.recipe_combo.blockSignals(True)
        self.recipe_combo.clear()
        self._recipes = {}
        pick = 0
        for r in recipes.available():
            label = (tr("Mule Default ({0})").format(r.version) if r.builtin else
                     r.label() + (f" – {r.author}" if r.author else ""))
            self.recipe_combo.addItem(label, r.id if r.ok else None)
            k = self.recipe_combo.count() - 1
            if not r.ok:
                self.recipe_combo.model().item(k).setEnabled(False)
                self.recipe_combo.setItemData(k, tr("Nicht nutzbar: ") + "; ".join(r.problems), Qt.ToolTipRole)
            else:
                self._recipes.setdefault(r.id, r)
                if r.id == wanted:
                    pick = k
        self._recipe_missing = wanted if wanted and wanted not in self._recipes else None
        self.recipe_combo.setCurrentIndex(pick)
        self.recipe_combo.blockSignals(False)
        if hasattr(self, "hints"):
            self._sync()

    def recipe(self):
        return self._recipes.get(self.recipe_combo.currentData()) or recipes.default()

    def recipe_text(self):
        """Info line under the recipe choice."""
        from . import review_round
        if self.discuss.isChecked():
            return tr("„Nur besprechen“ nutzt kein Recipe – der Brief bringt seinen kurzen Kern mit.")
        b = self.based_on.text().strip()
        if b and review_round.is_brief(b):
            base = review_round.base_of(b)
            lock = recipes.read_lock(base) or {}
            r = brief_v4.recipe_of(base)
            if r is None and lock:
                return tr("Review-Runde: der Brief nutzt „{0}“ {1} – auf diesem Rechner nicht installiert, die Runde bringt keine neue Version mit.").format(lock.get("name") or lock["id"], lock.get("version", ""))
            return tr("Review-Runde: es gilt das Recipe des Briefs – {0}.").format(
                (r or recipes.default()).label())
        r = self.recipe()
        lines = []
        if self._recipe_missing:
            lines.append(tr("Das gespeicherte Recipe „{0}“ ist hier nicht installiert – es gilt Mule Default.").format(self._recipe_missing))
        if r.description:
            lines.append(r.description)
        sm = recipes.summary(r)
        meta = [tr("von {0}").format(r.author)] if r.author else []
        if r.made_for:
            meta.append(tr("für {0}").format(", ".join(r.made_for)))
        if r.size:
            meta.append(tr("Größe: {0}").format(r.size))
        meta.append(tr("{0} Hook-Befehl(e)").format(len(sm["hooks"])))
        if not r.builtin:
            meta.append(tr("nicht von Mule geprüft – vor dem ersten Lauf ansehen (…)"))
        if sm["network"] and not r.builtin:
            meta.append(tr("{0} Stelle(n) mit Netz/Download in Skripten").format(len(sm["network"])))
        if sm["mode"] in ("bypassPermissions", "acceptEdits"):
            meta.append(tr("Rechte-Modus „{0}“").format(sm["mode"]))
        lines.append(" · ".join(meta))
        return "\n".join(lines)

    def _show_recipe(self):
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(QMessageBox.NoIcon, tr("Brief-Recipe"), summary_text(self.recipe()), QMessageBox.Close, self)
        box.exec()

    def _open_recipe_dir(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(recipes.user_dir()))

    def _new_recipe(self, name=None):
        """A nearly empty recipe of one's own, ready for a Claude session that writes it. -> Recipe or None."""
        if name is None:
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, tr("Neues Recipe"), tr("Name des Recipes (z. B. „Kreatur“, „Kleine Requisite“):"))
            if not ok or not name.strip():
                return None
        r = recipes.create_empty(name.strip())
        sentence = tr("Das ist ein neues Brief-Recipe für Mule in {0}. Lies START_HERE.md und FORMAT.md. Ich möchte damit Folgendes: ").format(os.path.normpath(r.path))
        return self._made_recipe(r, sentence)

    def _copy_recipe(self, name=None):
        """The chosen recipe as a recipe of one's own to change. -> Recipe or None."""
        src = self.recipe()
        if name is None:
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, tr("Als eigenes Recipe kopieren"),
                                            tr("Name der Kopie von „{0}“:").format(src.name), text=tr("{0} – meine Fassung").format(src.name))
            if not ok or not name.strip():
                return None
        r = recipes.copy_recipe(src, name.strip())
        sentence = tr("Das ist mein Brief-Recipe „{1}“ für Mule in {0}, eine Kopie von „{2}“. Lies START_HERE.md und FORMAT.md. Ich möchte daran Folgendes ändern: ").format(os.path.normpath(r.path), r.name, src.label())
        return self._made_recipe(r, sentence)

    def _made_recipe(self, r, sentence):
        """New recipe: choose it, sentence for a Claude session into the clipboard, open its folder."""
        from PySide6.QtWidgets import QApplication, QMessageBox
        self._fill_recipes(r.id)
        QApplication.clipboard().setText(sentence)
        self.recipe_made = r.path  # tests: no folder window
        if not getattr(self, "quiet", False):
            QMessageBox.information(self, tr("Brief-Recipe"), tr("„{0}“ liegt jetzt in\n{1}\nund ist im Dialog ausgewählt.\n\nSo arbeitest du daran: eine Claude-Sitzung in genau diesem Ordner starten und den Satz aus der Zwischenablage einfügen (Strg+V) – er sagt der KI, wo Anleitung und Format stehen; ergänze, was das Recipe anders machen soll. Änderungen gelten ab dem nächsten Export (… → Neu einlesen).").format(r.name, os.path.normpath(r.path)))
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(r.path))
        return r

    def _import_recipe_folder(self, path=None, ask=True):
        """A recipe folder from somewhere – checked and copied like a zip. -> Recipe or None."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        if not path:
            path = QFileDialog.getExistingDirectory(self, tr("Recipe-Ordner wählen (mit recipe.toml)"))
            if not path:
                return None
        try:
            r = recipes.unpack_folder(path)
        except recipes.RecipeError as exc:
            QMessageBox.warning(self, tr("Recipe importieren"), str(exc))
            return None
        return self._install_checked(r, ask, tr("Der Ordner bleibt, wo er ist."))

    def _import_recipe(self, path=None, ask=True):
        """Unpack a recipe zip, show what it does on this machine, install after confirmation. -> Recipe or None."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("Recipe importieren"), "", tr("Recipe (*.zip)"))
            if not path:
                return None
        try:
            r = recipes.unpack(path)
        except recipes.RecipeError as exc:
            QMessageBox.warning(self, tr("Recipe importieren"), str(exc))
            return None
        return self._install_checked(r, ask, tr("Die Zip-Datei bleibt, wo sie ist."))

    def _install_checked(self, r, ask, stays):
        """Show what an unpacked recipe does, copy it into the recipe folder after confirmation, choose it."""
        from PySide6.QtWidgets import QMessageBox
        try:
            if not r.ok:
                QMessageBox.warning(self, tr("Recipe importieren"), tr("Dieses Recipe ist nicht nutzbar:") + "\n• "
                                    + "\n• ".join(r.problems))
                return None
            exists = os.path.exists(recipes.target_of(r))
            if ask:
                where = tr("Mule kopiert es als Ordner nach {0}. {1}").format(
                    os.path.normpath(recipes.target_of(r)), stays)
                box = QMessageBox(QMessageBox.Question, tr("Recipe importieren"),
                                  summary_text(r) + "\n\n" + where + "\n\n"
                                  + (tr("Ein Recipe „{0}“ ist schon installiert – ersetzen?").format(r.id)
                                     if exists else tr("Installieren?")),
                                  QMessageBox.Yes | QMessageBox.No, self)
                if box.exec() != QMessageBox.Yes:
                    return None
            try:
                installed = recipes.install_unpacked(r, replace=exists)
            except recipes.RecipeError as exc:
                QMessageBox.warning(self, tr("Recipe importieren"), str(exc))
                return None
        finally:
            recipes.discard(r)
        self._fill_recipes(installed.id)
        return installed

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
            "based_on": self.based_on.text(),  # unused when discussing only, but remembered
            "recipe": self.recipe_combo.currentData() or ""})


def summary_text(r):
    """What a recipe is and does on this machine – before importing and on request in the dialog. A help for
    looking, not a guarantee: the files themselves decide."""
    sm = recipes.summary(r)
    def clean(cmd):
        for k, v in (("{{bash}}", "bash"), ("{{powershell}}", "powershell"), ("{{brief_dir}}", "<Brief>"),
                     ("{{work_dir}}", "<Arbeitsordner>")):
            cmd = cmd.replace(k, v)
        return cmd
    out = [f"{r.name} {r.version}" + (f" – {r.author}" if r.author else ""), r.description, ""]
    if r.made_for or r.size:
        out.append(tr("Gedacht für: {0}").format(", ".join(r.made_for) + (f" · {r.size}" if r.size else "")))
    out.append(tr("Werkzeug: {0} · Brief-Schnittstelle {1}").format(r.harness, r.interface))
    if r.forked_from:
        out.append(tr("Abgeleitet von: {0}").format(r.forked_from))
    out.append(tr("Dateien: {0} (Brief-Ordner {1}, Arbeitsordner {2})").format(sm["files"], len(sm["brief"]), len(sm["work"])))
    out.append(tr("Prüfsumme: {0}").format(recipes.digest(r)[:16]))
    out += ["", tr("Hooks – Befehle, die Claude Code auf deinem Rechner ausführt ({0}):").format(len(sm["hooks"]))]
    out += [f"• {e}: {clean(c)}" for e, c in sm["hooks"]] or [tr("• keine")]
    if sm["allow"] or sm["mode"]:
        out += ["", tr("Freigaben ohne Rückfrage:") + " " + ", ".join(sm["allow"] or ["–"])
                + (tr(" · Rechte-Modus „{0}“").format(sm["mode"]) if sm["mode"] else "")]
    if sm["mcp"]:
        out += ["", tr("Eigene MCP-Server: {0}").format(", ".join(sm["mcp"]))]
    if sm["network"]:
        out += ["", tr("Netz/Download in Skripten ({0}):").format(len(sm["network"]))]
        out += [f"• {f}:{k}  {t}" for f, k, t in sm["network"][:12]]
        if len(sm["network"]) > 12:
            out.append(tr("• … und {0} weitere").format(len(sm["network"]) - 12))
    out += ["", tr("Ein Recipe ist Anweisung und Programm zugleich: Regeln und Rollen steuern die KI, Hooks laufen auf deinem Rechner. Diese Übersicht ersetzt kein Lesen der Dateien – nimm nur Recipes, deren Quelle du traust.")]
    return "\n".join(x for x in out if x is not None).replace("\n\n\n", "\n\n")
