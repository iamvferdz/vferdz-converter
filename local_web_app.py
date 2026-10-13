import copy
import ctypes
from datetime import datetime
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import imageio_ffmpeg
import pystray
from PIL import Image
from pystray import MenuItem
from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.ffmpeg import FFmpegExtractAudioPP
from yt_dlp.utils import DownloadError


DOWNLOAD_FOLDER = Path.home() / "Downloads" / "YouTube to MP3"
VIDEO_DOWNLOAD_FOLDER = Path.home() / "Downloads" / "YouTube to MP4"
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
PLAYLIST_BATCH_SIZE = 10
UPDATE_REPOSITORY = "iamvferdz/vferdz-converter"
MAX_UPDATE_ARCHIVE_SIZE = 250 * 1024 * 1024
logger = logging.getLogger("vferdz_converter")


def resource_path(relative_path):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / relative_path


def ffmpeg_executable():
    if not getattr(sys, "frozen", False):
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def configure_logging():
    log_folder = app_data_folder()
    log_folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_folder / "app.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def app_data_folder():
    return Path(
        os.environ.get(
            "LOCALAPPDATA",
            str(Path.home() / "AppData" / "Local"),
        )
    ) / "VFERDZ Converter"


def stable_version_key(value):
    match = re.fullmatch(r"v?(\d+(?:\.\d+){1,3})", str(value).strip())
    if not match:
        raise ValueError("The update version is not a stable version number.")
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer_version(candidate, current):
    candidate_key = stable_version_key(candidate)
    current_key = stable_version_key(current)
    segment_count = max(len(candidate_key), len(current_key))
    return candidate_key + (0,) * (segment_count - len(candidate_key)) > (
        current_key + (0,) * (segment_count - len(current_key))
    )


def show_startup_error(message):
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(
            None,
            f"{message}\n\nDetails are in %LOCALAPPDATA%\\VFERDZ Converter\\app.log.",
            "VFERDZ Converter",
            0x10,
        )


def mp4_format_selector(height):
    return (
        f"bestvideo[ext=mp4][height={height}]+bestaudio[ext=m4a]"
        f"/best[ext=mp4][height={height}]"
    )


