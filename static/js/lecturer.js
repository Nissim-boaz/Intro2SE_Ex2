let chartInstance = null;
let statsInterval = null;
let qrTimerInterval = null;
let secondsRemainingInWindow = 6;
let windowDuration = 6;

document.addEventListener("DOMContentLoaded", () => {
  initChart();
  startQrLoop();
  startStatsPolling();
});

// Start Session Form Handler
async function handleStartSession(e) {
  e.preventDefault();
  const title = document.getElementById("session-title-input").value;
  const duration = document.getElementById("session-duration-input").value;
  const btn = document.getElementById("btn-start");
  btn.disabled = true;
  btn.textContent = "פותח סשן...";

  try {
    const res = await fetch("/sessions/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, duration })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      window.location.reload();
    } else {
      alert("שגיאה בפתיחת הסשן: " + (data.error || "שגיאה לא ידועה"));
      btn.disabled = false;
      btn.textContent = "התחל נוכחות";
    }
  } catch (err) {
    alert("שגיאת תקשורת: " + err.message);
    btn.disabled = false;
    btn.textContent = "התחל נוכחות";
  }
}

// Close Session Handler
async function closeSession(sessionId) {
  if (!confirm("האם אתה בטוח שברצונך לסיים את סשן הנוכחות?")) return;

  const btn = document.getElementById("btn-close-session");
  if (btn) btn.disabled = true;

  try {
    const res = await fetch(`/sessions/${sessionId}/close`, { method: "POST" });
    const data = await res.json();
    if (res.ok && data.success) {
      window.location.reload();
    } else {
      alert("שגיאה בסגירת הסשן: " + (data.error || "שגיאה לא ידועה"));
      if (btn) btn.disabled = false;
    }
  } catch (err) {
    alert("שגיאת תקשורת: " + err.message);
    if (btn) btn.disabled = false;
  }
}

// QR Code Rotation Loop (F2)
async function fetchCurrentQrToken() {
  const qrImg = document.getElementById("qr-image");
  if (!qrImg) return;

  try {
    const res = await fetch("/sessions/active/token");
    if (!res.ok) return;
    const data = await res.json();
    if (data.active) {
      secondsRemainingInWindow = data.seconds_remaining;
      windowDuration = data.window_duration || 6;
      // Refresh QR image with timestamp to bypass cache
      qrImg.src = `/sessions/active/qr.png?_t=${Date.now()}`;
      
      const directLink = document.getElementById("qr-direct-link");
      if (directLink && data.attend_url) {
        directLink.href = data.attend_url;
      }

      updateQrTimerDisplay();
    }
  } catch (e) {
    console.error("Error fetching QR token:", e);
  }
}

function startQrLoop() {
  const qrImg = document.getElementById("qr-image");
  if (!qrImg) return;

  // Initial fetch
  fetchCurrentQrToken();

  // Tick every second to update progress bar and fetch on window change
  qrTimerInterval = setInterval(() => {
    secondsRemainingInWindow -= 1;
    if (secondsRemainingInWindow <= 0) {
      fetchCurrentQrToken();
    } else {
      updateQrTimerDisplay();
    }
  }, 1000);
}

function updateQrTimerDisplay() {
  const secondsEl = document.getElementById("qr-seconds");
  const progressEl = document.getElementById("qr-progress");
  if (secondsEl) secondsEl.textContent = `${secondsRemainingInWindow} שניות`;
  if (progressEl) {
    const pct = Math.max(0, Math.min(100, (secondsRemainingInWindow / windowDuration) * 100));
    progressEl.style.width = `${pct}%`;
  }
}

// Live Stats Polling every 2 seconds
function startStatsPolling() {
  const tableCount = document.getElementById("attendees-table-count");
  if (!tableCount) return; // Not in active session view

  // Poll immediately and then every 2 seconds
  fetchStats();
  statsInterval = setInterval(fetchStats, 2000);
}

