import type { ModelOption } from "../api/types";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type ModelSelectorProps = {
  models: ModelOption[];
  provider: string;
  model: string;
  onChange: (provider: string, model: string) => void;
};

export function ModelSelector({ models, provider, model, onChange }: ModelSelectorProps) {
  const grouped = models.reduce<Record<string, ModelOption[]>>((acc, item) => {
    acc[item.provider] ??= [];
    acc[item.provider].push(item);
    return acc;
  }, {});

  const providerOptions = Object.keys(grouped);
  const activeProvider = provider || providerOptions[0] || "";
  const modelOptions = grouped[activeProvider] ?? [];
  const activeModel = model || modelOptions[0]?.name || "";

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div className="flex flex-col gap-1.5">
        <Label>模型厂商</Label>
        <Select
          value={activeProvider}
          onValueChange={(nextProvider) => {
            const nextModel = grouped[nextProvider]?.[0]?.name ?? "";
            onChange(nextProvider, nextModel);
          }}
          disabled={providerOptions.length === 0}
        >
          <SelectTrigger>
            <SelectValue placeholder="请选择厂商" />
          </SelectTrigger>
          <SelectContent>
            {providerOptions.map((item) => (
              <SelectItem key={item} value={item}>
                {item}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label>模型名称</Label>
        <Select
          value={activeModel}
          onValueChange={(next) => onChange(activeProvider, next)}
          disabled={modelOptions.length === 0}
        >
          <SelectTrigger>
            <SelectValue placeholder="请选择模型" />
          </SelectTrigger>
          <SelectContent>
            {modelOptions.map((item) => (
              <SelectItem key={`${item.provider}-${item.name}`} value={item.name}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}