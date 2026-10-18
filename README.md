<p align="center">
  <img src="/Assets/Images/logo.ico" width="80" alt="VFERDZ — Anime Expeditions logo">
</p>

<h1 align="center">VFERDZ | VFERDZ Converter</h1>

<p align="center">
  VFERDZ Converter is a local Windows app built to bring <strong>many conversion tools together in one place</strong>, with tools for formats such as documents, images, audio, and video. The app runs in your browser, with processing and downloads handled on your computer.
</p>

## Table of contents

- [Converter list](#converter-list)
  - [Current converters](#current-converters)
- [Requirements](#requirements)
- [Download and run](#download-and-run)
- [Features](#features)
- [Check for and install updates](#check-for-and-install-updates)
- [Development](#development)
- [Releases](#releases)

## Converter list (Current)

- [x] YouTube to MP3
- [x] YouTube to MP4

## Requirements

- 64-bit Windows 10 or newer
- An internet connection to download the project/release and access YouTube

## Download and run

1. Download `vferdz-converter-v<version>.zip` from the latest stable [GitHub release](https://github.com/iamvferdz/vferdz-converter/releases).
2. Extract the ZIP. It creates a `VFERDZ-CONVERTER` folder with `VFERDZ Converter.exe`, `VERSION`, and one `_internal` folder containing the app resources and runtime files.
3. Keep `VFERDZ Converter.exe`, `VERSION`, and `_internal` together in the `VFERDZ-CONVERTER` folder. Do not move or rename files inside `_internal`.
4. Double-click `VFERDZ Converter.exe`. The app opens in your browser and stays available from its notification-area icon.
5. Right-click the tray icon and choose **Exit** to stop the app.

The release bundle includes the Python runtime, app dependencies, Deno, and FFmpeg. Python, Deno, and FFmpeg do not need to be installed separately; the app does not download or install runtimes on the computer. The backend runs without a command-prompt window. Each converter page shows its recent conversion activity. App diagnostic logs are saved to `%LOCALAPPDATA%\VFERDZ Converter\app.log`.

## Features

### Converters

- **YouTube to MP3:** Convert a single YouTube music link or a playlist. Results show the track title, thumbnail when available, and MP3 file size; single-track downloads have an always-visible **Download MP3** button.
- **Video to MP4:** Convert a single video and choose from the available MP4 resolutions, or convert a playlist using the best available MP4 format for each video. A single-video conversion provides a download chip for each available resolution. The app does not re-encode local video files.
- Both converters have **Single** and **Playlist** modes. Single mode rejects playlist links, while Playlist mode requires one. Switching modes preserves current downloads without reloading the page.
- Playlist items are processed in batches of 10. Each successful item becomes available as soon as it is ready while the next batch continues. Unavailable or failed items are skipped, and their errors are listed when processing finishes.
- Stop an active conversion with the stop button. Refreshing or closing the page also requests that it stop. Progress and user-friendly errors are shown in the page, while detailed diagnostics remain available locally.

### Playlist downloads

- Download items individually, ZIP a single batch with **Download batch**, or ZIP all items ready so far with **All**.
- Display playlist results as a compact numbered list or a grid of up to five columns. The selected layout is remembered in the browser. Playlist batches start expanded and can be collapsed; in Grid view, hover or focus a track to reveal its download button.
- Playlist ZIPs use the playlist title in the filename, such as `vferdzconverter-My Playlist.zip` or `vferdzconverter-My Playlist-batch-1.zip`.
- MP3 files are saved in your user `Downloads\YouTube to MP3` folder; MP4 files are saved in `Downloads\YouTube to MP4`. Download links are tied to the current app session, so keep the app running while downloading.
- On desktop, the downloads list scrolls inside its panel so long playlists do not make the whole page scroll.

### Interface and activity

- The app opens its local web interface in your browser. Home links to the MP3 and MP4 converters; the Updates page and light/dark theme toggle are available from the header. Your theme choice is remembered in the browser.
- Each converter shows recent backend activity: one entry by default, or up to 60 entries with **Show more**. Detailed diagnostic logs are saved to `%LOCALAPPDATA%\VFERDZ Converter\app.log`.
- The app shows the installed version in the footer. Home also lists planned tools, such as PDF conversion. After a conversion finishes or fails, **Convert Again** lets you retry the current link.

The project dependencies include yt-dlp's JavaScript challenge components required for YouTube extraction.

## Check for and install updates

The app checks for a newer stable release when it opens and shows an update notice if one is available. Select **Download and install** to download the official release ZIP, verify its SHA-256 digest and contents, then replace the app bundle and restart automatically. The updater checks that the new version is ready before removing the previous bundle; if startup fails, it attempts to restore the previous bundle. The app does not update without your confirmation. You can also open **Updates** or select **Check for updates** to view release notes. The Updates page lists only releases published on GitHub; long release notes are collapsed by default and can be expanded with **Show more**.

To install an update:

1. Select **Download and install** in the app's update notice or on the Updates page.
2. The app closes, replaces the complete app folder, and starts the updated version.

Automatic updates replace the complete `VFERDZ-CONVERTER` folder, so keep its name as-is and keep the folder and its parent writable. Use it only for the app; do not store personal files inside it, because successful updates replace the entire folder. If it is in a protected location, move the complete app folder to a user-owned location such as one under `%LOCALAPPDATA%` and try again. Update files are downloaded only from the project's official GitHub releases and checked against GitHub's published SHA-256 digest before installation. The updater stages and validates the whole bundle, checks that the updated app starts, and keeps the prior folder available for rollback until startup succeeds.

Users upgrading from a single-file release must install the first folder-based release manually because older app versions can update only a single executable. From the old app, use **Download ZIP manually** on the Updates page or download the ZIP from GitHub; do not use its **Download and install** button. Extract the complete release ZIP; it creates a separate `VFERDZ-CONVERTER` folder. Start `VFERDZ Converter.exe` from that folder. Subsequent folder-based versions can be installed by the in-app updater.

Converted MP3 files are stored separately in your user `Downloads\YouTube to MP3` folder. The update process does not need to replace or delete that downloads folder.

The browser tab icon, tray icon, and header logo are loaded from `_internal\Assets\Images\logo.ico` and `_internal\Assets\Images\logo.png` inside the app folder.

Only download content you have permission to use.

## Development

To run from source, clone or download the project from GitHub and install Python 3.10 or newer. From the project folder, install the dependencies and start the development app:

```bat
python -m pip install -r requirements.txt
run-dev.bat
```

`run-dev.bat` is for development only. It starts `local_web_app.py` from the project folder; the browser opens automatically, and the console stays available while the app runs. Press **Ctrl+C** to stop it. Source mode adds the tray icon and uses FFmpeg from `PATH` when available. Release builds are still produced automatically by the GitHub Actions workflow described below.

## Releases

Version tags beginning with `v` (for example, `v1.0.0`) trigger a GitHub
Actions workflow that builds the Windows app bundle, places the executable
and all required runtime files and folders in a versioned ZIP, and attaches
the ZIP to the matching GitHub release.