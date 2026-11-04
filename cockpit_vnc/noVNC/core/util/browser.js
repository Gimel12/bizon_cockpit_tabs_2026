/*
 * noVNC: HTML5 VNC client
 * Copyright (C) 2019 The noVNC authors
 * Licensed under MPL 2.0 (see LICENSE.txt)
 *
 * See README.md for usage and integration instructions.
 *
 * Browser feature support detection
 */

import * as Log from './logging.js';
import Base64 from '../base64.js';

// Touch detection
export let isTouchDevice = ('ontouchstart' in document.documentElement) ||
                                 // required for Chrome debugger
                                 (document.ontouchstart !== undefined) ||
                                 // required for MS Surface
                                 (navigator.maxTouchPoints > 0) ||
                                 (navigator.msMaxTouchPoints > 0);
window.addEventListener('touchstart', function onFirstTouch() {
    isTouchDevice = true;
    window.removeEventListener('touchstart', onFirstTouch, false);
}, false);


// The goal is to find a certain physical width, the devicePixelRatio
// brings us a bit closer but is not optimal.
export let dragThreshold = 10 * (window.devicePixelRatio || 1);

let _supportsCursorURIs = false;

try {
    const target = document.createElement('canvas');
    target.style.cursor = 'url("data:image/x-icon;base64,AAACAAEACAgAAAIAAgA4AQAAFgAAACgAAAAIAAAAEAAAAAEAIAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAD/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////AAAAAAAAAAAAAAAAAAAAAA==") 2 2, default';

    if (target.style.cursor.indexOf("url") === 0) {
        Log.Info("Data URI scheme cursor supported");
        _supportsCursorURIs = true;
    } else {
        Log.Warn("Data URI scheme cursor not supported");
    }
} catch (exc) {
    Log.Error("Data URI scheme cursor test exception: " + exc);
}

export const supportsCursorURIs = _supportsCursorURIs;

let _hasScrollbarGutter = true;
try {
    // Create invisible container
    const container = document.createElement('div');
    container.style.visibility = 'hidden';
    container.style.overflow = 'scroll'; // forcing scrollbars
    document.body.appendChild(container);

    // Create a div and place it in the container
    const child = document.createElement('div');
    container.appendChild(child);

    // Calculate the difference between the container's full width
    // and the child's width - the difference is the scrollbars
    const scrollbarWidth = (container.offsetWidth - child.offsetWidth);

    // Clean up
    container.parentNode.removeChild(container);

    _hasScrollbarGutter = scrollbarWidth != 0;
} catch (exc) {
    Log.Error("Scrollbar test exception: " + exc);
}
export const hasScrollbarGutter = _hasScrollbarGutter;

export let supportsWebCodecsH264Decode = false;

