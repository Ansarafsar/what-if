export default function Loading() {
  return (
    <div
      className="mx-auto flex max-w-6xl flex-col items-center gap-6 px-4 py-24"
      role="status"
      aria-label="Loading"
    >
      <div className="h-10 w-72 animate-pulse rounded-md bg-muted" />
      <div className="h-40 w-full max-w-2xl animate-pulse rounded-xl bg-muted" />
    </div>
  );
}
