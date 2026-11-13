import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockApi, renderWithSWR } from "@/test/utils";

import { AccessKey } from "./AccessKey";

const ALICE = { name: "alice", role: "approver", authenticated: true };

describe("AccessKey", () => {
  it("shows nothing when the API runs without keys", async () => {
    const fetchMock = mockApi({
      "/api/me": [200, { name: null, role: "approver", authenticated: false }],
    });
    const { container } = renderWithSWR(<AccessKey />);
    await expect.poll(() => fetchMock.mock.calls.length).toBe(1);
    expect(container).toBeEmptyDOMElement();
  });

  it("asks for a key when the API answers 401, then shows who signed in", async () => {
    const user = userEvent.setup();
    let signedIn = false;
    const fetchMock = mockApi({
      "/api/me": () => (signedIn ? [200, ALICE] : [401, { detail: "Send an API key." }]),
      "POST /session": (init) => {
        expect(JSON.parse(String(init?.body))).toEqual({ key: "ops_alice-key" });
        signedIn = true;
        return [200, ALICE];
      },
    });
    renderWithSWR(<AccessKey />);
    const field = await screen.findByLabelText("API key");
    expect(field).toHaveAttribute("type", "password");
    await user.type(field, "ops_alice-key");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(screen.getByText("approver")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toContain("/session");
  });

  it("offers a key field to a visitor the API lets in without one", async () => {
    mockApi({
      "/api/me": [200, { name: null, role: "viewer", authenticated: false, keys_enabled: true }],
    });
    renderWithSWR(<AccessKey />);
    expect(await screen.findByLabelText("API key")).toHaveAttribute("type", "password");
  });

  it("explains a key the API does not know", async () => {
    const user = userEvent.setup();
    mockApi({
      "/api/me": [401, { detail: "Send an API key." }],
      "POST /session": [401, { detail: "The agent API does not know this key." }],
    });
    renderWithSWR(<AccessKey />);
    await user.type(await screen.findByLabelText("API key"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("does not know this key");
    expect(screen.getByLabelText("API key")).toHaveAttribute("aria-invalid", "true");
  });
});
