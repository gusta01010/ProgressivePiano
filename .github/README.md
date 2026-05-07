![](https://files.catbox.moe/14ixsq.png)

<p align="center">
</a>
</p>

***

Progressive Piano provides a modern way of playing virtual-piano based sheets on your computer keyboard, offering support for `.txt` sheets.

## What is Progressive Piano?

Progressive Piano (or PPiano for short) is an application designed for learning and entertainment, now with an advanced music theory engine and human-like playback. It features a clean, dark-mode user interface that allows you to play virtual piano sheets using your keyboard.

## Key Features

*   **Advanced Music Theory Engine:**
    *   **Dynamic Key Inference:** Actively analyzes musical phrases to infer the most likely musical key.
    *   **Auto-Chord Generation:** Automatically generates appropriate chords to accompany a melody.
    *   **Auto-Bass Generation:** Provides "Smart Octave" and "Force to Low Range" modes for automatic bass lines.
*   **Human-like Playback ("Imperfect Mode"):**
    *   Simulates natural human playing with randomized delays and two distinct imperfection algorithms ("New" and "Old").
    *   Adjustable parameters for fine-tuning the realism.
*   **Enhanced Playback & Dynamics:**
    *   **Smart Release:** Automatically releases higher-pitched notes for cleaner chord transitions.
    *   **Grouped Note Playback:** Play complex passages and arpeggios defined within brackets (e.g., `[abcd]`) using dedicated hotkeys.
*   **Improved User Interface:**
    *   **Real-time Note Highlighting:** The currently playing note is highlighted in the sheet display.
    *   **Interactive Playback Pointer:** Click any character in the sheet to jump to that position.
    *   **Built-in File Browser:** Quickly browse and load `.txt` sheets.
*   **`.txt` Sheet Support:** Loads `.txt` sheets from the application's directory or a dedicated `Sheets` subfolder.
*   **Window Pinning:** Keeps the application window on top for easy sheet reading.
*   **137 Sheets!**

## Installation and Usage

1.  **Download:** Download the latest release from the [Releases](https://github.com/gusta01010/ProgressivePiano/releases) section of this repository (currently old version available).
2.  **Extract:** Extract the downloaded archive to a folder of your choice.
3.  **Run:** Run `PPiano.exe`.
4.  **Sheets:** Place `.txt` sheet files in the same directory as `PPiano.exe` or in a subfolder named `Sheets`.

## Branches

Progressive Piano offers two branches to cater to different user needs:

*   **`main` (or `singlekey`):** The stable, classic branch. Provides a reliable and polished experience for single-note playback.
*   **`multikey`:** The development branch, featuring the latest v4.0.0+ enhancements. This branch enables chords, simultaneous notes, and all advanced music theory features. Recommended for users who want to try the latest experimental features.

## Commands

### Multikey Branch (`multikey` - v4.0.0)

| Hotkey                      | Action                                                                                             |
| :-------------------------- | :------------------------------------------------------------------------------------------------- |
| `F1`, `F2`, `F3`, `F4`      | Controls playback of note groups (e.g., `[aceg]`), playing individual notes or the whole group.      |
| `F5`                        | Plays Magic Harpejo                                                                                |
| `Numpad *`, `+`, `-`        | Produces a note and progresses to the next note in the sheet.                                      |
| `End`                       | Selects a random sheet from the application's directory or the `Sheets` folder.                      |
| `Pause`                     | Toggles "Smart Release" mode for automatic note release.                                           |
| `Page Up`                   | Toggles "Auto Bass" mode.                                                                          |
| `Page Dn`                   | Toggles "Harmony" mode.                                                                            |
| `del` `,` (comma)           | Returns to the beginning of the sheet.                                                             |

### Singlekey Branch (`main` or `singlekey`)

| Hotkey        | Action                                                                        |
| :------------ | :---------------------------------------------------------------------------- |
| `-`           | Produces a note (can be held) and progresses to the next note.               |
| `del` `,` (comma)   | Returns to the beginning of the sheet.                                       |

## Contributing

Contributions are very welcome! If you'd like to contribute, please follow these steps:

1.  Fork the repository.
2.  Create a new branch for your feature or bug fix.
3.  Make your changes and commit them.
4.  Submit a pull request to the `singlekey` or `multikey` branch.

## Questions or Suggestions?

Feel free to open an issue on GitHub or send me a direct message on Discord:

*   Discord: sonic\_8783

## Screenshots

*Note: Screenshots are from an older version.*
![](https://files.catbox.moe/99rma3.png)
![](https://files.catbox.moe/fxlove.png)

## License

This project is licensed under the [MIT License](../LICENSE) - see the `LICENSE` file for details.
