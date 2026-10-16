import json, os, re, time, traceback, uuid, math
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Key

try:
    from botocore.exceptions import ClientError
except ImportError:
    ClientError = Exception

table = boto3.resource("dynamodb").Table(os.environ["TABLE"])
DEFAULT_W = {"innovation": 20, "feasibility": 20, "cost": 15, "time": 15, "impact": 20, "scalability": 10}


from evaluation import words, sim, clamp, score_idea, rules_review


def score(d, others, wts):
    result = score_idea(d, others, wts)
    return result["scores"], result["total"]


bedrock = boto3.client("bedrock-runtime") if os.environ.get("MODEL_ID") else None
ses = boto3.client("ses")


def ai_review(d, others):
    if bedrock is None or not os.environ.get("MODEL_ID"):
        return None
    prompt = (
        "You review student cloud computing project ideas. Return only JSON with keys: "
        "innovation (0-10), summary, risks (list), suggestions (list), tech (list), "
        "closest, closestWhy.\n"
        f"Idea: {d['title']}\nDescription: {d['desc']}\nPlanned technologies: {d['stack']}\nExisting ideas:\n"
        + "\n".join(o["title"] + ": " + o["desc"] for o in others[:10])
    )
    out = bedrock.converse(modelId=os.environ["MODEL_ID"],
                           messages=[{"role": "user", "content": [{"text": prompt}]}])
    raw_text = out["output"]["message"]["content"][0]["text"]
    match = re.search(r"\{.*\}", raw_text, re.S)
    if not match:
        raise ValueError("Model returned no JSON object")
    result = json.loads(match.group(0))
    if not isinstance(result, dict):
        raise ValueError("Model response must be an object")
    try:
        innovation = float(result["innovation"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Model response innovation score is invalid")
    if not math.isfinite(innovation) or not 0 <= innovation <= 10:
        raise ValueError("Model response innovation score is outside 0-10")
    def text_list(value, limit, max_len=240):
        if not isinstance(value, list):
            return []
        return [str(x).strip()[:max_len] for x in value[:limit] if isinstance(x, (str, int, float)) and str(x).strip()]
    return {"innovation": innovation,
            "summary": str(result.get("summary", ""))[:500],
            "risks": text_list(result.get("risks"), 4),
            "suggestions": text_list(result.get("suggestions"), 4),
            "tech": text_list(result.get("tech"), 5, 100),
            "closest": str(result.get("closest", ""))[:120],
            "closestWhy": str(result.get("closestWhy", ""))[:300],
            "method": "optional-model-adapter",
            "disclaimer": "Model-generated advice is unverified; similarity is not proof of copying."}


def total_of(s, wts):
    return round(sum(float(s[k]) * wts[k] / 10 for k in wts))


def notify(item, status, feedback):
    sender = os.environ.get("SENDER")
    to = [e for e in [item.get("ownerEmail")] + list(item.get("team", [])) if e]
    if not sender or not to:
        return
    verdict = "approved" if status == "Approved" else "not approved"
    lines = [f'Your project idea "{item["title"]}" was {verdict}.',
             f'Score: {item["total"]} out of 100.']
    if feedback:
        lines.append("Faculty feedback: " + feedback)
    if status == "Approved":
        lines.append("You can now add your GitHub and demo links in the Idea Evaluator.")
    ses.send_email(
        Source=sender,
        Destination={"ToAddresses": to},
        Message={"Subject": {"Data": f'Idea {status.lower()}: {item["title"]}'},
                 "Body": {"Text": {"Data": "\n\n".join(lines)}}})


FIELDS = ("title", "desc", "users", "complexity", "skill", "budget", "weeks", "impact", "stack", "sdg", "why")
CLOUD = ("aws", "amazon", "lambda", "s3", "dynamodb", "cognito", "amplify", "ec2", "ecs", "eks", "cloudfront",
         "api gateway", "apigateway", "sns", "sqs", "bedrock", "sagemaker", "rds", "aurora", "azure", "gcp",
         "google cloud", "firebase", "firestore", "heroku", "vercel", "netlify", "cloudflare", "digitalocean",
         "atlas", "supabase", "serverless", "cloud")
LOCAL = ("offline", "desktop", "arduino", "raspberry", "esp32", "sqlite", "xampp", "local server",
         "local database", "localhost", "on-premise", "on premise")


def hits(text, words):
    return [k for k in words if re.search(r"(^|[^a-z0-9])" + re.escape(k) + r"([^a-z0-9]|$)", text.lower())]


def arch_of(stack):
    c, l = hits(stack, CLOUD), hits(stack, LOCAL)
    return "hybrid" if c and l else "cloud" if c else "local"


def clean_idea(body):
    if not isinstance(body, dict):
        raise ValueError("Idea must be an object")
    d = {k: body.get(k, "") for k in FIELDS}
    d["title"] = tidy(d["title"], 120)
    d["desc"] = str(d["desc"] or "").strip()[:1000]
    d["users"], d["why"], d["sdg"] = tidy(d["users"], 120), tidy(d["why"], 200), tidy(d["sdg"], 2)
    if len(d["title"]) < 3 or len(d["desc"]) < 20:
        raise ValueError("Title must have 3 characters and description 20 characters")
    for k, lo, hi in (("complexity", 1, 3), ("skill", 1, 3), ("impact", 1, 5), ("budget", 0, 10**7), ("weeks", 1, 52)):
        raw = d[k] if d[k] not in (None, "") else lo
        try:
            number = float(raw)
        except (ValueError, TypeError):
            raise ValueError(f"{k} must be numeric")
        if not math.isfinite(number) or number < lo or number > hi:
            raise ValueError(f"{k} is outside the allowed range")
        d[k] = number
    if d["sdg"] and (not d["sdg"].isdigit() or not 1 <= int(d["sdg"]) <= 17):
        raise ValueError("SDG must be between 1 and 17")
    d["stack"] = tidy(d["stack"], 200)
    if len(d["stack"]) < 3:
        raise ValueError("stack is required")
    d["arch"] = arch_of(d["stack"])
    return d


def get_weights():
    item = table.get_item(Key={"id": "config:weights"}).get("Item")
    return {k: int(v) for k, v in item["w"].items()} if item else dict(DEFAULT_W)


MAX_REQUESTS_PER_YEAR = 2
RESERVED = ("config:", "fp:", "asg:", "note:", "userstate:")
CLASSES = ("ECE A", "ECE B", "ECEAIML A", "ECEAIML B", "E&CE A", "E&CE B")


def today_local():
    offset = int(os.environ.get("TZ_OFFSET_MIN", "330"))
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + offset * 60))


