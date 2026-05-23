import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EmptyState } from "@/components/shared/EmptyState";

describe("EmptyState", () => {
  it("renders default title and message", () => {
    render(<EmptyState />);
    expect(screen.getByText("No data yet")).toBeTruthy();
    expect(screen.getByText("Run a scraper or merge to generate data.")).toBeTruthy();
  });

  it("renders custom title and message", () => {
    render(<EmptyState title="No exports" message="Nothing to show here" />);
    expect(screen.getByText("No exports")).toBeTruthy();
    expect(screen.getByText("Nothing to show here")).toBeTruthy();
  });

  it("renders the Inbox icon", () => {
    const { container } = render(<EmptyState />);
    const svg = container.querySelector("svg");
    expect(svg).toBeTruthy();
  });
});
