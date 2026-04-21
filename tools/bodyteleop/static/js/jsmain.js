import { handleKeyX, executePlan } from "./controls.js";
import { start, stop, lastChannelMessageTime, playSoundRequest } from "./webrtc.js";

export var pc = null;
export var dc = null;
const statusPollMs = 3000;

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
    $("#command-result").text(`Battery ${payload.status.batteryPercent}% - ${charging}`);
  } catch (e) {
    // Ignore intermittent status polling failures.
  }
}

async function sendCommand(name) {
  try {
    const response = await fetch(`/api/command/${name}`, {
      method: "POST",
      headers: apiHeaders(),
      body: "{}",
    });
    if (!response.ok) {
      $("#command-result").text(`Command failed (${response.status})`);
      return;
    }
    const payload = await response.json();
    $("#command-result").text(`Requested: ${payload.requested}`);
    refreshVehicleStatus();
  } catch (e) {
    $("#command-result").text("Command request failed");
  }
}

document.addEventListener('keydown', (e)=>(handleKeyX(e.key.toLowerCase(), 1)));
document.addEventListener('keyup', (e)=>(handleKeyX(e.key.toLowerCase(), 0)));
$(".keys").bind("mousedown touchstart", (e)=>handleKeyX($(e.target).attr('id').replace('key-', ''), 1));
$(".keys").bind("mouseup touchend", (e)=>handleKeyX($(e.target).attr('id').replace('key-', ''), 0));
$("#plan-button").click(executePlan);
$(".sound").click((e)=>{
  const sound = $(e.target).attr('id').replace('sound-', '')
  return playSoundRequest(sound);
});

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
setInterval(refreshVehicleStatus, statusPollMs);
refreshVehicleStatus();

start(pc, dc);