def youtube_js_runtime_options():
    runtimes = {}
    for runtime in ("deno", "node", "bun"):
        executable = (
            str(resource_path("Scripts") / "deno.exe")
            if runtime == "deno" and getattr(sys, "frozen", False)
            else shutil.which(runtime)
        )
        if executable and not Path(executable).is_file():
            executable = None
        if not executable and runtime == "deno":
            try:
                deno_files = distribution("deno").files or ()
            except PackageNotFoundError:
                deno_files = ()
            executable = next(
                (
                    str(path)
                    for path in map(distribution("deno").locate_file, deno_files)
                    if path.name.lower() in {"deno", "deno.exe"} and path.is_file()
                ),
                None,
            ) if deno_files else None
        if executable:
            runtimes[runtime] = {"path": executable}
    return {"js_runtimes": runtimes or {"deno": {}}}


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
    if mode in {"single", "mp4"} and is_playlist_url:
        if mode == "mp4":
            raise ValueError("MP4 mode only accepts a single YouTube video link, not a playlist link.")
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

        popen_options = {}
        if sys.platform == "win32":
            popen_options["creationflags"] = subprocess.CREATE_NO_WINDOW
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **popen_options,
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
        self.logs = {"mp3": [], "mp4": []}
        self.last_log_signature = {"mp3": None, "mp4": None}
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

    @staticmethod
    def _log_mode(mode):
        return "mp4" if mode == "mp4" else "mp3"

    def _record_state_log(self):
        mode = self._log_mode(self.state["mode"])
        status = self.state["status"]
        message = self.state["message"]
        if status == "idle" or not message:
            return

        log_message = re.sub(r"\s*\(\d+%\)|\s+\d+%$", "", message).strip()
        signature = (status, log_message)
        if signature == self.last_log_signature[mode]:
            return

        self.last_log_signature[mode] = signature
        self.logs[mode].append(
            {
                "time": datetime.now().astimezone().strftime("%H:%M:%S"),
                "status": status,
                "message": log_message,
            }
        )
        del self.logs[mode][:-60]

    def get_logs(self, mode):
        with self.lock:
            return [dict(entry) for entry in self.logs[self._log_mode(mode)]]

    def snapshot(self):
        with self.lock:
            self._record_state_log()
            state = dict(self.state)
            state["items"] = [dict(item) for item in self.state["items"]]
            return state

    def start(self, url, mode, request_id=None):
        with self.lock:
            with update_manager.lock:
                if update_manager.state["status"] in {
                    "downloading", "verifying", "restarting"
                }:
                    return False
            if self.state["status"] in {
                "preparing", "downloading", "converting", "stopping"
            }:
                return False
            token = secrets.token_urlsafe(24)
            request_id = request_id or secrets.token_urlsafe(24)
            cancel_event = threading.Event()
            self.cancel_event = cancel_event
            self.state = {
                "status": (
                    "preparing" if mode in {"playlist", "mp4"} else "downloading"
                ),
                "progress": 0,
                "message": (
                    "Preparing playlist..."
                    if mode == "playlist"
                    else "Finding available MP4 qualities..."
                    if mode == "mp4"
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
            self._record_state_log()
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
            self._record_state_log()
            return True

    @staticmethod
    def _check_cancelled(cancel_event):
        if cancel_event.is_set():
            raise DownloadError("Conversion was stopped.")

    def _download(self, url, mode, cancel_event):
        if mode == "playlist":
            self._download_playlist(url, cancel_event)
            return
        if mode == "mp4":
            self._download_mp4(url, cancel_event)
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
            **youtube_js_runtime_options(),
            "ffmpeg_location": ffmpeg_executable(),
            "quiet": True,
            "no_warnings": True,
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
        try:
            DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
            with YoutubeDL(options) as ydl:
                ydl.add_post_processor(
                    CancellableFFmpegExtractAudioPP(ydl, cancel_event)
                )
                info = ydl.extract_info(url, download=True)
                self._check_cancelled(cancel_event)
                output_path = Path(ydl.prepare_filename(info)).with_suffix(".mp3")
            if not output_path.is_file():
                raise FileNotFoundError(
                    "Conversion finished but the MP3 was not found: "
                    f"{info.get('title') or 'audio'}"
                )
            item = {
                "title": info.get("title") or "Audio",
                "thumbnail": self._safe_thumbnail(info.get("thumbnail") or ""),
                "file_size": output_path.stat().st_size,
                "path": output_path,
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

    def _download_mp4(self, url, cancel_event):
        try:
            self._check_cancelled(cancel_event)
            VIDEO_DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
            base_options = {
                **youtube_js_runtime_options(),
                "ffmpeg_location": ffmpeg_executable(),
                "quiet": True,
                "no_warnings": True,
                "outtmpl": str(
                    VIDEO_DOWNLOAD_FOLDER
                    / "%(title)s [%(id)s] %(height)sp.%(ext)s"
                ),
                "merge_output_format": "mp4",
                "noplaylist": True,
                "windowsfilenames": True,
                "progress_hooks": [],
                "postprocessor_hooks": [],
            }
            with YoutubeDL(base_options) as ydl:
                info = ydl.extract_info(url, download=False)
                self._check_cancelled(cancel_event)
                formats = info.get("formats") or []
                heights = sorted(
                    {
                        item["height"]
                        for item in formats
                        if item.get("ext") == "mp4"
                        and item.get("vcodec") != "none"
                        and isinstance(item.get("height"), int)
                    },
                    reverse=True,
                )
                if not heights:
                    raise ValueError(
                        "This video has no MP4-compatible video formats."
                    )

                title = info.get("title") or "Video"
                thumbnail = self._safe_thumbnail(info.get("thumbnail") or "")
                ready_items = []
                unavailable = []

                for index, height in enumerate(heights, start=1):
                    self._check_cancelled(cancel_event)
                    quality = f"{height}p"

                    def on_progress(data):
                        self._check_cancelled(cancel_event)
                        if data.get("status") != "downloading":
                            return
                        downloaded = data.get("downloaded_bytes", 0)
                        total = (
                            data.get("total_bytes")
                            or data.get("total_bytes_estimate")
                        )
                        quality_progress = (
                            min(99, int(downloaded * 100 / total))
                            if total
                            else 0
                        )
                        progress = int(
                            ((index - 1) + quality_progress / 100)
                            * 100
                            / len(heights)
                        )
                        with self.lock:
                            self._check_cancelled(cancel_event)
                            self.state.update(
                                status="downloading",
                                progress=progress,
                                message=(
                                    f"Downloading {quality} MP4 "
                                    f"({quality_progress}%)..."
                                ),
                            )

                    def on_postprocessor(data):
                        self._check_cancelled(cancel_event)
                        if data.get("status") != "started":
                            return
                        with self.lock:
                            self._check_cancelled(cancel_event)
                            self.state.update(
                                status="converting",
                                progress=int((index - 1) * 100 / len(heights)),
                                message=f"Combining {quality} video and audio into MP4...",
                            )

                    try:
                        ydl.params.update(
                            format=mp4_format_selector(height),
                            progress_hooks=[on_progress],
                            postprocessor_hooks=[on_postprocessor],
                        )
                        ydl.format_selector = ydl.build_format_selector(
                            mp4_format_selector(height)
                        )
                        variant = ydl.process_ie_result(
                            copy.deepcopy(info), download=True
                        )
                        self._check_cancelled(cancel_event)
                        output_path = Path(
                            ydl.prepare_filename(variant)
                        ).with_suffix(".mp4")
                        if not output_path.is_file():
                            raise FileNotFoundError(
                                f"The {quality} MP4 was not created."
                            )
                    except Exception as error:
                        if cancel_event.is_set():
                            raise
                        unavailable.append(
                            {
                                "index": index,
                                "title": quality,
                                "error": str(error),
                            }
                        )
                        logger.warning("Could not prepare %s: %s", quality, error)
                        continue

                    item = {
                        "title": title,
                        "quality": quality,
                        "height": height,
                        "thumbnail": thumbnail,
                        "file_size": output_path.stat().st_size,
                        "path": output_path,
                        "batch": 0,
                    }
                    ready_items.append(item)
                    with self.lock:
                        self._check_cancelled(cancel_event)
                        self.state["items"].append(item)
                        self.state.update(
                            status="downloading",
                            progress=int(index * 100 / len(heights)),
                            message=f"{quality} MP4 is ready.",
                        )

            if not ready_items:
                raise RuntimeError(
                    "Could not prepare any available MP4 qualities. "
                    + "; ".join(
                        f"{item['title']}: {item['error']}" for item in unavailable
                    )
                )
            with self.lock:
                self._check_cancelled(cancel_event)
                self.state.update(
                    status="done",
                    progress=100,
                    skipped_tracks=unavailable,
                    message=(
                        f"{len(ready_items)} MP4 quality "
                        f"{'is' if len(ready_items) == 1 else 'options are'} ready to download."
                        + (
                            f" {len(unavailable)} other "
                            f"{'quality was' if len(unavailable) == 1 else 'qualities were'} unavailable."
                            if unavailable
                            else ""
                        )
                    ),
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
                        message="The video qualities could not be prepared.",
                        error=str(error),
                    )

    def _download_playlist(self, url, cancel_event):
        try:
            self._check_cancelled(cancel_event)
            DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
            with YoutubeDL(
                {
                    **youtube_js_runtime_options(),
                    "quiet": True,
                    "no_warnings": True,
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
                            **youtube_js_runtime_options(),
                            "ffmpeg_location": ffmpeg_executable(),
                            "quiet": True,
                            "no_warnings": True,
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


class UpdateManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.shutdown_callback = None
        self.state = {
            "status": "idle",
            "progress": 0,
            "tag": "",
            "message": "",
            "error": "",
        }

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self, tag, digest):
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            return False, "Automatic updates are available in the standalone Windows app."
        if Path(sys.executable).name.lower() != "vferdz converter.exe":
            return False, "The app executable could not be identified for updating."
        try:
            if not is_newer_version(tag, resource_path("VERSION").read_text(encoding="utf-8").strip()):
                return False, "This update is not newer than the installed version."
        except (OSError, ValueError) as error:
            return False, f"Could not verify the update version: {error}"
        if not isinstance(digest, str) or not re.fullmatch(
            r"sha256:[0-9a-fA-F]{64}", digest
        ):
            return False, "GitHub did not provide a valid SHA-256 checksum for this release."
        with manager.lock:
            if manager.state["status"] in {
                "preparing", "downloading", "converting", "stopping"
            }:
                return False, "Finish or stop the current conversion before updating."
            with self.lock:
                if self.state["status"] in {"downloading", "verifying", "restarting"}:
                    return False, "An update is already in progress."
                self.state = {
                    "status": "downloading",
                    "progress": 0,
                    "tag": tag,
                    "message": "Downloading the verified update...",
                    "error": "",
                }
        threading.Thread(target=self._install, args=(tag, digest), daemon=True).start()
        return True, ""

    def _set_state(self, status, message, progress=None, error=""):
        with self.lock:
            self.state.update(
                status=status,
                message=message,
                error=error,
            )
            if progress is not None:
                self.state["progress"] = progress

    def _install(self, tag, digest):
        archive_path = None
        staged_path = None
        script_path = None
        target_path = Path(sys.executable).resolve()
        try:
            powershell = shutil.which("powershell.exe")
            if not powershell:
                raise RuntimeError("Windows PowerShell is not available to complete the update.")
            target_folder = target_path.parent
            try:
                with tempfile.NamedTemporaryFile(
                    prefix=".vferdz-write-check-", dir=target_folder, delete=True
                ):
                    pass
            except OSError as error:
                raise PermissionError(
                    "The app folder is not writable. Move VFERDZ Converter.exe to a folder "
                    "you own, such as a folder under %LOCALAPPDATA%, then retry."
                ) from error

            url = (
                f"https://github.com/{UPDATE_REPOSITORY}/releases/download/"
                f"{tag}/vferdz-converter-{tag}.zip"
            )
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/octet-stream",
                    "User-Agent": "VFERDZ-Converter-Updater",
                },
            )
            with tempfile.NamedTemporaryFile(
                prefix="vferdz-update-", suffix=".zip", delete=False
            ) as archive_file:
                archive_path = Path(archive_file.name)
                with urllib.request.urlopen(request, timeout=30) as response:
                    final_url = urlsplit(response.geturl())
                    if (
                        final_url.scheme != "https"
                        or final_url.hostname not in {
                            "github.com",
                            "release-assets.githubusercontent.com",
                            "objects.githubusercontent.com",
                        }
                    ):
                        raise RuntimeError("The update download redirected to an untrusted host.")
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > MAX_UPDATE_ARCHIVE_SIZE:
                        raise RuntimeError("The update archive is larger than the allowed size.")
                    digest_hash = hashlib.sha256()
                    downloaded = 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > MAX_UPDATE_ARCHIVE_SIZE:
                            raise RuntimeError("The update archive is larger than the allowed size.")
                        archive_file.write(chunk)
                        digest_hash.update(chunk)
                        self._set_state(
                            "downloading",
                            "Downloading the verified update...",
                            min(99, int(downloaded * 100 / int(content_length)))
                            if content_length and content_length.isdigit()
                            else 0,
                        )
                archive_file.flush()
                os.fsync(archive_file.fileno())

            if digest_hash.hexdigest().lower() != digest.removeprefix("sha256:").lower():
                raise RuntimeError("The update checksum did not match GitHub's SHA-256 digest.")

            self._set_state("verifying", "Verifying the update package...", 100)
            with zipfile.ZipFile(archive_path) as archive:
                if archive.namelist() != ["VFERDZ Converter.exe"]:
                    raise RuntimeError("The update ZIP must contain only VFERDZ Converter.exe.")
                if archive.getinfo("VFERDZ Converter.exe").file_size > MAX_UPDATE_ARCHIVE_SIZE:
                    raise RuntimeError("The app executable is larger than the allowed size.")
                if archive.testzip() is not None:
                    raise RuntimeError("The update ZIP is damaged.")
                with archive.open("VFERDZ Converter.exe") as source:
                    with tempfile.NamedTemporaryFile(
                        prefix=".vferdz-update-",
                        suffix=".exe",
                        dir=target_folder,
                        delete=False,
                    ) as staged_file:
                        staged_path = Path(staged_file.name)
                        header = source.read(2)
                        if header != b"MZ":
                            raise RuntimeError("The downloaded app is not a valid Windows executable.")
                        staged_file.write(header)
                        shutil.copyfileobj(source, staged_file)
                        staged_file.flush()
                        os.fsync(staged_file.fileno())

            self._set_state("verifying", "Preparing to replace the app...", 100)
            script = r"""
$ErrorActionPreference = 'Stop'
$target = $env:VFERDZ_UPDATE_TARGET
$staged = $env:VFERDZ_UPDATE_STAGED
$backup = "$target.previous-$([guid]::NewGuid().ToString('N'))"
$log = $env:VFERDZ_UPDATE_LOG
$scriptPath = $MyInvocation.MyCommand.Path
try {
    Wait-Process -Id ([int]$env:VFERDZ_UPDATE_PARENT) -ErrorAction SilentlyContinue
    $replaced = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            [System.IO.File]::Replace($staged, $target, $backup, $true)
            $replaced = $true
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $replaced) {
        throw 'The app file remained in use or could not be replaced.'
    }
    try {
        $app = Start-Process -FilePath $target -WorkingDirectory (Split-Path $target) -PassThru
        Start-Sleep -Seconds 3
        if (-not (Get-Process -Id $app.Id -ErrorAction SilentlyContinue)) {
            throw 'The updated app did not stay running.'
        }
        Remove-Item -LiteralPath $backup -Force
        Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) INFO Update to $($env:VFERDZ_UPDATE_TAG) installed."
        Remove-Item -LiteralPath $scriptPath -Force
        exit 0
    } catch {
        if (Test-Path -LiteralPath $backup) {
            Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
            Move-Item -LiteralPath $backup -Destination $target -Force
            Start-Process -FilePath $target -WorkingDirectory (Split-Path $target)
        }
        throw
    }
} catch {
    Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) ERROR Update failed: $($_.Exception.Message)"
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            "The update could not be installed. Your current version was kept or restored. Details are in %LOCALAPPDATA%\VFERDZ Converter\app.log.",
            'VFERDZ Converter update',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    } catch {}
    Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue
}
"""
            log_folder = app_data_folder()
            log_folder.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".ps1",
                prefix="vferdz-updater-",
                dir=log_folder,
                delete=False,
            ) as script_file:
                script_file.write(script)
                script_path = Path(script_file.name)

            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creation_flags,
                env={
                    **os.environ,
                    "VFERDZ_UPDATE_TARGET": str(target_path),
                    "VFERDZ_UPDATE_STAGED": str(staged_path),
                    "VFERDZ_UPDATE_PARENT": str(os.getpid()),
                    "VFERDZ_UPDATE_LOG": str(log_folder / "app.log"),
                    "VFERDZ_UPDATE_TAG": tag,
                },
            )
            staged_path = None
            script_path = None
            self._set_state(
                "restarting",
                "Update downloaded and verified. The app is restarting...",
                100,
            )
            if self.shutdown_callback:
                threading.Thread(target=self._shutdown_app, daemon=True).start()
        except Exception as error:
            logger.exception("Could not install update %s.", tag)
            self._set_state(
                "error",
                "The update could not be installed.",
                error=str(error),
            )
        finally:
            for path in (archive_path, staged_path, script_path):
                if path:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        logger.exception("Could not remove temporary update file %s.", path)

    def _shutdown_app(self):
        time.sleep(1)
        self.shutdown_callback()


