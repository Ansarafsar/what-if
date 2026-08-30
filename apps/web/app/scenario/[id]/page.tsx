import { ScenarioWorkspace } from "@/features/exploration/scenario-workspace";

export const metadata = {
  title: "Exploring",
};

export default async function ScenarioPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <ScenarioWorkspace scenarioId={id} />
    </div>
  );
}
