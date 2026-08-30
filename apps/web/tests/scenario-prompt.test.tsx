import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

import { ScenarioPrompt } from "@/features/exploration/scenario-prompt";
import { createScenario } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  createScenario: vi.fn(),
}));

describe("ScenarioPrompt", () => {
  beforeEach(() => {
    push.mockReset();
    vi.mocked(createScenario).mockReset();
    vi.mocked(createScenario).mockResolvedValue({ id: "abc-123", status: "created" });
  });

  it("renders domain picker with Auto-detect selected by default", () => {
    render(<ScenarioPrompt />);
    const auto = screen.getByRole("button", { name: /auto-detect/i });
    expect(auto).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /career/i })).toBeInTheDocument();
  });

  it("keeps explore disabled until input reaches minimum length", async () => {
    const user = userEvent.setup();
    render(<ScenarioPrompt />);
    const button = screen.getByRole("button", { name: /explore possibilities/i });
    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText(/describe your situation/i), "too short");
    expect(button).toBeDisabled();

    await user.type(
      screen.getByLabelText(/describe your situation/i),
      " — should I take this offer?"
    );
    expect(button).toBeEnabled();
  });

  it("creates scenario with selected domain and navigates to workspace", async () => {
    const user = userEvent.setup();
    render(<ScenarioPrompt />);

    await user.click(screen.getByRole("button", { name: /career/i }));
    await user.type(
      screen.getByLabelText(/describe your situation/i),
      "I got a job offer in Bengaluru and must decide soon."
    );
    await user.click(screen.getByRole("button", { name: /explore possibilities/i }));

    expect(createScenario).toHaveBeenCalledWith(
      expect.stringContaining("Bengaluru"),
      "career"
    );
    expect(push).toHaveBeenCalledWith("/scenario/abc-123");
  });

  it("fills the textarea from the flagship example", async () => {
    const user = userEvent.setup();
    render(<ScenarioPrompt />);
    await user.click(screen.getByRole("button", { name: /example scenario/i }));
    const value = (screen.getByLabelText(/describe your situation/i) as HTMLTextAreaElement).value;
    expect(value).toContain("Bengaluru");
    expect(value).toContain("40% more");
  });
});
