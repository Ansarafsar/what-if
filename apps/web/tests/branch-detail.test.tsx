import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BranchDetailSheet } from "@/features/exploration/branch-detail";
import type { GraphNode } from "@/lib/api";

const stateNode: GraphNode = {
  id: "n1",
  parent_id: "d1",
  node_type: "state",
  title: "Accept and relocate",
  description: "You move in six weeks.",
  plausibility: "high",
  score: 0.71,
  metadata: {
    strategy: "conventional",
    rationale: "Directly captures the raise.",
    reversible: false,
    depth: 2,
    path_labels: ["Accept and relocate"],
    state_delta: { location: ["Salem", "Bengaluru"], salary: 112000 },
    score_breakdown: { relevance: 0.175, novelty: 0.15, redundancy: -0.04 },
    effects: [
      {
        dimension: "money",
        direction: "up",
        magnitude: "high",
        order: 1,
        explanation: "40% more salary.",
      },
    ],
    evidence: {
      grounded_reasons: ["Consistent with the stated offer"],
      assumptions: [{ claim: "Rent is affordable", depends_on: ["salary"] }],
      risks: ["Relationship strain"],
      constraint_violations: ["'salary' would become 80000, violating salary >= 100000"],
      critic: { verdict: "revise", issues: ["needs a rent figure"] },
    },
    resulting_state: {
      title: "Accept and relocate",
      summary: "You move.",
      domain: "career",
      actors: [],
      entities: [],
      events: [],
      decision_hints: [],
      constraints: [],
      goals: [],
      relationships: [],
      resources: [],
      beliefs: [],
      uncertainties: [],
      missing_information: [],
      facts: [],
      state_variables: { location: "Bengaluru", salary: 112000 },
    },
  },
};

const decisionNode: GraphNode = {
  id: "d2",
  parent_id: "root",
  node_type: "decision",
  title: "Fork point",
  description: "Another choice you have not opened.",
  plausibility: null,
  score: null,
  metadata: {
    question: "Move now or wait a year?",
    importance: 0.62,
    expanded: false,
    depth: 1,
  },
};

const realityNode: GraphNode = {
  id: "root",
  parent_id: null,
  node_type: "reality",
  title: "You are here",
  description: "The situation as stated.",
  plausibility: null,
  score: null,
  metadata: {
    depth: 0,
    resulting_state: {
      ...(stateNode.metadata.resulting_state as NonNullable<
        GraphNode["metadata"]["resulting_state"]
      >),
      facts: [
        { claim: "Offer pays 40% more", evidence_type: "grounded", source: "user_input", confidence: 1 },
        { claim: "Network may grow", evidence_type: "inferred", source: "user_input", confidence: 0.7 },
      ],
    },
  },
};

describe("BranchDetailSheet on an outcome node", () => {
  it("surfaces the score breakdown the backend already sends", () => {
    render(<BranchDetailSheet node={stateNode} onClose={() => {}} />);
    const breakdown = screen.getByTestId("score-breakdown");
    expect(breakdown).toHaveTextContent("relevance");
    expect(breakdown).toHaveTextContent("0.175");
    expect(breakdown).toHaveTextContent("-0.040");
  });

  it("renders the state delta as before → after", () => {
    render(<BranchDetailSheet node={stateNode} onClose={() => {}} />);
    const table = screen.getByTestId("state-delta");
    expect(table).toHaveTextContent("Salem");
    expect(table).toHaveTextContent("Bengaluru");
    expect(table).toHaveTextContent("112000");
  });

  it("shows constraint violations as a warning", () => {
    render(<BranchDetailSheet node={stateNode} onClose={() => {}} />);
    expect(screen.getByTestId("constraint-violations")).toHaveTextContent("salary >= 100000");
  });

  it("answers why this branch appeared", () => {
    render(<BranchDetailSheet node={stateNode} onClose={() => {}} />);
    expect(screen.getByTestId("rationale")).toHaveTextContent("captures the raise");
  });

  it("shows the path taken to reach this branch", () => {
    render(<BranchDetailSheet node={stateNode} onClose={() => {}} />);
    expect(screen.getByTestId("path-labels")).toHaveTextContent("Accept and relocate");
  });

  it("closes when asked", async () => {
    const onClose = vi.fn();
    render(<BranchDetailSheet node={stateNode} onClose={onClose} />);
    await userEvent.click(screen.getByLabelText("Close details"));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("BranchDetailSheet on other node types", () => {
  it("renders a fork instead of showing nothing", () => {
    render(<BranchDetailSheet node={decisionNode} onClose={() => {}} />);
    expect(screen.getByTestId("branch-detail")).toHaveTextContent("Move now or wait a year?");
    expect(screen.getByTestId("branch-detail")).toHaveTextContent("not expanded");
  });

  it("renders reality with evidence chips", () => {
    render(<BranchDetailSheet node={realityNode} onClose={() => {}} />);
    const chips = screen.getByTestId("evidence-chips");
    expect(chips).toHaveTextContent("grounded");
    expect(chips).toHaveTextContent("inferred");
    expect(chips).toHaveTextContent("Offer pays 40% more");
  });
});
