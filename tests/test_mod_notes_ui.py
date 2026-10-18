"""Draft-safe Mod Notes workflows, using the existing lightweight Qt fixtures."""

import importlib
import sys
import tempfile
import unittest
from enum import IntFlag
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests import test_core as _fixtures
from src.core.mod_notes import NoteEntry


class TestModNotesDialog(unittest.TestCase):
    def setUp(self):
        self.qt = _fixtures.TestWidgetsLogging()._stub_widget_modules()
        self.qt.__enter__()
        self.addCleanup(self.qt.__exit__, None, None, None)
        sys.modules.pop("src.ui.widgets", None)
        self.module = importlib.import_module("src.ui.widgets")
        self.addCleanup(patch.stopall)
        patch.object(self.module, "QListWidgetItem", MagicMock()).start()

        class Buttons(IntFlag):
            Yes = 1
            No = 2
            Save = 4
            Discard = 8
            Cancel = 16

        self.buttons = Buttons
        self.module.QMessageBox.StandardButton = Buttons
        self.question = patch.object(self.module.QMessageBox, "question", return_value=Buttons.Cancel).start()
        self.critical = patch.object(self.module.QMessageBox, "critical").start()
        self.first = NoteEntry(
            "record-a", "catalogue-a", "<b>Alpha</b>", "texture_pack",
            "SLUS-20062", "original text", "2026-01-01", "2026-02-01",
        )
        self.second = NoteEntry(
            "record-b", "catalogue-b", "Beta", "pnach",
            text="widescreen", updated_at="2026-03-01",
        )
        self.dialog = dlg = self.module.ModNotesDialog.__new__(self.module.ModNotesDialog)
        dlg._config = object()
        dlg._all_notes = [self.first, self.second]
        dlg._notes = list(dlg._all_notes)
        dlg._current_note = None
        dlg._changing_note = False
        dlg._draft = ""
        for name in (
            "_search_timer", "_search_edit", "_type_combo", "_sort_combo",
            "_list_widget", "_summary_label", "_status_label", "_title_label",
            "_meta_label", "_draft_label", "_text_edit", "_save_btn",
            "_revert_btn", "_delete_btn",
        ):
            setattr(dlg, name, MagicMock())
        dlg._search_edit.text.return_value = ""
        dlg._search_edit.clear.side_effect = lambda: setattr(dlg._search_edit.text, "return_value", "")
        dlg._type_combo.currentText.return_value = "All"
        dlg._type_combo.setCurrentIndex.side_effect = lambda *_: setattr(
            dlg._type_combo.currentText, "return_value", "All",
        )
        dlg._sort_combo.currentText.return_value = "Recently updated"
        dlg._text_edit.toPlainText.side_effect = lambda: dlg._draft
        dlg._text_edit.setPlainText.side_effect = lambda text: setattr(dlg, "_draft", text)
        dlg._show_note(self.first)

    def _draft(self):
        self.dialog._text_edit.setPlainText("unsaved draft")
        self.dialog._sync_editor_state()

    def test_filters_keep_hidden_draft_without_reading_disk(self):
        self._draft()
        self.dialog._search_edit.text.return_value = "Beta widescreen"
        with patch("src.core.mod_notes.list_notes") as read:
            self.dialog._apply_filters()
        read.assert_not_called()
        self.assertEqual(self.dialog._notes, [self.second])
        self.assertIs(self.dialog._current_note, self.first)
        self.assertEqual(self.dialog._draft, "unsaved draft")
        self.assertIn("hidden", self.dialog._draft_label.setText.call_args.args[0])
        self.question.assert_not_called()

    def test_clear_filters_recovers_selected_draft(self):
        self._draft()
        self.dialog._search_edit.text.return_value = "no match"
        self.dialog._apply_filters()
        self.assertIn("Clear Filters", self.dialog._summary_label.setText.call_args.args[0])
        self.dialog._clear_filters()
        self.assertEqual(len(self.dialog._notes), 2)
        self.dialog._list_widget.setCurrentRow.assert_called_with(1)
        self.assertEqual(self.dialog._draft, "unsaved draft")

    def test_sorting_is_local_and_preserves_current_note(self):
        for sort, expected in (
            ("Recently updated", [self.second, self.first]),
            ("Oldest updated", [self.first, self.second]),
            ("Title (A–Z)", [self.first, self.second]),
        ):
            with self.subTest(sort=sort):
                self.dialog._sort_combo.currentText.return_value = sort
                self.dialog._apply_filters()
                self.assertEqual(self.dialog._notes, expected)
                self.assertIs(self.dialog._current_note, self.first)

    def test_search_matches_serial_and_id_across_fields(self):
        self.dialog._search_edit.text.return_value = "SLUS-20062 catalogue-a"
        self.dialog._apply_filters()
        self.assertEqual(self.dialog._notes, [self.first])

    def test_game_save_filter_includes_both_type_spellings(self):
        legacy = NoteEntry("l", "l", "Legacy", "save")
        current = NoteEntry("c", "c", "Current", "save_file")
        self.dialog._all_notes.extend([legacy, current])
        self.dialog._type_combo.currentText.return_value = "💾 Game Save"
        self.dialog._apply_filters()
        self.assertEqual(set(n.entry_id for n in self.dialog._notes), {"l", "c"})

    def test_cancel_selection_keeps_draft_and_restores_identity(self):
        self._draft()
        self.dialog._on_selection_changed(1)
        self.assertIs(self.dialog._current_note, self.first)
        self.assertEqual(self.dialog._draft, "unsaved draft")
        self.assertEqual(self.question.call_args.args[-1], self.buttons.Cancel)

    def test_discard_selection_opens_target_without_saving(self):
        self._draft()
        self.question.return_value = self.buttons.Discard
        with patch("src.core.mod_notes.upsert_note") as save:
            self.dialog._on_selection_changed(1)
        save.assert_not_called()
        self.assertIs(self.dialog._current_note, self.second)
        self.assertEqual(self.dialog._draft, self.second.text)

    def test_save_before_selection_then_open_target(self):
        self._draft()
        self.question.return_value = self.buttons.Save
        saved = NoteEntry(**{**self.first.to_dict(), "text": "unsaved draft"})
        with patch("src.core.mod_notes.upsert_note", return_value=saved) as save:
            self.dialog._on_selection_changed(1)
        self.assertEqual(save.call_args.kwargs["entry_id"], self.first.entry_id)
        self.assertIs(self.dialog._current_note, self.second)
        self.assertIn(saved, self.dialog._all_notes)

    def test_failed_save_prevents_selection_and_keeps_draft(self):
        self._draft()
        self.question.return_value = self.buttons.Save
        with patch("src.core.mod_notes.upsert_note", side_effect=OSError("disk full")):
            with self.assertLogs("src.ui.widgets", level="WARNING"):
                self.dialog._on_selection_changed(1)
        self.assertIs(self.dialog._current_note, self.first)
        self.assertEqual(self.dialog._draft, "unsaved draft")
        self.assertTrue(self.dialog._is_dirty())
        self.assertIn("retry", self.dialog._status_label.setText.call_args.args[0])

    def test_save_hidden_note_keeps_filter_and_editor(self):
        self._draft()
        self.dialog._search_edit.text.return_value = "Beta"
        saved = NoteEntry(**{**self.first.to_dict(), "text": "unsaved draft"})
        with patch("src.core.mod_notes.upsert_note", return_value=saved):
            self.assertTrue(self.dialog._save_current_note())
        self.assertEqual(self.dialog._notes, [self.second])
        self.assertIs(self.dialog._current_note, saved)
        self.assertFalse(self.dialog._is_dirty())

    def test_reselect_current_or_invalid_row_never_clears_draft(self):
        self._draft()
        for row in (0, -1, 99):
            self.dialog._on_selection_changed(row)
        self.assertEqual(self.dialog._draft, "unsaved draft")
        self.question.assert_not_called()

    def test_close_cancel_and_failed_save_do_not_finish_dialog(self):
        self._draft()
        with patch.object(self.module.QDialog, "done", create=True) as done:
            self.dialog.done(0)
            done.assert_not_called()
            self.question.return_value = self.buttons.Save
            with patch("src.core.mod_notes.upsert_note", side_effect=OSError("full")):
                with self.assertLogs("src.ui.widgets", level="WARNING"):
                    self.dialog.done(0)
            done.assert_not_called()
            self.question.return_value = self.buttons.Discard
            self.dialog.done(0)
            done.assert_called_once_with(0)

    def test_reload_cancel_does_not_read_disk(self):
        self._draft()
        with patch("src.core.mod_notes.list_notes") as read:
            self.dialog._refresh()
        read.assert_not_called()
        self.assertEqual(self.dialog._draft, "unsaved draft")

    def test_reload_failure_preserves_snapshot_and_draft(self):
        self._draft()
        self.question.return_value = self.buttons.Discard
        with patch("src.core.mod_notes.list_notes", side_effect=OSError("denied")) as read:
            with self.assertLogs("src.ui.widgets", level="WARNING"):
                self.dialog._refresh()
        read.assert_called_once_with(self.dialog._config, strict=True)
        self.assertEqual(self.dialog._all_notes, [self.first, self.second])
        self.assertEqual(self.dialog._draft, "unsaved draft")

    def test_reload_success_resolves_selected_entry_by_id(self):
        updated = NoteEntry(**{**self.first.to_dict(), "text": "external update"})
        with patch("src.core.mod_notes.list_notes", return_value=[updated, self.second]):
            self.dialog._refresh()
        self.assertIs(self.dialog._current_note, updated)
        self.assertEqual(self.dialog._draft, "external update")

    def test_new_note_cancel_does_not_prompt_for_title(self):
        self._draft()
        with patch("PyQt6.QtWidgets.QInputDialog", MagicMock(), create=True):
            self.dialog._on_new_note()
        self.assertEqual(self.dialog._draft, "unsaved draft")

    def test_new_same_title_note_does_not_overwrite_catalogue_note(self):
        input_dialog = MagicMock()
        input_dialog.getText.return_value = (self.first.entry_title, True)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.core.config_manager.get_exe_dir", return_value=tmp,
        ), patch("PyQt6.QtWidgets.QInputDialog", input_dialog, create=True):
            from src.core.mod_notes import upsert_note, list_notes
            upsert_note(self.dialog._config, self.first.entry_id, self.first.entry_title,
                        self.first.mod_type, text=self.first.text)
            self.dialog._on_new_note()
            self.dialog._on_new_note()
            notes = list_notes(self.dialog._config, strict=True)
        self.assertEqual(len(notes), 3)
        self.assertEqual(next(n.text for n in notes if n.entry_id == self.first.entry_id), self.first.text)
        self.assertEqual(len(set(n.entry_id for n in notes)), 3)

    def test_delete_and_clear_failures_keep_draft(self):
        self._draft()
        self.question.return_value = self.buttons.Yes
        for operation, method in (
            ("delete_note", self.dialog._on_delete_note),
            ("clear_notes", self.dialog._on_clear),
        ):
            with self.subTest(operation=operation):
                with patch("src.core.mod_notes." + operation, side_effect=OSError("denied")):
                    with self.assertLogs("src.ui.widgets", level="WARNING"):
                        method()
                self.assertEqual(self.dialog._draft, "unsaved draft")
                self.assertIs(self.dialog._current_note, self.first)
                self.assertEqual(self.question.call_args.args[-1], self.buttons.No)

    def test_delete_only_current_note_and_clear_success(self):
        self.question.return_value = self.buttons.Yes
        with patch("src.core.mod_notes.delete_note", return_value=True) as delete:
            self.dialog._on_delete_note()
        delete.assert_called_once_with(self.dialog._config, self.first.entry_id)
        self.assertEqual(self.dialog._all_notes, [self.second])
        self.assertIsNone(self.dialog._current_note)
        with patch("src.core.mod_notes.clear_notes", return_value=1):
            self.dialog._on_clear()
        self.assertEqual(self.dialog._all_notes, [])
        self.assertIn("New Note", self.dialog._summary_label.setText.call_args.args[0])

    def test_revert_cancel_or_confirm(self):
        self._draft()
        self.question.return_value = self.buttons.No
        self.dialog._on_revert()
        self.assertTrue(self.dialog._is_dirty())
        self.question.return_value = self.buttons.Yes
        self.dialog._on_revert()
        self.assertEqual(self.dialog._draft, self.first.text)
        self.assertFalse(self.dialog._is_dirty())


