"""Contains test cases for the widgets.py module."""

import sys
import unittest
from pathlib import Path
from unittest import mock

import wx

PATH = Path(__file__).parent
sys.path.insert(0, str(PATH.parent))

from youtube_dl_gui.widgets import ListBoxWithHeaders


class TestListBoxWithHeaders(unittest.TestCase):
    """Test cases for the ListBoxWithHeaders widget."""

    def setUp(self):
        self.app = wx.App()

        self.frame = wx.Frame(None)
        self.listbox = ListBoxWithHeaders(self.frame)

        self.listbox.add_header("Header")
        self.listbox.add_items([f"item{i}" for i in range(10)])

    def tearDown(self):
        self.frame.Destroy()
        del self.app

    def test_find_string_header_found(self):
        self.assertEqual(
            self.listbox.FindString(
                "Header",
            ),
            0,
        )

    def test_find_string_header_not_found(self):
        self.assertEqual(
            self.listbox.FindString(
                "Header2",
            ),
            wx.NOT_FOUND,
        )

    def test_find_string_item_found(self):
        self.assertEqual(
            self.listbox.FindString(
                "item1",
            ),
            2,
        )

    def test_find_string_item_not_found(self):
        self.assertEqual(
            self.listbox.FindString(
                "item",
            ),
            wx.NOT_FOUND,
        )

    def test_get_string_header(self):
        self.assertEqual(self.listbox.GetString(0), "Header")

    def test_get_string_item(self):
        self.assertEqual(self.listbox.GetString(10), "item9")

    def test_get_string_item_not_found(self):
        self.assertEqual(self.listbox.GetString(11), "")

    def test_get_string_item_negative_index(self):
        self.assertEqual(self.listbox.GetString(-1), "")

    def test_insert_items(self):
        self.listbox.SetSelection(1)

        self.listbox.InsertItems(["new_item1", "new_item2"], 1)
        self.assertEqual(self.listbox.GetString(1), "new_item1")
        self.assertEqual(self.listbox.GetString(2), "new_item2")
        self.assertEqual(self.listbox.GetString(3), "item0")

        self.assertTrue(self.listbox.IsSelected(3))  # Old selection + 2

    def test_set_selection_header(self):
        self.listbox.SetSelection(0)
        self.assertFalse(self.listbox.IsSelected(0))

    def test_set_selection_item_valid_index(self):
        self.listbox.SetSelection(1)
        self.assertEqual(self.listbox.GetSelection(), 1)

    def test_set_selection_item_invalid_index(self):
        self.listbox.SetSelection(1)
        self.assertEqual(self.listbox.GetSelection(), 1)

        self.listbox.SetSelection(wx.NOT_FOUND)
        self.assertEqual(self.listbox.GetSelection(), wx.NOT_FOUND)

    def test_set_string_item(self):
        self.listbox.SetString(1, "item_mod0")
        self.assertEqual(self.listbox.GetString(1), "item_mod0")

    def test_set_string_header(self):
        self.listbox.SetString(0, "New header")
        self.assertEqual(self.listbox.GetString(0), "New header")

        # Make sure that the header is not selectable
        self.listbox.SetSelection(0)
        self.assertFalse(self.listbox.IsSelected(0))

    def test_set_string_selection_header(self):
        self.assertFalse(self.listbox.SetStringSelection("Header"))
        self.assertFalse(self.listbox.IsSelected(0))

    def test_set_string_selection_item(self):
        self.assertTrue(self.listbox.SetStringSelection("item1"))
        self.assertTrue(self.listbox.IsSelected(2))

    def test_get_string_selection(self):
        self.listbox.SetSelection(1)
        self.assertEqual(self.listbox.GetStringSelection(), "item0")

    def test_get_string_selection_empty(self):
        self.assertEqual(self.listbox.GetStringSelection(), "")

    # wx.ItemContainer methods

    def test_append(self):
        self.listbox.Append("item666")
        self.assertEqual(self.listbox.GetString(11), "item666")

    def test_append_items(self):
        self.listbox.AppendItems(["new_item1", "new_item2"])
        self.assertEqual(self.listbox.GetString(11), "new_item1")
        self.assertEqual(self.listbox.GetString(12), "new_item2")

    def test_clear(self):
        self.listbox.Clear()
        self.assertEqual(self.listbox.GetItems(), [])

    def test_delete(self):
        self.listbox.Delete(0)
        self.assertEqual(self.listbox.GetString(0), "item0")

        # Test item selection
        self.listbox.SetSelection(0)
        self.assertTrue(self.listbox.IsSelected(0))

    # Test object extra methods

    def test_add_header(self):
        self.listbox.add_header("Header2")
        self.listbox.SetSelection(11)
        self.assertFalse(self.listbox.IsSelected(11))

    @mock.patch("wx.ListBox.Append")
    def test_add_item_with_prefix(self, mock_append):
        self.listbox.add_item("new_item")
        mock_append.assert_called_once_with(
            f"{ListBoxWithHeaders.TEXT_PREFIX}new_item", None
        )

    @mock.patch("wx.ListBox.Append")
    def test_add_item_without_prefix(self, mock_append):
        self.listbox.add_item("new_item", with_prefix=False)
        mock_append.assert_called_once_with("new_item", None)

    @mock.patch("wx.ListBox.AppendItems")
    def test_add_items_with_prefix(self, mock_append):
        self.listbox.AppendItems(["new_item1", "new_item2"])
        mock_append.assert_called_once_with(
            [
                f"{ListBoxWithHeaders.TEXT_PREFIX}new_item1",
                f"{ListBoxWithHeaders.TEXT_PREFIX}new_item2",
            ]
        )

    @mock.patch("wx.ListBox.AppendItems")
    def test_add_items_without_prefix(self, mock_append):
        self.listbox.AppendItems(["new_item1", "new_item2"], with_prefix=False)
        mock_append.assert_called_once_with(["new_item1", "new_item2"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
