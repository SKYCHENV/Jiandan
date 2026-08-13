# Jiandan

[简体中文](README.md) | [English](README_EN.md)

<img src="assets/brand/jiandan.png" alt="Jiandan" width="160">

**Copy images straight into Jianying.** Copy or capture an image, press `Ctrl+V` on Jianying's Media page, and Jiandan places it at the playhead on a track above the existing visual tracks.

## Why Jiandan Exists

Jianying does not let you paste a screenshot directly into its media library.

To use a screenshot, you would normally have to save an image from the web, or paste the screenshot into a chat, save it locally, find the file, and finally drag it into Jianying. The image is already on your clipboard, yet the workflow still sends you through several unnecessary steps.

That is why Jiandan exists. Take a screenshot or copy an image, return to Jianying, and press `Ctrl+V`. The image appears in the media library and on the timeline. No temporary chat message, no manual save, and no file dragging.

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer
- Jianying Pro

## Launch

Double-click `run.bat`.

On the first launch, the script creates a local `.venv`, installs the required packages, and opens the status window. Later launches start immediately. If Jiandan is already running, launching it again brings back the existing window instead of starting another service.

## Usage

1. Start Jiandan and make sure its status is enabled.
2. Open a Jianying project and stay on the Media page.
3. Capture or copy an image.
4. Return to Jianying and press `Ctrl+V`.
5. The image is placed at the playhead on a visual track above the existing tracks.

[Watch the real Jianying demo](demo/jiandan-demo.mp4)

Closing the status window sends Jiandan to the system tray. To stop it completely, right-click the tray icon and choose Exit.

## Project Layout

```text
jy_live_paste/      Application source
assets/brand/       Transparent brand assets
tests/              Automated tests
run.bat             Windows launcher
requirements.txt    Runtime dependencies
```

Imported images are stored under `a/<random-id>/i.png`. Jianying projects may reference these files, so do not delete them while you still need the related projects. Runtime diagnostics are written to `import-debug.log`.

## Development and Tests

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The automated suite covers clipboard safety, Jianying foreground detection, the import contract, window routing, and visual detection logic.

## How It Works

Jiandan conditionally registers `Ctrl+V`. It intercepts the shortcut only when Jianying is in the foreground and the clipboard contains an image. The image is saved to an isolated short path and passed to Jianying's native import flow. The system file picker is made invisible and non-activating as it opens, then receives only the exact path of the current image. Jiandan then invokes the imported media tile's native Add to Track command, allowing Jianying itself to place it at the playhead above existing visual tracks. Text clipboard content and paste operations in other applications keep their normal system behavior.