// BIZON: optional codec detection must not hold the entire VNC module graph
// (and Cockpit page startup) open when a browser decoder stalls.
async function _checkWebCodecsH264DecodeSupport() {
    if (!("VideoDecoder" in window) || !("EncodedVideoChunk" in window)) {
        return false;
    }
    const config = {
        codec: 'avc1.42401f',
        codedWidth: 1920,
        codedHeight: 1080,
        optimizeForLatency: true,
    };
    let decoder = null;
    let finished = false;
    let timer;
    async function probe() {
        const support = await VideoDecoder.isConfigSupported(config);
        // A late capability response after the deadline must not allocate a decoder.
        if (finished || !support.supported) return false;

        // Some browsers report H.264 support without decoding a real frame.
    const data = new Uint8Array(Base64.decode(
        'AAAAAWdCwBTZnpuAgICgAAADACAAAAZB4oVNAAAAAWjJYyyAAAABBgX//4Hc' +
        'Rem95tlIt5Ys2CDZI+7veDI2NCAtIGNvcmUgMTY0IHIzMTA4IDMxZTE5Zjkg' +
        'LSBILjI2NC9NUEVHLTQgQVZDIGNvZGVjIC0gQ29weWxlZnQgMjAwMy0yMDIz' +
        'IC0gaHR0cDovL3d3dy52aWRlb2xhbi5vcmcveDI2NC5odG1sIC0gb3B0aW9u' +
        'czogY2FiYWM9MCByZWY9NSBkZWJsb2NrPTE6MDowIGFuYWx5c2U9MHgxOjB4' +
        'MTExIG1lPWhleCBzdWJtZT04IHBzeT0xIHBzeV9yZD0xLjAwOjAuMDAgbWl4' +
        'ZWRfcmVmPTEgbWVfcmFuZ2U9MTYgY2hyb21hX21lPTEgdHJlbGxpcz0yIDh4' +
        'OGRjdD0wIGNxbT0wIGRlYWR6b25lPTIxLDExIGZhc3RfcHNraXA9MSBjaHJv' +
        'bWFfcXBfb2Zmc2V0PS0yIHRocmVhZHM9MSBsb29rYWhlYWRfdGhyZWFkcz0x' +
        'IHNsaWNlZF90aHJlYWRzPTAgbnI9MCBkZWNpbWF0ZT0xIGludGVybGFjZWQ9' +
        'MCBibHVyYXlfY29tcGF0PTAgY29uc3RyYWluZWRfaW50cmE9MCBiZnJhbWVz' +
        'PTAgd2VpZ2h0cD0wIGtleWludD1pbmZpbml0ZSBrZXlpbnRfbWluPTI1IHNj' +
        'ZW5lY3V0PTQwIGludHJhX3JlZnJlc2g9MCByY19sb29rYWhlYWQ9NTAgcmM9' +
        'YWJyIG1idHJlZT0xIGJpdHJhdGU9NDAwIHJhdGV0b2w9MS4wIHFjb21wPTAu' +
        'NjAgcXBtaW49MCBxcG1heD02OSBxcHN0ZXA9NCBpcF9yYXRpbz0xLjQwIGFx' +
        'PTE6MS4wMACAAAABZYiEBrxmKAAPVccAAS044AA5DRJMnkycJk4TPw=='));

        let gotframe = false;
        let error = null;
        decoder = new VideoDecoder({
            output: (frame) => {
                if (!finished) gotframe = true;
                frame.close();
            },
            error: (e) => { error = e; },
        });
        const chunk = new EncodedVideoChunk({timestamp: 0, type: 'key', data});
        decoder.configure(config);
        decoder.decode(chunk);
        await decoder.flush();
        return gotframe && error === null;
    }
    try {
        return await Promise.race([
            probe(),
            new Promise(resolve => { timer = setTimeout(() => resolve(false), 1200); }),
        ]);
    } catch (_) {
        return false;
    } finally {
        finished = true;
        clearTimeout(timer);
        if (decoder && decoder.state !== 'closed') {
            try { decoder.close(); } catch (_) { /* already closed by decoder error */ }
        }
    }
}
// Advertise H.264 only after a successful probe. Until then, normal RFB
// encodings remain available; no top-level await delays the page's controls.
_checkWebCodecsH264DecodeSupport().then(supported => {
    supportsWebCodecsH264Decode = supported;
});

/*
 * The functions for detection of platforms and browsers below are exported
 * but the use of these should be minimized as much as possible.
 *
 * It's better to use feature detection than platform detection.
 */

/* OS */

export function isMac() {
    return !!(/mac/i).exec(navigator.platform);
}

export function isWindows() {
    return !!(/win/i).exec(navigator.platform);
}

export function isIOS() {
    return (!!(/ipad/i).exec(navigator.platform) ||
            !!(/iphone/i).exec(navigator.platform) ||
            !!(/ipod/i).exec(navigator.platform));
}

export function isAndroid() {
    /* Android sets navigator.platform to Linux :/ */
    return !!navigator.userAgent.match('Android ');
}

export function isChromeOS() {
    /* ChromeOS sets navigator.platform to Linux :/ */
    return !!navigator.userAgent.match(' CrOS ');
}

/* Browser */

export function isSafari() {
    return !!navigator.userAgent.match('Safari/...') &&
           !navigator.userAgent.match('Chrome/...') &&
           !navigator.userAgent.match('Chromium/...') &&
           !navigator.userAgent.match('Epiphany/...');
}

export function isFirefox() {
    return !!navigator.userAgent.match('Firefox/...') &&
           !navigator.userAgent.match('Seamonkey/...');
}

export function isChrome() {
    return !!navigator.userAgent.match('Chrome/...') &&
           !navigator.userAgent.match('Chromium/...') &&
           !navigator.userAgent.match('Edg/...') &&
           !navigator.userAgent.match('OPR/...');
}

export function isChromium() {
    return !!navigator.userAgent.match('Chromium/...');
}

export function isOpera() {
    return !!navigator.userAgent.match('OPR/...');
}

export function isEdge() {
    return !!navigator.userAgent.match('Edg/...');
}

/* Engine */

export function isGecko() {
    return !!navigator.userAgent.match('Gecko/...');
}

export function isWebKit() {
    return !!navigator.userAgent.match('AppleWebKit/...') &&
           !navigator.userAgent.match('Chrome/...');
}

export function isBlink() {
    return !!navigator.userAgent.match('Chrome/...');
}
