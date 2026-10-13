# YouTube to MP3

A small local web app. The interface runs in your browser, while video and MP3 downloads and conversions happen on your computer.

## Requirements

- 64-bit Windows 10 or newer
- An internet connection to download the project/release and access YouTube

## Download and run

1. Download `vferdz-converter-v<version>.zip` from the latest stable [GitHub release](https://github.com/iamvferdz/vferdz-converter/releases).
2. Extract the ZIP. It contains only `VFERDZ Converter.exe`.
3. Double-click the executable. The app opens in your browser and stays available from its notification-area icon.
4. Right-click the tray icon and choose **Exit** to stop the app.

The standalone executable bundles Python, the app dependencies, Deno, and FFmpeg. Python, Deno, and FFmpeg do not need to be installed separately; the app does not download or install runtimes on the computer. The backend runs without a command-prompt window. Each converter page shows its recent conversion activity. App diagnostic logs are saved to `%LOCALAPPDATA%\VFERDZ Converter\app.log`.

To run from source instead, clone or download the project from GitHub, install Python 3.10 or newer, run `python -m pip install -r requirements.txt`, then run `python local_web_app.py`. This source mode also adds the tray icon and uses FFmpeg from `PATH` when available.

The app opens in your browser. From Home, choose **YouTube to MP3** to convert music or playlists, or **Video to MP4** to download a single YouTube video in MP4 format. The project dependencies include yt-dlp's JavaScript challenge components required for YouTube extraction. After conversion, the MP4 downloads panel shows a download chip for each available MP4 resolution. The app prepares these qualities one at a time and can combine separate video and audio streams when needed. MP4 files are saved in your user `Downloads\YouTube to MP4` folder. It does not accept playlist links or re-encode local video files.

## Check for and install updates

The app checks for a newer stable release when it opens and shows an update notice if one is available. Select **Download and install** to download the official release ZIP, verify its SHA-256 digest and contents, then replace the executable and restart the app automatically. The app does not update without your confirmation. You can also open **Updates** or select **Check for updates** to view release notes.

To install an update:

1. Select **Download and install** in the app's update notice or on the Updates page.
2. The app closes, replaces the executable, and starts the updated version.

Automatic updates require the standalone app to be in a folder you can write to. If it is in a protected folder, move it to a user-owned location such as `%LOCALAPPDATA%` and try again. Update files are downloaded only from the project's official GitHub releases and checked against GitHub's published SHA-256 digest before installation. If automatic installation is unavailable, download and extract the ZIP manually, then replace the executable after choosing **Exit** from the tray icon.

Converted MP3 files are stored separately in your user `Downloads\YouTube to MP3` folder. The update process does not need to replace or delete that downloads folder.

Frontend files are organized into `Pages` for the Home, YouTube to MP3, Video to MP4, and Updates pages, and `Assets\CSS` / `Assets\JS` for shared styling and behavior. Home lists available and planned tools. Choose a converter to open its separate page. Home and Updates are available from the header; the footer shows the VFERDZ Converter logo/name and installed version, with links to available tools underneath.

Choose **Single** or **Playlist** before pasting a link. Single mode rejects playlist links; Playlist mode requires a playlist link. Switching between these tabs preserves the current downloads and does not restart the page. During conversion, keep the page open and wait for processing to finish; use the stop button beside the convert button to cancel. Refreshing or closing the page also requests that any active conversion stop. Download errors are shown in user-friendly language while the local status API retains the underlying technical error. Playlist downloads can be displayed as a compact numbered list or a grid of up to five columns; the selected view is remembered in the browser. In Grid view, hover or focus a track to show its download button. Each playlist batch has a collapse toggle and starts expanded. Use the **All** button to ZIP all tracks ready so far, or **Download batch** to ZIP just that batch. ZIPs are named using the playlist title, for example `vferdzconverter-My Playlist.zip` and `vferdzconverter-My Playlist-batch-1.zip`. Download links are tied to the current app session; keep the app running and start the conversion again if you restart it. On desktop, the downloads list scrolls inside its panel so long playlists do not make the whole page scroll. Playlist mode automatically converts tracks in batches of 10. Each track becomes available for download as soon as it is converted, while the next batch continues in the background. If a track is private, restricted, unavailable, or otherwise fails to download or convert, the app skips it and continues; skipped tracks and their errors are listed when processing is complete. When the playlist finishes, the ZIP contains every successfully converted track. Converted files are saved in `Downloads\YouTube to MP3` in your user folder.

The Updates page lists only releases published on GitHub; it does not show local changelog entries as releases. Long release notes are collapsed by default and can be expanded with **Show more**.

Each converter's input panel shows the latest backend activity on one line by default. Select **Show more** to view up to 60 recent activity entries, or **Show less** to return to the latest update. Detailed diagnostic information remains in the local app log.

After conversion, the MP3 page shows the track title, thumbnail when available, and MP3 file size. Single-music downloads have an always-visible **Download MP3** button below the track details. The MP4 page displays the video title and thumbnail when available, with a download chip for each available resolution. The convert button changes to **Convert Again** after a conversion finishes or fails, so you can retry the current link without an extra button.

The browser tab icon and header logo are loaded from `Assets\Images\logo.ico` and `Assets\Images\logo.png`.

Only download content you have permission to use.

## Releases

Version tags beginning with `v` (for example, `v1.0.0`) trigger a GitHub
Actions workflow that builds the standalone Windows executable, places only
that executable inside a versioned ZIP, and attaches the ZIP to the matching
GitHub release.