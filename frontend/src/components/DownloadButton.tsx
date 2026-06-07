import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

type DownloadButtonProps = {
  versionId: string;
  href: string;
  disabled?: boolean;
};

export function DownloadButton({ versionId, href, disabled }: DownloadButtonProps) {
  if (disabled) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span>
            <Button variant="default" disabled className="gap-2">
              <Download className="h-4 w-4" />
              下载 DOCX
            </Button>
          </span>
        </TooltipTrigger>
        <TooltipContent>翻译完成后可下载</TooltipContent>
      </Tooltip>
    );
  }

  return (
    <Button asChild className="gap-2">
      <a href={href} data-version-id={versionId}>
        <Download className="h-4 w-4" />
        下载 DOCX
      </a>
    </Button>
  );
}