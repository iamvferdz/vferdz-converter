import json
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.ffmpeg import FFmpegExtractAudioPP
from yt_dlp.utils import DownloadError


DOWNLOAD_FOLDER = Path.home() / "Downloads" / "YouTube to MP3"
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
PLAYLIST_BATCH_SIZE = 10


def validate_youtube_mode_url(url, mode):
    parsed_url = urlsplit(url)
    hostname = (parsed_url.hostname or "").lower()
    if (
        parsed_url.scheme not in {"http", "https"}
        or hostname not in ALLOWED_HOSTS
        or parsed_url.username
        or parsed_url.password
    ):
        raise ValueError("Enter a valid YouTube video URL.")

    has_playlist_id = bool(parse_qs(parsed_url.query).get("list", [""])[0].strip())
    is_playlist_url = hostname != "youtu.be" and (
        parsed_url.path.rstrip("/") == "/playlist" or has_playlist_id
    )
    if mode == "playlist" and not (is_playlist_url and has_playlist_id):
        raise ValueError("Playlist mode only accepts a YouTube playlist link.")
    if mode == "single" and is_playlist_url:
        raise ValueError(
            "Single mode accepts a music/video link, not a playlist link. "
            "Choose Playlist mode instead."
        )


class CancellableFFmpegExtractAudioPP(FFmpegExtractAudioPP):
    def __init__(self, downloader, cancel_event):
        super().__init__(
            downloader, preferredcodec="mp3", preferredquality="192"
        )
        self.cancel_event = cancel_event

    def run_ffmpeg(self, path, out_path, codec, more_opts):
        options = ["-vn"]
        if codec is not None:
            options.extend(["-acodec", codec])
        options.extend(more_opts)
        self.check_version()
        oldest_mtime = Path(path).stat().st_mtime
        command = [self.executable, "-y"]
        if self.basename == "ffmpeg":
            command.extend(["-loglevel", "repeat+info"])

        for kind, files in (("i", [(path, [])]), ("o", [(out_path, options)])):
            for index, (filename, file_options) in enumerate(files, start=1):
                file_options = list(file_options)
                config_keys = [f"_{kind}{index}", f"_{kind}"]
                if kind == "o":
                    file_options.extend(["-movflags", "+faststart"])
                    if index == 1:
                        config_keys.append("")
                file_options.extend(
                    self._configuration_args(self.basename, config_keys)
                )
                if kind == "i":
                    file_options.append("-i")
                command.extend(file_options)
                command.append(self._ffmpeg_filename_argument(filename))

        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        while True:
            try:
                _, stderr = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if not self.cancel_event.is_set():
                    continue
                process.terminate()
                try:
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                raise DownloadError(
                    "Conversion was stopped."
                )

        if self.cancel_event.is_set():
            raise DownloadError("Conversion was stopped.")
        if process.returncode:
            message = stderr.strip().splitlines()
            raise RuntimeError(message[-1] if message else "FFmpeg conversion failed.")
        self.try_utime(out_path, oldest_mtime, oldest_mtime)


class DownloadManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {
            "status": "idle",
            "progress": 0,
            "message": "Paste a YouTube link to get started.",
            "mode": "single",
            "items": [],
            "skipped_tracks": [],
            "playlist_title": "",
            "playlist_thumbnail": "",
            "playlist_creator": "",
            "playlist_total": 0,
            "current_batch": 0,
            "batch_count": 0,
            "error": "",
            "token": "",
            "request_id": "",
        }
        self.cancel_event = threading.Event()

    def snapshot(self):
        with self.lock:
            state = dict(self.state)
            state["items"] = [dict(item) for item in self.state["items"]]
            return state

    def start(self, url, mode, request_id=None):
        with self.lock:
            if self.state["status"] in {
                "preparing", "downloading", "converting", "stopping"
            }:
                return False
            token = secrets.token_urlsafe(24)
            request_id = request_id or secrets.token_urlsafe(24)
            cancel_event = threading.Event()
            self.cancel_event = cancel_event
            self.state = {
                "status": "preparing" if mode == "playlist" else "downloading",
                "progress": 0,
                "message": (
                    "Preparing playlist..."
                    if mode == "playlist"
                    else "Starting download..."
                ),
                "mode": mode,
                "items": [],
                "skipped_tracks": [],
                "playlist_title": "",
                "playlist_thumbnail": "",
                "playlist_creator": "",
                "playlist_total": 0,
                "current_batch": 0,
                "batch_count": 0,
                "error": "",
                "token": token,
                "request_id": request_id,
            }
        threading.Thread(
            target=self._download, args=(url, mode, cancel_event), daemon=True
        ).start()
        return True

    def stop(self, request_id):
        with self.lock:
            if (
                not request_id
                or not self.state["request_id"]
                or not secrets.compare_digest(request_id, self.state["request_id"])
                or self.state["status"] not in {
                    "preparing", "downloading", "converting"
                }
            ):
                return False
            self.cancel_event.set()
            self.state.update(
                status="stopping",
                message="Stopping conversion...",
            )
            return True

    @staticmethod
    def _check_cancelled(cancel_event):
        if cancel_event.is_set():
            raise DownloadError("Conversion was stopped.")

    def _download(self, url, mode, cancel_event):
        if mode == "playlist":
            self._download_playlist(url, cancel_event)
            return

        def on_progress(data):
            self._check_cancelled(cancel_event)
            if data.get("status") != "downloading":
                return
            downloaded = data.get("downloaded_bytes", 0)
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            track_progress = min(99, int(downloaded * 100 / total)) if total else 0
            index = data.get("playlist_index") or 1
            count = data.get("playlist_count")
            progress = (
                min(99, int(((index - 1) + track_progress / 100) * 100 / count))
                if mode == "playlist" and count
                else track_progress
            )
            with self.lock:
                self._check_cancelled(cancel_event)
                self.state["progress"] = progress
                if mode == "playlist" and count:
                    self.state["message"] = (
                        f"Downloading track {index} of {count}... "
                        f"{track_progress}%"
                    )
                elif mode == "playlist":
                    self.state["message"] = f"Downloading track {index}..."
                else:
                    self.state["message"] = (
                        f"Downloading... {track_progress}%"
                        if total
                        else "Downloading..."
                    )

        def on_postprocessor(data):
            self._check_cancelled(cancel_event)
            if data.get("status") == "started":
                entry = data.get("info_dict") or {}
                index = entry.get("playlist_index")
                count = entry.get("playlist_count")
                with self.lock:
                    self._check_cancelled(cancel_event)
                    self.state["status"] = "converting"
                    if mode == "playlist" and index and count:
                        self.state["message"] = (
                            f"Converting track {index} of {count} to MP3..."
                        )
                    elif mode == "playlist":
                        self.state["message"] = "Converting playlist track to MP3..."
                    else:
                        self.state["message"] = "Converting to MP3..."

        options = {
            "format": "bestaudio/best",
            "outtmpl": str(DOWNLOAD_FOLDER / "%(title)s [%(id)s].%(ext)s"),
            "noplaylist": True,
            "windowsfilenames": True,
            "postprocessors": [],
            "progress_hooks": [on_progress],
            "postprocessor_hooks": [on_postprocessor],
        }
        try:
            DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
            with YoutubeDL(options) as ydl:
                ydl.add_post_processor(
                    CancellableFFmpegExtractAudioPP(ydl, cancel_event)
                )
                info = ydl.extract_info(url, download=True)
                self._check_cancelled(cancel_event)
                mp3_path = Path(ydl.prepare_filename(info)).with_suffix(".mp3")
            if not mp3_path.is_file():
                raise FileNotFoundError(
                    f"Conversion finished but the MP3 was not found: "
                    f"{info.get('title') or 'audio'}"
                )
            item = {
                "title": info.get("title") or "Audio",
                "thumbnail": self._safe_thumbnail(info.get("thumbnail") or ""),
                "file_size": mp3_path.stat().st_size,
                "path": mp3_path,
                "batch": 0,
            }
            with self.lock:
                self._check_cancelled(cancel_event)
                self.state.update(
                    status="done",
                    progress=100,
                    message="Your MP3 is ready.",
                    items=[item],
                )
        except Exception as error:
            with self.lock:
                if cancel_event.is_set():
                    self.state.update(
                        status="stopped",
                        message="Conversion was stopped.",
                    )
                else:
                    self.state.update(
                        status="error",
                        message="The download could not be completed.",
                        error=str(error),
                    )

    def _download_playlist(self, url, cancel_event):
        try:
            self._check_cancelled(cancel_event)
            DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
            with YoutubeDL(
                {
                    "extract_flat": "in_playlist",
                    "skip_download": True,
                    "noplaylist": False,
                }
            ) as ydl:
                playlist = ydl.extract_info(url, download=False)
                self._check_cancelled(cancel_event)
                entries = [
                    entry for entry in playlist.get("entries", []) if entry
                ] if playlist else []
            if not entries:
                raise ValueError("No videos were found in this playlist.")

            total = len(entries)
            batch_count = (total + PLAYLIST_BATCH_SIZE - 1) // PLAYLIST_BATCH_SIZE
            playlist_thumbnail = self._safe_thumbnail(
                (playlist.get("thumbnail") or "")
                or (
                    (playlist.get("thumbnails") or [{}])[-1].get("url")
                    if playlist.get("thumbnails")
                    else ""
                )
            )
            playlist_creator = (
                playlist.get("uploader")
                or playlist.get("channel")
                or playlist.get("creator")
                or playlist.get("uploader_id")
                or "Unknown creator"
            )
            with self.lock:
                self._check_cancelled(cancel_event)
                self.state.update(
                    status="downloading",
                    message=f"Playlist found: {total} tracks. Starting batch 1 of {batch_count}.",
                    playlist_title=(
                        playlist.get("title")
                        or playlist.get("playlist_title")
                        or "mp3youtubeplaylist"
                    ),
                    playlist_thumbnail=playlist_thumbnail,
                    playlist_creator=playlist_creator,
                    playlist_total=total,
                    batch_count=batch_count,
                    current_batch=1,
                )

            for batch_start in range(0, total, PLAYLIST_BATCH_SIZE):
                self._check_cancelled(cancel_event)
                batch_number = batch_start // PLAYLIST_BATCH_SIZE + 1
                batch_entries = entries[batch_start : batch_start + PLAYLIST_BATCH_SIZE]
                with self.lock:
                    self._check_cancelled(cancel_event)
                    self.state.update(
                        status="downloading",
                        current_batch=batch_number,
                        message=f"Downloading batch {batch_number} of {batch_count}...",
                    )

                for batch_offset, entry in enumerate(batch_entries):
                    self._check_cancelled(cancel_event)
                    playlist_index = batch_start + batch_offset + 1
                    title = (
                        entry.get("title") or f"Track {playlist_index}"
                        if isinstance(entry, dict)
                        else f"Track {playlist_index}"
                    )
                    with self.lock:
                        self._check_cancelled(cancel_event)
                        self.state.update(
                            status="downloading",
                            message=(
                                f"Batch {batch_number} of {batch_count}: "
                                f"downloading track {playlist_index} of {total}..."
                            ),
                        )

                    try:
                        video_url = self._playlist_video_url(entry)

                        def on_progress(data):
                            self._check_cancelled(cancel_event)
                            if data.get("status") != "downloading":
                                return
                            downloaded = data.get("downloaded_bytes", 0)
                            file_total = (
                                data.get("total_bytes")
                                or data.get("total_bytes_estimate")
                            )
                            track_progress = (
                                min(99, int(downloaded * 100 / file_total))
                                if file_total
                                else 0
                            )
                            progress = int(
                                ((playlist_index - 1) + track_progress / 100)
                                * 100
                                / total
                            )
                            with self.lock:
                                self.state.update(
                                    status="downloading",
                                    progress=progress,
                                    message=(
                                        f"Batch {batch_number} of {batch_count}: "
                                        f"downloading track {playlist_index} of {total} "
                                        f"({track_progress}%)."
                                    ),
                                )

                        def on_postprocessor(data):
                            self._check_cancelled(cancel_event)
                            if data.get("status") == "started":
                                with self.lock:
                                    self._check_cancelled(cancel_event)
                                    self.state.update(
                                        status="converting",
                                        message=(
                                            f"Batch {batch_number} of {batch_count}: "
                                            f"converting track {playlist_index} of "
                                            f"{total} to MP3..."
                                        ),
                                    )

                        options = {
                            "format": "bestaudio/best",
                            "outtmpl": str(
                                DOWNLOAD_FOLDER / "%(title)s [%(id)s].%(ext)s"
                            ),
                            "noplaylist": True,
                            "windowsfilenames": True,
                            "postprocessors": [],
                            "progress_hooks": [on_progress],
                            "postprocessor_hooks": [on_postprocessor],
                        }
                        with YoutubeDL(options) as ydl:
                            ydl.add_post_processor(
                                CancellableFFmpegExtractAudioPP(ydl, cancel_event)
                            )
                            info = ydl.extract_info(video_url, download=True)
                            self._check_cancelled(cancel_event)
                            if not info:
                                raise ValueError(
                                    f"Could not download playlist track "
                                    f"{playlist_index}: {title}"
                                )
                            mp3_path = Path(ydl.prepare_filename(info)).with_suffix(
                                ".mp3"
                            )
                        if not mp3_path.is_file():
                            raise FileNotFoundError(
                                f"Conversion finished but an MP3 was not found for "
                                f"track {playlist_index}: "
                                f"{info.get('title') or title}"
                            )
                        item = {
                            "title": info.get("title") or title,
                            "thumbnail": self._safe_thumbnail(
                                info.get("thumbnail") or entry.get("thumbnail") or ""
                            ),
                            "file_size": mp3_path.stat().st_size,
                            "path": mp3_path,
                            "batch": batch_number,
                        }
                        with self.lock:
                            self.state["items"].append(item)
                            self.state["progress"] = int(
                                playlist_index * 100 / total
                            )
                    except Exception as error:
                        if cancel_event.is_set():
                            raise
                        with self.lock:
                            self.state["skipped_tracks"].append(
                                {
                                    "index": playlist_index,
                                    "title": title,
                                    "error": str(error)[:300],
                                }
                            )
                            self.state.update(
                                status="downloading",
                                progress=int(playlist_index * 100 / total),
                                message=(
                                    f"Skipped track {playlist_index} of {total} "
                                    f"({title}); continuing with the playlist."
                                ),
                            )

            with self.lock:
                if cancel_event.is_set():
                    self.state.update(
                        status="stopped",
                        message="Conversion was stopped.",
                    )
                    return
                ready_count = len(self.state["items"])
                skipped_count = len(self.state["skipped_tracks"])
                completion_message = (
                    f"Playlist complete: {ready_count} of {total} tracks ready."
                )
                if skipped_count:
                    completion_message += (
                        f" Skipped {skipped_count} unavailable or failed "
                        f"{'track' if skipped_count == 1 else 'tracks'}."
                    )
                self.state.update(
                    status="done",
                    progress=100,
                    message=completion_message,
                )
        except Exception as error:
            with self.lock:
                if cancel_event.is_set():
                    self.state.update(
                        status="stopped",
                        message="Conversion was stopped.",
                    )
                else:
                    self.state.update(
                        status="error",
                        message=(
                            f"Playlist could not be processed. "
                            f"{len(self.state['items'])} tracks are ready and "
                            f"{len(self.state['skipped_tracks'])} tracks were skipped."
                            if self.state["mode"] == "playlist"
                            else "The download could not be completed."
                        ),
                        error=str(error),
                    )

    @staticmethod
    def _playlist_video_url(entry):
        video_url = entry.get("webpage_url") or entry.get("url") or ""
        parsed_url = urlsplit(video_url)
        hostname = (parsed_url.hostname or "").lower()
        if (
            parsed_url.scheme in {"http", "https"}
            and hostname in ALLOWED_HOSTS
        ):
            return video_url
        if parsed_url.scheme or parsed_url.netloc:
            raise ValueError(
                f"Playlist track URL is not a supported YouTube URL: "
                f"{entry.get('title') or 'unknown'}."
            )
        video_id = entry.get("id") or video_url
        extractor = (entry.get("ie_key") or "Youtube").lower()
        if not video_id or extractor not in {
            "youtube",
            "youtubevideo",
        }:
            raise ValueError(
                f"Could not determine a video URL for playlist track "
                f"{entry.get('title') or 'unknown'}."
            )
        return f"https://www.youtube.com/watch?v={quote(str(video_id), safe='')}"

    @staticmethod
    def _safe_thumbnail(thumbnail):
        try:
            parsed_thumbnail = urlsplit(thumbnail)
            thumbnail_host = (parsed_thumbnail.hostname or "").lower()
            if (
                parsed_thumbnail.scheme == "https"
                and (
                    thumbnail_host == "youtube.com"
                    or thumbnail_host.endswith(".youtube.com")
                    or thumbnail_host == "ytimg.com"
                    or thumbnail_host.endswith(".ytimg.com")
                )
            ):
                return thumbnail
        except ValueError:
            pass
        return ""


