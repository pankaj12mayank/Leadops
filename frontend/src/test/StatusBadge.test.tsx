import { render, screen } from "@testing-library/react";
import { StatusBadge } from "@/components/shared/StatusBadge";

describe("StatusBadge", () => {
  it("renders status value", () => {
    render(<StatusBadge value="running" />);
    expect(screen.getByText("running")).toBeInTheDocument();
  });

  it("renders source type", () => {
    render(<StatusBadge value="clutch" type="source" />);
    expect(screen.getByText("clutch")).toBeInTheDocument();
  });

  it("falls back to gray for unknown values", () => {
    render(<StatusBadge value="unknown" />);
    const el = screen.getByText("unknown");
    expect(el).toBeInTheDocument();
    expect(el.className).toContain("gray");
  });
});