def asg_state(a):
    t = today_local()
    return "Closed" if a.get("closed") or t > a["closes"] else "Upcoming" if t < a["opens"] else "Open"


def note(emails, text):
    now = int(time.time())
    for e in {x.lower() for x in emails if x}:
        table.put_item(Item={"id": "note:" + str(uuid.uuid4()), "recordType": "notification", "to": e, "text": text[:300], "at": now,
                             "seen": False, "ttl": now + 90 * 86400})
MAX_IDEAS_PER_DAY = 5


def tidy(text, limit):
    return " ".join(str(text).split())[:limit]


def scan_all():
    """Load application records through the recordType GSI, never a full-table scan."""
    items = []
    for kind in ("idea", "project", "assignment", "notification", "config"):
        kw = {"IndexName": "recordType-index", "KeyConditionExpression": Key("recordType").eq(kind)}
        while True:
            page = table.query(**kw)
            items.extend(page.get("Items", []))
            last = page.get("LastEvaluatedKey")
            if not last:
                break
            kw["ExclusiveStartKey"] = last
    return items


def requests_used(projects, me):
    year = time.gmtime().tm_year
    return sum(1 for p in projects for r in p["requests"]
               if r["sub"] == me and time.gmtime(int(r.get("created", time.time()))).tm_year == year)


def open_slots(p):
    return int(p["slots"]) - sum(1 for r in p["requests"] if r["status"] == "Accepted")


def is_open(p):
    return p["status"] == "Open" and open_slots(p) > 0 and (not p.get("deadline") or today_local() <= p["deadline"])


