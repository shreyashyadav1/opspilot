"""API keys and roles: who may read, start investigations, and approve the agent's actions."""

from dataclasses import replace

import pytest

from opspilot_api.auth import Authenticator, digest, parse_anonymous_role, parse_keys
from opspilot_api.errors import ApiError
from opspilot_api.keys import main as keys_main
from opspilot_api.settings import ApiSettings
from tests.api.support import TERMINAL, build_app, serve, wait_for

KEYS = {"alice": "ops_alice-key", "olly": "ops_olly-key", "vic": "ops_vic-key"}
ENTRIES = (
    f"alice:approver:{digest(KEYS['alice'])},"
    f" olly:operator:{digest(KEYS['olly'])} ,"
    f"vic:viewer:{digest(KEYS['vic'])}"
)
ALERT = {"alert": "Checkout error rate above SLO", "target": "storefront"}


def bearer(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {KEYS[name]}"}


@pytest.fixture
def secured(settings: ApiSettings) -> ApiSettings:
    return replace(settings, api_keys=parse_keys(ENTRIES))


# -- key parsing -----------------------------------------------------------------------------


def test_entries_are_parsed_with_their_roles():
    keys = parse_keys(ENTRIES)
    assert [(k.name, k.role) for k in keys] == [
        ("alice", "approver"),
        ("olly", "operator"),
        ("vic", "viewer"),
    ]
    assert keys[0].sha256 == digest("ops_alice-key")
    assert parse_keys(None) == () == parse_keys(" , ")


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("alice:approver", "expected name:role:sha256"),
        (f"alice:admin:{'a' * 64}", "role must be one of"),
        ("alice:approver:not-a-digest", "64-character hex"),
        (f"al ice:approver:{'a' * 64}", "name must be"),
        (f"a:viewer:{'a' * 64},b:viewer:{'a' * 64}", "same key"),
        (f"a:viewer:{'a' * 64},a:approver:{'b' * 64}", "same name"),
    ],
)
def test_a_malformed_entry_is_a_startup_error(raw, message):
    with pytest.raises(ValueError, match=message):
        parse_keys(raw)


def test_settings_read_keys_from_the_environment(monkeypatch):
    monkeypatch.setattr("opspilot_api.settings.load_dotenv", lambda: None)
    monkeypatch.setenv("OPSPILOT_API_KEYS", ENTRIES)
    assert [k.name for k in ApiSettings.from_env().api_keys] == ["alice", "olly", "vic"]
    monkeypatch.setenv("OPSPILOT_API_KEYS", "broken")
    with pytest.raises(ValueError, match="expected name:role:sha256"):
        ApiSettings.from_env()


def test_authenticator_checks_scheme_key_and_role():
    auth = Authenticator(parse_keys(ENTRIES))
    assert auth.require("Bearer ops_olly-key", "operator").name == "olly"
    assert auth.require("bearer ops_alice-key", "viewer").role == "approver"
    for header in (None, "", "Basic ops_olly-key", "Bearer ", "Bearer wrong"):
        with pytest.raises(ApiError) as missing:
            auth.require(header, "viewer")
        assert missing.value.status_code == 401
        assert missing.value.headers == {"WWW-Authenticate": "Bearer"}
    with pytest.raises(ApiError) as forbidden:
        auth.require("Bearer ops_olly-key", "approver")
    assert forbidden.value.status_code == 403


def test_without_keys_everyone_is_an_unauthenticated_approver():
    principal = Authenticator(()).require(None, "approver")
    assert (principal.name, principal.authenticated) == (None, False)


@pytest.mark.parametrize(
    ("raw", "with_keys", "expected"),
    [
        (None, False, "approver"),
        (None, True, None),
        ("", True, None),
        ("none", True, None),
        (" Viewer ", True, "viewer"),
        ("operator", True, "operator"),
        ("viewer", False, "viewer"),
        ("approver", False, "approver"),
    ],
)
def test_anonymous_role_defaults_to_open_without_keys_and_closed_with_them(
    raw, with_keys, expected
):
    keys = parse_keys(ENTRIES) if with_keys else ()
    assert parse_anonymous_role(raw, keys) == expected


