// 관리자 대시보드: Django가 ORM으로 집계해 json_script로 넘긴 값으로 Chart.js 차트를 그린다.
(() => {
  const data = JSON.parse(document.getElementById("chart-data").textContent);
  if (typeof Chart === "undefined") {
    document.querySelectorAll("canvas").forEach((c) => c.replaceWith(Object.assign(document.createElement("p"), {
      className: "error", textContent: "Chart.js를 불러오지 못했습니다 (static/vendor 확인).",
    })));
    return;
  }
  Chart.defaults.maintainAspectRatio = false;  // .chart-box 높이에 맞춤
  const statusColors = { PENDING: "#9aa0ad", STARTED: "#3b82f6", SUCCESS: "#2f9e5a", FAILURE: "#d9534f" };

  new Chart(document.getElementById("actionChart"), {
    type: "bar",
    data: { labels: data.actions.labels, datasets: [{ label: "예측 건수", data: data.actions.values, backgroundColor: "#3d43c4" }] },
    options: { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, ticks: { precision: 0 } } } },
  });

  new Chart(document.getElementById("statusChart"), {
    type: "doughnut",
    data: {
      labels: data.statuses.labels,
      datasets: [{ data: data.statuses.values, backgroundColor: data.statuses.keys.map((k) => statusColors[k]) }],
    },
    options: { plugins: { legend: { position: "right" } } },
  });

  new Chart(document.getElementById("inputChart"), {
    type: "pie",
    data: { labels: data.inputs.labels, datasets: [{ data: data.inputs.values, backgroundColor: ["#3d43c4", "#18a3a0"] }] },
  });

  new Chart(document.getElementById("timeChart"), {
    type: "bar",
    data: { labels: data.inputs.labels, datasets: [{ label: "평균 처리 시간(초)", data: data.inputs.avg_time, backgroundColor: ["#3d43c4", "#18a3a0"] }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
  });
})();
