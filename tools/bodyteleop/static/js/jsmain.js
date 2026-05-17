import { start, stop, lastChannelMessageTime } from "./webrtc.js";

export var pc = null;
export var dc = null;
const statusPollMs = 3000;
let isAuthenticated = true;
let videoSearchTimer = null;
let liveVideoTimeout = null;
let liveVideoVisible = false;

function apiHeaders() {
  return {
    "Content-Type": "application/json",
  };
}

function snapshotUrl(cameraKey) {
  const params = new URLSearchParams({
    camera: cameraKey,
    t: String(Date.now()),
  });
  return `/api/camera/snapshot?${params.toString()}`;
}

function showLiveVideo() {
  liveVideoVisible = true;
  $("#video").removeClass("d-none");
  $("#camera-fallback").addClass("d-none");
  $("#camera-status").text("Live video connected");
}

function showSnapshotFallback(message) {
  liveVideoVisible = false;
  $("#video").addClass("d-none");
  $("#camera-fallback").removeClass("d-none");
  if (message) {
    $("#camera-status").text(message);
  }
}

async function refreshCameraSnapshot(message) {
  const cameraKey = $("#snapshot-camera").val() || "wide";
  const img = $("#camera-snapshot")[0];
  if (!img) {
    return;
  }

  showSnapshotFallback(message || "Loading snapshot...");
  $("#camera-status").text(`Loading ${cameraKey} snapshot...`);

  await new Promise((resolve) => {
    const clearHandlers = () => {
      img.onload = null;
      img.onerror = null;
    };
    img.onload = () => {
      clearHandlers();
      $("#camera-status").text(`${cameraKey} snapshot updated`);
      resolve();
    };
    img.onerror = () => {
      clearHandlers();
      $("#camera-status").text(`${cameraKey} snapshot unavailable`);
      resolve();
    };
    img.src = snapshotUrl(cameraKey);
  });
}

function scheduleSnapshotFallback(message) {
  if (liveVideoTimeout !== null) {
    clearTimeout(liveVideoTimeout);
  }
  liveVideoTimeout = window.setTimeout(() => {
    const video = $("#video")[0];
    if (!video || liveVideoVisible || video.readyState >= 2) {
      return;
    }
    refreshCameraSnapshot(message || "Live video unavailable offroad. Showing snapshot fallback.");
  }, 5000);
}

function setupCameraFallback() {
  const video = $("#video")[0];
  if (!video) {
    return;
  }

  video.addEventListener("loadeddata", () => {
    showLiveVideo();
  });
  video.addEventListener("playing", () => {
    showLiveVideo();
  });
  video.addEventListener("stalled", () => {
    refreshCameraSnapshot("Live video stalled. Showing snapshot fallback.");
  });
  video.addEventListener("emptied", () => {
    scheduleSnapshotFallback("Live video unavailable offroad. Showing snapshot fallback.");
  });
  video.addEventListener("error", () => {
    refreshCameraSnapshot("Live video failed. Showing snapshot fallback.");
  });
  $("#snapshot-refresh").on("click", () => refreshCameraSnapshot());
  $("#snapshot-camera").on("change", () => refreshCameraSnapshot());
  scheduleSnapshotFallback("Live video unavailable offroad. Showing snapshot fallback.");
}

function latestCommandStatus(commandStatuses, names) {
  let latest = null;
  names.forEach((name) => {
    const status = commandStatuses[name];
    if (!status || !status.state) {
      return;
    }
    const updatedAt = Number(status.updatedAt || 0);
    if (!latest || updatedAt >= latest.updatedAt) {
      latest = { name, status, updatedAt };
    }
  });
  return latest;
}

function formatCommandStatus(name, status) {
  if (!status || !status.state) {
    return "";
  }

  const reason = status.reason || "updated";
  if (name === "remote_start") {
    return `remote start ${status.state}: ${reason}`;
  }
  if (name === "charge_start") {
    return `charge start ${status.state}: ${reason}`;
  }
  if (name === "charge_stop") {
    return `charge stop ${status.state}: ${reason}`;
  }
  if (name === "sentry_toggle") {
    return `sentry ${status.state}: ${reason}`;
  }
  return `${name} ${status.state}: ${reason}`;
}

