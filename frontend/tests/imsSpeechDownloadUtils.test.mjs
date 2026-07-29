import assert from "node:assert/strict";
import test from "node:test";

const moduleUrl = new URL("../src/pages/imsSpeechDownloadUtils.ts", import.meta.url);

async function loadUtils() {
  try {
    return await import(moduleUrl.href);
  } catch {
    return null;
  }
}

function buildItem(overrides = {}) {
  return {
    drama_index: 0,
    episode_index: 1,
    filename: "episode.one.mov",
    input_public_url: "https://oss.example/input.mov",
    detext_video_url: "https://oss.example/detext.mov",
    translations: {
      en: {
        media_url: "https://oss.example/en.mp4?signature=1",
        translated_audio_url: "https://oss.example/en.mp3?signature=1",
        subtitle_url: "https://oss.example/en-raw.srt",
        subtitle_signed_url: "https://oss.example/en-signed.srt?signature=1",
        fix_subtitle_url: "https://oss.example/en-fix.ass?signature=1",
        bilingual_subtitle_url: "https://oss.example/en-bilingual.srt",
      },
    },
    ...overrides,
  };
}

test("resolves shared and selected-language IMS resources", async () => {
  const utils = await loadUtils();
  assert.equal(typeof utils?.getImsResourceUrl, "function");

  const item = buildItem();
  assert.equal(
    utils.getImsResourceUrl(item, "original", "en"),
    "https://oss.example/input.mov",
  );
  assert.equal(
    utils.getImsResourceUrl(item, "erased", "en"),
    "https://oss.example/detext.mov",
  );
  assert.equal(
    utils.getImsResourceUrl(item, "dubbed-video", "en"),
    "https://oss.example/en.mp4?signature=1",
  );
  assert.equal(
    utils.getImsResourceUrl(item, "translated-subtitle", "en"),
    "https://oss.example/en-raw.srt",
  );
  assert.equal(utils.getImsResourceUrl(item, "dubbed-video", "pt"), null);

  const signedOnly = buildItem({
    translations: {
      en: {
        ...item.translations.en,
        subtitle_url: null,
      },
    },
  });
  assert.equal(
    utils.getImsResourceUrl(signedOnly, "translated-subtitle", "en"),
    "https://oss.example/en-signed.srt?signature=1",
  );
});

test("targets a hidden frame so cross-origin attachments do not open popups", async () => {
  const utils = await loadUtils();
  assert.equal(typeof utils?.triggerImsBrowserDownload, "function");

  const elements = [];
  const appended = [];
  const removed = [];
  let scheduledCleanup = null;
  const previousDocument = globalThis.document;
  const previousWindow = globalThis.window;
  globalThis.document = {
    createElement(tagName) {
      const element = {
        tagName,
        clicked: false,
        removed: false,
        click() {
          this.clicked = true;
        },
        remove() {
          this.removed = true;
        },
      };
      elements.push(element);
      return element;
    },
    body: {
      appendChild(element) {
        appended.push(element);
      },
      removeChild(element) {
        removed.push(element);
      },
    },
  };
  globalThis.window = {
    setTimeout(callback, delay) {
      scheduledCleanup = { callback, delay };
      return 1;
    },
  };

  try {
    utils.triggerImsBrowserDownload(
      "https://oss.example/video.mp4",
      "d1-e1-video.mp4",
    );
  } finally {
    globalThis.document = previousDocument;
    globalThis.window = previousWindow;
  }

  const iframe = elements.find((element) => element.tagName === "iframe");
  const anchor = elements.find((element) => element.tagName === "a");
  assert.equal(iframe.hidden, true);
  assert.match(iframe.name, /^ims-download-/);
  assert.equal(anchor.href, "https://oss.example/video.mp4");
  assert.equal(anchor.download, "d1-e1-video.mp4");
  assert.equal(anchor.target, iframe.name);
  assert.equal(anchor.rel, undefined);
  assert.equal(anchor.clicked, true);
  assert.deepEqual(appended, [iframe, anchor]);
  assert.deepEqual(removed, [anchor]);
  assert.equal(scheduledCleanup.delay, 60_000);
  scheduledCleanup.callback();
  assert.equal(iframe.removed, true);
});

test("builds stable filenames with resource extensions and fallbacks", async () => {
  const utils = await loadUtils();
  assert.equal(typeof utils?.buildImsDownloadFilename, "function");

  const item = buildItem();
  assert.equal(
    utils.buildImsDownloadFilename(item, "original", "en"),
    "d1-e2-episode.one.mov",
  );
  assert.equal(
    utils.buildImsDownloadFilename(item, "erased", "en"),
    "d1-e2-episode.one-erased.mov",
  );
  assert.equal(
    utils.buildImsDownloadFilename(item, "dubbed-video", "en"),
    "d1-e2-episode.one-en-dubbed.mp4",
  );
  assert.equal(
    utils.buildImsDownloadFilename(item, "translated-audio", "en"),
    "d1-e2-episode.one-en-audio.mp3",
  );
  assert.equal(
    utils.buildImsDownloadFilename(item, "fix-subtitle", "en"),
    "d1-e2-episode.one-en-fix.ass",
  );

  const missingExtensions = buildItem({
    filename: "episode",
    translations: {
      en: {
        ...item.translations.en,
        media_url: "https://oss.example/video?signature=1",
        translated_audio_url: "https://oss.example/audio?signature=1",
        subtitle_signed_url: "https://oss.example/subtitle?signature=1",
      },
    },
  });
  assert.equal(
    utils.buildImsDownloadFilename(missingExtensions, "dubbed-video", "en"),
    "d1-e2-episode-en-dubbed.mp4",
  );
  assert.equal(
    utils.buildImsDownloadFilename(missingExtensions, "translated-audio", "en"),
    "d1-e2-episode-en-audio.wav",
  );
  assert.equal(
    utils.buildImsDownloadFilename(missingExtensions, "translated-subtitle", "en"),
    "d1-e2-episode-en-translated.srt",
  );
});

test("counts only items that expose the selected resource", async () => {
  const utils = await loadUtils();
  assert.equal(typeof utils?.countImsResources, "function");

  const items = [
    buildItem(),
    buildItem({
      episode_index: 2,
      translations: {
        en: {
          ...buildItem().translations.en,
          media_url: null,
          translated_audio_url: null,
        },
      },
    }),
  ];

  assert.equal(utils.countImsResources(items, "original", "en"), 2);
  assert.equal(utils.countImsResources(items, "dubbed-video", "en"), 1);
  assert.equal(utils.countImsResources(items, "translated-audio", "en"), 1);
  assert.equal(utils.countImsResources(items, "dubbed-video", "pt"), 0);
});

test("does not expose expired signed resources", async () => {
  const utils = await loadUtils();
  const expired = buildItem({
    translations: {
      en: {
        ...buildItem().translations.en,
        fix_subtitle_url: "https://oss.example/fix.srt?Expires=1&Signature=expired",
      },
    },
  });
  const valid = buildItem({
    translations: {
      en: {
        ...buildItem().translations.en,
        fix_subtitle_url:
          "https://oss.example/fix.srt?Expires=9999999999&Signature=valid",
      },
    },
  });

  assert.equal(utils.getImsResourceUrl(expired, "fix-subtitle", "en"), null);
  assert.equal(
    utils.getImsResourceUrl(valid, "fix-subtitle", "en"),
    "https://oss.example/fix.srt?Expires=9999999999&Signature=valid",
  );
});