update_manager = UpdateManager()


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

        request_path = urlsplit(self.path).path
        if request_path == "/api/logs":
            query = parse_qs(urlsplit(self.path).query)
            modes = query.get("mode", [])
            if len(modes) != 1 or modes[0] not in {"mp3", "mp4"}:
                self._send_json(400, {"error": "Choose MP3 or MP4 logs."})
                return
            manager.snapshot()
            self._send_json(200, {"logs": manager.get_logs(modes[0])})
            return
        if request_path == "/api/update/status":
            self._send_json(
                200,
                {
                    "supported": (
                        sys.platform == "win32"
                        and getattr(sys, "frozen", False)
                        and Path(sys.executable).name.lower() == "vferdz converter.exe"
                    ),
                    **update_manager.snapshot(),
                },
            )
            return

        static_files = {
            "/": ("Pages/index.html", "text/html; charset=utf-8"),
            "/index.html": ("Pages/index.html", "text/html; charset=utf-8"),
            "/updates": ("Pages/updates.html", "text/html; charset=utf-8"),
            "/updates.html": ("Pages/updates.html", "text/html; charset=utf-8"),
            "/converter": ("Pages/converter.html", "text/html; charset=utf-8"),
            "/converter.html": ("Pages/converter.html", "text/html; charset=utf-8"),
            "/mp4-converter": ("Pages/mp4.html", "text/html; charset=utf-8"),
            "/mp4.html": ("Pages/mp4.html", "text/html; charset=utf-8"),
            "/Assets/CSS/app.css": ("Assets/CSS/app.css", "text/css; charset=utf-8"),
            "/Assets/JS/app.js": ("Assets/JS/app.js", "text/javascript; charset=utf-8"),
        }
        if self.path in static_files:
            self._send_static_file(*static_files[self.path])
        elif self.path in {"/Assets/Images/logo.ico", "/Assets/Images/logo.png"}:
            self._send_brand_asset(self.path)
        elif self.path == "/api/version":
            try:
                version = resource_path("VERSION").read_text(encoding="utf-8").strip()
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
                            "quality": item.get("quality", ""),
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
        file_path = resource_path(filename)
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
        asset_path = resource_path(Path("Assets") / "Images" / asset_name)
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
        if self.path == "/api/update/install":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0 or content_length > 4096:
                    raise ValueError("The update request has an invalid size.")
                body = json.loads(self.rfile.read(content_length))
                tag = body.get("tag")
                digest = body.get("digest")
                if not isinstance(tag, str) or len(tag) > 64:
                    raise ValueError("The release version is invalid.")
                if not isinstance(digest, str) or len(digest) > 80:
                    raise ValueError("The release checksum is invalid.")
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                AttributeError,
                ValueError,
            ) as error:
                self._send_json(400, {"error": str(error)})
                return
            started, error = update_manager.start(tag, digest)
            if not started:
                self._send_json(409, {"error": error})
                return
            self._send_json(202, {"message": "The update is being downloaded."})
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
            if mode not in {"single", "playlist", "mp4"}:
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

        try:
            ffmpeg_path = Path(ffmpeg_executable())
        except (FileNotFoundError, RuntimeError) as error:
            logger.exception("Could not locate FFmpeg.")
            self._send_json(
                503,
                {"error": f"The bundled FFmpeg executable could not be loaded: {error}"},
            )
            return
        if not ffmpeg_path.is_file():
            self._send_json(
                503,
                {"error": "The bundled FFmpeg executable could not be found."},
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
        extension = "mp4" if state["mode"] == "mp4" else "mp3"
        quality = f" {item['quality']}" if item.get("quality") else ""
        filename = f"{item['title']}{quality}.{extension}"
        encoded_filename = quote(filename, safe="")
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "video/mp4" if extension == "mp4" else "audio/mpeg",
        )
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="video.{extension}"; '
            f"filename*=UTF-8''{encoded_filename}",
        )
        self.end_headers()
        with path.open("rb") as media:
            shutil.copyfileobj(media, self.wfile)

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
        logger.debug("HTTP %s", format_string % args)


