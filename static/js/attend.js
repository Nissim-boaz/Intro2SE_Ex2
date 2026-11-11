let cookieSecondsRemaining = 300;
let cookieInterval = null;

document.addEventListener("DOMContentLoaded", () => {
  startCookieCountdown();
});

function startCookieCountdown() {
  const timerEl = document.getElementById("cookie-timer");
  if (!timerEl) return;

  cookieInterval = setInterval(() => {
    cookieSecondsRemaining -= 1;
    if (cookieSecondsRemaining <= 0) {
      clearInterval(cookieInterval);
      timerEl.textContent = "פג תוקף";
      showResult("danger", "פג תוקף הסריקה (5 דקות). יש לסרוק מחדש את ה-QR מהלוח.");
      const signinSec = document.getElementById("signin-section");
      if (signinSec) signinSec.style.display = "none";
    } else {
      const mins = Math.floor(cookieSecondsRemaining / 60);
      const secs = cookieSecondsRemaining % 60;
      timerEl.textContent = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }
  }, 1000);
}

// Google Identity Services callback (for real Google OAuth)
async function handleGoogleCredentialResponse(response) {
  if (!response || !response.credential) {
    showResult("danger", "שגיאה בקבלת אימות מ-Google");
    return;
  }
  await submitAttendanceToken(response.credential);
}

// Submit token to backend
async function submitAttendanceToken(token) {
  const signinSec = document.getElementById("signin-section");
  if (signinSec) signinSec.style.opacity = "0.5";

  showResult("warning", "מאמת נתונים ורושם נוכחות...");

  try {
    const res = await fetch("/attend/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ google_token: token })
    });

    const data = await res.json();

    if (signinSec) signinSec.style.display = "none";

    if (res.ok && data.success) {
      if (data.already_registered) {
        showResult("warning", `ℹ️ ${data.message}`);
      } else if (data.status === "suspicious") {
        showResult("warning", `⚠️ ${data.message}`);
      } else {
        showResult("success", `✅ ${data.message} שלום ${data.attendance.student_name}!`);
      }
    } else {
      showResult("danger", `❌ ${data.message || "שגיאה ברישום הנוכחות"}`);
    }
  } catch (err) {
    showResult("danger", `שגיאת תקשורת: ${err.message}`);
    if (signinSec) {
      signinSec.style.opacity = "1";
      signinSec.style.display = "block";
    }
  }
}

function showResult(type, message) {
  const box = document.getElementById("result-box");
  if (!box) return;

  box.style.display = "block";
  box.className = `alert alert-${type}`;
  box.innerHTML = message;
}

// Mock Google Auth Helper (for local testing)
async function openGoogleMockModal() {
  const modal = document.getElementById("mock-modal");
  if (!modal) return;
  modal.style.display = modal.style.display === "none" ? "block" : "none";

  const listDiv = document.getElementById("mock-students-list");
  if (listDiv.children.length === 0) {
    listDiv.innerHTML = "<p style='font-size:0.85rem; color:#888;'>טוען רשימת סטודנטים מה-CSV...</p>";
    try {
      const res = await fetch("/auth/mock/students");
      const data = await res.json();
      if (data.students && data.students.length > 0) {
        listDiv.innerHTML = data.students.map(s => `
          <button type="button" class="btn btn-outline btn-sm" style="width: 100%; margin-bottom: 0.3rem; text-align: right; justify-content: space-between;"
                  onclick="selectMockStudent('${escapeHtml(s.email)}', '${escapeHtml(s.name)}')">
            <span><strong>${escapeHtml(s.name)}</strong></span>
            <span style="font-size: 0.8rem; color: #666;">${escapeHtml(s.email)}</span>
          </button>
        `).join("");
      } else {
        listDiv.innerHTML = "<p style='font-size:0.85rem; color:red;'>לא נמצאו סטודנטים ב-CSV</p>";
      }
    } catch (e) {
      listDiv.innerHTML = "<p style='font-size:0.85rem; color:red;'>שגיאה בטעינת סטודנטים</p>";
    }
  }
}

function selectMockStudent(email, name) {
  const mockToken = `mock:${email}:${name}`;
  submitAttendanceToken(mockToken);
}

function submitCustomMockEmail() {
  const emailInput = document.getElementById("custom-test-email");
  const email = (emailInput.value || "").trim();
  if (!email) {
    alert("נא להזין כתובת אימייל");
    return;
  }
  const mockToken = `mock:${email}:משתמש בדיקה`;
  submitAttendanceToken(mockToken);
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/[&<>"']/g, m => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[m]));
}