async function refreshVehicleStatus() {
  if (!isAuthenticated) {
    return;
  }
  try {
    const response = await fetch("/api/status", { headers: apiHeaders() });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    if (!payload.ok) {
      return;
    }

    const charging = payload.status.charging ? "charging" : "not charging";
    const sentry = payload.status.sentryEnabled ? "enabled" : "disabled";
    const commandStatuses = payload.status.commandStatuses || {};
    const latestVehicleCommand = latestCommandStatus(commandStatuses, ["remote_start", "charge_start", "charge_stop"]);
    const commandText = latestVehicleCommand ? ` - ${formatCommandStatus(latestVehicleCommand.name, latestVehicleCommand.status)}` : "";
    const sentryStatus = commandStatuses.sentry_toggle || {};
    const sentryText = sentryStatus.state ? ` (${formatCommandStatus("sentry_toggle", sentryStatus)})` : "";
    $("#command-result").text(`Battery ${payload.status.batteryPercent}% - ${charging}${commandText}`);
    $("#device-voltage").text(`${payload.status.deviceVoltage ?? 0}V`);
    $("#sentry-result").text(`Sentry mode: ${sentry}${sentryText}`);
  } catch (e) {
    // Ignore intermittent status polling failures.
  }
}

async function sendCommand(name) {
  if (!isAuthenticated) {
    $("#command-result").text("Please login first");
    return;
  }
  const body = {};
  if (name === "remote_start") {
    body.ac = {
      enabled: $("#ac-enabled").is(":checked"),
      temperatureC: Number($("#ac-temp-c").val() || 21),
      fanLevel: Number($("#ac-fan-level").val() || 2),
      frontDefrost: $("#ac-front-defrost").is(":checked"),
    };
  }

  try {
    const response = await fetch(`/api/command/${name}`, {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      $("#command-result").text(`Command failed (${response.status})`);
      return;
    }
    const payload = await response.json();
    const resultText = payload.state ? formatCommandStatus(payload.requested, payload) : `Requested: ${payload.requested}`;
    $("#command-result").text(resultText);
    if (name === "sentry_toggle" && payload.ok && Object.prototype.hasOwnProperty.call(payload, "enabled")) {
      const sentryMode = payload.enabled ? "enabled" : "disabled";
      const sentryState = payload.state ? ` (${formatCommandStatus("sentry_toggle", payload)})` : "";
      $("#sentry-result").text(`Sentry mode: ${sentryMode}${sentryState}`);
    }
    refreshVehicleStatus();
  } catch (e) {
    $("#command-result").text("Command request failed");
  }
}

function setActiveTab(name) {
  const capture = name === "capture";
  const videos = name === "videos";
  $("#controls-tab").toggleClass("d-none", capture || videos);
  $("#capture-tab").toggleClass("d-none", !capture);
  $("#videos-tab").toggleClass("d-none", !videos);
  $("#tab-controls").toggleClass("btn-light active", !capture && !videos).toggleClass("btn-outline-light", capture || videos);
  $("#tab-capture").toggleClass("btn-light active", capture).toggleClass("btn-outline-light", !capture);
  $("#tab-videos").toggleClass("btn-light active", videos).toggleClass("btn-outline-light", !videos);

  if (videos) {
    refreshVideoLibrary();
  }
}

async function refreshCaptureStatus() {
  if (!isAuthenticated) {
    return;
  }
  try {
    const response = await fetch("/api/capture/status", { headers: apiHeaders() });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    const capture = payload.capture || {};
    if (capture.running) {
      $("#capture-result").text(`Capturing ${capture.label} -> ${capture.outFile}`);
    } else if (capture.outFile) {
      $("#capture-result").text(`Capture stopped -> ${capture.outFile}`);
    } else {
      $("#capture-result").text("Capture idle");
    }
  } catch (_e) {
    $("#capture-result").text("Capture status unavailable");
  }
}

async function startCapture() {
  if (!isAuthenticated) {
    $("#capture-result").text("Please login first");
    return;
  }
  const body = {
    label: $("#capture-label").val() || "capture",
    seconds: Number($("#capture-seconds").val() || 180),
  };
  try {
    const response = await fetch("/api/capture/start", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      $("#capture-result").text(payload.error || `Capture failed (${response.status})`);
      return;
    }
    refreshCaptureStatus();
  } catch (_e) {
    $("#capture-result").text("Capture request failed");
  }
}

async function stopCapture() {
  if (!isAuthenticated) {
    $("#capture-result").text("Please login first");
    return;
  }
  try {
    const response = await fetch("/api/capture/stop", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({}),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      $("#capture-result").text(payload.error || `Stop failed (${response.status})`);
      return;
    }
    refreshCaptureStatus();
  } catch (_e) {
    $("#capture-result").text("Stop request failed");
  }
}

function formatVideoTime(unixSeconds) {
  if (!unixSeconds) {
    return "Unknown time";
  }
  return new Date(unixSeconds * 1000).toLocaleString();
}

function buildVideoUrl(routeName, segmentNum, cameraKey) {
  const params = new URLSearchParams({
    route: routeName,
    segment: String(segmentNum),
    camera: cameraKey,
  });
  const token = localToken();
  if (token) {
    params.set("token", token);
  }
  return `/api/videos/stream?${params.toString()}`;
}

function playLibraryVideo(routeName, segmentNum, cameraKey, cameraLabel) {
  const video = $("#library-video")[0];
  if (!video) {
    return;
  }
  video.src = buildVideoUrl(routeName, segmentNum, cameraKey);
  video.load();
  video.play().catch(() => {});
  $("#library-video-label").text(`Playing ${routeName} segment ${segmentNum} (${cameraLabel})`);
}

async function setVideoProtection(routeName, segmentNum, cameraKey, shouldProtect) {
  if (!isAuthenticated) {
    $("#videos-result").text("Please login first");
    return;
  }

  try {
    const response = await fetch("/api/videos/protect", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({
        route: routeName,
        segment: segmentNum,
        camera: cameraKey,
        protected: shouldProtect,
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      $("#videos-result").text(payload.error || `Protection update failed (${response.status})`);
      return;
    }
    $("#videos-result").text(`${shouldProtect ? "Protected" : "Unprotected"} ${routeName} segment ${segmentNum} (${cameraKey})`);
    refreshVideoLibrary();
  } catch (_e) {
    $("#videos-result").text("Protection update failed");
  }
}

async function deleteVideo(routeName, segmentNum, cameraKey, cameraLabel) {
  if (!isAuthenticated) {
    $("#videos-result").text("Please login first");
    return;
  }

  const basicConfirm = window.confirm(`Delete ${routeName} segment ${segmentNum} (${cameraLabel})?`);
  if (!basicConfirm) {
    return;
  }

  let force = false;
  try {
    const response = await fetch("/api/videos/delete", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({
        route: routeName,
        segment: segmentNum,
        camera: cameraKey,
        force,
      }),
    });
    const payload = await response.json();
    if (response.status === 409 && payload.protected) {
      const protectedConfirm = window.confirm(`${payload.warning}\n\nDelete anyway?`);
      if (!protectedConfirm) {
        $("#videos-result").text("Protected video kept");
        return;
      }

      force = true;
      const forcedResponse = await fetch("/api/videos/delete", {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({
          route: routeName,
          segment: segmentNum,
          camera: cameraKey,
          force,
        }),
      });
      const forcedPayload = await forcedResponse.json();
      if (!forcedResponse.ok || !forcedPayload.ok) {
        $("#videos-result").text(forcedPayload.error || `Delete failed (${forcedResponse.status})`);
        return;
      }
    } else if (!response.ok || !payload.ok) {
      $("#videos-result").text(payload.error || `Delete failed (${response.status})`);
      return;
    }

    $("#videos-result").text(`Deleted ${routeName} segment ${segmentNum} (${cameraLabel})`);
    refreshVideoLibrary();
  } catch (_e) {
    $("#videos-result").text("Delete request failed");
  }
}

function renderVideoLibrary(routes) {
  const container = $("#video-route-list");
  container.empty();

  if (!routes.length) {
    container.append('<div class="command-result">No matching videos found.</div>');
    return;
  }

  routes.forEach((route) => {
    const card = $('<div class="video-route-card"></div>');
    card.append(`
      <div class="video-route-header">
        <div class="video-route-name">${route.displayName}</div>
        <div class="video-route-time">${route.segmentCount} segment(s) - ${formatVideoTime(route.modifiedAt)}</div>
      </div>
    `);

    const segmentList = $('<div class="video-segment-list"></div>');
    route.segments.forEach((segment) => {
      const segmentRow = $('<div class="video-segment"></div>');
      segmentRow.append(`<div class="video-segment-name">Segment ${segment.segmentNum}</div>`);

      const actions = $('<div class="video-camera-actions"></div>');
      segment.cameras.forEach((camera) => {
        const item = $('<div class="video-camera-item"></div>');
        if (camera.protected) {
          item.append('<span class="video-protected-badge">Protected</span>');
        }

        const playButton = $(`<button class="btn btn-sm btn-outline-light">${camera.label}</button>`);
        playButton.on("click", () => playLibraryVideo(route.routeName, segment.segmentNum, camera.key, camera.label));
        item.append(playButton);

        const protectButton = $(`<button class="btn btn-sm ${camera.protected ? "btn-secondary" : "btn-success"}">${camera.protected ? "Unprotect" : "Protect"}</button>`);
        protectButton.on("click", () => setVideoProtection(route.routeName, segment.segmentNum, camera.key, !camera.protected));
        item.append(protectButton);

        const deleteButton = $('<button class="btn btn-sm btn-danger">Delete</button>');
        deleteButton.on("click", () => deleteVideo(route.routeName, segment.segmentNum, camera.key, camera.label));
        item.append(deleteButton);

        actions.append(item);
      });

      segmentRow.append(actions);
      segmentList.append(segmentRow);
    });

    card.append(segmentList);
    container.append(card);
  });
}

async function refreshVideoLibrary() {
  if (!isAuthenticated) {
    $("#videos-result").text("Please login first");
    return;
  }

  const query = ($("#video-search").val() || "").trim();
  const params = new URLSearchParams({ limit: "80" });
  if (query) {
    params.set("query", query);
  }

  $("#videos-result").text("Loading video library...");
  try {
    const response = await fetch(`/api/videos?${params.toString()}`, { headers: apiHeaders() });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      $("#videos-result").text(payload.error || `Video library failed (${response.status})`);
      return;
    }

    renderVideoLibrary(payload.routes || []);
    $("#videos-result").text(`Showing ${payload.routes.length} route(s) from ${payload.libraryRoot}`);
  } catch (_e) {
    $("#videos-result").text("Video library unavailable");
  }
}

async function refreshAuthStatus() {
  isAuthenticated = true;
  $("#auth-result").text("Local network access enabled");
}

async function doAuth(path) {
  await refreshAuthStatus();
}

setInterval( () => {
  const dt = new Date().getTime();
  if ((dt - lastChannelMessageTime) > 1000) {
    $(".pre-blob").removeClass('blob');
    $("#battery").text("-");
    $("#ping-time").text('-');
    $("video")[0].load();
    scheduleSnapshotFallback("Live video unavailable offroad. Showing snapshot fallback.");
  }
}, 5000);

$("#cmd-remote-start").on("click", () => sendCommand("remote_start"));
$("#cmd-charge-start").on("click", () => sendCommand("charge_start"));
$("#cmd-charge-stop").on("click", () => sendCommand("charge_stop"));
$("#cmd-sentry-toggle").on("click", () => sendCommand("sentry_toggle"));
$("#tab-controls").on("click", () => setActiveTab("controls"));
$("#tab-capture").on("click", () => setActiveTab("capture"));
$("#tab-videos").on("click", () => setActiveTab("videos"));
$("#capture-start").on("click", startCapture);
$("#capture-stop").on("click", stopCapture);
$("#videos-refresh").on("click", refreshVideoLibrary);
$("#video-search").on("input", () => {
  if (videoSearchTimer !== null) {
    clearTimeout(videoSearchTimer);
  }
  videoSearchTimer = window.setTimeout(refreshVideoLibrary, 250);
});
setInterval(refreshVehicleStatus, statusPollMs);
setInterval(refreshAuthStatus, statusPollMs);
setInterval(refreshCaptureStatus, statusPollMs);
refreshAuthStatus();
refreshVehicleStatus();
refreshCaptureStatus();
setupCameraFallback();

start(pc, dc);
