import importlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("TABLE", "unit-test-table")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
os.environ.setdefault("ALLOWED_ORIGIN", "http://localhost:8000")
backend = importlib.import_module("lambda_function")


class FakeTable:
    def __init__(self):
        self.items = {}
    def get_item(self, Key, **kwargs):
        return {"Item": self.items[Key["id"]]} if Key["id"] in self.items else {}
    def put_item(self, Item):
        self.items[Item["id"]] = Item


@pytest.fixture
def table(monkeypatch):
    value = FakeTable()
    monkeypatch.setattr(backend, "table", value)
    return value


def event(method, sub="student-sub", body=None):
    return {
        "resource": "/sync", "httpMethod": method,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": {"sub": sub, "email": "student@example.edu", "cognito:groups": "[]"}}}
    }


def test_sync_requires_verified_authorizer_claims():
    response = backend.handler({"httpMethod": "GET", "resource": "/sync"}, None)
    assert response["statusCode"] == 401


def test_sync_get_is_keyed_by_authenticated_subject(table):
    table.items["userstate:student-sub"] = {"id": "userstate:student-sub", "owner": "student-sub", "payload": '{"ideas4":"[]"}', "updatedAt": 1}
    response = backend.handler(event("GET"), None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["state"] == {"ideas4": "[]"}
    other = backend.handler(event("GET", sub="different-sub"), None)
    assert json.loads(other["body"])["state"] is None


def test_sync_put_uses_claim_subject_and_validates_payload(table):
    response = backend.handler(event("PUT", body={"state": {"ideas4": "[]", "weights1": "{}"}, "owner": "victim-sub"}), None)
    assert response["statusCode"] == 200
    stored = table.items["userstate:student-sub"]
    assert stored["owner"] == "student-sub"
    assert json.loads(stored["payload"]) == {"ideas4": "[]", "weights1": "{}"}
    bad = backend.handler(event("PUT", body={"state": {"passwords": "{}"}}), None)
    assert bad["statusCode"] == 400


def api_event(resource, method, sub="student-sub", email="student@example.edu", groups=None, body=None, path_id=None):
    event = {
        "resource": resource,
        "httpMethod": method,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": {
            "sub": sub, "email": email,
            "cognito:groups": groups if groups is not None else "[]",
            "name": "Test User"
        }}}
    }
    if path_id is not None:
        event["pathParameters"] = {"id": path_id}
    return event


def test_student_cannot_create_faculty_assignment(monkeypatch, table):
    monkeypatch.setattr(backend, "scan_all", lambda: [])
    monkeypatch.setattr(backend, "get_weights", lambda: dict(backend.DEFAULT_W))
    response = backend.handler(api_event("/assignments", "POST", body={}), None)
    assert response["statusCode"] == 403
    assert table.items == {}


def test_idea_list_is_scoped_to_owner_or_team(monkeypatch, table):
    records = [
        {"id": "idea-one", "recordType": "idea", "owner": "student-sub", "ownerEmail": "student@example.edu", "team": [], "status": "Pending", "s": {}, "total": 50},
        {"id": "idea-two", "recordType": "idea", "owner": "another-sub", "ownerEmail": "other@example.edu", "team": ["student@example.edu"], "status": "Pending", "s": {}, "total": 60},
        {"id": "idea-three", "recordType": "idea", "owner": "another-sub", "ownerEmail": "other@example.edu", "team": [], "status": "Pending", "s": {}, "total": 70},
    ]
    monkeypatch.setattr(backend, "scan_all", lambda: records)
    monkeypatch.setattr(backend, "get_weights", lambda: dict(backend.DEFAULT_W))
    response = backend.handler(api_event("/ideas", "GET"), None)
    payload = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert {x["id"] for x in payload} == {"idea-one", "idea-two"}


def test_delete_cannot_target_private_workspace_record(monkeypatch, table):
    monkeypatch.setattr(backend, "scan_all", lambda: [])
    monkeypatch.setattr(backend, "get_weights", lambda: dict(backend.DEFAULT_W))
    response = backend.handler(api_event("/ideas/{id}", "DELETE", path_id="userstate:victim-sub"), None)
    assert response["statusCode"] == 403
    assert table.items == {}
