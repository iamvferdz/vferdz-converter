const form = document.querySelector("#form");
    const input = document.querySelector("#url");
    const button = document.querySelector("#submit");
    const stopButton = document.querySelector("#stop-conversion");
    const conversionNotice = document.querySelector("#conversion-notice");
    const urlLabel = document.querySelector("#url-label");
    const singleTab = document.querySelector("#single-tab");
    const playlistTab = document.querySelector("#playlist-tab");
    const status = document.querySelector("#status");
    const progress = document.querySelector("#progress");
    const zipDownload = document.querySelector("#download-zip");
    const downloadsMode = document.querySelector("#downloads-mode");
    const viewToolbar = document.querySelector("#view-toolbar");
    const viewButtons = [...document.querySelectorAll(".view-button")];
    const emptyState = document.querySelector("#empty-state");
    const skippedSummary = document.querySelector("#skipped-summary");
    const skippedHeading = document.querySelector("#skipped-heading");
    const skippedList = document.querySelector("#skipped-list");
    const playlistSummary = document.querySelector("#playlist-summary");
    const playlistSummaryThumb = document.querySelector("#playlist-summary-thumb");
    const playlistSummaryTitle = document.querySelector("#playlist-summary-title");
    const playlistSummaryCreator = document.querySelector("#playlist-summary-creator");
    const resultList = document.querySelector("#result-list");
    const themeToggle = document.querySelector("#theme-toggle");
    const releaseList = document.querySelector("#release-list");
    const appVersion = document.querySelector("#app-version");
    const updatesDescription = document.querySelector("#updates-description");
    const refreshReleasesButton = document.querySelector("#refresh-releases");
    const updateCheckStatus = document.querySelector("#update-check-status");
    const githubReleasesUrl =
      "https://api.github.com/repos/iamvferdz/vferdz-converter/releases?per_page=100";
    let publishedReleasesCache = null;
    let publishedReleasesRequest = null;
    let mode = "single";
    let timer;
    let pollController;
    let operationId = 0;
    let activeRequestId = "";
    let renderedItems = 0;
    let renderedBatch = 0;
    let currentBatchItems = null;
    let currentAppVersion = "";
    let downloadView = localStorage.getItem("youtube-to-mp3-download-view");
    if (!["list", "grid"].includes(downloadView)) {
      downloadView = "grid";
    }

    function setDownloadView(view) {
      downloadView = view;
      if (!resultList) return;
      resultList.classList.remove("view-list", "view-grid");
      resultList.classList.add(`view-${view}`);
      for (const viewButton of viewButtons) {
        viewButton.setAttribute(
          "aria-pressed",
          String(viewButton.dataset.view === view),
        );
      }
      localStorage.setItem("youtube-to-mp3-download-view", view);
    }

    if (resultList) setDownloadView(downloadView);
    for (const viewButton of viewButtons) {
      viewButton.addEventListener("click", () => {
        setDownloadView(viewButton.dataset.view);
      });
    }

    function setTheme(theme) {
      document.documentElement.dataset.theme = theme;
      const isDark = theme === "dark";
      const action = isDark ? "light" : "dark";
      themeToggle.setAttribute("aria-label", `Switch to ${action} mode`);
      themeToggle.title = `Switch to ${action} mode`;
      themeToggle.setAttribute("aria-pressed", String(isDark));
      localStorage.setItem("youtube-to-mp3-theme", theme);
    }

    const savedTheme = localStorage.getItem("youtube-to-mp3-theme");
    setTheme(savedTheme === "light" ? "light" : "dark");

    themeToggle.addEventListener("click", () => {
      setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    });

    refreshReleasesButton?.addEventListener("click", async () => {
      await loadUpdates(true);
    });

    async function loadAppVersion() {
      try {
        const response = await fetch("/api/version", { cache: "no-store" });
        if (!response.ok) throw new Error(`Version request failed (${response.status}).`);
        const result = await response.json();
        if (!result.version) throw new Error("The version response was empty.");
        currentAppVersion = result.version;
        appVersion.textContent = result.version;
        if (updatesDescription) {
          updatesDescription.textContent =
            `Installed version ${result.version}. Published release notes are loaded from GitHub.`;
        }
        return result.version;
      } catch (error) {
        appVersion.textContent = "unavailable";
        if (updatesDescription) {
          updatesDescription.textContent =
            "Could not read the installed version. Published release notes are loaded from GitHub.";
        }
        console.error("Could not load the app version.", error);
        return "";
      }
    }

    function compareVersions(first, second) {
      const parseVersion = (value) => {
        const match = String(value).trim().match(
          /^v?(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/i,
        );
        if (!match) return null;
        return {
          numbers: match[1].split(".").map(Number),
          prerelease: match[2] ? match[2].split(".") : [],
        };
      };
      const left = parseVersion(first);
      const right = parseVersion(second);
      if (!left || !right) return null;
      const segmentCount = Math.max(left.numbers.length, right.numbers.length);
      for (let index = 0; index < segmentCount; index += 1) {
        const difference = (left.numbers[index] || 0) - (right.numbers[index] || 0);
        if (difference) return Math.sign(difference);
      }
      if (!left.prerelease.length || !right.prerelease.length) {
        return Number(Boolean(right.prerelease.length)) - Number(Boolean(left.prerelease.length));
      }
      const prereleaseLength = Math.max(left.prerelease.length, right.prerelease.length);
      for (let index = 0; index < prereleaseLength; index += 1) {
        const leftPart = left.prerelease[index];
        const rightPart = right.prerelease[index];
        if (leftPart === undefined || rightPart === undefined) {
          return leftPart === undefined ? -1 : 1;
        }
        if (leftPart === rightPart) continue;
        const leftNumeric = /^\d+$/.test(leftPart);
        const rightNumeric = /^\d+$/.test(rightPart);
        if (leftNumeric && rightNumeric) {
          return Math.sign(Number(leftPart) - Number(rightPart));
        }
        if (leftNumeric !== rightNumeric) return leftNumeric ? -1 : 1;
        return leftPart < rightPart ? -1 : 1;
      }
      return 0;
    }

    async function fetchPublishedReleases(forceRefresh = false) {
      if (!forceRefresh && publishedReleasesCache) return publishedReleasesCache;
      if (publishedReleasesRequest) return publishedReleasesRequest;
      publishedReleasesRequest = (async () => {
        const response = await fetch(githubReleasesUrl, {
          headers: { Accept: "application/vnd.github+json" },
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error(`GitHub releases request failed (${response.status}).`);
        }
        const releases = await response.json();
        if (!Array.isArray(releases)) {
          throw new Error("GitHub returned an invalid releases list.");
        }
        publishedReleasesCache = releases.filter((release) => !release.draft);
        return publishedReleasesCache;
      })();
      try {
        return await publishedReleasesRequest;
      } finally {
        publishedReleasesRequest = null;
      }
    }

    function addReleaseCard({ title, date, body, url, assetUrl }) {
      const card = document.createElement("article");
      card.className = "release-card";
      const header = document.createElement("div");
      header.className = "release-header";
      const heading = document.createElement("h3");
      heading.className = "release-title";
      heading.textContent = title;
      const dateLabel = document.createElement("time");
      dateLabel.className = "release-date";
      dateLabel.textContent = date
        ? new Date(date).toLocaleDateString()
        : "Date unavailable";
      if (date) dateLabel.dateTime = date;
      header.append(heading, dateLabel);
      const releaseBody = document.createElement("div");
      releaseBody.className = "release-body is-collapsed";
      renderReleaseBody(releaseBody, body);
      card.append(header, releaseBody);
      releaseList.append(card);
      if (releaseBody.scrollHeight > releaseBody.clientHeight + 1) {
        const expandButton = document.createElement("button");
        expandButton.className = "release-expand";
        expandButton.type = "button";
        expandButton.textContent = "Show more";
        expandButton.setAttribute("aria-expanded", "false");
        expandButton.addEventListener("click", () => {
          const expanded = expandButton.getAttribute("aria-expanded") !== "true";
          expandButton.setAttribute("aria-expanded", String(expanded));
          expandButton.textContent = expanded ? "Show less" : "Show more";
          releaseBody.classList.toggle("is-collapsed", !expanded);
        });
        card.append(expandButton);
      } else {
        releaseBody.classList.remove("is-collapsed");
      }

      const actions = document.createElement("div");
      actions.className = "release-actions";
      const safeReleaseUrl = trustedGitHubUrl(url);
      const safeAssetUrl = trustedGitHubUrl(assetUrl);
      if (safeReleaseUrl) {
        const releaseLink = document.createElement("a");
        releaseLink.className = "release-link";
        releaseLink.href = safeReleaseUrl;
        releaseLink.target = "_blank";
        releaseLink.rel = "noopener noreferrer";
        releaseLink.textContent = "View GitHub release";
        actions.append(releaseLink);
      }
      if (safeAssetUrl) {
        const downloadLink = document.createElement("a");
        downloadLink.className = "release-link";
        downloadLink.href = safeAssetUrl;
        downloadLink.target = "_blank";
        downloadLink.rel = "noopener noreferrer";
        downloadLink.textContent = "Download ZIP";
        actions.append(downloadLink);
      }
      if (actions.childElementCount) card.append(actions);
    }

    function trustedGitHubUrl(rawUrl) {
      if (!rawUrl) return "";
      try {
        const url = new URL(rawUrl);
        return url.protocol === "https:" && url.hostname === "github.com"
          ? url.href
          : "";
      } catch {
        return "";
      }
    }

    function appendInlineReleaseText(parent, text) {
      const pattern = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;
      let offset = 0;
      for (const match of text.matchAll(pattern)) {
        parent.append(document.createTextNode(text.slice(offset, match.index)));
        if (match[1]) {
          const strong = document.createElement("strong");
          strong.textContent = match[1];
          parent.append(strong);
        } else if (match[2]) {
          const code = document.createElement("code");
          code.textContent = match[2];
          parent.append(code);
        } else {
          const link = document.createElement("a");
          link.href = match[4];
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = match[3];
          parent.append(link);
        }
        offset = match.index + match[0].length;
      }
      parent.append(document.createTextNode(text.slice(offset)));
    }

    function renderReleaseBody(container, body) {
      let list;
      for (const line of String(body || "").split(/\r?\n/)) {
        const text = line.trim();
        if (!text) {
          list = null;
          continue;
        }
        const heading = text.match(/^#{1,6}\s+(.+)$/);
        if (heading) {
          list = null;
          const subheading = document.createElement("h4");
          appendInlineReleaseText(subheading, heading[1]);
          container.append(subheading);
        } else if (/^[-*]\s+/.test(text)) {
          if (!list) {
            list = document.createElement("ul");
            list.className = "release-bullets";
            container.append(list);
          }
          const item = document.createElement("li");
          appendInlineReleaseText(item, text.replace(/^[-*]\s+/, ""));
          list.append(item);
        } else {
          list = null;
          const paragraph = document.createElement("p");
          appendInlineReleaseText(paragraph, text);
          container.append(paragraph);
        }
      }
      if (!container.childElementCount) {
        const paragraph = document.createElement("p");
        paragraph.textContent = "No release notes were provided.";
        container.append(paragraph);
      }
    }

    async function loadUpdates(forceRefresh = false) {
      if (!releaseList || !refreshReleasesButton) return;
      refreshReleasesButton.disabled = true;
      if (updateCheckStatus) updateCheckStatus.textContent = "Checking GitHub for updates...";
      releaseList.replaceChildren();
      const loading = document.createElement("p");
      loading.className = "release-status";
      loading.textContent = "Loading GitHub releases...";
      releaseList.append(loading);
      try {
        const releases = await fetchPublishedReleases(forceRefresh);
        releaseList.replaceChildren();
        const latestStableRelease = releases
          .filter((release) => !release.prerelease
            && typeof release.tag_name === "string"
            && compareVersions(
            release.tag_name,
            currentAppVersion,
          ) !== null)
          .reduce((latest, release) => (
            !latest || compareVersions(release.tag_name, latest.tag_name) > 0
              ? release
              : latest
          ), null);
        if (updateCheckStatus) {
          if (!currentAppVersion) {
            updateCheckStatus.textContent = "The installed version could not be read.";
          } else if (!latestStableRelease) {
            updateCheckStatus.textContent = releases.length
              ? "No stable release with a comparable version is available."
              : "No published GitHub releases are available to check against.";
          } else if (compareVersions(latestStableRelease.tag_name, currentAppVersion) > 0) {
            updateCheckStatus.textContent =
              `A new update is available: ${latestStableRelease.tag_name}. Download its ZIP from the release list below.`;
          } else {
            updateCheckStatus.textContent = `You are up to date (version ${currentAppVersion}).`;
          }
        }
        if (!releases.length) {
          const empty = document.createElement("p");
          empty.className = "release-status";
          empty.textContent = "No published GitHub releases are available yet.";
          releaseList.append(empty);
          return;
        }
        for (const release of releases) {
          const asset = (release.assets || []).find(
            (item) => typeof item.name === "string"
              && item.name.toLowerCase().endsWith(".zip"),
          );
          addReleaseCard({
            title: release.name || release.tag_name,
            date: release.published_at || release.created_at,
            body: release.body || "",
            url: release.html_url,
            assetUrl: asset ? asset.browser_download_url : "",
          });
        }
      } catch (error) {
        console.warn("Could not load published GitHub releases.", error);
        if (updateCheckStatus) {
          updateCheckStatus.textContent =
            "Could not check for updates. Check your connection and try again.";
        }
        releaseList.replaceChildren();
        const failure = document.createElement("p");
        failure.className = "release-status";
        failure.textContent =
          "GitHub releases could not be loaded. Check your connection or browse releases on GitHub.";
        releaseList.append(failure);
      } finally {
        refreshReleasesButton.disabled = false;
      }
    }

    loadAppVersion().then(() => {
      if (releaseList) loadUpdates();
    });

    if (form) {
    function selectMode(selectedMode) {
      const changed = mode !== selectedMode;
      mode = selectedMode;
      const isPlaylist = mode === "playlist";
      singleTab.setAttribute("aria-selected", String(!isPlaylist));
      playlistTab.setAttribute("aria-selected", String(isPlaylist));
      urlLabel.textContent = isPlaylist ? "YouTube Playlist Link" : "YouTube Music Link";
      input.placeholder = isPlaylist
        ? "https://www.youtube.com/playlist?list=..."
        : "https://www.youtube.com/watch?v=...";
      if (changed) {
        button.textContent = isPlaylist ? "Convert Playlist" : "Convert to MP3";
      }
    }

    function setModeTabsDisabled(disabled) {
      singleTab.disabled = disabled;
      playlistTab.disabled = disabled;
    }

    singleTab.addEventListener("click", () => selectMode("single"));
    playlistTab.addEventListener("click", () => selectMode("playlist"));

    function validateModeUrl(rawUrl, selectedMode) {
      let parsedUrl;
      try {
        parsedUrl = new URL(rawUrl);
      } catch {
        return "Enter a valid YouTube link.";
      }
      const hostname = parsedUrl.hostname.toLowerCase();
      if (
        !["http:", "https:"].includes(parsedUrl.protocol)
        || !["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"].includes(hostname)
        || parsedUrl.username
        || parsedUrl.password
      ) {
        return "Enter a valid YouTube link.";
      }
      const isPlaylistUrl =
        hostname !== "youtu.be"
        && (
          parsedUrl.pathname.replace(/\/+$/, "") === "/playlist"
          || Boolean(parsedUrl.searchParams.get("list")?.trim())
        );
      if (selectedMode === "playlist" && !isPlaylistUrl) {
        return "Playlist mode only accepts a YouTube playlist link.";
      }
      if (
        selectedMode === "single"
        && hostname !== "youtu.be"
        && parsedUrl.pathname.replace(/\/+$/, "") === "/playlist"
      ) {
        return "Single mode accepts a music/video link, not a playlist link. Choose Playlist mode instead.";
      }
      return "";
    }

    zipDownload.addEventListener("click", () => {
      zipDownload.classList.add("clicked");
    });

    function showResults(
      items,
      resultMode,
      zipUrl,
      zipFilename,
      playlistTotal,
      status,
      skippedTracks,
      playlistTitle,
      playlistThumbnail,
      playlistCreator,
    ) {
      skippedList.replaceChildren();
      skippedSummary.hidden = skippedTracks.length === 0;
      const hasPlaylistSummary = resultMode === "playlist" && playlistTitle;
      playlistSummary.hidden = !hasPlaylistSummary;
      if (hasPlaylistSummary) {
        playlistSummaryTitle.textContent = playlistTitle;
        const creatorText = playlistCreator ? `by ${playlistCreator}` : "Playlist creator unavailable";
        playlistSummaryCreator.textContent = creatorText;
        if (playlistThumbnail) {
          playlistSummaryThumb.src = playlistThumbnail;
          playlistSummaryThumb.alt = `Thumbnail for ${playlistTitle}`;
          playlistSummaryThumb.hidden = false;
        } else {
          playlistSummaryThumb.removeAttribute("src");
          playlistSummaryThumb.hidden = true;
        }
      }
      if (skippedTracks.length) {
        skippedHeading.textContent = `Skipped tracks (${skippedTracks.length})`;
        if (items.length === 0) {
          emptyState.textContent =
            "No tracks were converted successfully. See skipped tracks above for details.";
        }
        for (const skipped of skippedTracks) {
          const entry = document.createElement("li");
          entry.textContent =
            `${skipped.index}. ${skipped.title}: ${friendlyErrorMessage(skipped.error)}`;
          skippedList.append(entry);
        }
      }
      if (items.length < renderedItems) {
        resultList.replaceChildren();
        renderedItems = 0;
        renderedBatch = 0;
        currentBatchItems = null;
      }
      zipDownload.hidden = resultMode !== "playlist" || !zipUrl;
      viewToolbar.hidden = resultMode !== "playlist";
      const safeZipFilename =
        zipFilename || "vferdzconverter-mp3youtubeplaylist.zip";
      downloadsMode.textContent = resultMode === "playlist"
        ? playlistTotal
          ? `${items.length} of ${playlistTotal} playlist tracks ready`
          : "Preparing playlist batches..."
        : "Single MP3";
      if (!zipDownload.hidden) {
        zipDownload.href = zipUrl;
        zipDownload.download = safeZipFilename;
        const zipDescription = status === "done"
          ? "Download the entire playlist as a ZIP"
          : "Download all ready playlist tracks as a ZIP";
        zipDownload.setAttribute("aria-label", zipDescription);
        zipDownload.title = zipDescription;
      } else {
        zipDownload.removeAttribute("href");
      }
      for (const [offset, item] of items.slice(renderedItems).entries()) {
        if (item.batch && item.batch !== renderedBatch) {
          const batchGroup = document.createElement("section");
          batchGroup.className = "batch-group";
          const batchHeading = document.createElement("h3");
          batchHeading.className = "batch-heading";
          const batchToggle = document.createElement("button");
          batchToggle.className = "batch-toggle";
          batchToggle.type = "button";
          batchToggle.setAttribute("aria-expanded", "true");
          batchToggle.setAttribute("aria-controls", `batch-items-${item.batch}`);
          batchToggle.setAttribute("aria-label", `Collapse batch ${item.batch}`);
          const batchLabel = document.createElement("span");
          batchLabel.textContent = `Batch ${item.batch}`;
          const chevron = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          chevron.classList.add("batch-chevron");
          chevron.setAttribute("viewBox", "0 0 24 24");
          chevron.setAttribute("aria-hidden", "true");
          const chevronPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
          chevronPath.setAttribute("d", "m9 18 6-6-6-6");
          chevron.append(chevronPath);
          batchToggle.append(chevron, batchLabel);
          const batchItems = document.createElement("div");
          batchItems.className = "batch-items";
          batchItems.id = `batch-items-${item.batch}`;
          const batchDownload = document.createElement("a");
          batchDownload.className = "download batch-download";
          batchDownload.href = `${zipUrl}?batch=${item.batch}`;
          const zipBaseName = safeZipFilename.replace(/\.zip$/i, "");
          batchDownload.download =
            `${zipBaseName}-batch-${item.batch}.zip`;
          batchDownload.setAttribute(
            "aria-label",
            `Download all MP3s in batch ${item.batch} as a ZIP`,
          );
          batchDownload.title = `Download all MP3s in batch ${item.batch} as a ZIP`;
          batchDownload.innerHTML =
            '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0 4-4m-4 4-4-4"></path><path d="M5 15v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"></path></svg><span>Download batch</span>';
          batchDownload.addEventListener("click", () => {
            batchDownload.classList.add("clicked");
          });
          batchToggle.addEventListener("click", () => {
            const expanded = batchToggle.getAttribute("aria-expanded") === "true";
            batchToggle.setAttribute("aria-expanded", String(!expanded));
            batchToggle.setAttribute(
              "aria-label",
              `${expanded ? "Expand" : "Collapse"} batch ${item.batch}`,
            );
            batchItems.hidden = expanded;
          });
          batchHeading.append(batchToggle, batchDownload);
          batchGroup.append(batchHeading, batchItems);
          resultList.append(batchGroup);
          currentBatchItems = batchItems;
          renderedBatch = item.batch;
        }
        const card = document.createElement("article");
        card.className = "result-item";

        const trackNumber = document.createElement("span");
        trackNumber.className = "track-number";
        trackNumber.textContent = String(renderedItems + offset + 1);
        trackNumber.setAttribute("aria-hidden", "true");
        card.append(trackNumber);

        if (item.thumbnail) {
          const image = document.createElement("img");
          image.className = "thumbnail";
          image.src = item.thumbnail;
          image.alt = `Thumbnail for ${item.title}`;
          image.addEventListener("error", () => image.remove());
          card.append(image);
        }

        const details = document.createElement("div");
        details.className = "result-details";
        const title = document.createElement("h2");
        title.className = "result-title";
        title.textContent = item.title;
        const size = document.createElement("p");
        size.className = "file-size";
        size.textContent = `MP3 file size: ${formatFileSize(item.file_size)}`;
        const link = document.createElement("a");
        link.className = "download track-download";
        link.href = item.download_url;
        link.download = `${item.title}.mp3`;
        link.addEventListener("click", () => {
          link.classList.add("clicked");
        });
        details.append(title, size);
        link.setAttribute("aria-label", `Download ${item.title} as MP3`);
        link.title = `Download ${item.title} as MP3`;
        link.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0 4-4m-4 4-4-4"></path><path d="M5 15v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"></path></svg>';
        if (resultMode === "single") {
          const downloadLabel = document.createElement("span");
          downloadLabel.textContent = "Download MP3";
          link.append(downloadLabel);
        }
        card.append(details, link);
        (currentBatchItems || resultList).append(card);
      }
      renderedItems = items.length;
      resultList.hidden = items.length === 0;
      resultList.classList.toggle("single-results", resultMode === "single");
      emptyState.hidden = items.length > 0;
    }

    function formatFileSize(bytes) {
      if (bytes < 1024) return `${bytes} B`;
      const units = ["KB", "MB", "GB", "TB"];
      let size = bytes;
      let unit = -1;
      do {
        size /= 1024;
        unit += 1;
      } while (size >= 1024 && unit < units.length - 1);
      return `${size.toFixed(1)} ${units[unit]}`;
    }

    function showError(message) {
      status.textContent = friendlyErrorMessage(message);
      status.classList.add("error");
      button.disabled = false;
      setModeTabsDisabled(false);
      progress.hidden = true;
      resultList.hidden = renderedItems === 0;
      emptyState.hidden = renderedItems > 0;
    }

    function friendlyErrorMessage(message) {
      const error = String(message || "").trim();
      const normalized = error.toLowerCase();
      if (/http error 403|http error 401|forbidden/.test(normalized)) {
        return "YouTube refused this download. The video may be restricted or YouTube may be temporarily blocking requests. Try again later or choose another video.";
      }
      if (/http error 429|too many requests/.test(normalized)) {
        return "YouTube is receiving too many requests right now. Please wait a while before trying again.";
      }
      if (/private video/.test(normalized)) {
        return "This video is private and cannot be downloaded. Try a public video instead.";
      }
      if (/sign in|not a bot|login required/.test(normalized)) {
        return "YouTube requires additional verification for this video. Try again later or choose another video.";
      }
      if (/no videos were found|empty playlist/.test(normalized)) {
        return "No downloadable videos were found in this playlist. Check the playlist link and availability.";
      }
      if (/video unavailable|not available|has been removed|does not exist/.test(normalized)) {
        return "This video is unavailable. It may have been removed or restricted; try another video.";
      }
      if (/ffmpeg/.test(normalized)) {
        return "Audio conversion could not be completed. Check that FFmpeg is installed and available, then try again.";
      }
      if (/timed out|timeout|connection reset|temporary failure|network is unreachable/.test(normalized)) {
        return "The connection to YouTube was interrupted. Check your internet connection and try again.";
      }
      if (!error || /^error:\s*$/i.test(error)) {
        return "The download could not be completed. Check the link and try again.";
      }
      return "The download could not be completed. Check that the link is available and try again.";
    }

    async function pollStatus(currentOperationId) {
      if (currentOperationId !== operationId) return;
      pollController = new AbortController();
      try {
        const response = await fetch("/api/status", {
          cache: "no-store",
          signal: pollController.signal,
        });
        const result = await response.json();
        if (currentOperationId !== operationId) return;
        status.classList.remove("error");
        status.textContent = result.message;
        progress.value = result.progress;
        progress.hidden = !["preparing", "downloading", "converting", "stopping"].includes(result.status);
        const isActive = ["preparing", "downloading", "converting", "stopping"].includes(result.status);
        stopButton.hidden = !isActive;
        stopButton.disabled = result.status === "stopping";
        conversionNotice.hidden = !isActive;
        if (result.status !== "stopping" && isActive) {
          conversionNotice.textContent = "Please wait while conversion finishes. Keep this page open; playlist tracks are processed one at a time.";
        }
        showResults(
          result.items,
          result.mode,
          result.zip_url,
          result.zip_filename,
          result.playlist_total,
          result.status,
          result.skipped_tracks || [],
          result.playlist_title,
          result.playlist_thumbnail,
          result.playlist_creator,
        );
        if (result.status === "done") {
          button.disabled = false;
          button.textContent = "Convert Again";
          setModeTabsDisabled(false);
          activeRequestId = "";
          clearTimeout(timer);
        } else if (result.status === "error") {
          showError(result.error || result.message);
          button.textContent = "Convert Again";
          activeRequestId = "";
          clearTimeout(timer);
        } else if (result.status === "stopped") {
          button.disabled = false;
          button.textContent = mode === "playlist" ? "Convert Playlist" : "Convert to MP3";
          stopButton.hidden = true;
          stopButton.disabled = false;
          conversionNotice.hidden = true;
          setModeTabsDisabled(false);
          activeRequestId = "";
          clearTimeout(timer);
        } else {
          timer = setTimeout(() => pollStatus(currentOperationId), 700);
        }
      } catch (error) {
        if (error.name === "AbortError" || currentOperationId !== operationId) return;
        showError("Could not connect to the local app. Restart it and try again.");
        stopButton.hidden = true;
        stopButton.disabled = false;
        conversionNotice.hidden = true;
        button.textContent = "Convert Again";
        activeRequestId = "";
        clearTimeout(timer);
      }
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const linkError = validateModeUrl(input.value.trim(), mode);
      if (linkError) {
        status.textContent = linkError;
        status.classList.add("error");
        input.setAttribute("aria-invalid", "true");
        return;
      }
      input.removeAttribute("aria-invalid");
      clearTimeout(timer);
      if (pollController) pollController.abort();
      const currentOperationId = ++operationId;
      activeRequestId = crypto.randomUUID();
      const requestId = activeRequestId;
      zipDownload.hidden = true;
      zipDownload.removeAttribute("href");
      zipDownload.classList.remove("clicked");
      playlistSummary.hidden = true;
      resultList.hidden = true;
      resultList.classList.remove("single-results");
      resultList.replaceChildren();
      skippedSummary.hidden = true;
      skippedList.replaceChildren();
      renderedItems = 0;
      renderedBatch = 0;
      currentBatchItems = null;
      emptyState.hidden = false;
      emptyState.textContent = mode === "playlist"
        ? "Playlist tracks will appear here as each one is converted."
        : "Your MP3 download will appear here when conversion is complete.";
      status.classList.remove("error");
      status.textContent = "Starting download...";
      button.textContent = mode === "playlist" ? "Convert Playlist" : "Convert to MP3";
      progress.value = 0;
      progress.hidden = false;
      button.disabled = true;
      stopButton.hidden = true;
      stopButton.disabled = false;
      conversionNotice.hidden = false;
      setModeTabsDisabled(true);
      try {
        const response = await fetch("/api/download", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: input.value.trim(), mode, request_id: requestId })
        });
        const result = await response.json();
        if (currentOperationId !== operationId) return;
        if (!response.ok) {
          showError(result.error || "Could not start the download.");
          stopButton.hidden = true;
          stopButton.disabled = false;
          conversionNotice.hidden = true;
          button.textContent = "Convert Again";
          activeRequestId = "";
          return;
        }
        stopButton.hidden = false;
        await pollStatus(currentOperationId);
      } catch (error) {
        if (currentOperationId !== operationId) return;
        showError("Could not connect to the local app. Restart it and try again.");
        stopButton.hidden = true;
        stopButton.disabled = false;
        conversionNotice.hidden = true;
        button.textContent = "Convert Again";
        activeRequestId = "";
      }
    });

    stopButton.addEventListener("click", async () => {
      if (!activeRequestId || stopButton.disabled) return;
      stopButton.disabled = true;
      status.classList.remove("error");
      status.textContent = "Stopping conversion...";
      conversionNotice.textContent = "Stopping the current conversion...";
      try {
        const response = await fetch("/api/stop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ request_id: activeRequestId }),
        });
        const result = await response.json();
        if (!response.ok || !result.stopped) {
          throw new Error(result.error || "The conversion could not be stopped.");
        }
      } catch (error) {
        status.textContent = error.message || "Could not stop the conversion.";
        status.classList.add("error");
        stopButton.disabled = false;
        conversionNotice.textContent = "Please wait while conversion finishes. Keep this page open; playlist tracks are processed one at a time.";
      }
    });

    window.addEventListener("pagehide", () => {
      if (!activeRequestId) return;
      const body = new Blob(
        [JSON.stringify({ request_id: activeRequestId })],
        { type: "application/json" },
      );
      if (!navigator.sendBeacon("/api/stop", body)) {
        fetch("/api/stop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          keepalive: true,
        });
      }
    });
    }
