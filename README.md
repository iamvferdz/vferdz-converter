# YouTube to MP3

A small local web app. The interface runs in your browser, while downloading and MP3 conversion happen on your computer.

## Requirements

- Python 3.10 or newer
- FFmpeg installed and available on `PATH`

## Run

On Windows, double-click `Start YouTube to MP3.bat`. Keep its console window open while using the app; press `Ctrl+C` there to stop it.

The first time, install the Python dependency from this folder:

```powershell
python -m pip install -r requirements.txt
```

You can also start the app manually:

```powershell
python local_web_app.py
```

The app opens in your browser. Choose **Single video** or **Playlist** before pasting a link. Playlist downloads can be displayed as a compact numbered list or a grid of up to five columns; the selected view is remembered in the browser. In Grid view, hover or focus a track to show its download button. Each playlist batch has a collapse toggle and starts expanded. Use the **All** button to ZIP all tracks ready so far, or **Download batch** to ZIP just that batch. ZIPs are named using the playlist title, for example `vferdzconverter-My Playlist.zip` and `vferdzconverter-My Playlist-batch-1.zip`. Download links are tied to the current app session; keep the app running and start the conversion again if you restart it. On desktop, the downloads list scrolls inside its panel so long playlists do not make the whole page scroll. Playlist mode automatically converts tracks in batches of 10. Each track becomes available for download as soon as it is converted, while the next batch continues in the background. If a track is private, restricted, unavailable, or otherwise fails to download or convert, the app skips it and continues; skipped tracks and their errors are listed when processing is complete. When the playlist finishes, the ZIP contains every successfully converted track. Keep the terminal window open while using the app; press `Ctrl+C` there to stop it. Converted files are saved in `Downloads\YouTube to MP3` in your user folder.

After conversion, the page shows the track title, thumbnail when available, and MP3 file size.

The browser tab icon and header logo are loaded from `Assets\Images\logo.ico` and `Assets\Images\logo.png`.

Only download content you have permission to use.