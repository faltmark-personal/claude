from runna_playlist.models import Track

SPEC = "Warm up: 10m@Z2, 5x(Rep: 4m@Z4, Recovery: 90s@Z1), 6m@Z5, Cool down: 8m@Z1"


def workout(client):
    r = client.post("/api/workout/parse", json={"spec": SPEC, "name": "Test"})
    assert r.status_code == 200, r.text
    w = r.json()["workout"]
    return {"name": w["name"], "segments": [dict(s, duration=s["duration_s"]) for s in w["segments"]]}


def rows(plan):
    return [{"key": i["track"]["key"], "block": i["block"], "locked": i["locked"]} for i in plan["items"]]


def test_settings_roundtrip_and_validation(client):
    s = client.get("/api/settings").json()
    assert s["settings"]["cadence_spm"] == 163 and s["settings"]["mode"] == "demo"
    assert client.put("/api/settings", json={"cadence_spm": 170}).json()["settings"]["cadence_spm"] == 170
    assert client.put("/api/settings", json={"zones": {"ranges": {"2": [150, 140]}}}).status_code == 400
    assert client.put("/api/settings", json={"mode": "spotify"}).status_code == 400
    assert client.get("/api/zones/from-cadence?spm=163").json()["ranges"]["4"] == [158, 170]


def test_plan_edit_and_save_in_demo_mode(client, state):
    w = workout(client)
    plan = client.post("/api/plan", json={"workout": w, "seed": 1}).json()
    assert plan["items"] and abs(plan["timing"]["difference_s"]) <= 90
    # demo library is thin at Z5, so recommendations kick in
    assert any(not i["track"]["liked"] for i in plan["items"])
    assert all(i["track"]["liked"] for i in plan["items"] if plan["blocks"][i["block"]]["zone"] == 2)

    r = rows(plan)
    alts = client.post("/api/plan/alternatives", json={"workout": w, "items": r, "index": 0}).json()["alternatives"]
    assert alts and alts[0]["track"]["key"] not in {x["key"] for x in r}
    r[0]["key"] = alts[0]["track"]["key"]
    r = [r[1], r[0]] + r[2:]
    re = client.post("/api/plan/retime", json={"workout": w, "items": r}).json()
    assert re["items"][1]["track"]["key"] == alts[0]["track"]["key"]
    assert re["items"][1]["start_s"] == re["items"][0]["end_s"]

    csv = client.post("/api/plan/export.csv", json={"workout": w, "items": r}).text
    assert csv.startswith("#,start") and "music.youtube.com" in csv

    saved = client.post("/api/playlist/save", json={"workout": w, "items": r, "title": "My run"}).json()
    assert saved["saved"] == len(r) and not saved["not_found"]
    assert state.source().saved["My run"][1] == alts[0]["track"]["video_id"]
    # Recommendations got YouTube ids on save; old keys still work afterwards.
    assert all(i["track"]["video_id"] for i in saved["plan"]["items"])
    assert client.post("/api/plan/retime", json={"workout": w, "items": r}).status_code == 200


def test_locked_songs_survive_regenerate(client):
    w = workout(client)
    plan = client.post("/api/plan", json={"workout": w, "seed": 1}).json()
    keep = plan["items"][2]
    again = client.post("/api/plan", json={"workout": w, "seed": 99,
                                           "locked": [{"key": keep["track"]["key"], "block": keep["block"]}]}).json()
    assert keep["track"]["key"] in [i["track"]["key"] for i in again["items"]]


def test_library_and_bpm_override(client):
    lib = client.get("/api/library").json()
    assert len(lib["tracks"]) == 70 and set(lib["coverage_s"]) == {"1", "2", "3", "4", "5"}
    key = lib["tracks"][0]["key"]
    assert client.put("/api/library/bpm", json={"key": key, "bpm": 82}).json()["track"]["bpm"] == 82
    lib = client.get("/api/library").json()
    t = next(t for t in lib["tracks"] if t["key"] == key)
    assert t["bpm_source"] == "manual" and 4 in t["zones"]
    assert client.put("/api/library/bpm", json={"key": key, "bpm": 400}).status_code == 400


def test_auth_required_modes(client):
    client.put("/api/settings", json={"mode": "youtube_data"})
    assert client.post("/api/library/sync", json={}).status_code == 409
    assert client.post("/api/auth/ytmusic", json={"headers_raw": "nope"}).status_code == 400


def test_bad_workout_rejected(client):
    assert client.post("/api/workout/parse", json={"spec": "10m@Z9"}).status_code == 400
    assert client.post("/api/plan", json={}).status_code == 400