@pytest.mark.parametrize(
    ("raw", "with_keys", "message"),
    [
        ("none", False, "needs OPSPILOT_API_KEYS"),
        ("approver", True, "anyone approve without a key"),
        ("admin", True, "must be one of none, viewer"),
    ],
)
def test_an_unsafe_or_unusable_anonymous_role_is_a_startup_error(raw, with_keys, message):
    keys = parse_keys(ENTRIES) if with_keys else ()
    with pytest.raises(ValueError, match=message):
        parse_anonymous_role(raw, keys)


def test_settings_check_the_anonymous_role_at_startup(monkeypatch):
    monkeypatch.setattr("opspilot_api.settings.load_dotenv", lambda: None)
    monkeypatch.setenv("OPSPILOT_API_KEYS", ENTRIES)
    monkeypatch.setenv("OPSPILOT_ANONYMOUS_ROLE", "viewer")
    assert ApiSettings.from_env().anonymous_access == "viewer"
    monkeypatch.setenv("OPSPILOT_ANONYMOUS_ROLE", "approver")
    with pytest.raises(ValueError, match="anyone approve"):
        ApiSettings.from_env()
    monkeypatch.delenv("OPSPILOT_API_KEYS")
    assert ApiSettings.from_env().anonymous_access == "approver"


def test_a_keyless_caller_gets_the_anonymous_role_but_a_bad_key_is_still_refused():
    auth = Authenticator(parse_keys(ENTRIES), "viewer")
    for header in (None, "", "  "):
        principal = auth.require(header, "viewer")
        assert (principal.name, principal.role, principal.authenticated) == (
            None,
            "viewer",
            False,
        )
    for header in ("Bearer wrong", "Basic ops_olly-key", "Bearer "):
        with pytest.raises(ApiError) as refused:
            auth.require(header, "viewer")
        assert refused.value.status_code == 401
    with pytest.raises(ApiError) as forbidden:
        auth.require(None, "operator")
    assert forbidden.value.status_code == 403
    assert forbidden.value.detail == (
        "Without an API key you have the viewer role; this needs operator."
    )
    assert auth.require("Bearer ops_alice-key", "approver").name == "alice"


def test_without_keys_the_anonymous_role_can_be_lowered():
    auth = Authenticator((), "operator")
    assert auth.require(None, "operator").authenticated is False
    with pytest.raises(ApiError) as forbidden:
        auth.require(None, "approver")
    assert forbidden.value.status_code == 403


def test_key_command_prints_a_key_and_its_entry(capsys):
    assert keys_main(["new", "alice", "approver"]) == 0
    key_line, entry_line = capsys.readouterr().out.splitlines()
    key = key_line.removeprefix("key:").strip()
    assert key.startswith("ops_")
    assert len(key) > 40
    (parsed,) = parse_keys(entry_line.removeprefix("entry:").strip())
    assert (parsed.name, parsed.role, parsed.sha256) == ("alice", "approver", digest(key))


# -- the API with keys on --------------------------------------------------------------------


