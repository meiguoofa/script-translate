import { useState } from "react";
import { ShieldCheck, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "@/components/ui/sonner";
import { verifyPassphrase } from "@/api/client";
import { setPassphrase } from "@/lib/passphrase";

type Props = {
  onVerified: () => void;
};

export function PassphraseGate({ onVerified }: Props) {
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    setSubmitting(true);
    try {
      setPassphrase(trimmed);
      await verifyPassphrase(trimmed);
      toast.success("访问密钥已验证");
      onVerified();
    } catch {
      setPassphrase("");
      toast.error("访问密钥不正确，请重新输入");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card className="mx-auto max-w-md">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5" />
          访问密钥
        </CardTitle>
        <CardDescription>该页面包含付费 API 调用，请先输入访问密钥继续。</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="passphrase">访问密钥</Label>
            <Input
              id="passphrase"
              type="password"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              autoFocus
              required
            />
          </div>
          <Button type="submit" disabled={submitting || !value.trim()}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {submitting ? "校验中…" : "确认"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
