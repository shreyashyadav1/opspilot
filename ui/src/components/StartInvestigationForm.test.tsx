import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LLM, PLAYBOOK, config, investigation } from "@/test/fixtures";
import { mockApi, renderWithSWR } from "@/test/utils";

import { StartInvestigationForm } from "./StartInvestigationForm";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

describe("StartInvestigationForm", () => {
  beforeEach(() => push.mockReset());

  it("starts an investigation and opens it", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "/api/config": [200, config()],
      "POST /api/investigations": [201, investigation({ id: "inv-0042", status: "queued" })],
    });
    renderWithSWR(<StartInvestigationForm />);

    await user.click(screen.getByRole("button", { name: "Checkout p95 latency above SLO" }));
    expect(screen.getByLabelText("Alert")).toHaveValue("Checkout p95 latency above SLO");
    await user.selectOptions(screen.getByLabelText("Fired on"), "orders");
    await user.type(screen.getByLabelText("Firing for (min)"), "5");
    await user.click(screen.getByRole("button", { name: "Start investigation" }));

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      alert: "Checkout p95 latency above SLO",
      service: "orders",
      details: "POST /checkout p95 latency is above the 800 ms SLO.",
      firing_minutes: 5,
      model: null,
    });
    expect(push).toHaveBeenCalledWith("/investigations/inv-0042");
  });

  it("validates before sending anything", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "/api/config": [200, config()] });
    renderWithSWR(<StartInvestigationForm />);
    await user.clear(screen.getByLabelText("Alert"));
    await user.type(screen.getByLabelText("Alert"), "x");
    await user.click(screen.getByRole("button", { name: "Start investigation" }));
    expect(screen.getByRole("alert")).toHaveTextContent("at least 3 characters");
    expect(screen.getByLabelText("Alert")).toHaveFocus();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("offers the baseline when the configured LLM cannot run", async () => {
    mockApi({
      "/api/config": [
        200,
        config({
          model: LLM,
          models: [LLM, PLAYBOOK],
          model_error: "GROQ_API_KEY is not set.",
        }),
      ],
    });
    renderWithSWR(<StartInvestigationForm />);
    expect(await screen.findByText(/GROQ_API_KEY is not set/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start investigation" })).toBeDisabled();
    const model = screen.getByLabelText("Model");
    expect(model).toHaveTextContent("Rule-based playbook (rule-based baseline)");
    await userEvent.setup().selectOptions(model, "fake:playbook");
    expect(screen.getByRole("button", { name: "Start investigation" })).toBeEnabled();
  });
});