class TestModNotesStrictStore(unittest.TestCase):
    def test_corrupt_stores_are_never_overwritten_by_mutations_or_export(self):
        from src.core.mod_notes import upsert_note, delete_note, clear_notes, export_notes_csv, list_notes

        for data in (
            "{invalid", "{}", "[7]", '[{"entry_id": "a", "text": 7}]',
            '[{"entry_id": ""}]', '[{"entry_id": "a"}, {"entry_id": "a"}]',
        ):
            with self.subTest(data=data), tempfile.TemporaryDirectory() as tmp, patch(
                "src.core.config_manager.get_exe_dir", return_value=tmp,
            ):
                path = Path(tmp) / "mod_notes.json"
                path.write_text(data, encoding="utf-8")
                export = Path(tmp) / "export.csv"
                export.write_text("previous export", encoding="utf-8")
                for action in (
                    lambda: list_notes(None, strict=True),
                    lambda: upsert_note(None, "new", "New", "other"),
                    lambda: delete_note(None, "a"),
                    lambda: clear_notes(None),
                    lambda: export_notes_csv(None, str(export)),
                ):
                    with self.assertLogs("src.core.mod_notes", level="WARNING"):
                        with self.assertRaises(ValueError):
                            action()
                    self.assertEqual(path.read_text(encoding="utf-8"), data)
                    self.assertEqual(export.read_text(encoding="utf-8"), "previous export")

    def test_unreadable_store_is_not_treated_as_empty(self):
        from src.core.mod_notes import list_notes, upsert_note

        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.core.config_manager.get_exe_dir", return_value=tmp,
        ):
            (Path(tmp) / "mod_notes.json").write_text("[]")
            with patch("builtins.open", side_effect=PermissionError("denied")):
                for action in (lambda: list_notes(None, strict=True), lambda: upsert_note(None, "a", "A", "other")):
                    with self.assertLogs("src.core.mod_notes", level="WARNING"):
                        with self.assertRaises(PermissionError):
                            action()


if __name__ == "__main__":
    unittest.main()
