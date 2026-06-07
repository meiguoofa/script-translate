type DownloadButtonProps = {
  versionId: string;
  href: string;
  disabled?: boolean;
};

export function DownloadButton({ versionId, href, disabled }: DownloadButtonProps) {
  return (
    <a className={`primary-button ${disabled ? "is-disabled" : ""}`} href={disabled ? undefined : href} data-version-id={versionId}>
      下载 DOCX
    </a>
  );
}
