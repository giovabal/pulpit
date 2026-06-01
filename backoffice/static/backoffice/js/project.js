(function () {
    "use strict";
    var API = "/manage/api/project/";

    var $form  = document.getElementById("project-form");
    var $title = document.getElementById("project-title");
    var $desc  = document.getElementById("project-description");
    var $crit  = document.getElementById("project-criteria");
    var $notes = document.getElementById("project-notes");
    var $save  = document.getElementById("project-save");

    function fill(data) {
        $title.value = data.title || "";
        $desc.value  = data.description || "";
        $crit.value  = data.criteria || "";
        $notes.value = data.notes || "";
    }

    function load() {
        apiFetch(API)
            .then(fill)
            .catch(function (e) { showToast("Error loading project: " + e.message, "error"); });
    }

    $form.addEventListener("submit", function (e) {
        e.preventDefault();
        $save.disabled = true;
        apiFetch(API, {
            method: "PUT",
            body: {
                title: $title.value.trim(),
                description: $desc.value,
                criteria: $crit.value,
                notes: $notes.value,
            },
        })
            .then(function (data) { fill(data); showToast("Saved."); })
            .catch(function (e) { showToast("Error: " + e.message, "error"); })
            .finally(function () { $save.disabled = false; });
    });

    load();
})();
