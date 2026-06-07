import type { ModelOption } from "../api/types";

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
    <div className="field-grid model-grid">
      <label>
        <span>模型厂商</span>
        <select
          value={activeProvider}
          onChange={(event) => {
            const nextProvider = event.target.value;
            const nextModel = grouped[nextProvider]?.[0]?.name ?? "";
            onChange(nextProvider, nextModel);
          }}
        >
          {providerOptions.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>模型名称</span>
        <select value={activeModel} onChange={(event) => onChange(activeProvider, event.target.value)}>
          {modelOptions.map((item) => (
            <option key={`${item.provider}-${item.name}`} value={item.name}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
