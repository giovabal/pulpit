(function () {
    "use strict";
    var INFO = "/manage/api/maintenance/";
    var RUN  = "/manage/api/maintenance/optimize/";

    var $engine         = document.getElementById("bo-maint-engine");
    var $size           = document.getElementById("bo-maint-size");
    var $strategies     = document.getElementById("bo-maint-strategies");
    var $runBtn         = document.getElementById("bo-maint-run");
    var $result         = document.getElementById("bo-maint-result");
    var $resultBody     = document.getElementById("bo-maint-result-body");
    var $resultSummary  = document.getElementById("bo-maint-result-summary");

    function fmtBytes(n) {
        if (n === null || n === undefined) return "—";
        var units = ["B", "KB", "MB", "GB", "TB"];
        var i = 0;
        var v = Number(n);
        while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
        return v.toFixed(v >= 100 || i === 0 ? 0 : 2) + " " + units[i];
    }

    function fmtDuration(seconds) {
        if (seconds === null || seconds === undefined) return "—";
        if (seconds < 1) return (seconds * 1000).toFixed(0) + " ms";
        if (seconds < 60) return seconds.toFixed(2) + " s";
        var m = Math.floor(seconds / 60);
        var s = Math.round(seconds - m * 60);
        return m + "m " + s + "s";
    }

    function renderStrategies(strategies, engine) {
        $strategies.innerHTML = "";
        if (!strategies.length) {
            $strategies.innerHTML = '<p class="bo-empty">Engine "' + engine + '" has no supported optimization strategies.</p>';
            return;
        }
        strategies.forEach(function (s) {
            var row = document.createElement("label");
            row.className = "bo-maint-strategy";
            var cb = document.createElement("input");
            cb.type = "checkbox"; cb.value = s.name; cb.checked = true;
            var body = document.createElement("div"); body.className = "bo-maint-strategy-body";
            var label = document.createElement("span"); label.className = "bo-maint-strategy-label"; label.textContent = s.label;
            var desc = document.createElement("span"); desc.className = "bo-maint-strategy-desc"; desc.textContent = s.description;
            body.appendChild(label); body.appendChild(desc);
            row.appendChild(cb); row.appendChild(body);
            $strategies.appendChild(row);
        });
    }

    function renderResult(data) {
        $result.classList.remove("d-none");
        $resultBody.innerHTML = "";
        data.steps.forEach(function (step) {
            var tr = document.createElement("tr");
            tr.className = step.status === "ok" ? "bo-maint-row--ok" : "bo-maint-row--error";
            var tdName = document.createElement("td"); tdName.textContent = step.name;
            var tdStatus = document.createElement("td");
            tdStatus.textContent = step.status === "ok" ? "OK" : ("Error: " + (step.error || "unknown"));
            var tdDur = document.createElement("td"); tdDur.className = "bo-td--num";
            tdDur.textContent = fmtDuration(step.duration_seconds);
            tr.appendChild(tdName); tr.appendChild(tdStatus); tr.appendChild(tdDur);
            $resultBody.appendChild(tr);
        });
        var parts = ["Total " + fmtDuration(data.total_duration_seconds)];
        if (data.size_before_bytes !== null && data.size_after_bytes !== null) {
            var delta = data.size_before_bytes - data.size_after_bytes;
            parts.push("size " + fmtBytes(data.size_before_bytes) + " → " + fmtBytes(data.size_after_bytes));
            if (delta > 0) parts.push("saved " + fmtBytes(delta));
            else if (delta < 0) parts.push("grew " + fmtBytes(-delta));
        }
        $resultSummary.textContent = parts.join(" · ");
    }

    function loadInfo() {
        apiFetch(INFO).then(function (data) {
            $engine.textContent = data.engine;
            $size.textContent = fmtBytes(data.size_bytes);
            renderStrategies(data.strategies, data.engine);
            $runBtn.disabled = !data.supported || !data.strategies.length;
        }).catch(function (e) { showToast("Error: " + e.message, "error"); });
    }

    function run() {
        var picks = [].slice.call($strategies.querySelectorAll("input[type=checkbox]:checked"))
            .map(function (cb) { return cb.value; });
        if (!picks.length) { showToast("Pick at least one strategy.", "error"); return; }
        if (!confirm("Run database optimization now? VACUUM can lock the database for several minutes.")) return;

        var originalHtml = $runBtn.innerHTML;
        $runBtn.disabled = true;
        $runBtn.innerHTML = '<i class="bi bi-hourglass-split me-1" aria-hidden="true"></i>Running…';

        apiFetch(RUN, { method: "POST", body: { strategies: picks } })
            .then(function (data) {
                renderResult(data);
                loadInfo();
                var failed = data.steps.some(function (s) { return s.status !== "ok"; });
                showToast(failed ? "Optimization stopped on error." : "Optimization complete.", failed ? "error" : "success");
            })
            .catch(function (e) { showToast("Error: " + e.message, "error"); })
            .finally(function () {
                $runBtn.innerHTML = originalHtml;
                $runBtn.disabled = false;
            });
    }

    $runBtn.addEventListener("click", run);
    loadInfo();
})();