manager = DownloadManager()


class LocalAppHandler(BaseHTTPRequestHandler):
    @staticmethod
    def _playlist_zip_filename(title, batch=None):
        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", title).strip(" .-")
        safe_title = safe_title[:120].rstrip(" .-") or "mp3youtubeplaylist"
        suffix = f"-batch-{batch}" if batch is not None else ""
        return f"vferdzconverter-{safe_title}{suffix}.zip"

    def _expected_host(self):
        return f"127.0.0.1:{self.server.server_port}"

    def _is_local_request(self):
        return self.headers.get("Host") == self._expected_host()

    def _send_json(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._is_local_request():
            self.send_error(403)
            return

        static_files = {
            "/": ("Pages/index.html", "text/html; charset=utf-8"),
            "/index.html": ("Pages/index.html", "text/html; charset=utf-8"),
            "/updates": ("Pages/updates.html", "text/html; charset=utf-8"),
            "/updates.html": ("Pages/updates.html", "text/html; charset=utf-8"),
            "/converter": ("Pages/converter.html", "text/html; charset=utf-8"),
            "/converter.html": ("Pages/converter.html", "text/html; charset=utf-8"),
            "/Assets/CSS/app.css": ("Assets/CSS/app.css", "text/css; charset=utf-8"),
            "/Assets/JS/app.js": ("Assets/JS/app.js", "text/javascript; charset=utf-8"),
        }
        if self.path in static_files:
            self._send_static_file(*static_files[self.path])
        elif self.path in {"/Assets/Images/logo.ico", "/Assets/Images/logo.png"}:
            self._send_brand_asset(self.path)
        elif self.path == "/api/version":
            try:
                version = Path(__file__).with_name("VERSION").read_text(
                    encoding="utf-8"
                ).strip()
            except OSError as error:
                self._send_json(
                    500,
                    {"error": f"Could not read the version file: {error}"},
                )
                return
            if not version:
                self._send_json(500, {"error": "The version file is empty."})
                return
            self._send_json(200, {"version": version})
        elif self.path == "/api/status":
            state = manager.snapshot()
            self._send_json(
                200,
                {
                    "status": state["status"],
                    "progress": state["progress"],
                    "message": state["message"],
                    "mode": state["mode"],
                    "items": [
                        {
                            "title": item["title"],
                            "thumbnail": item["thumbnail"],
                            "file_size": item["file_size"],
                            "download_url": f"/api/file/{state['token']}/{index}",
                            "batch": item["batch"],
                        }
                        for index, item in enumerate(state["items"])
                    ],
                    "skipped_tracks": state["skipped_tracks"],
                    "playlist_title": state.get("playlist_title", ""),
                    "playlist_thumbnail": state.get("playlist_thumbnail", ""),
                    "playlist_creator": state.get("playlist_creator", ""),
                    "playlist_total": state["playlist_total"],
                    "current_batch": state["current_batch"],
                    "batch_count": state["batch_count"],
                    "zip_filename": (
                        self._playlist_zip_filename(state["playlist_title"])
                        if state["playlist_title"]
                        else self._playlist_zip_filename("mp3youtubeplaylist")
                    ),
                    "zip_url": (
                        f"/api/zip/{state['token']}"
                        if state["items"] and state["mode"] == "playlist"
                        else ""
                    ),
                    "error": state["error"],
                },
            )
        elif self.path.startswith("/api/zip/"):
            parsed_request = urlsplit(self.path)
            batch_values = parse_qs(parsed_request.query).get("batch", [])
            if len(batch_values) > 1:
                self.send_error(400, "Only one batch may be requested.")
                return
            try:
                batch = int(batch_values[0]) if batch_values else None
            except ValueError:
                self.send_error(400, "Invalid playlist batch.")
                return
            self._send_playlist_zip(
                parsed_request.path.removeprefix("/api/zip/"), batch
            )
        elif self.path.startswith("/api/file/"):
            self._send_file(self.path.removeprefix("/api/file/"))
        else:
            self.send_error(404)

    def _send_static_file(self, filename, content_type):
        file_path = Path(__file__).parent.joinpath(*filename.split("/"))
        try:
            contents = file_path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(contents)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(contents)

    def _send_brand_asset(self, request_path):
        asset_name = "logo.ico" if request_path.endswith(".ico") else "logo.png"
        asset_path = Path(__file__).parent / "Assets" / "Images" / asset_name
        if not asset_path.is_file():
            self.send_error(404)
            return
        content_type = "image/x-icon" if asset_name.endswith(".ico") else "image/png"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(asset_path.stat().st_size))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        with asset_path.open("rb") as asset:
            shutil.copyfileobj(asset, self.wfile)

    def do_POST(self):
        expected_origin = f"http://{self._expected_host()}"
        if (
            not self._is_local_request()
            or self.headers.get("Origin") not in (None, expected_origin)
        ):
            self.send_error(403)
            return
        if self.path == "/api/stop":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0 or content_length > 8192:
                    raise ValueError("Request body has an invalid size.")
                body = json.loads(self.rfile.read(content_length))
                request_id = body.get("request_id")
                if (
                    not isinstance(request_id, str)
                    or not request_id
                    or len(request_id) > 128
                ):
                    raise ValueError("Invalid conversion request ID.")
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                AttributeError,
                ValueError,
            ) as error:
                self._send_json(400, {"error": str(error)})
                return
            self._send_json(200, {"stopped": manager.stop(request_id)})
            return
        if self.path != "/api/download":
            self.send_error(404)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 8192:
                raise ValueError("Request body has an invalid size.")
            body = json.loads(self.rfile.read(content_length))
            url = body.get("url", "").strip()
            mode = body.get("mode", "single")
            request_id = body.get("request_id")
            if mode not in {"single", "playlist"}:
                raise ValueError("Choose single video or playlist mode.")
            if (
                not isinstance(request_id, str)
                or not request_id
                or len(request_id) > 128
            ):
                raise ValueError("Invalid conversion request ID.")
            validate_youtube_mode_url(url, mode)
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, ValueError) as error:
            self._send_json(400, {"error": str(error)})
            return

        if shutil.which("ffmpeg") is None:
            self._send_json(
                503,
                {"error": "FFmpeg is required. Install it and make sure it is on PATH."},
            )
            return
        if not manager.start(url, mode, request_id):
            self._send_json(
                409,
                {"error": "A conversion is already in progress. Please wait for it to finish."},
            )
            return
        self._send_json(202, {"message": "Download started."})

    def _send_file(self, token):
        state = manager.snapshot()
        try:
            download_token, item_index = token.rsplit("/", 1)
            item_index = int(item_index)
            if item_index < 0:
                raise ValueError("Invalid track index.")
            item = state["items"][item_index]
        except (ValueError, IndexError):
            self.send_error(404)
            return
        if (
            state["status"] not in {
                "downloading", "converting", "stopping", "stopped", "done", "error"
            }
            or not download_token
            or not secrets.compare_digest(download_token, state["token"])
        ):
            self.send_error(404)
            return
        path = item["path"]
        if not path or not path.is_file():
            self.send_error(404)
            return
        filename = f"{item['title']}.mp3"
        encoded_filename = quote(filename, safe="")
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="audio.mp3"; filename*=UTF-8\'\'{encoded_filename}',
        )
        self.end_headers()
        with path.open("rb") as audio:
            shutil.copyfileobj(audio, self.wfile)

    def _send_playlist_zip(self, token, batch=None):
        state = manager.snapshot()
        if (
            not token
            or not secrets.compare_digest(token, state["token"])
        ):
            self.send_error(
                410,
                "This playlist download link has expired. Keep the app running and "
                "convert the playlist again to create a new download link.",
            )
            return
        if (
            state["status"] not in {
                "downloading", "converting", "stopping", "stopped", "done", "error"
            }
            or state["mode"] != "playlist"
            or not state["items"]
            or (batch is not None and batch < 1)
        ):
            self.send_error(404, "No playlist MP3 files are currently available.")
            return
        items = [
            item for item in state["items"]
            if batch is None or item["batch"] == batch
        ]
        if not items:
            self.send_error(
                404,
                "No MP3 files are ready for this batch yet, or the playlist session "
                "has expired. Keep the app running and try again after a track is ready.",
            )
            return
        if any(not item["path"].is_file() for item in items):
            self.send_error(
                404,
                "One or more converted MP3 files are no longer available. "
                "Check that the files still exist in Downloads\\YouTube to MP3.",
            )
            return
        filename = self._playlist_zip_filename(state["playlist_title"], batch)
        ascii_filename = filename.encode("ascii", "replace").decode("ascii")

        with tempfile.TemporaryFile(mode="w+b") as archive:
            try:
                with zipfile.ZipFile(
                    archive, mode="w", compression=zipfile.ZIP_DEFLATED,
                    compresslevel=1,
                ) as zipped:
                    for item in items:
                        zipped.write(item["path"], arcname=item["path"].name)
            except OSError:
                self.send_error(500, "Could not create the playlist ZIP file.")
                return
            archive.seek(0, 2)
            archive_size = archive.tell()
            archive.seek(0)

            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(archive_size))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{ascii_filename}"; '
                f"filename*=UTF-8''{quote(filename, safe='')}",
            )
            self.end_headers()
            shutil.copyfileobj(archive, self.wfile)

    def log_message(self, format_string, *args):
        print(f"[local app] {format_string % args}")


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalAppHandler)
    address = f"http://127.0.0.1:{server.server_port}/"
    print(f"YouTube to MP3 is running at {address}")
    print("Keep this window open while using the app. Press Ctrl+C to stop.")
    webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping the local app...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