def mail(to, subject, text):
    sender = os.environ.get("SENDER")
    if sender and to:
        ses.send_email(Source=sender, Destination={"ToAddresses": to},
                       Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": text}}})


def project_view(p, me, faculty, used=0):
    out = {k: p.get(k) for k in ("id", "title", "desc", "skills", "slots", "deadline", "status", "ownerName", "ownerEmail")}
    mine = next((r for r in p["requests"] if r["sub"] == me), None)
    out.update(left=open_slots(p), open=is_open(p), myRequest=mine["status"] if mine else None,
               team=[r["name"] or "Student" for r in p["requests"] if r["status"] == "Accepted"])
    if faculty or (mine and mine["status"] == "Accepted"):
        out.update(gh=p.get("gh", ""), demo=p.get("demo", ""), pub=p.get("pub", True))
    if faculty:
        out["requests"] = p["requests"]
    else:
        out["requestsUsed"] = used
    return out


def handle_project(event, claims, is_faculty, projects):
    key = {"id": event["pathParameters"]["id"]}
    b = json.loads(event["body"])
    me, act = claims["sub"], b.get("action")
    for _ in range(3):
        p = table.get_item(Key=key).get("Item")
        if not p or not key["id"].startswith("fp:"):
            return reply(404, {"error": "Project not found"})
        mine = next((r for r in p["requests"] if r["sub"] == me), None)
        owner = is_faculty and p["owner"] == me
        notice, alerts = None, []
        if act == "request" and not is_faculty:
            msg = str(b.get("msg", "")).strip()[:160]
            if requests_used(projects, me) >= MAX_REQUESTS_PER_YEAR:
                return reply(400, {"error": "You have used both requests for this year"})
            if len(msg) < 5 or mine or not is_open(p):
                return reply(400, {"error": "This request cannot be made"})
            p["requests"].append({"id": str(uuid.uuid4()), "sub": me, "email": claims.get("email", ""),
                                  "name": claims.get("name", ""), "msg": msg, "status": "Pending",
                                  "created": int(time.time())})
            alerts.append(([p.get("ownerEmail", "")], f'{claims.get("name") or claims.get("email", "A student")} asked to join "{p["title"]}".'))
        elif act == "withdraw" and not is_faculty and mine and mine["status"] == "Pending":
            mine["status"] = "Withdrawn"
            alerts.append(([p.get("ownerEmail", "")], f'{claims.get("name") or claims.get("email", "A student")} withdrew the request for "{p["title"]}".'))
        elif act == "remove" and owner:
            r = next((x for x in p["requests"] if x["id"] == b.get("requestId")), None)
            if not r or r["status"] != "Accepted":
                return reply(400, {"error": "This student cannot be removed"})
            r["status"] = "Removed"
            notice = ([r["email"]], f'Removed from project: {p["title"]}', f'You were removed from "{p["title"]}".')
            alerts.append(([r["email"]], f'You were removed from "{p["title"]}".'))
        elif act == "decide" and owner:
            r = next((x for x in p["requests"] if x["id"] == b.get("requestId")), None)
            dec = b.get("decision")
            if not r or r["status"] != "Pending" or dec not in ("Accepted", "Declined") or (dec == "Accepted" and open_slots(p) < 1):
                return reply(400, {"error": "This decision cannot be made"})
            r["status"] = dec
            notice = ([r["email"]], f'Project request {dec.lower()}: {p["title"]}',
                      f'Your request to join "{p["title"]}" was {dec.lower()}.'
                      + (" Add your demo link in the Idea Evaluator when the project is ready." if dec == "Accepted" else ""))
            alerts.append(([r["email"]], f'Your request to join "{p["title"]}" was {dec.lower()}.'))
        elif act == "toggle" and owner:
            p["status"] = "Closed" if p["status"] == "Open" else "Open"
        elif act == "links" and mine and mine["status"] == "Accepted":
            gh, demo = str(b.get("gh", "")).strip()[:200], str(b.get("demo", "")).strip()[:300]
            if not (gh or demo) or (gh and not gh.startswith("https://github.com/")) or (demo and not demo.startswith("https://")):
                return reply(400, {"error": "Check the links"})
            p["gh"], p["demo"], p["pub"] = gh, demo, bool(b.get("pub", True))
        else:
            return reply(403, {"error": "Not allowed"})
        old = int(p.get("ver", 0))
        try:
            table.update_item(Key=key, UpdateExpression="SET requests=:r, #s=:s, gh=:g, demo=:d, pub=:p, ver=:nv",
                              ConditionExpression="attribute_not_exists(ver) OR ver = :old",
                              ExpressionAttributeNames={"#s": "status"},
                              ExpressionAttributeValues={":r": p["requests"], ":s": p["status"], ":g": p.get("gh", ""),
                                                         ":d": p.get("demo", ""), ":p": p.get("pub", True),
                                                         ":nv": old + 1, ":old": old})
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            continue
        for to, text in alerts:
            try:
                note(to, text)
            except Exception:
                pass
        if notice:
            try:
                mail(*notice)
            except Exception:
                pass
        return reply(200, {"ok": True})
    return reply(409, {"error": "Busy, please try again"})


def enc(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    return str(o)


def reply(code, body):
    origin = os.environ.get("ALLOWED_ORIGIN", "http://localhost:8000")
    return {"statusCode": code, "headers": {"Content-Type": "application/json",
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
            "Vary": "Origin"}, "body": json.dumps(body, default=enc)}


def handler(event, context):
    try:
        event["requestContext"]["authorizer"]["claims"]
    except (KeyError, TypeError):
        return reply(401, {"error": "Not signed in"})
    try:
        return process(event)
    except (ValueError, KeyError, TypeError, AttributeError):
        print(traceback.format_exc())
        return reply(400, {"error": "The request is not valid"})
    except Exception:
        print(traceback.format_exc())
        return reply(500, {"error": "Something went wrong"})


def process(event):
    claims = event["requestContext"]["authorizer"]["claims"]
    groups = claims.get("cognito:groups", [])
    if isinstance(groups, str):
        try:
            groups = json.loads(groups) if groups.startswith("[") else groups.split(",")
        except ValueError:
            groups = []
    is_faculty = "faculty" in groups
    method = event["httpMethod"]

    # Private, per-Cognito-user browser-state synchronization. The caller cannot
    # choose the owner key; it is always derived from the verified token's sub.
    if event.get("resource") == "/sync":
        sub = claims.get("sub")
        if not sub:
            return reply(401, {"error": "Not signed in"})
        key = {"id": "userstate:" + sub}
        if method == "GET":
            item = table.get_item(Key=key, ConsistentRead=True).get("Item")
            if not item:
                return reply(200, {"state": None})
            try:
                state = json.loads(item.get("payload", "{}"))
            except (TypeError, ValueError):
                return reply(500, {"error": "Saved workspace data could not be read"})
            return reply(200, {"state": state, "updatedAt": item.get("updatedAt")})
        if method == "PUT":
            try:
                body = json.loads(event.get("body") or "{}")
                state = body.get("state")
                allowed = {"ideas4", "fp1", "asg1", "notes1", "wlog1", "weights1", "theme1"}
                if not isinstance(state, dict) or set(state) - allowed:
                    raise ValueError("Unexpected state keys")
                if any(not isinstance(v, str) for v in state.values()):
                    raise ValueError("State values must be JSON strings")
                # Keep below DynamoDB's 400 KB item limit with room for metadata.
                payload = json.dumps(state, separators=(",", ":"), ensure_ascii=False)
                if len(payload.encode("utf-8")) > 300_000:
                    return reply(413, {"error": "Workspace is too large to synchronize"})
                for value in state.values():
                    json.loads(value)  # reject malformed serialized values
            except (ValueError, TypeError, AttributeError):
                return reply(400, {"error": "Workspace state is invalid"})
            table.put_item(Item={"id": key["id"], "owner": sub, "payload": payload,
                                 "updatedAt": int(time.time()), "recordType": "userstate"})
            return reply(200, {"ok": True})
        return reply(405, {"error": "Method not allowed"})

    everything = scan_all()
    every_idea = [i for i in everything if not i["id"].startswith(RESERVED)]
    items = [i for i in every_idea if not i.get("deleted")]
    projects = [i for i in everything if i["id"].startswith("fp:")]
    assignments = [i for i in everything if i["id"].startswith("asg:")]
    wts = get_weights()
    email = claims.get("email", "").lower()
    mine = lambda i: i["owner"] == claims["sub"] or email in i.get("team", [])

    if event.get("resource") == "/settings":
        cfg = table.get_item(Key={"id": "config:weights"}).get("Item") or {}
        if method == "GET":
            return reply(200, {"weights": wts, "log": list(cfg.get("log", []))[-5:]})
        if method == "PUT" and is_faculty:
            try:
                nw = {k: int(json.loads(event["body"])["weights"][k]) for k in DEFAULT_W}
            except (KeyError, TypeError, ValueError):
                return reply(400, {"error": "Send all six weights as whole numbers"})
            if sum(nw.values()) != 100 or min(nw.values()) < 0:
                return reply(400, {"error": "Weights must be 0 or more and add up to 100"})
            who = claims.get("name") or claims.get("email", "")
            entry = {"at": int(time.time()), "by": who, "text": "Weights set: " + ", ".join(f"{k} {v}" for k, v in nw.items())}
            table.put_item(Item={"id": "config:weights", "recordType": "config", "w": nw, "log": (list(cfg.get("log", [])) + [entry])[-50:]})
            for i in items:
                sc = {k: float(v) for k, v in i["s"].items()}
                table.update_item(
                    Key={"id": i["id"]},
                    UpdateExpression="SET #total=:t",
                    ExpressionAttributeNames={"#total": "total"},
                    ExpressionAttributeValues={":t": total_of(sc, nw)}
                )
            return reply(200, {"ok": True, "rescored": len(items)})
        return reply(403, {"error": "Not allowed"})

    if event.get("resource") in ("/assignments", "/assignments/{id}"):
        if method == "GET":
            return reply(200, [{**a, "state": asg_state(a)} for a in sorted(assignments, key=lambda a: -int(a.get("created", 0)))])
        if method == "POST" and is_faculty:
            try:
                b = json.loads(event["body"])
                title, desc = tidy(b["title"], 120), str(b["desc"]).strip()[:1000]
                classes = [c for c in b["classes"] if c in CLASSES]
                opens, closes, team_max = str(b["opens"])[:10], str(b["closes"])[:10], int(b["teamMax"])
                time.strptime(opens, "%Y-%m-%d")
                time.strptime(closes, "%Y-%m-%d")
                if len(title) < 3 or len(desc) < 20 or not classes or not 1 <= team_max <= 4 or closes < opens or closes < today_local():
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                return reply(400, {"error": "Check the title, description, classes, dates, and team size"})
            item = {"id": "asg:" + str(uuid.uuid4()), "recordType": "assignment", "owner": claims["sub"], "ownerName": claims.get("name", ""),
                    "title": title, "desc": desc, "classes": sorted(set(classes)), "opens": opens, "closes": closes,
                    "teamMax": team_max, "timeline": str(b.get("timeline", ""))[:600], "formats": str(b.get("formats", ""))[:600],
                    "closed": False, "created": int(time.time())}
            table.put_item(Item=item)
            return reply(201, item)
        if method == "PATCH" and is_faculty:
            key = {"id": event["pathParameters"]["id"]}
            a = table.get_item(Key=key).get("Item")
            if not a or not key["id"].startswith("asg:"):
                return reply(404, {"error": "Assignment not found"})
            table.update_item(Key=key, UpdateExpression="SET closed=:c", ExpressionAttributeValues={":c": not a.get("closed", False)})
            return reply(200, {"ok": True})
        return reply(403, {"error": "Not allowed"})

    if event.get("resource") == "/notifications":
        mine_notes = sorted((n for n in everything if n["id"].startswith("note:") and n["to"] == email), key=lambda n: -int(n["at"]))
        if method == "GET":
            return reply(200, [{k: n[k] for k in ("id", "text", "at", "seen")} for n in mine_notes[:30]])
        if method == "PATCH":
            for n in mine_notes:
                if not n["seen"]:
                    table.update_item(Key={"id": n["id"]}, UpdateExpression="SET seen=:t", ExpressionAttributeValues={":t": True})
            return reply(200, {"ok": True})
        return reply(403, {"error": "Not allowed"})

    if event.get("resource") == "/library" and method == "GET":
        show = ("id", "title", "desc", "stack", "sdg", "total", "demo")
        out = [{**{k: i.get(k) for k in show}, "by": i.get("ownerName") or "Student"}
               for i in items
               if i["status"] == "Approved" and i.get("demo") and i.get("pub", True)]
        for p in projects:
            if p.get("demo") and p.get("pub", True):
                team = [r["name"] or "Student" for r in p["requests"] if r["status"] == "Accepted"]
                out.append({"id": p["id"], "title": p["title"], "desc": p["desc"], "stack": p["skills"],
                            "demo": p["demo"], "total": None, "sdg": "", "faculty": True,
                            "by": ", ".join([p.get("ownerName") or "Faculty"] + team)})
        return reply(200, out)

    if event.get("resource") == "/projects":
        if method == "GET":
            return reply(200, [project_view(p, claims["sub"], is_faculty, requests_used(projects, claims["sub"])) for p in projects
                               if is_faculty or is_open(p) or any(r["sub"] == claims["sub"] for r in p["requests"])])
        if method == "POST" and is_faculty:
            try:
                b = json.loads(event["body"])
                title, desc, skills = tidy(b["title"], 120), str(b["desc"]).strip()[:1000], tidy(b["skills"], 200)
                slots, deadline = int(b["slots"]), str(b.get("deadline", ""))[:10]
                if len(title) < 3 or len(desc) < 20 or len(skills) < 2 or not 1 <= slots <= 4:
                    raise ValueError
                if deadline:
                    time.strptime(deadline, "%Y-%m-%d")
            except (KeyError, TypeError, ValueError):
                return reply(400, {"error": "Check the title, description, skills, slots, and date"})
            item = {"id": "fp:" + str(uuid.uuid4()), "recordType": "project", "owner": claims["sub"], "ownerName": claims.get("name", ""),
                    "title": title, "desc": desc, "skills": skills, "slots": slots, "deadline": deadline,
                    "status": "Open", "requests": [], "gh": "", "demo": "", "pub": True, "ver": 0, "created": int(time.time()),
                    "ownerEmail": claims.get("email", "")}
            table.put_item(Item=item)
            return reply(201, item)
        return reply(403, {"error": "Not allowed"})

    if event.get("resource") == "/projects/{id}" and method == "PATCH":
        return handle_project(event, claims, is_faculty, projects)

    if method == "GET":
        return reply(200, items if is_faculty else [i for i in items if mine(i)])

    if method == "DELETE":
        key = {"id": event["pathParameters"]["id"]}
        item = None if key["id"].startswith(RESERVED) else table.get_item(Key=key).get("Item")
        if item and item.get("recordType") == "idea" and not item.get("deleted") and item["owner"] == claims["sub"] and item["status"] != "Approved":
            table.update_item(Key=key, UpdateExpression="SET deleted=:d", ExpressionAttributeValues={":d": True})
            return reply(200, {"ok": True})
        return reply(403, {"error": "Not allowed"})

    body = json.loads(event["body"], parse_float=Decimal)

    if method == "POST":
        asg = next((a for a in assignments if a["id"] == str(body.get("asg", ""))), None)
        cls = str(body.get("cls", ""))
        if not asg or cls not in asg["classes"] or asg_state(asg) != "Open":
            return reply(400, {"error": "Idea submission is not open for this class"})
        day_ago = time.time() - 86400
        if sum(1 for i in every_idea if i["owner"] == claims["sub"] and float(i.get("created", 0)) > day_ago) >= MAX_IDEAS_PER_DAY:
            return reply(429, {"error": f"You can submit {MAX_IDEAS_PER_DAY} ideas per day"})
        if not isinstance(body.get("team", []), list):
            raise ValueError("team must be a list")
        try:
            clean = clean_idea(body)
        except (ValueError, TypeError):
            return reply(400, {"error": "A field in the idea is missing or not valid"})
        if len(body.get("team", [])) > int(asg["teamMax"]) - 1:
            return reply(400, {"error": f'This assignment allows teams of up to {int(asg["teamMax"])} students'})
        team = [str(t).strip().lower() for t in body.get("team", [])]
        dom = os.environ.get("EMAIL_DOMAIN", "").lower()
        team = [t for t in team if re.fullmatch(r"\S+@\S+\.\S+", t) and t != email and (not dom or t.endswith("@" + dom))]
        s, total = score(clean, items, wts)
        item = {**clean, "team": team, "cls": cls, "asg": asg["id"], "id": str(uuid.uuid4()), "recordType": "idea", "owner": claims["sub"], "s": s,
                "total": total, "status": "Pending", "feedback": "", "created": int(time.time()),
                "autoInnovation": s["innovation"], "ownerEmail": claims.get("email", ""),
                "ownerName": claims.get("name", "")}
        try:
            item["ai"] = ai_review(clean, items) or rules_review(clean, items, wts)
        except Exception:
            item["ai"] = rules_review(clean, items, wts)
        table.put_item(Item=json.loads(json.dumps(item, default=str), parse_float=Decimal))
        return reply(201, item)

    if method == "PATCH" and is_faculty:
        key = {"id": event["pathParameters"]["id"]}
        item = table.get_item(Key=key).get("Item")
        if not item or item.get("recordType") != "idea" or key["id"].startswith(RESERVED) or item.get("deleted"):
            return reply(404, {"error": "Idea not found"})
        if body.get("status") not in ("Pending", "Approved", "Rejected"):
            return reply(400, {"error": "Status must be Pending, Approved, or Rejected"})
        body["feedback"] = str(body.get("feedback", ""))[:1000]
        expr = "SET #s=:st, feedback=:f"
        values = {":st": body["status"], ":f": body["feedback"]}
        total = item["total"]
        if "innovation" in body:
            ov = body["innovation"]
            sc = {k: float(v) for k, v in item["s"].items()}
            if ov is None:
                sc["innovation"] = float(item.get("autoInnovation", sc["innovation"]))
            else:
                if not 0 <= float(ov) <= 100:
                    return reply(400, {"error": "Override must be from 0 to 100"})
                sc["innovation"] = float(ov) / 10
            total = total_of(sc, wts)
            values.update({":sc": sc, ":t": total, ":ov": ov})
            expr += ", s=:sc, #total=:t, ovr=:ov"
        entries, who = [], claims.get("name") or claims.get("email", "")
        if body["status"] != item["status"]:
            entries.append(f'Status: {item["status"]} to {body["status"]}')
        if "innovation" in body:
            old, new = item.get("ovr"), body["innovation"]
            if (old is None) != (new is None) or (new is not None and float(new) != float(old)):
                auto = round(float(item.get("autoInnovation", 0)) * 10)
                entries.append("Innovation override removed" if new is None else f"Innovation score set to {new} (automatic score {auto})")
        if entries:
            now = int(time.time())
            values[":lg"] = (list(item.get("log", [])) + [{"at": now, "by": who, "text": t} for t in entries])[-50:]
            expr += ", log=:lg"
        table.update_item(Key=key, UpdateExpression=expr,
                          ExpressionAttributeNames={"#s": "status", "#total": "total"},
                          ExpressionAttributeValues=json.loads(json.dumps(values, default=str), parse_float=Decimal))
        if body["status"] in ("Approved", "Rejected") and body["status"] != item["status"]:
            try:
                note([item.get("ownerEmail", "")] + list(item.get("team", [])),
                     f'Your idea "{item["title"]}" was {body["status"].lower()}.')
            except Exception:
                pass
            try:
                notify({**item, "total": total}, body["status"], body["feedback"])
            except Exception:
                pass
        return reply(200, {"ok": True})

    if method == "PATCH":
        key = {"id": event["pathParameters"]["id"]}
        item = table.get_item(Key=key).get("Item")
        gh, demo = str(body.get("gh", ""))[:200], str(body.get("demo", ""))[:300]
        ok_url = lambda u: not u or u.startswith("https://")
        if key["id"].startswith(RESERVED) or (item and (item.get("recordType") != "idea" or item.get("deleted"))):
            item = None
        if item and mine(item) and item["status"] == "Approved" and ok_url(demo) and (not gh or gh.startswith("https://github.com/")):
            table.update_item(Key=key, UpdateExpression="SET gh=:g, demo=:d, note=:n, pub=:p",
                              ExpressionAttributeValues={":g": gh, ":d": demo, ":n": str(body.get("note", ""))[:500],
                                                         ":p": bool(body.get("pub", True))})
            return reply(200, {"ok": True})

    return reply(403, {"error": "Not allowed"})
