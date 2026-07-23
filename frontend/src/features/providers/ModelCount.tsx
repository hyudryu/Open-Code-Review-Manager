import { useModels } from "../../api/hooks";

export function ModelCount({ providerId }: { providerId: string }) {
  const models = useModels(providerId);
  if (models.isLoading) return <span>…</span>;
  const list = models.data ?? [];
  const manual = list.filter((m) => m.is_manual).length;
  return (
    <span>
      {list.length}
      {manual ? <span style={{ color: "var(--text-tertiary)" }}> ({manual} manual)</span> : null}
    </span>
  );
}
