import { start, stop, lastChannelMessageTime } from "./webrtc.js";

export var pc = null;
export var dc = null;
const statusPollMs = 3000;
let isAuthenticated = false;

function localToken() {
  return $("#local-token").val() || "";
}

function apiHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Local-Token": localToken(),
  };
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
    $("#command-result").text(`Battery ${payload.status.batteryPercent}% - ${charging}`);
    $("#device-voltage").text(`${payload.status.deviceVoltage ?? 0}V`);
    $("#sentry-result").text(`Sentry mode: ${sentry}`);
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
    $("#command-result").text(`Requested: ${payload.requested}`);
    if (name === "sentry_toggle" && payload.ok) {
      $("#sentry-result").text(`Sentry mode: ${payload.enabled ? "enabled" : "disabled"}`);
    }
    refreshVehicleStatus();
  } catch (e) {
    $("#command-result").text("Command request failed");
  }
}

async function refreshAuthStatus() {
  try {
    const response = await fetch("/api/auth/status");
    if (!response.ok) {
      isAuthenticated = false;
      return;
    }
    const payload = await response.json();
    isAuthenticated = payload.authenticated;
    if (payload.setupRequired) {
      $("#auth-result").text("Setup required: enter username/password and press Setup");
    } else if (isAuthenticated) {
      $("#auth-result").text("Authenticated");
    } else {
      $("#auth-result").text("Not authenticated");
    }
  } catch (_e) {
    isAuthenticated = false;
  }
}

async function doAuth(path) {
  const username = $("#auth-username").val() || "";
  const password = $("#auth-password").val() || "";
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({ username, password }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      $("#auth-result").text(payload.error || `Auth failed (${response.status})`);
      isAuthenticated = false;
      return;
    }
    await refreshAuthStatus();
  } catch (_e) {
    $("#auth-result").text("Auth request failed");
    isAuthenticated = false;
  }
}

setInterval( () => {
  const dt = new Date().getTime();
  if ((dt - lastChannelMessageTime) > 1000) {
    $(".pre-blob").removeClass('blob');
    $("#battery").text("-");
    $("#ping-time").text('-');
    $("video")[0].load();
  }
}, 5000);

$("#cmd-remote-start").on("click", () => sendCommand("remote_start"));
$("#cmd-charge-start").on("click", () => sendCommand("charge_start"));
$("#cmd-charge-stop").on("click", () => sendCommand("charge_stop"));
$("#cmd-sentry-toggle").on("click", () => sendCommand("sentry_toggle"));
$("#auth-login").on("click", () => doAuth("/api/auth/login"));
$("#auth-setup").on("click", () => doAuth("/api/auth/setup"));
setInterval(refreshVehicleStatus, statusPollMs);
setInterval(refreshAuthStatus, statusPollMs);
refreshAuthStatus();
refreshVehicleStatus();

start(pc, dc);
