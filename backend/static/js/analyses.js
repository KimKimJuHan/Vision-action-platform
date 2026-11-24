// 분석 화면: 입력 방식 전환 → POST /api/analyses/ → 작업 ID로 상태 Polling → 완료 시 결과 표시
(() => {
  const form = document.getElementById("analysis-form");
  const startBtn = document.getElementById("start-btn");
  const formError = document.getElementById("form-error");
  const statusText = document.getElementById("status-text");
  const steps = document.querySelectorAll("#steps li");
  const resultTable = document.getElementById("result-table");
  const resultEmpty = document.getElementById("result-empty");
  const POLL_MS = 1500;
  const POLL_LIMIT_MS = 10 * 60 * 1000;
  let inputType = "UPLOAD";

  const csrf = () => form.querySelector("[name=csrfmiddlewaretoken]").value;

  // ---- 탭 전환
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      inputType = tab.dataset.input;
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== inputType));
    });
  });

  // ---- 상태 단계 표시
  function renderSteps(status) {
    steps.forEach((li) => (li.className = ""));
    const [pending, started, done] = steps;
    done.textContent = "완료";
    if (status === "PENDING") pending.className = "active";
    if (status === "STARTED") { pending.className = "done"; started.className = "active"; }
    if (status === "SUCCESS") { pending.className = "done"; started.className = "done"; done.className = "ok"; done.textContent = "완료"; }
    if (status === "FAILURE") { pending.className = "done"; started.className = "done"; done.className = "fail"; done.textContent = "실패"; }
  }

  function renderResults(job) {
    const body = resultTable.querySelector("tbody");
    body.innerHTML = "";
    if (!job.predictions.length) {
      resultTable.hidden = true;
      resultEmpty.hidden = false;
      resultEmpty.textContent = job.result_message || "예측 결과가 없습니다.";
      return;
    }
    job.predictions.forEach((p) => {
      const tr = document.createElement("tr");
      const label = p.action_label === "UNCERTAIN" ? "판단 불확실" : p.action_display;
      const warn = p.is_uncertain && p.action_label !== "UNCERTAIN" ? ' <span class="badge warn">불확실</span>' : "";
      tr.innerHTML = `<td>${p.track_id}</td><td>${escapeHtml(label)}${warn}</td>` +
        `<td>${Math.round(p.confidence * 100)}%</td><td>${p.window_count}</td>`;
      body.appendChild(tr);
    });
    resultTable.hidden = false;
    resultEmpty.hidden = true;
  }

  // 작업이 끝나면 '최근 분석 이력' 표를 서버 데이터로 다시 그린다 (새로고침 없이)
  async function refreshHistory() {
    const body = document.getElementById("history-body");
    if (!body) return;
    try {
      const res = await fetch("/api/analyses/", { credentials: "same-origin" });
      if (!res.ok) return;
      const data = await res.json();
      const jobs = (data.results || data).slice(0, 10);
      if (!jobs.length) return;
      body.innerHTML = jobs.map((j) => {
        const created = new Date(j.created_at);
        const pad = (n) => String(n).padStart(2, "0");
        const when = `${pad(created.getMonth() + 1)}/${pad(created.getDate())} ${pad(created.getHours())}:${pad(created.getMinutes())}`;
        const first = j.predictions[0];
        const pred = first
          ? `${escapeHtml(first.action_display)} (${Math.round(first.confidence * 100)}%)` +
            (j.predictions.length > 1 ? ` <span class="muted small">외 ${j.predictions.length - 1}명</span>` : "")
          : "-";
        const took = j.total_time_sec ? `${j.total_time_sec.toFixed(1)}초` : "-";
        return `<tr><td>#${j.id}</td><td>${escapeHtml(j.title || "-")}</td><td>${escapeHtml(j.input_type_display)}</td>` +
          `<td>${escapeHtml(j.expected_action_display || "-")}</td><td>${pred}</td>` +
          `<td><span class="badge s-${j.status}">${escapeHtml(j.status_display)}</span></td>` +
          `<td>${took}</td><td>${when}</td><td><a href="/analyses/${j.id}/">상세</a></td></tr>`;
      }).join("");
    } catch (err) {
      /* 이력 갱신 실패는 분석 결과 표시에 영향을 주지 않음 */
    }
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text ?? "";
    return div.innerHTML;
  }

  async function poll(jobId, startedAt) {
    try {
      const res = await fetch(`/api/analyses/${jobId}/status/`, { credentials: "same-origin" });
      if (!res.ok) throw new Error(`상태 조회 실패 (HTTP ${res.status})`);
      const st = await res.json();
      renderSteps(st.status);
      if (st.status === "PENDING") statusText.textContent = `작업 #${jobId} 대기열에 등록됨`;
      if (st.status === "STARTED") statusText.textContent =
        inputType === "IP_WEBCAM" ? `작업 #${jobId} 카메라 영상 수집·AI 분석 중… 카메라 앞에서 동작하세요` : `작업 #${jobId} AI 분석 중…`;
      if (st.done) {
        const detail = await (await fetch(`/api/analyses/${jobId}/`, { credentials: "same-origin" })).json();
        if (st.status === "SUCCESS") {
          statusText.innerHTML = `작업 #${jobId} 완료 · ${escapeHtml(detail.result_message)} <a href="/analyses/${jobId}/">상세 보기</a>`;
          renderResults(detail);
        } else {
          statusText.innerHTML = `<span class="error">작업 #${jobId} 실패: ${escapeHtml(st.error_message)}</span>`;
        }
        startBtn.disabled = false;
        refreshHistory();
        return;
      }
      if (Date.now() - startedAt > POLL_LIMIT_MS) throw new Error("응답 대기 시간이 너무 깁니다. 이력에서 다시 확인하세요.");
      setTimeout(() => poll(jobId, startedAt), POLL_MS);
    } catch (err) {
      statusText.innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
      startBtn.disabled = false;
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    formError.hidden = true;
    const data = new FormData();
    data.append("input_type", inputType);
    data.append("title", form.title.value);
    data.append("expected_action", form.expected_action.value);
    if (inputType === "UPLOAD") {
      const file = form.video_file.files[0];
      if (!file) { formError.textContent = "분석할 영상을 선택하세요."; formError.hidden = false; return; }
      data.append("video_file", file);
    } else {
      if (!form.camera_key) { formError.textContent = "등록된 카메라가 없습니다."; formError.hidden = false; return; }
      data.append("camera_key", form.camera_key.value);
    }

    startBtn.disabled = true;
    resultTable.hidden = true;
    resultEmpty.hidden = false;
    resultEmpty.textContent = "분석 결과를 기다리는 중입니다.";
    renderSteps("PENDING");
    statusText.textContent = "요청을 보내는 중…";

    try {
      const res = await fetch("/api/analyses/", {
        method: "POST", body: data, credentials: "same-origin", headers: { "X-CSRFToken": csrf() },
      });
      const body = await res.json().catch(() => ({}));
      if (res.status !== 202) {
        const msg = Object.values(body).flat().join(" ") || `요청 실패 (HTTP ${res.status})`;
        throw new Error(msg);
      }
      // 서버는 분석을 기다리지 않고 작업 ID만 즉시 돌려준다
      statusText.textContent = `작업 #${body.id} 접수됨`;
      poll(body.id, Date.now());
    } catch (err) {
      formError.textContent = err.message;
      formError.hidden = false;
      statusText.textContent = "요청이 접수되지 않았습니다.";
      steps.forEach((li) => (li.className = ""));
      startBtn.disabled = false;
    }
  });
})();
