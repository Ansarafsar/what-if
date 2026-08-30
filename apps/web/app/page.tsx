import { ScenarioPrompt } from "@/features/exploration/scenario-prompt";

export default function HomePage() {
  return (
    <div className="mx-auto flex max-w-6xl flex-col items-center px-4 py-16 sm:py-20">
      <h1 className="text-balance text-center text-4xl font-bold tracking-tight sm:text-5xl">
        You are here.
      </h1>
      <p className="mt-3 text-center text-lg text-muted-foreground">
        What situation do you want to explore?
      </p>

      <div className="mt-10 flex w-full justify-center">
        <ScenarioPrompt />
      </div>
    </div>
  );
}
