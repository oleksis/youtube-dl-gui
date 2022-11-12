"""Contains test cases for the ListBoxComboPopup in widgets.py module."""

import sys
import unittest
from pathlib import Path

import wx

PATH = Path(__file__).parent
sys.path.insert(0, str(PATH.parent))

from youtube_dl_gui.widgets import ListBoxComboPopup


class TestCustomComboBox(unittest.TestCase):
    """Test cases for the CustomComboBox widget."""

    def setUp(self) -> None:
        self.app = wx.App()
        self.frame = wx.Frame(None)

        self.combobox = wx.ComboCtrl(self.frame, size=(180, -1), style=wx.CB_READONLY)
        self._popup_ctrl = ListBoxComboPopup(self.combobox)
        self.combobox.SetPopupControl(self._popup_ctrl)

        self._lb_popup_ctr = self._popup_ctrl.GetControl()

        # Call directly the ListBoxWithHeaders methods
        self._lb_popup_ctr.add_header("Header")
        self._lb_popup_ctr.add_items([f"item{i}" for i in range(10)])

    def tearDown(self):
        self.frame.Destroy()
        del self.app

    def test_init(self):
        choices = ["item0", "item1", "item2"]
        combobox = wx.ComboCtrl(self.frame, size=(180, -1), style=wx.CB_READONLY)
        popup_ctrl = ListBoxComboPopup(combobox)
        combobox.SetPopupControl(popup_ctrl)

        lb_popup_ctr = popup_ctrl.GetControl()
        lb_popup_ctr.AppendItems(choices)

        popup_ctrl.SetStringSelection("item1")

        self.assertEqual(popup_ctrl.GetStringValue(), "item1")
        self.assertEqual(popup_ctrl.GetSelection(), 1)
        self.assertEqual(lb_popup_ctr.GetCount(), 3)

    # wx.ComboBox methods
    # Not all of them since most of them are calls to ListBoxWithHeaders
    # methods and we already have tests for those

    def test_is_list_empty_false(self):
        self.assertFalse(self._popup_ctrl.IsListEmpty())

    def test_is_list_empty_true(self):
        self._popup_ctrl.Clear()
        self.assertTrue(self._popup_ctrl.IsListEmpty())

    def test_is_text_empty_false(self):
        self.combobox.SetValue("somevalue")
        self.assertFalse(self.combobox.GetValue() == "")

    def test_is_text_empty_true(self):
        self.assertTrue(self.combobox.GetValue() == "")

    def test_set_selection_item(self):
        self._popup_ctrl.SetSelection(1)
        self.assertEqual(self._popup_ctrl.GetSelection(), 1)
        self.assertEqual(self.combobox.GetValue(), "item0")

    def test_set_selection_header(self):
        self._popup_ctrl.SetSelection(0)
        self.assertEqual(self._popup_ctrl.GetSelection(), wx.NOT_FOUND)
        self.assertEqual(self.combobox.GetValue(), "")

    def test_set_string_selection_item(self):
        self._popup_ctrl.SetStringSelection("item0")
        self.assertEqual(self._popup_ctrl.GetStringValue(), "item0")
        self.assertEqual(self.combobox.GetValue(), "item0")

    def test_set_string_selection_header(self):
        self._popup_ctrl.SetStringSelection("Header")
        self.assertEqual(self.combobox.GetStringSelection(), "")
        self.assertEqual(self.combobox.GetValue(), "")

    def test_set_string_selection_invalid_string(self):
        self._popup_ctrl.SetStringSelection("abcde")
        self.assertEqual(self.combobox.GetStringSelection(), "")
        self.assertEqual(self.combobox.GetValue(), "")

    # wx.ItemContainer methods

    def test_clear(self):
        self.combobox.SetValue("value")
        self._popup_ctrl.Clear()
        self.assertEqual(self._popup_ctrl.GetControl().GetCount(), 0)
        self.assertEqual(self.combobox.GetValue(), "")

    def test_append(self):
        self._popup_ctrl.GetControl().Append("item10")
        self.assertEqual(self._popup_ctrl.GetControl().GetCount(), 12)

    def test_append_items(self):
        self._popup_ctrl.GetControl().AppendItems(["item10", "item11"])
        self.assertEqual(self._popup_ctrl.GetControl().GetCount(), 13)

    def test_delete(self):
        self._popup_ctrl.GetControl().Delete(1)
        self.assertEqual(self._popup_ctrl.GetControl().GetString(1), "item1")

    # wx.TextEntry methods

    def test_get_value(self):
        self.combobox.SetValue("value")
        self.assertEqual(self.combobox.GetValue(), "value")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
