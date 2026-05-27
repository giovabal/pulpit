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
        $strategies.replaceChildren();
        if (!strategies.length) {
            var p = document.createElement("p");
            p.className = "bo-empty";
            p.textContent = 'Engine "' + engine + '" has no supported optimization strategies.';
            $strategies.appendChild(p);
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

    // ── Purge out-of-target messages ─────────────────────────────────────────
    var PURGE_PREVIEW = "/manage/api/maintenance/purge-preview/";
    var PURGE_RUN     = "/manage/api/maintenance/purge/";

    var $purgeMarked      = document.getElementById("bo-purge-marked");
    var $purgeMsgs        = document.getElementById("bo-purge-msgs");
    var $purgeFiles       = document.getElementById("bo-purge-files");
    var $purgeRefreshBtn  = document.getElementById("bo-purge-refresh");
    var $purgeRunBtn      = document.getElementById("bo-purge-run");
    var $purgeHint        = document.getElementById("bo-purge-hint");
    var $purgeResult      = document.getElementById("bo-purge-result");
    var $purgeResultSum   = document.getElementById("bo-purge-result-summary");

    function fmtCount(n) {
        if (n === null || n === undefined) return "—";
        return Number(n).toLocaleString();
    }

    function loadPurgePreview() {
        $purgeMarked.textContent = "…";
        $purgeMsgs.textContent = "…";
        $purgeFiles.textContent = "…";
        $purgeRunBtn.disabled = true;
        $purgeHint.textContent = "";
        apiFetch(PURGE_PREVIEW).then(function (data) {
            $purgeMarked.textContent = fmtCount(data.marked_in_target_channels);
            $purgeMsgs.textContent = fmtCount(data.messages);
            $purgeFiles.textContent = fmtCount(data.media_files);
            if (!data.supported) {
                $purgeHint.textContent = data.detail || "Purge unavailable.";
                $purgeRunBtn.disabled = true;
                return;
            }
            $purgeRunBtn.disabled = data.messages === 0;
            if (data.messages === 0) $purgeHint.textContent = "Nothing to delete.";
        }).catch(function (e) {
            $purgeHint.textContent = "Preview failed: " + e.message;
            showToast("Error: " + e.message, "error");
        });
    }

    function runPurge() {
        var msgs = $purgeMsgs.textContent;
        var files = $purgeFiles.textContent;
        var msg = "Delete " + msgs + " messages and remove " + files +
                  " media files from disk?\n\nThis cannot be undone.";
        if (!confirm(msg)) return;

        var originalHtml = $purgeRunBtn.innerHTML;
        $purgeRunBtn.disabled = true;
        $purgeRunBtn.innerHTML = '<i class="bi bi-hourglass-split me-1" aria-hidden="true"></i>Purging…';
        $purgeRefreshBtn.disabled = true;

        apiFetch(PURGE_RUN, { method: "POST", body: {} })
            .then(function (data) {
                $purgeResult.classList.remove("d-none");
                var parts = [
                    "Deleted " + fmtCount(data.deleted_messages) + " messages",
                    "removed " + fmtCount(data.removed_files) + " of " + fmtCount(data.candidate_media_files) + " media files",
                    "in " + fmtDuration(data.total_duration_seconds),
                ];
                if (data.failed_files) {
                    parts.push(fmtCount(data.failed_files) + " files could not be removed");
                }
                if (data.size_before_bytes !== null && data.size_after_bytes !== null) {
                    parts.push("DB size " + fmtBytes(data.size_before_bytes) + " → " + fmtBytes(data.size_after_bytes));
                }
                $purgeResultSum.textContent = parts.join(" · ");
                showToast(data.failed_files
                    ? "Purge completed with file errors."
                    : "Purge complete. Run VACUUM above to reclaim DB pages.",
                    data.failed_files ? "error" : "success");
                loadPurgePreview();
                loadInfo();  // refresh disk-size readout
            })
            .catch(function (e) {
                showToast("Purge failed: " + e.message, "error");
            })
            .finally(function () {
                $purgeRunBtn.innerHTML = originalHtml;
                $purgeRefreshBtn.disabled = false;
            });
    }

    $purgeRefreshBtn.addEventListener("click", loadPurgePreview);
    $purgeRunBtn.addEventListener("click", runPurge);
    // Preview is opt-in (counts can be expensive); user clicks "Preview" to scan.

    // ── Purge orphan media files ─────────────────────────────────────────────
    var ORPHAN_PREVIEW = "/manage/api/maintenance/orphan-media-preview/";
    var ORPHAN_RUN     = "/manage/api/maintenance/orphan-media/";

    var $orphanFiles      = document.getElementById("bo-orphan-files");
    var $orphanBytes      = document.getElementById("bo-orphan-bytes");
    var $orphanRefreshBtn = document.getElementById("bo-orphan-refresh");
    var $orphanRunBtn     = document.getElementById("bo-orphan-run");
    var $orphanHint       = document.getElementById("bo-orphan-hint");
    var $orphanResult     = document.getElementById("bo-orphan-result");
    var $orphanResultSum  = document.getElementById("bo-orphan-result-summary");

    function loadOrphanPreview() {
        $orphanFiles.textContent = "scanning…";
        $orphanBytes.textContent = "…";
        $orphanRunBtn.disabled = true;
        $orphanHint.textContent = "";
        apiFetch(ORPHAN_PREVIEW).then(function (data) {
            $orphanFiles.textContent = fmtCount(data.files);
            $orphanBytes.textContent = fmtBytes(data.bytes);
            if (!data.supported) {
                $orphanHint.textContent = data.detail || "Scan unavailable.";
                $orphanRunBtn.disabled = true;
                return;
            }
            $orphanRunBtn.disabled = data.files === 0;
            if (data.files === 0) $orphanHint.textContent = "Nothing to remove.";
        }).catch(function (e) {
            $orphanHint.textContent = "Preview failed: " + e.message;
            showToast("Error: " + e.message, "error");
        });
    }

    function runOrphanCleanup() {
        var files = $orphanFiles.textContent;
        var size = $orphanBytes.textContent;
        if (!confirm("Remove " + files + " orphan files (" + size + ") from disk?\n\nThis cannot be undone.")) return;

        var originalHtml = $orphanRunBtn.innerHTML;
        $orphanRunBtn.disabled = true;
        $orphanRunBtn.innerHTML = '<i class="bi bi-hourglass-split me-1" aria-hidden="true"></i>Removing…';
        $orphanRefreshBtn.disabled = true;

        apiFetch(ORPHAN_RUN, { method: "POST", body: {} })
            .then(function (data) {
                $orphanResult.classList.remove("d-none");
                var parts = [
                    "Removed " + fmtCount(data.removed_files) + " files (" + fmtBytes(data.removed_bytes) + ")",
                    "in " + fmtDuration(data.total_duration_seconds),
                ];
                if (data.failed_files) {
                    parts.push(fmtCount(data.failed_files) + " files could not be removed");
                }
                if (data.empty_dirs_removed) {
                    parts.push("cleaned up " + fmtCount(data.empty_dirs_removed) + " empty directories");
                }
                $orphanResultSum.textContent = parts.join(" · ");
                showToast(data.failed_files ? "Cleanup completed with errors." : "Cleanup complete.",
                    data.failed_files ? "error" : "success");
                loadOrphanPreview();
            })
            .catch(function (e) { showToast("Cleanup failed: " + e.message, "error"); })
            .finally(function () {
                $orphanRunBtn.innerHTML = originalHtml;
                $orphanRefreshBtn.disabled = false;
            });
    }

    $orphanRefreshBtn.addEventListener("click", loadOrphanPreview);
    $orphanRunBtn.addEventListener("click", runOrphanCleanup);
    // Preview is opt-in (the scan walks the whole media tree and can take many
    // seconds on a large install); user clicks "Preview" to start it.

    // ── New-version banner ───────────────────────────────────────────────────
    // window.pulpitVersion is published by webapp/static/webapp/js/version_check.js
    // (loaded in the page shell before this script). Reuse its single cached
    // lookup: reveal the banner when an update exists, and wire its dismiss button
    // to clear the attention dots. The banner itself stays in place — only the
    // dots are dismissed, until a newer release supersedes the stored version.
    var $verBanner = document.getElementById("bo-version-banner");
    var $verText = document.getElementById("bo-version-banner-text");

    // Reveal + populate the page-top banner for a status that signals an update.
    // Shared by the once-a-day cached lookup (window.pulpitVersion, on load) and
    // the explicit "Check for updates" card below, so a forced check that finds a
    // newer release surfaces the banner immediately too.
    function revealVersionBanner(status) {
        if (!$verBanner || !status || !status.update_available) return;
        if ($verText) {
            $verText.textContent =
                "Pulpit " + status.latest + " is available — you are running " + status.current + ".";
        }
        $verBanner.classList.remove("d-none");
    }

    if ($verBanner && window.pulpitVersion) {
        var $verDismiss = document.getElementById("bo-version-banner-dismiss");
        window.pulpitVersion.ready.then(revealVersionBanner);
        if ($verDismiss) {
            $verDismiss.addEventListener("click", function () {
                window.pulpitVersion.dismiss();
            });
        }
    }

    // ── Check for updates (explicit, cache-bypassing) ────────────────────────
    // Forces a fresh upstream check via the Maintenance API (the dots/banner
    // otherwise read a once-a-day cache), then reports the verdict in the card.
    var UPDATE_CHECK = "/manage/api/maintenance/check-updates/";

    var $updateLatest    = document.getElementById("bo-update-latest");
    var $updateCheckBtn  = document.getElementById("bo-update-check");
    var $updateHint      = document.getElementById("bo-update-hint");
    var $updateResult    = document.getElementById("bo-update-result");
    var $updateResultSum = document.getElementById("bo-update-result-summary");

    function renderUpdateResult(data) {
        $updateLatest.textContent = data.latest || "unknown";
        $updateResult.classList.remove("d-none");
        $updateResultSum.replaceChildren();

        if (!data.latest) {
            $updateResultSum.textContent =
                "Could not determine the latest version — GitHub was unreachable, or update checks " +
                "are unavailable for this deployment. Try again shortly.";
            return;
        }
        if (!data.update_available) {
            $updateResultSum.textContent = "You are running the latest version (" + data.current + ").";
            return;
        }
        $updateResultSum.append(
            "Pulpit " + data.latest + " is available — you are running " + data.current +
            ". Upgrade with git pull. "
        );
        if (data.repository_url) {
            var link = document.createElement("a");
            link.href = data.repository_url;
            link.target = "_blank";
            link.rel = "noopener";
            link.className = "update-banner-link";
            link.textContent = "View on GitHub";
            $updateResultSum.append(link);
        }
        revealVersionBanner(data);
    }

    function checkUpdates() {
        var originalHtml = $updateCheckBtn.innerHTML;
        $updateCheckBtn.disabled = true;
        $updateCheckBtn.innerHTML = '<i class="bi bi-hourglass-split me-1" aria-hidden="true"></i>Checking…';
        $updateLatest.textContent = "…";
        $updateHint.textContent = "Contacting GitHub…";

        apiFetch(UPDATE_CHECK, { method: "POST", body: {} })
            .then(function (data) {
                renderUpdateResult(data);
                if (!data.latest) {
                    showToast("Couldn't reach GitHub for the version check.", "error");
                } else if (data.update_available) {
                    showToast("Update available: Pulpit " + data.latest + ".", "success");
                } else {
                    showToast("You're on the latest version.", "success");
                }
            })
            .catch(function (e) { showToast("Update check failed: " + e.message, "error"); })
            .finally(function () {
                $updateCheckBtn.innerHTML = originalHtml;
                $updateCheckBtn.disabled = false;
                $updateHint.textContent = "";
            });
    }

    $updateCheckBtn.addEventListener("click", checkUpdates);
})();
