from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_keeps_supplied_design_and_runtime_config():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "--acc:#6d3df0" in html
    assert "./config.js" in html
    assert "./api-client.js" in html
    assert "auth-card" in html


def test_no_old_cognito_ids_or_hosted_ui_origin_remain():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    config = (ROOT / "frontend" / "config.js").read_text(encoding="utf-8")
    template = (ROOT / "template.yaml").read_text(encoding="utf-8")
    combined = html + config + template
    assert "ap-south-1_" + "Xr4xa2906" not in combined
    assert "pamq4m9ebevid8m883jkhv1k2" not in combined
    assert "main." + "d1mkr23liin8gp.amplifyapp.com" not in combined


def test_sync_client_does_not_send_local_demo_data():
    client = (ROOT / "frontend" / "api-client.js").read_text(encoding="utf-8")
    assert "user.localDemo" in client
    assert 'Authorization: token' in client
    assert 'request("/ideas"' in client
    assert 'request("/assignments"' in client
    assert 'request("/projects"' in client
    assert 'request("/settings"' in client
    assert 'request("/notifications"' in client


def test_local_demo_exposes_faculty_preview_without_granting_deployed_access():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'id="faculty-demo-login"' in html
    assert '!hasCognito' in html
    assert 'local:faculty-demo' in html
    assert "does not grant faculty access in AWS" in html


def test_cloud_frontend_uses_domain_routes_and_does_not_seed_shared_demo_records():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    client = (ROOT / "frontend" / "api-client.js").read_text(encoding="utf-8")
    assert 'if(!ideas.length&&!hasCognito)seed();' in html
    assert 'if(!asgs.length&&!hasCognito)' in html
    assert 'if(!fps.length&&!hasCognito)' in html
    for route in ('"/ideas"', '"/assignments"', '"/projects"', '"/settings"', '"/notifications"', '"/library"'):
        assert route in client
    assert 'cloud-state-updated' in client
