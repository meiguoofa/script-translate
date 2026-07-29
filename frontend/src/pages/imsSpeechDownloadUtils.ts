import type { ImsSpeechJobItemOut } from "@/api/types";

export type ImsDownloadResourceType =
  | "original"
  | "erased"
  | "dubbed-video"
  | "translated-audio"
  | "translated-subtitle"
  | "fix-subtitle"
  | "bilingual-subtitle";

function splitFilename(filename: string) {
  const safeFilename = filename || "video";
  const dotIndex = safeFilename.lastIndexOf(".");
  if (dotIndex <= 0 || dotIndex === safeFilename.length - 1) {
    return { filename: safeFilename, stem: safeFilename, extension: "" };
  }
  return {
    filename: safeFilename,
    stem: safeFilename.slice(0, dotIndex),
    extension: safeFilename.slice(dotIndex + 1).toLowerCase(),
  };
}

function extensionFromUrl(url: string | null, fallback: string) {
  if (!url) return fallback;
  try {
    const filename = new URL(url).pathname.split("/").pop() || "";
    const dotIndex = filename.lastIndexOf(".");
    const extension =
      dotIndex >= 0 ? filename.slice(dotIndex + 1).toLowerCase() : "";
    return /^[a-z0-9]{1,10}$/.test(extension) ? extension : fallback;
  } catch {
    return fallback;
  }
}

function usableUrl(...urls: Array<string | null | undefined>): string | null {
  for (const url of urls) {
    if (!url) continue;
    try {
      const expires = new URL(url).searchParams.get("Expires");
      if (expires) {
        const expiresAt = Number(expires);
        if (Number.isFinite(expiresAt) && expiresAt <= Date.now() / 1000) {
          continue;
        }
      }
    } catch {
      // Keep non-standard but otherwise usable URLs.
    }
    return url;
  }
  return null;
}

export function getImsResourceUrl(
  item: ImsSpeechJobItemOut,
  type: ImsDownloadResourceType,
  language: string,
): string | null {
  switch (type) {
    case "original":
      return usableUrl(item.input_public_url);
    case "erased":
      return usableUrl(item.detext_video_url);
    case "dubbed-video":
      return usableUrl(item.translations[language]?.media_url);
    case "translated-audio":
      return usableUrl(item.translations[language]?.translated_audio_url);
    case "translated-subtitle": {
      const translation = item.translations[language];
      return usableUrl(
        translation?.subtitle_url,
        translation?.subtitle_signed_url,
      );
    }
    case "fix-subtitle":
      return usableUrl(item.translations[language]?.fix_subtitle_url);
    case "bilingual-subtitle":
      return usableUrl(item.translations[language]?.bilingual_subtitle_url);
  }
}

export function triggerImsBrowserDownload(url: string, filename: string) {
  const iframe = document.createElement("iframe");
  iframe.name = `ims-download-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  iframe.hidden = true;
  document.body.appendChild(iframe);

  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.target = iframe.name;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);

  window.setTimeout(() => iframe.remove(), 60_000);
}

export function buildImsDownloadFilename(
  item: ImsSpeechJobItemOut,
  type: ImsDownloadResourceType,
  language: string,
): string {
  const prefix = `d${item.drama_index + 1}-e${item.episode_index + 1}`;
  const { filename, stem, extension } = splitFilename(item.filename);
  const url = getImsResourceUrl(item, type, language);

  switch (type) {
    case "original":
      return `${prefix}-${filename}`;
    case "erased":
      return `${prefix}-${stem}-erased.${extensionFromUrl(url, extension || "mp4")}`;
    case "dubbed-video":
      return `${prefix}-${stem}-${language}-dubbed.${extensionFromUrl(url, extension || "mp4")}`;
    case "translated-audio":
      return `${prefix}-${stem}-${language}-audio.${extensionFromUrl(url, "wav")}`;
    case "translated-subtitle":
      return `${prefix}-${stem}-${language}-translated.${extensionFromUrl(url, "srt")}`;
    case "fix-subtitle":
      return `${prefix}-${stem}-${language}-fix.${extensionFromUrl(url, "srt")}`;
    case "bilingual-subtitle":
      return `${prefix}-${stem}-${language}-bilingual.${extensionFromUrl(url, "srt")}`;
  }
}

export function countImsResources(
  items: ImsSpeechJobItemOut[],
  type: ImsDownloadResourceType,
  language: string,
) {
  return items.filter((item) => getImsResourceUrl(item, type, language)).length;
}
