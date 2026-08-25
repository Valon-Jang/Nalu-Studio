from __future__ import annotations

import tkinter as tk
import unittest


class ManualSubmissionBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.root.withdraw()
        self.input = tk.Text(self.root)
        self.input.mark_set("manual_submission_end", "1.0")
        self.input.mark_gravity("manual_submission_end", tk.LEFT)

    def tearDown(self) -> None:
        if hasattr(self, "root"):
            self.root.destroy()

    def test_second_manual_submission_excludes_already_spoken_text(self) -> None:
        self.input.insert("1.0", "첫 대사")
        first_end = self.input.index("end-1c")
        self.assertEqual(self.input.get("manual_submission_end", first_end).strip(), "첫 대사")
        self.input.mark_set("manual_submission_end", first_end)

        self.input.insert("end-1c", "\n둘째 대사")
        second_end = self.input.index("end-1c")
        self.assertEqual(self.input.get("manual_submission_end", second_end).strip(), "둘째 대사")


if __name__ == "__main__":
    unittest.main()
