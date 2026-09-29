const loginScreen = document.getElementById("login-screen");
const chatScreen = document.getElementById("chat-screen");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const messagesEl = document.getElementById("messages");
const showSqlToggle = document.getElementById("show-sql-toggle");
const logoutBtn = document.getElementById("logout-btn");

function fmtCell(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") {
    return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(v);
}

function renderTable(columns, rows) {
  if (!columns.length || !rows.length) return "";
  const thead = "<tr>" + columns.map(c => `<th>${c}</th>`).join("") + "</tr>";
  const tbody = rows.map(r => "<tr>" + r.map(c => `<td>${fmtCell(c)}</td>`).join("") + "</tr>").join("");
  return `<div class="result-table-wrap"><table class="result-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`;
}

function addMessage(role, text, opts = {}) {
  const row = document.createElement("div");
  row.className = `msg-row ${role}` + (opts.error ? " error" : "");
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  if (opts.sql) {
    const sqlBlock = document.createElement("div");
    sqlBlock.className = "sql-block";
    sqlBlock.textContent = opts.sql;
    bubble.appendChild(sqlBlock);
  }
  if (opts.columns && opts.rows) {
    const tableHtml = renderTable(opts.columns, opts.rows);
    if (tableHtml) {
      const wrap = document.createElement("div");
      wrap.innerHTML = tableHtml;
      bubble.appendChild(wrap);
    }
    if (opts.rowCount > opts.rows.length) {
      const note = document.createElement("div");
      note.className = "row-count-note";
      note.textContent = `Showing ${opts.rows.length} of ${opts.rowCount} rows.`;
      bubble.appendChild(note);
    }
  }

  row.appendChild(bubble);
  messagesEl.appendChild(row);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return row;
}

function addTyping() {
  const row = document.createElement("div");
  row.className = "msg-row assistant";
  row.id = "typing-indicator";
  row.innerHTML = `<div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div>`;
  messagesEl.appendChild(row);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

function setUserBadge(user) {
  document.getElementById("user-name").textContent = user.full_name;
  document.getElementById("user-role").textContent = user.role;
  let scope = "";
  if (user.role === "ram") scope = `Territory: ${user.territory_name}`;
  else if (user.role === "director") scope = `Region: ${user.region_name}`;
  else scope = "All territories & regions";
  document.getElementById("user-scope").textContent = scope;
}

async function checkSession() {
  try {
    const res = await fetch("/me");
    if (!res.ok) throw new Error("not logged in");
    const data = await res.json();
    setUserBadge(data.user);
    loginScreen.hidden = true;
    chatScreen.hidden = false;
    chatInput.focus();
  } catch {
    loginScreen.hidden = false;
    chatScreen.hidden = true;
  }
}

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  loginError.hidden = true;
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  const btn = loginForm.querySelector("button");
  btn.disabled = true;
  try {
    const res = await fetch("/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      loginError.textContent = data.detail || "Login failed.";
      loginError.hidden = false;
      return;
    }
    setUserBadge(data.user);
    messagesEl.innerHTML = "";
    loginScreen.hidden = true;
    chatScreen.hidden = false;
    chatInput.focus();
  } catch {
    loginError.textContent = "Could not reach the server. Please try again.";
    loginError.hidden = false;
  } finally {
    btn.disabled = false;
  }
});

logoutBtn.addEventListener("click", async () => {
  await fetch("/logout", { method: "POST" });
  loginScreen.hidden = false;
  chatScreen.hidden = true;
  document.getElementById("email").value = "";
  document.getElementById("password").value = "";
});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = chatInput.value.trim();
  if (!question) return;
  addMessage("user", question);
  chatInput.value = "";
  const sendBtn = chatForm.querySelector("button");
  sendBtn.disabled = true;
  addTyping();

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question, show_sql: showSqlToggle.checked }),
    });
    const data = await res.json();
    removeTyping();

    if (res.status === 401) {
      addMessage("assistant", "Your session expired. Please log in again.", { error: true });
      setTimeout(checkSession, 1200);
      return;
    }

    addMessage("assistant", data.answer || "Sorry, something went wrong.", {
      error: !res.ok,
      sql: showSqlToggle.checked ? data.sql : null,
      columns: data.columns,
      rows: data.rows,
      rowCount: data.row_count,
    });
  } catch (err) {
    removeTyping();
    addMessage("assistant", "Network error — please try again.", { error: true });
  } finally {
    sendBtn.disabled = false;
    chatInput.focus();
  }
});

checkSession();