def main():
    try:
        configure_logging()
    except OSError as error:
        show_startup_error(f"Could not initialize app logging: {error}")
        return

    server = None
    icon = None
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), LocalAppHandler)
        update_manager.shutdown_callback = server.shutdown
        address = f"http://127.0.0.1:{server.server_port}/"

        def open_app(icon, item):
            webbrowser.open(address)

        def exit_app(icon, item):
            logger.info("App exit requested from the system tray.")
            server.shutdown()
            icon.stop()

        with Image.open(
            resource_path(Path("Assets") / "Images" / "logo.ico")
        ) as tray_image:
            icon = pystray.Icon(
                "VFERDZ Converter",
                tray_image.copy(),
                "VFERDZ Converter",
                menu=pystray.Menu(
                    MenuItem("Open VFERDZ Converter", open_app, default=True),
                    MenuItem("Exit", exit_app),
                ),
            )
        icon.run_detached()
        logger.info("VFERDZ Converter is running at %s", address)
        if not webbrowser.open(address):
            logger.warning("Could not open the app in a browser: %s", address)
        server.serve_forever()
    except Exception as error:
        logger.exception("The local app failed to start or stopped unexpectedly.")
        show_startup_error(str(error))
    finally:
        if icon:
            icon.stop()
        if server:
            server.server_close()


if __name__ == "__main__":
    main()
