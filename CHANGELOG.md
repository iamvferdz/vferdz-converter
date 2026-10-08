# Changelog

All notable changes to VFERDZ CONVERTER are documented here.

## [0.1.2] - 10/08/2026

### Improved
- **Modified Files**: release.yml

## [0.1.1] - 10/08/2026

### New
- **Stop Convert Button**: Added a stop conversion feature. Users can now stop an ongoing conversion while keeping already converted videos/music available for download.
- **Convert Again Button**: Added a retry conversion button to resolve cases where conversions fail after the first attempt.
- **Manual Update Check**: Added a Check for updates button on the Updates page so you can check for published releases when you choose.
- **New Page**: Home Page, Update Page and YouTube to MP3 page (Separate page per conversion tools).
- **Added Footer**: list of conversion tools.

### Improved
- **Your Download Section**: The download list will now remain intact when switching between tabs (Single Convert and Playlist Convert).
- **Error Messages**: Improved error messages to provide clearer, more user-friendly feedback.
- **Update Information**: The Updates page now tells you whether a newer release is available and provides links to published release downloads.
- **Installation Guide**: Added setup and manual update instructions to the README, including the requirements for running the app.

### Fixed
- **Conversion Stopping After First Attempt**: Fixed an issue where the conversion process would stop unexpectedly after the first conversion. Added a Convert Again button as a recovery option.
- **Playlist and Single Conversion Validation**: Fixed an issue where playlist links could be converted in the Single tab and single video/music links could be converted in the Playlist tab. The tabs now properly handle their intended input types.
- **Unwanted Update Checks**: Removed automatic background checks. Updates are checked when you open the Updates page or click Check for updates; the app does not automatically download or install updates.

## [0.1.0] - 10/07/2026 🎉 First Release

### New Features
- **Clean Interface**: Introduced a modern and organized UI layout.
- **MP3 Converter**: Supports converting content from both single links and playlist links.
- **Multiple Download Modes**:
  - Manual download
  - Batch download
  - Bulk download