async def test_every_route_but_health_needs_a_key(secured, tools):
    async with serve(build_app(secured, tools, "escalate")) as client:
        assert (await client.get("/health")).status_code == 200
        for path in ("/config", "/me", "/investigations", "/benchmarks"):
            response = await client.get(path)
            assert response.status_code == 401, path
            assert response.headers["www-authenticate"] == "Bearer"
        assert (await client.post("/investigations", json=ALERT)).status_code == 401
        wrong = await client.get("/config", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401
        config = (await client.get("/config", headers=bearer("vic"))).json()
        assert config["auth_required"] is True
        me = (await client.get("/me", headers=bearer("olly"))).json()
        assert me == {
            "name": "olly",
            "role": "operator",
            "authenticated": True,
            "keys_enabled": True,
        }


async def test_viewers_read_and_operators_start_investigations(secured, tools):
    async with serve(build_app(secured, tools, "escalate")) as client:
        refused = await client.post("/investigations", json=ALERT, headers=bearer("vic"))
        assert refused.status_code == 403
        assert "needs operator" in refused.json()["detail"]
        created = await client.post("/investigations", json=ALERT, headers=bearer("olly"))
        assert created.status_code == 201
        client.headers.update(bearer("vic"))
        done = await wait_for(client, created.json()["id"], TERMINAL)
        assert done["status"] == "advisory"
        assert (await client.get("/investigations")).status_code == 200


async def test_only_an_approver_can_decide_and_the_key_names_the_reviewer(secured, tools):
    async with serve(build_app(secured, tools, "rollback_deploy")) as client:
        client.headers.update(bearer("olly"))
        investigation_id = (await client.post("/investigations", json=ALERT)).json()["id"]
        await wait_for(client, investigation_id, {"awaiting_approval"})
        url = f"/investigations/{investigation_id}/decision"

        for name in ("vic", "olly"):
            refused = await client.post(url, json={"decision": "approve"}, headers=bearer(name))
            assert refused.status_code == 403
        spoofed = await client.post(
            url, json={"decision": "approve", "reviewer": "bob"}, headers=bearer("alice")
        )
        assert spoofed.status_code == 422
        assert tools.rollbacks == []

        approved = await client.post(
            url,
            json={"decision": "approve", "comment": "matches the deploy"},
            headers=bearer("alice"),
        )
        assert approved.status_code == 200
        done = await wait_for(client, investigation_id, TERMINAL)
    assert done["status"] == "executed"
    assert done["approval"]["reviewer"] == "alice"
    assert done["approval"]["authenticated"] is True
    decision = next(e for e in done["trace"] if e["kind"] == "decision")
    assert decision["data"] == {
        "decision": "approve",
        "reviewer": "alice",
        "comment": "matches the deploy",
        "authenticated": True,
    }
    assert len(tools.rollbacks) == 1


async def test_without_keys_the_api_stays_open_and_says_so(settings, tools):
    async with serve(build_app(settings, tools, "rollback_deploy")) as client:
        assert (await client.get("/config")).json()["auth_required"] is False
        me = (await client.get("/me")).json()
        assert me == {
            "name": None,
            "role": "approver",
            "authenticated": False,
            "keys_enabled": False,
        }
        investigation_id = (await client.post("/investigations", json=ALERT)).json()["id"]
        await wait_for(client, investigation_id, {"awaiting_approval"})
        rejected = await client.post(
            f"/investigations/{investigation_id}/decision", json={"decision": "reject"}
        )
        approval = rejected.json()["approval"]
    assert (approval["reviewer"], approval["authenticated"]) == ("operator", False)


async def test_a_public_demo_is_watchable_without_a_key_but_only_approvers_act(secured, tools):
    public = replace(secured, anonymous_role="viewer")
    async with serve(build_app(public, tools, "rollback_deploy")) as client:
        me = (await client.get("/me")).json()
        assert me == {"name": None, "role": "viewer", "authenticated": False, "keys_enabled": True}
        assert (await client.get("/investigations")).status_code == 200
        refused = await client.post("/investigations", json=ALERT)
        assert refused.status_code == 403
        assert refused.json()["detail"].startswith("Without an API key you have the viewer role")
        assert (
            await client.get("/config", headers={"Authorization": "Bearer nope"})
        ).status_code == 401

        created = await client.post("/investigations", json=ALERT, headers=bearer("olly"))
        investigation_id = created.json()["id"]
        await wait_for(client, investigation_id, {"awaiting_approval"})
        url = f"/investigations/{investigation_id}/decision"
        assert (await client.post(url, json={"decision": "approve"})).status_code == 403
        assert tools.rollbacks == []
        approved = await client.post(url, json={"decision": "approve"}, headers=bearer("alice"))
        assert approved.status_code == 200
        done = await wait_for(client, investigation_id, TERMINAL)
    assert (done["approval"]["reviewer"], done["approval"]["authenticated"]) == ("alice", True)
    assert len(tools.rollbacks) == 1


async def test_demo_faults_need_an_operator_and_auth_comes_first(secured, tools):
    async with serve(build_app(secured, tools, "escalate")) as client:
        # Demo injection is disabled here; a caller without a key learns nothing about that.
        assert (await client.post("/demo/reset")).status_code == 401
        assert (await client.post("/demo/reset", headers=bearer("vic"))).status_code == 403
        assert (await client.get("/demo/catalog", headers=bearer("vic"))).status_code == 404
        assert (await client.post("/demo/reset", headers=bearer("olly"))).status_code == 404
        assert (await client.get("/investigations/inv-9999/events")).status_code == 401
