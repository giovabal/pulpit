/* Animated custom emoji and stickers (webapp/templatetags/custom_emoji.py, _post_card.html).
   Loaded by the base template on every page.

   Elements with data-tgs-src hold a TGS file — gzipped Lottie JSON, Telegram's animated
   sticker format — drawn with lottie-web, fetched from the CDN the first time a page shows
   one. Until then, and for good without JavaScript or DecompressionStream, they keep their
   fallback content: the emoji character, or a download link for a sticker. <video data-play>
   elements are webm emoji and stickers. Both animate only while on screen:
   data-play="loop" (the default) plays while visible, data-play="hover" only while the
   pill or cell holding it is hovered or focused. Under prefers-reduced-motion nothing plays
   on its own; hovering still does.

   Publishes window.PulpitCustomEmoji = { scan(root) } for markup added after load. */
(function() {
    "use strict";

    var LOTTIE_SRC = "https://cdn.jsdelivr.net/npm/lottie-web@5.12.2/build/player/lottie_light.min.js";
    var HOVER_TARGET = ".post-reaction, .reaction-pill, .custom-emoji-cell, .emoji-pack-preview, .bo-emoji-preview";
    var reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    var lottiePromise = null;
    // url → Promise of the decompressed JSON text. Parsed afresh for every animation:
    // lottie-web rewrites the data object it is given, so instances must not share one.
    var tgsText = {};

    function loadLottie() {
        if (window.lottie) {
            return Promise.resolve(window.lottie);
        }
        if (!lottiePromise) {
            lottiePromise = new Promise(function(resolve, reject) {
                var script = document.createElement("script");
                script.src = LOTTIE_SRC;
                script.async = true;
                script.onload = function() {
                    if (window.lottie) {
                        resolve(window.lottie);
                    } else {
                        reject(new Error("lottie-web did not load"));
                    }
                };
                script.onerror = function() {
                    lottiePromise = null;
                    reject(new Error("lottie-web did not load"));
                };
                document.head.appendChild(script);
            });
        }
        return lottiePromise;
    }

    function fetchTgs(url) {
        if (!tgsText[url]) {
            tgsText[url] = fetch(url).then(function(response) {
                if (!response.ok || !response.body) {
                    throw new Error("HTTP " + response.status);
                }
                return new Response(response.body.pipeThrough(new DecompressionStream("gzip"))).text();
            });
            tgsText[url].catch(function() {
                delete tgsText[url];
            });
        }
        return tgsText[url];
    }

    function wantsPlay(el) {
        return el._hovered || (el.dataset.play !== "hover" && el._visible && !reduceMotion);
    }

    function sync(el) {
        var play = wantsPlay(el);
        if (el.tagName === "VIDEO") {
            if (play) {
                var started = el.play();
                if (started && started.catch) {
                    started.catch(function() {});
                }
            } else {
                el.pause();
            }
            return;
        }
        if (!el._anim) {
            return;
        }
        if (play) {
            el._anim.play();
        } else if (el.dataset.play === "hover") {
            el._anim.goToAndStop(0, true);
        } else {
            el._anim.pause();
        }
    }

    function mount(el) {
        if (el._mounting) {
            return;
        }
        el._mounting = true;
        Promise.all([loadLottie(), fetchTgs(el.dataset.tgsSrc)]).then(function(results) {
            var data = JSON.parse(results[1]);
            var fallback = Array.prototype.slice.call(el.childNodes);
            fallback.forEach(function(node) {
                el.removeChild(node);
            });
            try {
                el._anim = results[0].loadAnimation({
                    container: el,
                    renderer: "svg",
                    loop: true,
                    autoplay: false,
                    animationData: data,
                    rendererSettings: { preserveAspectRatio: "xMidYMid meet" },
                });
            } catch (e) {
                el.textContent = "";
                fallback.forEach(function(node) {
                    el.appendChild(node);
                });
                return;
            }
            if (el.dataset.label) {
                el.setAttribute("role", "img");
                el.setAttribute("aria-label", el.dataset.label);
            }
            el.classList.add("is-animated");
            el._anim.addEventListener("DOMLoaded", function() {
                sync(el);
            });
            sync(el);
        }).catch(function() {
            // Keep the fallback content; the next page load tries again.
        });
    }

    var observer = "IntersectionObserver" in window ? new IntersectionObserver(function(entries) {
        entries.forEach(function(entry) {
            var el = entry.target;
            el._visible = entry.isIntersecting;
            if (el._visible && el.dataset.tgsSrc) {
                mount(el);
            }
            sync(el);
        });
    }, { rootMargin: "200px" }) : null;

    function bindHover(el) {
        var target = el.closest(HOVER_TARGET) || el;
        var on = function() {
            el._hovered = true;
            sync(el);
        };
        var off = function() {
            el._hovered = false;
            sync(el);
        };
        target.addEventListener("mouseenter", on);
        target.addEventListener("mouseleave", off);
        target.addEventListener("focusin", on);
        target.addEventListener("focusout", off);
    }

    function scan(root) {
        var els = (root || document).querySelectorAll("[data-tgs-src], video[data-play]");
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            if (el._customEmojiBound) {
                continue;
            }
            el._customEmojiBound = true;
            if (el.dataset.play === "hover") {
                bindHover(el);
            }
            if (observer) {
                observer.observe(el);
            } else {
                el._visible = true;
                if (el.dataset.tgsSrc) {
                    mount(el);
                }
                sync(el);
            }
        }
    }

    window.PulpitCustomEmoji = { scan: scan };
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function() {
            scan(document);
        });
    } else {
        scan(document);
    }
})();
