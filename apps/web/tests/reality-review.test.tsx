import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RealityReview } from "@/features/exploration/reality-review";
import type { RealityState } from "@/lib/api";

const state: RealityState = {
  title: "Bengaluru offer vs current life",
  summary: "A career decision with family and startup tradeoffs.",
  domain: "career",
  actors: ["user"],
  entities: [],
  events: [
    { description: "Got an offer paying 40% more", timestamp: null, evidence_type: "grounded" },
    { description: "Might grow network", timestamp: null, evidence_type: "inferred" },
  ],
  decision_hints: [{ question: "Accept or negotiate?", options_hint: ["accept", "negotiate"], importance: 0.9 }],
  constraints: [
    { description: "Budget cap", kind: "financial", key: "monthly_cost", operator: "<=", value: 30000 },
  ],
  goals: ["Build a startup"],
  relationships: ["Partner in current city"],
  resources: ["Stable salary"],
  beliefs: [],
  uncertainties: ["Remote possibility"],
  missing_information: ["Bengaluru rent"],
  facts: [],
  state_variables: {},
};

describe("RealityReview", () => {
  it("shows the detected domain as a badge", () => {
    render(<RealityReview state={state} />);
    expect(screen.getByTestId("domain-badge")).toHaveTextContent("career");
  });

  it("labels evidence classes per event", () => {
    render(<RealityReview state={state} />);
    expect(screen.getByText("grounded")).toBeInTheDocument();
    expect(screen.getByText("inferred")).toBeInTheDocument();
    expect(screen.getByText(/40% more/)).toBeInTheDocument();
  });

  it("renders numeric constraint in machine-readable form", () => {
    render(<RealityReview state={state} />);
    expect(screen.getByText(/monthly_cost <= 30000/)).toBeInTheDocument();
  });

  it("separates unknowns from missing information", () => {
    render(<RealityReview state={state} />);
    expect(screen.getByText("? Remote possibility")).toBeInTheDocument();
    expect(screen.getByText("✗ Bengaluru rent")).toBeInTheDocument();
  });
});
