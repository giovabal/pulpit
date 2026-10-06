/* Full-size picture viewer for post cards (webapp/_post_card.html).

   Every stored picture is wrapped in <a class="post-image-link" data-lightbox="post-<pk>">
   pointing at its file, so it opens in a new tab without JavaScript. A plain click
   opens it here instead, on a dark overlay: fitted to the screen, toggled to 1:1
   pixels by clicking the image, with ‹ › (arrow keys, swipe) through the other
   pictures of the same post. Esc, the × button or a click on the backdrop close it
   and focus returns to the picture. One delegated listener, so cards re-rendered
   after load work too. */
(function() {
    'use strict';

    var SWIPE_MIN_PX = 50;

    var box = null;
    var stage, img, prevBtn, nextBtn, closeBtn, count, size, original;
    var items = [];
    var index = 0;
    var opener = null;
    var touchX = null;

    function el(tag, className, attrs) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        Object.keys(attrs || {}).forEach(function(k) { node.setAttribute(k, attrs[k]); });
        return node;
    }

    function iconButton(className, label, icon) {
        var b = el('button', 'lightbox-btn ' + className, { type: 'button', 'aria-label': label, title: label });
        b.innerHTML = '<i class="bi ' + icon + '" aria-hidden="true"></i>';
        return b;
    }

    function build() {
        box = el('div', 'lightbox', { role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Picture viewer' });
        box.hidden = true;
        stage = el('div', 'lightbox-stage');
        img = el('img', 'lightbox-img', { alt: '' });
        stage.appendChild(img);
        closeBtn = iconButton('lightbox-close', 'Close (Esc)', 'bi-x-lg');
        prevBtn = iconButton('lightbox-prev', 'Previous picture', 'bi-chevron-left');
        nextBtn = iconButton('lightbox-next', 'Next picture', 'bi-chevron-right');
        var bar = el('div', 'lightbox-bar');
        count = el('span', 'lightbox-count', { 'aria-live': 'polite' });
        size = el('span', 'lightbox-size');
        original = el('a', 'lightbox-original', { target: '_blank', rel: 'noopener' });
        original.textContent = 'Open file';
        bar.appendChild(count);
        bar.appendChild(size);
        bar.appendChild(original);
        box.appendChild(stage);
        box.appendChild(prevBtn);
        box.appendChild(nextBtn);
        box.appendChild(closeBtn);
        box.appendChild(bar);
        document.body.appendChild(box);

        closeBtn.addEventListener('click', close);
        prevBtn.addEventListener('click', function() { show(index - 1); });
        nextBtn.addEventListener('click', function() { show(index + 1); });
        // A click on the backdrop (not the picture or the controls) closes.
        stage.addEventListener('click', function(e) { if (e.target === stage) close(); });
        img.addEventListener('click', toggleZoom);
        img.addEventListener('load', function() {
            box.classList.remove('is-loading');
            size.textContent = img.naturalWidth + ' × ' + img.naturalHeight + ' px';
            updateZoomable();
        });
        img.addEventListener('error', function() {
            box.classList.remove('is-loading');
            size.textContent = 'Could not load this picture';
        });
        // On the document, not the dialog: a step that disables the focused arrow
        // must not strand the keyboard on <body>.
        document.addEventListener('keydown', function(e) { if (!box.hidden) onKey(e); });
        stage.addEventListener('touchstart', function(e) {
            touchX = e.touches.length === 1 ? e.touches[0].clientX : null;
        }, { passive: true });
        stage.addEventListener('touchend', function(e) {
            if (touchX === null || box.classList.contains('is-zoomed')) return;
            var dx = e.changedTouches[0].clientX - touchX;
            touchX = null;
            if (Math.abs(dx) >= SWIPE_MIN_PX) show(index + (dx < 0 ? 1 : -1));
        });
        window.addEventListener('resize', updateZoomable);
    }

    // Zoom only makes sense when the picture is shrunk to fit.
    function updateZoomable() {
        var fitted = img.clientWidth < img.naturalWidth || img.clientHeight < img.naturalHeight;
        box.classList.toggle('is-zoomable', fitted || box.classList.contains('is-zoomed'));
    }

    function toggleZoom() {
        if (!box.classList.contains('is-zoomable')) return;
        box.classList.toggle('is-zoomed');
        img.title = box.classList.contains('is-zoomed') ? 'Click to fit the screen' : 'Click for actual size';
        stage.scrollTop = 0;
        stage.scrollLeft = 0;
    }

    function show(i) {
        if (i < 0 || i >= items.length) return;
        index = i;
        var link = items[i];
        var thumb = link.querySelector('img');
        box.classList.remove('is-zoomed', 'is-zoomable');
        box.classList.add('is-loading');
        size.textContent = '';
        img.title = 'Click for actual size';
        img.alt = thumb ? thumb.alt : '';
        img.src = link.href;
        original.href = link.href;
        count.textContent = items.length > 1 ? (i + 1) + ' / ' + items.length : '';
        prevBtn.hidden = items.length < 2;
        nextBtn.hidden = items.length < 2;
        var focused = document.activeElement;
        prevBtn.disabled = i === 0;
        nextBtn.disabled = i === items.length - 1;
        // Reaching either end disables the arrow just used: hand focus to the other one.
        if (focused === prevBtn && prevBtn.disabled) nextBtn.focus();
        else if (focused === nextBtn && nextBtn.disabled) prevBtn.focus();
        // Warm the neighbours so stepping through an album doesn't stall.
        [i - 1, i + 1].forEach(function(j) {
            if (j >= 0 && j < items.length) new Image().src = items[j].href;
        });
    }

    function open(link) {
        if (!box) build();
        var group = link.getAttribute('data-lightbox');
        items = Array.prototype.filter.call(document.querySelectorAll('a[data-lightbox]'), function(a) {
            return a.getAttribute('data-lightbox') === group;
        });
        opener = link;
        box.hidden = false;
        document.documentElement.classList.add('lightbox-open');
        show(Math.max(0, items.indexOf(link)));
        closeBtn.focus();
    }

    function close() {
        box.hidden = true;
        document.documentElement.classList.remove('lightbox-open');
        img.removeAttribute('src');
        if (opener) opener.focus();
        opener = null;
    }

    function onKey(e) {
        if (e.key === 'Escape') {
            e.preventDefault();
            close();
        } else if (e.key === 'ArrowLeft') {
            e.preventDefault();
            show(index - 1);
        } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            show(index + 1);
        } else if (e.key === 'Tab') {
            // Keep focus inside the dialog.
            var focusable = Array.prototype.filter.call(box.querySelectorAll('button, a[href]'), function(n) {
                return !n.hidden && !n.disabled;
            });
            var first = focusable[0];
            var last = focusable[focusable.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    }

    document.addEventListener('click', function(e) {
        // Modified or non-primary clicks keep the browser's open-in-new-tab behaviour.
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        var link = e.target.closest('a[data-lightbox]');
        if (!link) return;
        e.preventDefault();
        open(link);
    });
})();
