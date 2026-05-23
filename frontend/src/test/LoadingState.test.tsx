import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LoadingState, PageLoading } from "@/components/shared/LoadingState";

describe("LoadingState", () => {
  it("renders default 3 rows with 3 skeleton slots each", () => {
    const { container } = render(<LoadingState />);
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBe(9);
  });

  it("renders custom row count", () => {
    const { container } = render(<LoadingState rows={5} />);
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBe(15);
  });
});

describe("PageLoading", () => {
  it("renders loading text", () => {
    render(<PageLoading />);
    expect(screen.getByText("Loading...")).toBeTruthy();
  });

  it("renders a spinner", () => {
    const { container } = render(<PageLoading />);
    const spinner = container.querySelector(".animate-spin");
    expect(spinner).toBeTruthy();
  });
});