async function fetchStats() {
  try {
    const res = await fetch("/api/dashboard/stats");
    if (!res.ok) return;
    const data = await res.json();
    if (!data.active) return;

    // Update session countdown
    const timeRemText = document.getElementById("time-remaining-text");
    if (timeRemText && data.remaining_seconds !== undefined) {
      const mins = Math.floor(data.remaining_seconds / 60);
      const secs = data.remaining_seconds % 60;
      timeRemText.textContent = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }

    // Update Counter Boxes
    document.getElementById("stat-total").textContent = data.total_attendees;
    document.getElementById("stat-present").textContent = data.present_count;
    document.getElementById("stat-suspicious").textContent = data.suspicious_count;
    document.getElementById("stat-rejected").textContent = data.rejected_attempts.length;
    document.getElementById("attendees-table-count").textContent = data.total_attendees;
    document.getElementById("rejected-table-count").textContent = data.rejected_attempts.length;

    // Update Attendees Table
    renderAttendeesTable(data.attendees);

    // Update Rejected Table
    renderRejectedTable(data.rejected_attempts);

    // Update Chart
    if (chartInstance && data.chart) {
      chartInstance.data.labels = data.chart.labels;
      chartInstance.data.datasets[0].data = data.chart.values;
      chartInstance.update();
    }
  } catch (err) {
    console.error("Error polling stats:", err);
  }
}

function renderAttendeesTable(attendees) {
  const tbody = document.getElementById("attendees-tbody");
  if (!tbody) return;

  if (!attendees || attendees.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">טרם נרשמה נוכחות</td></tr>`;
    return;
  }

  tbody.innerHTML = attendees.map(a => {
    const isSuspicious = a.status === "suspicious";
    const rowClass = isSuspicious ? "suspicious" : "";
    const badge = isSuspicious
      ? `<span class="badge badge-danger">חשוד (מחוץ לקמפוס)</span>`
      : `<span class="badge badge-success">נוכח</span>`;

    let actionBtn = "";
    if (isSuspicious) {
      actionBtn = `<button class="btn btn-success btn-sm" onclick="approveSuspicious(${a.id})">אישור</button>`;
    } else if (a.approved_at) {
      actionBtn = `<span class="badge badge-success">אושר ידנית</span>`;
    } else {
      actionBtn = `<span style="color: var(--text-muted);">-</span>`;
    }

    const timeStr = a.timestamp ? a.timestamp.substring(11, 19) : "";

    return `
      <tr class="${rowClass}">
        <td><strong>${escapeHtml(a.student_name)}</strong></td>
        <td>${escapeHtml(a.email)}</td>
        <td>${timeStr}</td>
        <td><code>${escapeHtml(a.ip_address)}</code></td>
        <td>${badge}</td>
        <td>${actionBtn}</td>
      </tr>
    `;
  }).join("");
}

function renderRejectedTable(rejected) {
  const tbody = document.getElementById("rejected-tbody");
  if (!tbody) return;

  if (!rejected || rejected.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">אין ניסיונות שנדחו</td></tr>`;
    return;
  }

  tbody.innerHTML = rejected.map(r => {
    const timeStr = r.timestamp ? r.timestamp.substring(11, 19) : "";
    return `
      <tr>
        <td>${escapeHtml(r.student_name || "-")}</td>
        <td>${escapeHtml(r.email)}</td>
        <td>${timeStr}</td>
        <td><code>${escapeHtml(r.ip_address)}</code></td>
        <td><span class="badge badge-warning">${escapeHtml(r.reason)}</span></td>
      </tr>
    `;
  }).join("");
}

// Approve Suspicious Attendance (F10)
async function approveSuspicious(attendanceId) {
  try {
    const res = await fetch(`/api/attendance/${attendanceId}/approve`, {
      method: "POST"
    });
    const data = await res.json();
    if (res.ok && data.success) {
      fetchStats(); // Instantly update view
    } else {
      alert("שגיאה באישור הנוכחות: " + (data.error || "שגיאה"));
    }
  } catch (e) {
    alert("שגיאת תקשורת: " + e.message);
  }
}

// Chart.js Setup
function initChart() {
  const canvas = document.getElementById("attendanceChart");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  chartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [{
        label: "נוכחים מצטברים",
        data: [],
        borderColor: "#1a73e8",
        backgroundColor: "rgba(26, 115, 232, 0.1)",
        tension: 0.3,
        fill: true,
        pointBackgroundColor: "#1a73e8",
        pointRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          beginAtZero: true,
          ticks: { stepSize: 1, precision: 0 }
        },
        x: {
          grid: { display: false }
        }
      },
      plugins: {
        legend: { display: false }
      }
    }
  });
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/[&<>"']/g, m => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[m]));
}


function toggleQrFullscreen() {
  const elem = document.getElementById("qr-main-container");
  if (!elem) return;

  if (!document.fullscreenElement) {
    if (elem.requestFullscreen) {
      elem.requestFullscreen();
    } else if (elem.webkitRequestFullscreen) {
      elem.webkitRequestFullscreen();
    }
  } else {
    if (document.exitFullscreen) {
      document.exitFullscreen();
    }
  }
}
