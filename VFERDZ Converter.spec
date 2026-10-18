from importlib.metadata import distribution
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata
from PyInstaller.building.api import COLLECT


project_root = Path(SPECPATH)
datas = [
    (str(project_root / "Pages"), "Pages"),
    (str(project_root / "Assets"), "Assets"),
    (str(project_root / "VERSION"), "."),
]
binaries = []
hiddenimports = []

for package in ("yt_dlp", "yt_dlp_ejs", "imageio_ffmpeg", "pystray", "PIL"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)

deno_distribution = distribution("deno")
deno_executable = next(
    (
        deno_distribution.locate_file(file)
        for file in deno_distribution.files or ()
        if Path(file).name.lower() == "deno.exe"
    ),
    None,
)
if deno_executable is None or not deno_executable.is_file():
    raise RuntimeError("The Windows Deno executable was not found in the deno package.")
binaries.append((str(deno_executable), "Scripts"))

for package in ("yt-dlp", "yt-dlp-ejs", "deno", "imageio-ffmpeg", "pystray", "Pillow"):
    datas.extend(copy_metadata(package))

analysis = Analysis(
    ["local_web_app.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="VFERDZ Converter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(project_root / "Assets" / "Images" / "logo.ico"),
    contents_directory="_internal",
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VFERDZ-CONVERTER",
)
