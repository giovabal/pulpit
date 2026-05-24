import js from "@eslint/js";
import globals from "globals";

// Shared rule set. eqeqeq keeps the intentional `== null` idiom used throughout
// the codebase (matches both null and undefined); everything else must be strict.
// Unused catch bindings are tolerated (many `catch (e) {}` ignore-and-fallback sites).
const RULES = {
    eqeqeq: ["error", "always", { null: "ignore" }],
    "no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" }],
    "no-empty": ["error", { allowEmptyCatch: true }],
};

// Globals published by the classic (non-module) tables_sort.js to the export bundle.
const TABLES_SORT_GLOBALS = {
    fmtInt: "readonly",
    sigFig: "readonly",
    heatmapBg: "readonly",
    divergingHeatmapBg: "readonly",
    numSortVal: "readonly",
    initSortableTables: "readonly",
};

export default [
    {
        // Generated / vendored / collected output — never first-party source.
        ignores: ["node_modules/**", ".venv/**", "staticfiles/**", "graph/**", "exports/**"],
    },
    js.configs.recommended,

    // ── Static HTML export bundle — ES modules (graph.js, graph3d.js, *_table.js, …) ──
    {
        files: ["webapp_engine/map/js/**/*.js"],
        ignores: ["webapp_engine/map/js/tables_sort.js"],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "module",
            globals: {
                ...globals.browser,
                ...TABLES_SORT_GLOBALS,
                THREE: "readonly",
                Sigma: "readonly",
                Chart: "readonly",
                bootstrap: "readonly",
                PulpitA11y: "readonly",
                // Injected by the export HTML before the module loads:
                DATA_DIR: "readonly",
                EXTRA_LAYOUTS: "readonly",
                EXTRA_LAYOUTS_3D: "readonly",
                VERTICAL_LAYOUT: "readonly",
            },
        },
        rules: RULES,
    },
    {
        // tables_sort.js — classic script that publishes the table helpers above.
        files: ["webapp_engine/map/js/tables_sort.js"],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "script",
            globals: { ...globals.browser, PulpitA11y: "readonly" },
        },
        rules: RULES,
    },

    // ── Backoffice admin — classic scripts; crud.js publishes the shared API ──
    {
        files: ["backoffice/static/backoffice/js/**/*.js"],
        ignores: ["backoffice/static/backoffice/js/crud.js"],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "script",
            globals: {
                ...globals.browser,
                bootstrap: "readonly",
                BACKOFFICE_PAGE_SIZE: "readonly",
                renderPagination: "readonly",
                getCsrfToken: "readonly",
                apiFetch: "readonly",
                showToast: "readonly",
                confirmDelete: "readonly",
                fmtInt: "readonly",
                fmtDate: "readonly",
                makeDeleteBtn: "readonly",
                makeEditBtn: "readonly",
                makeProfilePicEl: "readonly",
            },
        },
        rules: RULES,
    },
    {
        files: ["backoffice/static/backoffice/js/crud.js"],
        languageOptions: { ecmaVersion: 2022, sourceType: "script", globals: { ...globals.browser, bootstrap: "readonly" } },
        rules: RULES,
    },

    // ── Live webapp — classic scripts; http.js publishes the fetch/CSRF globals ──
    {
        files: ["webapp/static/webapp/js/**/*.js"],
        ignores: ["webapp/static/webapp/js/http.js"],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "script",
            globals: {
                ...globals.browser,
                PulpitA11y: "readonly",
                Chart: "readonly",
                fetchJson: "readonly",
                fetchJsonOrNull: "readonly",
                getCsrfToken: "readonly",
            },
        },
        rules: RULES,
    },
    {
        files: ["webapp/static/webapp/js/http.js"],
        languageOptions: { ecmaVersion: 2022, sourceType: "script", globals: { ...globals.browser } },
        rules: RULES,
    },
];
