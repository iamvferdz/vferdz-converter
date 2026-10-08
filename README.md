# YouTube to MP3

A small local web app. The interface runs in your browser, while downloading and MP3 conversion happen on your computer.

## Requirements

- Windows 10 or newer
- Python 3.10 or newer, added to `PATH`
- FFmpeg installed and available on `PATH`
- An internet connection to download the project/release and access YouTube

## Install and run

1. Download and extract the project ZIP from the GitHub Releases page.
2. Install FFmpeg and make sure `ffmpeg` works in a new terminal (`ffmpeg -version`).
3. Open PowerShell in the extracted project folder. This is the folder containing `local_web_app.py` and `requirements.txt`.
4. Install the Python dependency:

   ```powershell
   python -m pip install -r requirements.txt
   ```

5. Double-click `Start YouTube to MP3.bat`, or run `python local_web_app.py` from PowerShell.
6. Keep the console window open while using the app. Press `Ctrl+C` in it to stop the app.

The app opens in your browser. The `.bat` launcher uses a console window so startup errors and logs are visible.

## Check for and install updates

Updates are checked when you open the Updates page and whenever you select **Check for updates**. There is no background or interval check. The page reports whether a newer stable GitHub release is available and lists ZIP downloads for published releases. The app does not install or replace files automatically.

To update manually:

1. Open **Updates** in the app and select **Check for updates**, or visit the [GitHub Releases page](https://github.com/iamvferdz/vferdz-converter/releases).
2. If a newer stable release is available, download its project ZIP.
3. Stop the app by pressing `Ctrl+C` in its console window.
4. Make a backup of the current project folder.
5. Extract the ZIP. It contains a versioned top-level folder; copy the files and folders inside that folder into the existing project folder and allow files to be replaced. Do not extract it into a new location if you want to keep using the existing launcher shortcut.
6. If `requirements.txt` changed, run `python -m pip install --upgrade -r requirements.txt` from the updated project folder.
7. Start the app again with `Start YouTube to MP3.bat`.

Converted MP3 files are stored separately in your user `Downloads\YouTube to MP3` folder. The update process does not need to replace or delete that downloads folder.

Frontend files are organized into `Pages` for the Home, YouTube to MP3, and Updates pages, and `Assets\CSS` / `Assets\JS` for shared styling and behavior. Home lists available and planned tools. Choose **YouTube to MP3** to open its separate conversion page. Home and Updates are available from the header; the footer shows the VFERDZ Converter logo/name and installed version, with links to available tools underneath.

Choose **Single** or **Playlist** before pasting a link. Single mode rejects playlist links; Playlist mode requires a playlist link. Switching between these tabs preserves the current downloads and does not restart the page. During conversion, keep the page open and wait for processing to finish; use the stop button beside the convert button to cancel. Refreshing or closing the page also requests that any active conversion stop. Download errors are shown in user-friendly language while the local status API retains the underlying technical error. Playlist downloads can be displayed as a compact numbered list or a grid of up to five columns; the selected view is remembered in the browser. In Grid view, hover or focus a track to show its download button. Each playlist batch has a collapse toggle and starts expanded. Use the **All** button to ZIP all tracks ready so far, or **Download batch** to ZIP just that batch. ZIPs are named using the playlist title, for example `vferdzconverter-My Playlist.zip` and `vferdzconverter-My Playlist-batch-1.zip`. Download links are tied to the current app session; keep the app running and start the conversion again if you restart it. On desktop, the downloads list scrolls inside its panel so long playlists do not make the whole page scroll. Playlist mode automatically converts tracks in batches of 10. Each track becomes available for download as soon as it is converted, while the next batch continues in the background. If a track is private, restricted, unavailable, or otherwise fails to download or convert, the app skips it and continues; skipped tracks and their errors are listed when processing is complete. When the playlist finishes, the ZIP contains every successfully converted track. Keep the terminal window open while using the app; press `Ctrl+C` there to stop it. Converted files are saved in `Downloads\YouTube to MP3` in your user folder.

The Updates page lists only releases published on GitHub; it does not show local changelog entries as releases. Long release notes are collapsed by default and can be expanded with **Show more**.

After conversion, the page shows the track title, thumbnail when available, and MP3 file size. Single-music downloads have an always-visible **Download MP3** button below the track details. The convert button changes to **Convert Again** after a conversion finishes or fails, so you can retry the current link without an extra button.

The browser tab icon and header logo are loaded from `Assets\Images\logo.ico` and `Assets\Images\logo.png`.

Only download content you have permission to use.

## Releases

Version tags beginning with `v` (for example, `v1.0.0`) trigger a GitHub
Actions workflow that creates a ZIP of the tracked project files and attaches
it to the matching GitHub release.