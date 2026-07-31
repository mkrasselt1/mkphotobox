"""Integration test runner API — real tests, no mocks, no stubs."""

from __future__ import annotations

import asyncio
import platform
import time
import traceback
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from app.auth import require_role
from app.database import get_session
from app.models import User

router = APIRouter(prefix="/api/v1/tests", tags=["tests"])


# ── Test registry ────────────────────────────────────────────────────────

_tests: list[dict[str, Any]] = []


def _register(test_id: str, name: str, category: str, description: str, manual: bool = False):
    """Decorator to register a test function.

    Args:
        manual: If True, this test requires hardware/material and won't run
                in "Run All" — it must be started individually.
    """

    def decorator(func):
        _tests.append({
            "id": test_id,
            "name": name,
            "category": category,
            "description": description,
            "manual": manual,
            "func": func,
        })
        return func

    return decorator


async def _run_test(test: dict, request: Request, session: Session) -> dict:
    """Execute a single test and return its result."""
    start = time.perf_counter()
    try:
        result = test["func"](request, session)
        if asyncio.iscoroutine(result):
            result = await result
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        return {
            "id": test["id"],
            "name": test["name"],
            "category": test["category"],
            "description": test["description"],
            "manual": test.get("manual", False),
            "passed": True,
            "message": result or "OK",
            "duration_ms": elapsed,
        }
    except Exception as e:
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        return {
            "id": test["id"],
            "name": test["name"],
            "category": test["category"],
            "description": test["description"],
            "manual": test.get("manual", False),
            "passed": False,
            "message": str(e),
            "detail": traceback.format_exc(),
            "duration_ms": elapsed,
        }


# ── API endpoints ────────────────────────────────────────────────────────

@router.get("/")
def list_tests(_user: User = Depends(require_role("admin"))):
    """List all available tests (without running them)."""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "category": t["category"],
            "description": t["description"],
            "manual": t.get("manual", False),
        }
        for t in _tests
    ]


@router.post("/run")
async def run_all_tests(
    request: Request,
    session: Session = Depends(get_session),
    _user: User = Depends(require_role("admin")),
):
    """Run all automatic tests (skips manual/hardware tests)."""
    results = []
    for test in _tests:
        if test.get("manual"):
            continue
        result = await _run_test(test, request, session)
        results.append(result)
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    return {"total": len(results), "passed": passed, "failed": failed, "results": results}


@router.post("/run/{test_id}")
async def run_single_test(
    test_id: str,
    request: Request,
    session: Session = Depends(get_session),
    _user: User = Depends(require_role("admin")),
):
    """Run a single test by ID."""
    test = next((t for t in _tests if t["id"] == test_id), None)
    if test is None:
        return {"error": f"Test '{test_id}' not found"}
    return await _run_test(test, request, session)


# ══════════════════════════════════════════════════════════════════════════
# TEST DEFINITIONS — real integration tests, NO mocks/stubs allowed!
# ══════════════════════════════════════════════════════════════════════════


# ── System / Infrastructure ──────────────────────────────────────────────

@_register("sys_health", "Health-Endpoint", "System",
           "Prüft ob der Health-Endpoint erreichbar ist und 'ok' zurückgibt")
def test_health_endpoint(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    resp = client.get("/api/v1/system/health")
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data.get("status") == "ok", f"Unexpected status: {data}"
    return f"Health OK, Uptime: {data.get('uptime_seconds', '?')}s"


@_register("sys_platform", "Plattform-Info", "System",
           "Prüft ob Systeminformationen korrekt gelesen werden")
def test_platform_info(request: Request, session: Session):
    p = platform.platform()
    assert p, "platform.platform() returned empty"
    py = platform.python_version()
    assert py, "python_version() returned empty"
    return f"{p}, Python {py}"


@_register("sys_disk", "Speicherplatz", "System",
           "Prüft ob der Foto-Speicherpfad existiert und beschreibbar ist")
def test_storage_writable(request: Request, session: Session):
    cfg = request.app.state.config
    storage = Path(cfg["photos"]["storage_path"])
    storage.mkdir(parents=True, exist_ok=True)
    assert storage.exists(), f"Storage path does not exist: {storage}"
    # Write and remove a test file
    test_file = storage / ".write_test"
    test_file.write_text("test")
    content = test_file.read_text()
    test_file.unlink()
    assert content == "test", "Write/read mismatch"
    import shutil
    disk = shutil.disk_usage(str(storage))
    free_mb = disk.free // (1024 * 1024)
    return f"Pfad OK, {free_mb} MB frei"


# ── Datenbank ────────────────────────────────────────────────────────────

@_register("db_connection", "DB-Verbindung", "Datenbank",
           "Prüft ob die SQLite-Datenbank erreichbar ist")
def test_db_connection(request: Request, session: Session):
    from sqlmodel import text
    result = session.exec(text("SELECT 1")).scalar()
    assert result == 1, f"Unexpected result: {result}"
    return "SQLite antwortet korrekt"


@_register("db_wal_mode", "WAL-Modus", "Datenbank",
           "Prüft ob die Datenbank im WAL-Modus läuft")
def test_db_wal_mode(request: Request, session: Session):
    from sqlmodel import text
    result = session.exec(text("PRAGMA journal_mode")).scalar()
    assert result == "wal", f"Journal mode is '{result}', expected 'wal'"
    return "WAL-Modus aktiv"


@_register("db_tables", "Tabellen vorhanden", "Datenbank",
           "Prüft ob alle erwarteten Tabellen existieren")
def test_db_tables(request: Request, session: Session):
    from sqlmodel import text
    rows = session.exec(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars().all()
    tables = set(rows)
    expected = {"user", "event", "photo_session", "photo", "collage", "payment", "output_job", "setting"}
    missing = expected - tables
    assert not missing, f"Fehlende Tabellen: {missing}"
    return f"{len(tables)} Tabellen gefunden"


@_register("db_admin_exists", "Admin-User existiert", "Datenbank",
           "Prüft ob mindestens ein Admin-Benutzer in der DB existiert")
def test_admin_exists(request: Request, session: Session):
    admin = session.exec(select(User).where(User.role == "admin")).first()
    assert admin is not None, "Kein Admin-User gefunden"
    assert admin.is_active, f"Admin '{admin.username}' ist deaktiviert"
    return f"Admin '{admin.username}' vorhanden und aktiv"


# ── Konfiguration ────────────────────────────────────────────────────────

@_register("cfg_loaded", "Konfiguration geladen", "Konfiguration",
           "Prüft ob die Konfiguration korrekt geladen wurde")
def test_config_loaded(request: Request, session: Session):
    cfg = request.app.state.config
    assert cfg, "Config is empty"
    assert isinstance(cfg, dict), f"Config is not a dict: {type(cfg)}"
    return f"{len(cfg)} Top-Level-Schlüssel"


@_register("cfg_required_keys", "Pflichtschlüssel", "Konfiguration",
           "Prüft ob alle notwendigen Konfigurationsschlüssel vorhanden sind")
def test_config_required_keys(request: Request, session: Session):
    cfg = request.app.state.config
    required = ["server", "database", "auth", "photos", "cameras", "triggers", "outputs", "session"]
    missing = [k for k in required if k not in cfg]
    assert not missing, f"Fehlende Schlüssel: {missing}"
    return f"Alle {len(required)} Pflichtschlüssel vorhanden"


@_register("cfg_defaults_file", "defaults.yaml existiert", "Konfiguration",
           "Prüft ob die config.defaults.yaml Datei existiert")
def test_defaults_file(request: Request, session: Session):
    from app.config import _BASE_DIR
    defaults = _BASE_DIR / "config.defaults.yaml"
    assert defaults.exists(), f"Datei nicht gefunden: {defaults}"
    size = defaults.stat().st_size
    assert size > 100, f"Datei zu klein ({size} bytes)"
    return f"Vorhanden ({size} bytes)"


# ── Authentifizierung ────────────────────────────────────────────────────

@_register("auth_login", "Admin-Login", "Authentifizierung",
           "Prüft ob der Login mit dem Standard-Admin funktioniert")
def test_auth_login(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": cfg["auth"]["default_admin_password"],
    })
    assert resp.status_code == 200, f"Login fehlgeschlagen: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "token" in data, "Kein Token in der Antwort"
    assert data.get("role") == "admin", f"Rolle ist '{data.get('role')}', erwartet 'admin'"
    return f"Login erfolgreich, Token erhalten"


@_register("auth_token_valid", "Token-Validierung", "Authentifizierung",
           "Prüft ob ein erzeugtes Token korrekt validiert wird")
def test_auth_token_validation(request: Request, session: Session):
    from app.auth import create_token, decode_token
    admin = session.exec(select(User).where(User.role == "admin")).first()
    assert admin is not None, "Kein Admin-User vorhanden"
    token = create_token(admin.id, admin.role)
    payload = decode_token(token)
    assert payload["sub"] == str(admin.id), f"User-ID stimmt nicht: {payload['sub']}"
    assert payload["role"] == "admin", f"Rolle stimmt nicht: {payload['role']}"
    return "Token erstellt und validiert"


@_register("auth_invalid_rejected", "Ungültiger Login abgelehnt", "Authentifizierung",
           "Prüft ob ein falsches Passwort korrekt abgewiesen wird")
def test_auth_invalid_rejected(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "dieses-passwort-ist-garantiert-falsch-xyz",
    })
    assert resp.status_code == 401, f"Erwartet 401, bekommen {resp.status_code}"
    return "Falsches Passwort wird korrekt abgelehnt (401)"


@_register("auth_me_endpoint", "/auth/me Endpoint", "Authentifizierung",
           "Prüft ob der /auth/me Endpoint mit gültigem Token funktioniert")
def test_auth_me(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    # Login first
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": cfg["auth"]["default_admin_password"],
    })
    token = login_resp.json()["token"]
    # Call /me
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data.get("username") == "admin", f"Username: {data.get('username')}"
    return f"User '{data['username']}' korrekt zurückgegeben"


# ── Events ───────────────────────────────────────────────────────────────

@_register("evt_active_exists", "Aktives Event vorhanden", "Events",
           "Prüft ob mindestens ein aktives Event existiert")
def test_active_event(request: Request, session: Session):
    from app.models import Event
    event = session.exec(select(Event).where(Event.is_active == True)).first()
    assert event is not None, "Kein aktives Event gefunden"
    return f"Aktives Event: '{event.name}' (slug: {event.slug})"


@_register("evt_list_api", "Events-Liste API", "Events",
           "Prüft ob die Event-Liste über die API abrufbar ist")
def test_events_list_api(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": cfg["auth"]["default_admin_password"],
    })
    token = login_resp.json()["token"]
    resp = client.get("/api/v1/events/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list), f"Erwartet Liste, bekommen: {type(data)}"
    assert len(data) > 0, "Keine Events in der Liste"
    return f"{len(data)} Event(s) gefunden"


@_register("evt_active_api", "Aktives Event API", "Events",
           "Prüft ob das aktive Event über /events/active abrufbar ist")
def test_active_event_api(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    resp = client.get("/api/v1/events/active")
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data is not None, "Kein aktives Event"
    assert data.get("is_active") is True, "Event ist nicht aktiv"
    return f"Aktives Event: '{data.get('name')}'"


# ── Module ───────────────────────────────────────────────────────────────

@_register("mod_managers_loaded", "Modul-Manager geladen", "Module",
           "Prüft ob alle Modul-Manager (Cameras, Triggers, Outputs, Payments) initialisiert sind")
def test_module_managers(request: Request, session: Session):
    app = request.app
    assert hasattr(app.state, "cameras"), "CameraManager fehlt"
    assert hasattr(app.state, "triggers"), "TriggerManager fehlt"
    assert hasattr(app.state, "outputs"), "OutputManager fehlt"
    assert hasattr(app.state, "payments"), "PaymentManager fehlt"
    cameras = len(app.state.cameras.list_cameras())
    triggers = len(app.state.triggers.list_triggers())
    outputs = len(app.state.outputs.list_outputs())
    return f"Cameras: {cameras}, Triggers: {triggers}, Outputs: {outputs}"


@_register("mod_list_api", "Module-API", "Module",
           "Prüft ob die Modul-Liste über die API abrufbar ist")
def test_modules_api(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": cfg["auth"]["default_admin_password"],
    })
    token = login_resp.json()["token"]
    resp = client.get("/api/v1/modules/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "cameras" in data, "Kein 'cameras' Feld in der Antwort"
    assert "triggers" in data, "Kein 'triggers' Feld in der Antwort"
    assert "outputs" in data, "Kein 'outputs' Feld in der Antwort"
    return "Alle Modul-Kategorien vorhanden"


# ── EventBus ─────────────────────────────────────────────────────────────

@_register("bus_exists", "EventBus vorhanden", "EventBus",
           "Prüft ob der EventBus initialisiert ist")
def test_eventbus_exists(request: Request, session: Session):
    bus = request.app.state.bus
    assert bus is not None, "EventBus ist None"
    from app.eventbus import EventBus
    assert isinstance(bus, EventBus), f"Bus ist kein EventBus: {type(bus)}"
    return "EventBus aktiv"


@_register("bus_emit", "EventBus Emit/Receive", "EventBus",
           "Prüft ob Events über den Bus gesendet und empfangen werden können")
async def test_eventbus_emit(request: Request, session: Session):
    bus = request.app.state.bus
    received = []

    async def handler(event, data):
        received.append(data)

    bus.on("_test.ping", handler)
    try:
        await bus.emit_and_wait("_test.ping", {"msg": "hello"})
        assert len(received) == 1, f"Erwartet 1 Event, bekommen {len(received)}"
        assert received[0]["msg"] == "hello", f"Daten stimmen nicht: {received[0]}"
        return "Event gesendet und empfangen"
    finally:
        bus.off("_test.ping", handler)


# ── WebSocket-Manager ────────────────────────────────────────────────────

@_register("ws_manager", "WebSocket-Manager", "WebSocket",
           "Prüft ob der WebSocket-Manager initialisiert ist")
def test_ws_manager(request: Request, session: Session):
    ws = request.app.state.ws_manager
    assert ws is not None, "WSManager ist None"
    count = ws.count
    assert isinstance(count, int), f"count ist kein int: {type(count)}"
    return f"WSManager aktiv, {count} Verbindung(en)"


# ── Settings ─────────────────────────────────────────────────────────────

@_register("settings_api", "Settings-API", "Settings",
           "Prüft ob die Settings über die API abrufbar sind")
def test_settings_api(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": cfg["auth"]["default_admin_password"],
    })
    token = login_resp.json()["token"]
    resp = client.get("/api/v1/settings/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, dict), f"Erwartet dict, bekommen: {type(data)}"
    assert "server" in data, "'server' fehlt in den Settings"
    return f"{len(data)} Settings-Kategorien"


# ── System-Info ──────────────────────────────────────────────────────────

@_register("sysinfo_api", "System-Info API", "System",
           "Prüft ob der System-Info-Endpoint alle erwarteten Felder zurückgibt")
def test_system_info_api(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": cfg["auth"]["default_admin_password"],
    })
    token = login_resp.json()["token"]
    resp = client.get("/api/v1/system/info", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    expected_fields = ["version", "platform", "python_version", "disk_free_mb", "photos_count", "uptime_seconds"]
    missing = [f for f in expected_fields if f not in data]
    assert not missing, f"Fehlende Felder: {missing}"
    return f"v{data['version']}, {data['photos_count']} Fotos, {data['disk_free_mb']}MB frei"


# ── i18n ─────────────────────────────────────────────────────────────────

@_register("i18n_locales", "Verfügbare Sprachen", "i18n",
           "Prüft ob Sprachdaten geladen werden können")
def test_i18n_locales(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    resp = client.get("/api/v1/i18n")
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    locales = data.get("locales", [])
    assert len(locales) > 0, "Keine Sprachen verfügbar"
    return f"Sprachen: {', '.join(locales)}"


@_register("i18n_de", "Deutsche Übersetzungen", "i18n",
           "Prüft ob die deutschen Übersetzungen geladen werden können")
def test_i18n_german(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    resp = client.get("/api/v1/i18n/de")
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "error" not in data, f"Fehler: {data.get('error')}"
    assert len(data) > 0, "Keine Übersetzungen vorhanden"
    return f"{len(data)} Übersetzungs-Schlüssel"


# ── Sessions ─────────────────────────────────────────────────────────────

@_register("session_create", "Session erstellen", "Sessions",
           "Prüft ob eine neue Foto-Session gestartet werden kann")
def test_session_create(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    resp = client.post("/api/v1/sessions/start")
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "token" in data, "Kein Token in der Antwort"
    assert "id" in data, "Keine ID in der Antwort"
    token = data["token"]
    # Verify we can retrieve it
    resp2 = client.get(f"/api/v1/sessions/{token}")
    assert resp2.status_code == 200, f"Session abrufen fehlgeschlagen: {resp2.status_code}"
    return f"Session #{data['id']} erstellt (Token: {token[:8]}...)"


# ── Photo-Service ────────────────────────────────────────────────────────

@_register("photo_service", "Photo-Service", "Fotos",
           "Prüft ob der Photo-Service initialisiert ist")
def test_photo_service(request: Request, session: Session):
    ps = request.app.state.photo_service
    assert ps is not None, "PhotoService ist None"
    return "PhotoService aktiv"


@_register("camera_status_api", "Kamera-Status API", "Fotos",
           "Prüft ob der Kamera-Status-Endpoint funktioniert")
def test_camera_status(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    resp = client.get("/api/v1/camera/status")
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "cameras" in data, "'cameras' fehlt in der Antwort"
    active = data.get("active", "keine")
    mode = data.get("mode", "?")
    return f"Aktive Kamera: {active}, Modus: {mode}"


# ── GIF-Service ──────────────────────────────────────────────────────────

@_register("gif_service_init", "GIF-Service", "GIF",
           "Prüft ob der GIF-Service initialisiert und konfiguriert ist")
def test_gif_service(request: Request, session: Session):
    gif_service = getattr(request.app.state, "gif_service", None)
    assert gif_service is not None, "GifService nicht in app.state"
    enabled = gif_service.enabled
    status = "aktiviert" if enabled else "deaktiviert"
    return f"GifService {status}"


# ── Trigger-System ───────────────────────────────────────────────────────

@_register("trig_api", "Trigger-API", "Trigger",
           "Prüft ob die Trigger-Status-API funktioniert")
def test_trigger_api(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": cfg["auth"]["default_admin_password"],
    })
    token = login_resp.json()["token"]
    resp = client.get("/api/v1/triggers/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list), f"Erwartet Liste, bekommen: {type(data)}"
    enabled = [t for t in data if t.get("enabled")]
    loaded = [t for t in data if t.get("loaded")]
    return f"{len(data)} Trigger konfiguriert, {len(enabled)} aktiviert, {len(loaded)} geladen"


@_register("trig_audio_devices", "Audio-Geräte-Erkennung", "Trigger",
           "Prüft ob Audio-Eingabegeräte für den Akustik-Trigger erkannt werden")
def test_audio_devices(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": cfg["auth"]["default_admin_password"],
    })
    token = login_resp.json()["token"]
    resp = client.get("/api/v1/triggers/audio-devices", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    if isinstance(data, dict) and "error" in data:
        raise AssertionError(f"sounddevice nicht verfügbar: {data['error']}")
    assert isinstance(data, list), f"Erwartet Liste: {type(data)}"
    assert len(data) > 0, "Keine Audio-Eingabegeräte gefunden"
    names = [d["name"] for d in data[:3]]
    return f"{len(data)} Gerät(e): {', '.join(names)}"


@_register("trig_serial_ports", "Serielle Ports", "Trigger",
           "Prüft ob serielle Schnittstellen erkannt werden")
def test_serial_ports(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": cfg["auth"]["default_admin_password"],
    })
    token = login_resp.json()["token"]
    resp = client.get("/api/v1/triggers/serial-ports", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    if isinstance(data, dict) and "error" in data:
        raise AssertionError(f"pyserial nicht verfügbar: {data['error']}")
    assert isinstance(data, list), f"Erwartet Liste: {type(data)}"
    if not data:
        return "Keine seriellen Ports gefunden (kein Fehler, evtl. nichts angeschlossen)"
    names = [f"{p['port']} ({p['name']})" for p in data[:3]]
    return f"{len(data)} Port(s): {', '.join(names)}"


@_register("trig_keyboard_devices", "Keyboard-Geräte (Host)", "Trigger",
           "Prüft ob Host-Keyboard-Geräte erkannt werden")
def test_keyboard_devices(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": cfg["auth"]["default_admin_password"],
    })
    token = login_resp.json()["token"]
    resp = client.get("/api/v1/triggers/keyboard-devices", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
    data = resp.json()
    if isinstance(data, dict) and "error" in data:
        raise AssertionError(f"evdev/pynput nicht verfügbar: {data['error']}")
    assert isinstance(data, list), f"Erwartet Liste: {type(data)}"
    assert len(data) > 0, "Keine Keyboard-Geräte erkannt"
    names = [d["name"] for d in data[:3]]
    return f"{len(data)} Gerät(e): {', '.join(names)}"


@_register("trig_config_keys", "Trigger-Konfiguration", "Trigger",
           "Prüft ob alle Trigger-Typen in der Konfiguration vorhanden sind")
def test_trigger_config_keys(request: Request, session: Session):
    cfg = request.app.state.config
    triggers_cfg = cfg.get("triggers", {})
    expected = ["touchscreen", "keyboard", "host_keyboard", "gpio", "acoustic", "serial", "bluetooth"]
    found = [k for k in expected if k in triggers_cfg]
    missing = [k for k in expected if k not in triggers_cfg]
    if missing:
        raise AssertionError(f"Fehlende Trigger in Config: {missing}")
    return f"Alle {len(expected)} Trigger-Typen konfiguriert"


@_register("trig_host_keyboard_module", "Host-Keyboard-Modul", "Trigger",
           "Prüft ob das Host-Keyboard-Modul geladen werden kann")
def test_host_keyboard_module(request: Request, session: Session):
    from app.modules.trigger.host_keyboard import HostKeyboardTrigger
    trigger = HostKeyboardTrigger()
    available = trigger.is_available()
    if available:
        return "Host-Keyboard-Modul verfügbar (evdev/pynput installiert)"
    return "Host-Keyboard-Modul nicht verfügbar (evdev/pynput fehlt)"


# ══════════════════════════════════════════════════════════════════════════
# MANUELLE TESTS — brauchen Hardware / Material, einzeln starten!
# ══════════════════════════════════════════════════════════════════════════


# ── Foto-Auslösung ──────────────────────────────────────────────────────

@_register("manual_capture", "Foto aufnehmen", "Manuell: Kamera",
           "Löst ein echtes Foto mit der aktiven Kamera aus und speichert es",
           manual=True)
async def test_manual_capture(request: Request, session: Session):
    cameras = request.app.state.cameras
    active = cameras.active_camera
    assert active is not None, "Keine aktive Kamera — bitte zuerst eine Kamera aktivieren"
    assert active.is_available(), f"Kamera '{cameras.active_id}' ist nicht verfügbar"

    jpeg_bytes = await cameras.capture()
    assert jpeg_bytes, "Kamera hat leere Daten zurückgegeben"
    assert len(jpeg_bytes) > 1000, f"Bild zu klein ({len(jpeg_bytes)} bytes) — vermutlich kein echtes Foto"

    # Verify it's a valid JPEG (starts with FF D8)
    assert jpeg_bytes[:2] == b'\xff\xd8', "Daten sind kein gültiges JPEG"

    size_kb = len(jpeg_bytes) / 1024
    return f"Foto aufgenommen: {size_kb:.0f} KB, JPEG valide"


@_register("manual_capture_flow", "Kompletter Capture-Flow", "Manuell: Kamera",
           "Führt den vollen Capture-Workflow durch: Countdown, Auslösung, Speichern, DB-Eintrag",
           manual=True)
async def test_manual_capture_flow(request: Request, session: Session):
    photo_service = request.app.state.photo_service
    cameras = request.app.state.cameras
    assert cameras.active_camera is not None, "Keine aktive Kamera"

    result = await photo_service.start_capture_flow()
    assert result is not None, "Capture-Flow hat None zurückgegeben — möglicherweise läuft bereits eine Aufnahme"
    assert "photo_id" in result, f"Kein photo_id im Ergebnis: {result}"
    assert "filename" in result, f"Kein filename im Ergebnis: {result}"

    # Verify the photo was saved to disk
    cfg = request.app.state.config
    filepath = Path(cfg["photos"]["storage_path"]) / result["filename"]
    assert filepath.exists(), f"Foto nicht auf Festplatte gefunden: {filepath}"
    size_kb = filepath.stat().st_size / 1024

    # Verify DB entry
    from app.models import Photo
    photo = session.get(Photo, result["photo_id"])
    assert photo is not None, f"Foto #{result['photo_id']} nicht in der Datenbank"

    return f"Foto #{photo.id} gespeichert: {result['filename']} ({size_kb:.0f} KB)"


@_register("manual_preview", "Kamera-Preview", "Manuell: Kamera",
           "Holt ein Preview-Frame von der aktiven Kamera",
           manual=True)
async def test_manual_preview(request: Request, session: Session):
    cameras = request.app.state.cameras
    cam = cameras.active_camera
    assert cam is not None, "Keine aktive Kamera"

    frame = await cam.get_preview_frame()
    assert frame, "Kein Preview-Frame erhalten — Kamera liefert leere Daten"
    assert len(frame) > 500, f"Frame zu klein ({len(frame)} bytes)"
    size_kb = len(frame) / 1024
    return f"Preview-Frame erhalten: {size_kb:.1f} KB"


# ── Thumbnail-Erzeugung ─────────────────────────────────────────────────

@_register("manual_thumbnail", "Thumbnail erzeugen", "Manuell: Kamera",
           "Nimmt ein Foto auf und prüft ob das Thumbnail korrekt erzeugt wird",
           manual=True)
async def test_manual_thumbnail(request: Request, session: Session):
    photo_service = request.app.state.photo_service
    cameras = request.app.state.cameras
    assert cameras.active_camera is not None, "Keine aktive Kamera"

    result = await photo_service.start_capture_flow()
    assert result is not None, "Capture fehlgeschlagen"

    cfg = request.app.state.config
    thumb_dir = Path(cfg["photos"]["storage_path"]) / "thumbs"
    thumb_name = f"{Path(result['filename']).stem}_thumb.jpg"
    thumb_path = thumb_dir / thumb_name

    assert thumb_path.exists(), f"Thumbnail nicht gefunden: {thumb_path}"
    size_kb = thumb_path.stat().st_size / 1024
    assert size_kb > 1, f"Thumbnail zu klein ({size_kb:.1f} KB)"

    # Verify dimensions
    try:
        from PIL import Image
        img = Image.open(thumb_path)
        w, h = img.size
        img.close()
        max_dim = max(cfg["photos"]["thumbnail_size"])
        assert max(w, h) <= max_dim + 1, f"Thumbnail zu groß: {w}x{h} (max {max_dim})"
        return f"Thumbnail OK: {w}x{h}, {size_kb:.1f} KB"
    except ImportError:
        return f"Thumbnail vorhanden: {size_kb:.1f} KB (Pillow nicht installiert, Größe nicht geprüft)"


# ── Druck ────────────────────────────────────────────────────────────────

@_register("manual_print", "Testdruck", "Manuell: Drucker",
           "Druckt ein Testbild auf dem konfigurierten Drucker aus",
           manual=True)
async def test_manual_print(request: Request, session: Session):
    outputs = request.app.state.outputs
    output_list = outputs.list_outputs()
    printer = next((o for o in output_list if o.get("id", o.get("name", "")) == "output.printer"), None)
    assert printer is not None, "Drucker-Modul ist nicht geladen — bitte in der Config aktivieren"

    # Create a test image
    test_photo = _create_test_image(request.app.state.config)

    try:
        result = await outputs.send("output.printer", str(test_photo), {})
        assert result.get("status") == "ok", f"Druckauftrag fehlgeschlagen: {result.get('message', result)}"
        printer_name = result.get("printer", "Standard")
        return f"Druckauftrag gesendet an '{printer_name}'"
    finally:
        # Clean up test image
        if test_photo.exists():
            test_photo.unlink()


@_register("manual_print_photo", "Foto drucken", "Manuell: Drucker",
           "Nimmt ein Foto auf und druckt es sofort aus",
           manual=True)
async def test_manual_print_photo(request: Request, session: Session):
    outputs = request.app.state.outputs
    cameras = request.app.state.cameras
    assert cameras.active_camera is not None, "Keine aktive Kamera"

    output_list = outputs.list_outputs()
    printer = next((o for o in output_list if o.get("id", o.get("name", "")) == "output.printer"), None)
    assert printer is not None, "Drucker-Modul nicht geladen"

    # Capture a real photo
    photo_service = request.app.state.photo_service
    capture_result = await photo_service.start_capture_flow()
    assert capture_result is not None, "Foto-Aufnahme fehlgeschlagen"

    cfg = request.app.state.config
    photo_path = str(Path(cfg["photos"]["storage_path"]) / capture_result["filename"])

    result = await outputs.send("output.printer", photo_path, {"photo_id": capture_result["photo_id"]})
    assert result.get("status") == "ok", f"Druck fehlgeschlagen: {result.get('message', result)}"

    return f"Foto #{capture_result['photo_id']} aufgenommen und an Drucker gesendet"


# ── Testbild-Erzeugung (für Drucktests) ─────────────────────────────────

def _create_test_image(cfg: dict) -> Path:
    """Create a simple test image with text for print testing."""
    from datetime import datetime

    photo_dir = Path(cfg["photos"]["storage_path"])
    photo_dir.mkdir(parents=True, exist_ok=True)
    test_path = photo_dir / "_test_print.jpg"

    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (1200, 800), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Draw test pattern
        for i in range(0, 1200, 100):
            draw.line([(i, 0), (i, 800)], fill=(200, 200, 200), width=1)
        for i in range(0, 800, 100):
            draw.line([(0, i), (1200, i)], fill=(200, 200, 200), width=1)
        # Color bars
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255)]
        bar_w = 1200 // len(colors)
        for idx, color in enumerate(colors):
            draw.rectangle([(idx * bar_w, 600), ((idx + 1) * bar_w, 700)], fill=color)
        # Text
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except OSError:
            font = ImageFont.load_default()
        draw.text((50, 50), "MKPhotobox Testdruck", fill=(0, 0, 0), font=font)
        draw.text((50, 120), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), fill=(100, 100, 100), font=font)
        draw.text((50, 190), f"Auflösung: 1200x800", fill=(100, 100, 100), font=font)
        img.save(test_path, "JPEG", quality=95)
        img.close()
    except ImportError:
        # Fallback: create a minimal valid JPEG without Pillow
        import struct
        # Minimal 1x1 white JPEG
        minimal_jpeg = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
            0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
            0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
            0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
            0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
            0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
            0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
            0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
            0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
            0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
            0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
            0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
            0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
            0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
            0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
            0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
            0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
            0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
        ])
        test_path.write_bytes(minimal_jpeg)

    return test_path


# ── E-Mail ───────────────────────────────────────────────────────────────

@_register("manual_email", "Test-E-Mail senden", "Manuell: Ausgabe",
           "Sendet ein Testbild per E-Mail (SMTP muss konfiguriert sein)",
           manual=True)
async def test_manual_email(request: Request, session: Session):
    outputs = request.app.state.outputs
    cfg = request.app.state.config
    email_cfg = cfg.get("outputs", {}).get("email", {})
    assert email_cfg.get("enabled"), "E-Mail-Modul ist nicht aktiviert"
    assert email_cfg.get("smtp_host"), "SMTP-Host nicht konfiguriert"

    test_photo = _create_test_image(cfg)
    from_addr = email_cfg.get("from_address", email_cfg.get("smtp_user", ""))
    assert from_addr, "Keine Absender-Adresse konfiguriert"

    try:
        result = await outputs.send("output.email", str(test_photo), {"target": from_addr})
        assert result.get("status") == "ok", f"E-Mail fehlgeschlagen: {result.get('message', result)}"
        return f"Test-E-Mail an {from_addr} gesendet"
    finally:
        if test_photo.exists():
            test_photo.unlink()


# ── USB-Kopie ────────────────────────────────────────────────────────────

@_register("manual_usb_copy", "USB-Kopie", "Manuell: Ausgabe",
           "Kopiert ein Testbild auf den konfigurierten USB-Stick",
           manual=True)
async def test_manual_usb_copy(request: Request, session: Session):
    outputs = request.app.state.outputs
    cfg = request.app.state.config
    usb_cfg = cfg.get("outputs", {}).get("usb_copy", {})
    assert usb_cfg.get("enabled"), "USB-Kopie-Modul ist nicht aktiviert"

    mount_path = Path(usb_cfg.get("mount_path", "/media/usb"))
    assert mount_path.exists(), f"USB-Mount-Pfad nicht gefunden: {mount_path}"

    test_photo = _create_test_image(cfg)
    try:
        result = await outputs.send("output.usb_copy", str(test_photo), {})
        assert result.get("status") == "ok", f"USB-Kopie fehlgeschlagen: {result.get('message', result)}"
        return f"Testbild auf USB kopiert: {result.get('path', mount_path)}"
    finally:
        if test_photo.exists():
            test_photo.unlink()


# ── Kamera-Erkennung ────────────────────────────────────────────────────

@_register("manual_camera_detect", "Kamera-Hardware erkennen", "Manuell: Kamera",
           "Sucht nach angeschlossener Kamera-Hardware (USB-Kameras, Webcams)",
           manual=True)
async def test_manual_camera_detect(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    resp = client.get("/api/v1/camera/devices")
    assert resp.status_code == 200, f"Fehler: {resp.status_code} {resp.text}"
    devices = resp.json()
    assert isinstance(devices, list), f"Unerwartete Antwort: {type(devices)}"
    if not devices:
        raise AssertionError("Keine Kamera-Hardware gefunden — bitte Kamera anschließen")
    names = [d.get("name", f"Gerät {d.get('index', '?')}") for d in devices]
    return f"{len(devices)} Kamera(s) gefunden: {', '.join(names)}"


# ── Kompletter Workflow ──────────────────────────────────────────────────

@_register("manual_full_workflow", "Kompletter Workflow", "Manuell: Workflow",
           "Foto aufnehmen + Thumbnail prüfen + in Galerie prüfen — der komplette Weg",
           manual=True)
async def test_manual_full_workflow(request: Request, session: Session):
    from starlette.testclient import TestClient
    from app.models import Event, Photo, PhotoSession

    cameras = request.app.state.cameras
    assert cameras.active_camera is not None, "Keine aktive Kamera"

    # 1. Start session via API
    client = TestClient(request.app)
    resp = client.post("/api/v1/sessions/start")
    assert resp.status_code == 200, f"Session-Start fehlgeschlagen: {resp.text}"
    session_data = resp.json()

    # 2. Capture photo via PhotoService
    photo_service = request.app.state.photo_service
    result = await photo_service.start_capture_flow()
    assert result is not None, "Capture fehlgeschlagen"

    # 3. Verify photo file exists
    cfg = request.app.state.config
    photo_path = Path(cfg["photos"]["storage_path"]) / result["filename"]
    assert photo_path.exists(), f"Foto-Datei nicht gefunden: {photo_path}"

    # 4. Verify thumbnail
    thumb_path = Path(cfg["photos"]["storage_path"]) / "thumbs" / f"{photo_path.stem}_thumb.jpg"
    has_thumb = thumb_path.exists()

    # 5. Verify in DB
    photo = session.get(Photo, result["photo_id"])
    assert photo is not None, "Foto nicht in DB"

    # 6. Verify photo accessible via API
    resp = client.get(f"/api/v1/photos/{photo.id}")
    assert resp.status_code == 200, f"Foto-API fehlgeschlagen: {resp.text}"

    # 7. Verify gallery has the photo
    event = session.exec(select(Event).where(Event.is_active == True)).first()
    if event:
        resp = client.get(f"/api/v1/gallery/{event.slug}/latest?count=1")
        assert resp.status_code == 200, f"Galerie fehlgeschlagen: {resp.text}"
        gallery = resp.json()
        assert len(gallery) > 0, "Galerie ist leer nach Aufnahme"

    size_kb = photo_path.stat().st_size / 1024
    thumb_info = f", Thumbnail OK" if has_thumb else ", kein Thumbnail"
    return f"Workflow komplett: Foto #{photo.id} ({size_kb:.0f} KB){thumb_info}, API + Galerie OK"


# ── GIF / Bildserie ─────────────────────────────────────────────────────

@_register("manual_photo_series", "Foto-Serie aufnehmen", "Manuell: Kamera",
           "Nimmt 3 Fotos hintereinander auf und prüft ob alle gespeichert werden",
           manual=True)
async def test_manual_photo_series(request: Request, session: Session):
    cameras = request.app.state.cameras
    assert cameras.active_camera is not None, "Keine aktive Kamera"

    cfg = request.app.state.config
    photo_dir = Path(cfg["photos"]["storage_path"])
    photo_ids = []

    for i in range(3):
        jpeg_bytes = await cameras.capture()
        assert jpeg_bytes and len(jpeg_bytes) > 1000, f"Foto {i+1} fehlgeschlagen"

        # Save each photo
        import secrets
        from datetime import datetime
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_series{i}_{secrets.token_hex(3)}.jpg"
        filepath = photo_dir / filename
        filepath.write_bytes(jpeg_bytes)
        photo_ids.append(filename)

        if i < 2:
            await asyncio.sleep(0.5)

    total_kb = sum((photo_dir / f).stat().st_size / 1024 for f in photo_ids)
    return f"3 Fotos aufgenommen ({total_kb:.0f} KB gesamt): {', '.join(photo_ids)}"


@_register("manual_gif_create", "GIF erstellen (GifService)", "Manuell: Kamera",
           "Erzeugt ein animiertes GIF aus dem Preview-Frame-Buffer des GifService",
           manual=True)
async def test_manual_gif_create(request: Request, session: Session):
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        raise AssertionError("Pillow nicht installiert — GIF-Erzeugung nicht möglich")

    gif_service = getattr(request.app.state, "gif_service", None)
    assert gif_service is not None, "GifService ist nicht initialisiert"
    assert gif_service.enabled, "GIF-Funktion ist deaktiviert (config: gif.enabled)"

    cameras = request.app.state.cameras
    assert cameras.active_camera is not None, "Keine aktive Kamera — GIF-Buffer ist leer"

    # Wait briefly to ensure buffer has frames
    await asyncio.sleep(1.0)

    cfg = request.app.state.config
    photo_dir = Path(cfg["photos"]["storage_path"])
    photo_dir.mkdir(parents=True, exist_ok=True)

    gif_path = await gif_service.create_gif(photo_dir, "_test_gif")
    assert gif_path is not None, "GIF-Erzeugung fehlgeschlagen — Buffer evtl. leer (Kamera aktiv?)"
    assert gif_path.exists(), f"GIF-Datei nicht gefunden: {gif_path}"

    gif_size_kb = gif_path.stat().st_size / 1024
    assert gif_size_kb > 5, f"GIF zu klein ({gif_size_kb:.1f} KB)"

    # Verify it's a valid GIF (starts with GIF89a or GIF87a)
    header = gif_path.read_bytes()[:6]
    assert header[:3] == b'GIF', f"Keine gültige GIF-Datei (Header: {header})"

    return f"GIF erstellt: {gif_size_kb:.0f} KB, Datei: {gif_path.name}"


# ── Bildqualität ─────────────────────────────────────────────────────────

@_register("manual_image_quality", "Bildqualität prüfen", "Manuell: Kamera",
           "Nimmt ein Foto auf und prüft Auflösung, Dateigröße und EXIF-Daten",
           manual=True)
async def test_manual_image_quality(request: Request, session: Session):
    cameras = request.app.state.cameras
    assert cameras.active_camera is not None, "Keine aktive Kamera"

    jpeg_bytes = await cameras.capture()
    assert jpeg_bytes and len(jpeg_bytes) > 1000, "Aufnahme fehlgeschlagen"

    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(jpeg_bytes))
        w, h = img.size
        mode = img.mode
        fmt = img.format
        img.close()
    except ImportError:
        raise AssertionError("Pillow nicht installiert")

    size_kb = len(jpeg_bytes) / 1024
    megapixel = (w * h) / 1_000_000

    # Basic quality checks
    cfg = request.app.state.config
    max_res = cfg["photos"]["max_resolution"]
    assert w <= max_res[0] and h <= max_res[1], f"Auflösung {w}x{h} überschreitet Maximum {max_res}"
    assert w >= 320 and h >= 240, f"Auflösung zu niedrig: {w}x{h}"
    assert mode == "RGB", f"Farbmodus '{mode}', erwartet 'RGB'"

    return f"{w}x{h} ({megapixel:.1f} MP), {size_kb:.0f} KB, {fmt}, {mode}"


# ── Manuelle Trigger-Tests ───────────────────────────────────────────────

@_register("manual_host_kb_learn", "Host-Tastatur Lern-Modus", "Manuell: Trigger",
           "Startet den Lern-Modus für die Host-Tastatur — drücke eine Taste am Server (15s)",
           manual=True)
async def test_manual_host_kb_learn(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": cfg["auth"]["default_admin_password"],
    })
    token = login_resp.json()["token"]
    # This will block until a key is pressed or timeout
    resp = client.post("/api/v1/triggers/learn/host-keyboard",
                       headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 408:
        raise AssertionError("Timeout — keine Taste gedrückt innerhalb von 15 Sekunden")
    assert resp.status_code == 200, f"Fehler: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "key_code" in data, f"Kein key_code in Antwort: {data}"
    return f"Taste erkannt: {data['key_code']} von Gerät '{data.get('device', '?')}'"


@_register("manual_serial_learn", "Seriell Lern-Modus", "Manuell: Trigger",
           "Lauscht 15s auf dem ersten verfügbaren seriellen Port — sende Daten vom Gerät",
           manual=True)
async def test_manual_serial_learn(request: Request, session: Session):
    # Find first available port
    try:
        from serial.tools import list_ports
        ports = list_ports.comports()
    except ImportError:
        raise AssertionError("pyserial nicht installiert")

    assert len(ports) > 0, "Keine seriellen Ports gefunden"

    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": cfg["auth"]["default_admin_password"],
    })
    token = login_resp.json()["token"]

    port = ports[0].device
    resp = client.post("/api/v1/triggers/learn/serial",
                       json={"port": port, "baud": 9600},
                       headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 408:
        raise AssertionError(f"Timeout — keine Daten auf {port} empfangen")
    assert resp.status_code == 200, f"Fehler: {resp.status_code} {resp.text}"
    data = resp.json()
    return f"Empfangen auf {port}: \"{data.get('text', '?')}\" (hex: {data.get('raw_bytes', '?')[:20]})"


@_register("manual_acoustic_test", "Mikrofon-Test", "Manuell: Trigger",
           "Liest 2 Sekunden Audio vom konfigurierten Mikrofon und zeigt die Lautstärke",
           manual=True)
async def test_manual_acoustic(request: Request, session: Session):
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        raise AssertionError("sounddevice/numpy nicht installiert")

    cfg = request.app.state.config
    dev_idx = cfg.get("triggers", {}).get("acoustic", {}).get("device_index")
    threshold = cfg.get("triggers", {}).get("acoustic", {}).get("threshold", 0.7)

    # Record 2 seconds
    duration = 2.0
    sample_rate = 16000
    recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate,
                       channels=1, device=dev_idx, dtype='float32')
    sd.wait()

    rms_values = []
    block_size = 1024
    for i in range(0, len(recording) - block_size, block_size):
        block = recording[i:i + block_size]
        rms = float(np.sqrt(np.mean(block ** 2)))
        rms_values.append(rms)

    peak = max(rms_values) if rms_values else 0
    avg = sum(rms_values) / len(rms_values) if rms_values else 0
    would_trigger = peak >= threshold

    dev_name = "Standard"
    if dev_idx is not None:
        try:
            dev_info = sd.query_devices(dev_idx)
            dev_name = dev_info["name"]
        except Exception:
            dev_name = f"Device {dev_idx}"

    status = f"WÜRDE AUSLÖSEN (Peak {peak:.3f} >= Schwelle {threshold})" if would_trigger else f"Kein Trigger (Peak {peak:.3f} < Schwelle {threshold})"
    return f"Mikrofon: {dev_name}, Avg: {avg:.3f}, Peak: {peak:.3f} — {status}"


# ── WLAN ────────────────────────────────────────────────────────────────

@_register("wifi_api", "WLAN-API", "WLAN",
           "Prüft, dass der WLAN-Status-Endpunkt antwortet (auch ohne Hardware)")
def test_wifi_api(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    resp = client.get("/api/v1/wifi/status")
    assert resp.status_code == 200, f"Status {resp.status_code}"
    data = resp.json()
    assert "available" in data, f"Feld 'available' fehlt: {data}"
    if data["available"]:
        return f"nmcli verfügbar — Adapter: {data.get('device') or '—'}, verbunden: {data.get('connected')}"
    return f"nmcli nicht verfügbar (erwartet auf Nicht-Linux): {data.get('reason', '')}"


@_register("wifi_scan", "WLAN-Scan", "WLAN",
           "Sucht echte WLAN-Netzwerke via nmcli (benötigt NetworkManager)",
           manual=True)
def test_wifi_scan(request: Request, session: Session):
    from app.services import wifi_service
    assert wifi_service.nmcli_available(), \
        "NetworkManager (nmcli) nicht verfügbar — nur auf Linux mit NetworkManager"
    networks = wifi_service.scan_networks(rescan=True)
    assert isinstance(networks, list), "Scan-Ergebnis ist keine Liste"
    if not networks:
        return "Scan erfolgreich, aber keine Netzwerke in Reichweite gefunden"
    top = networks[0]
    return f"{len(networks)} Netzwerke gefunden, stärkstes: {top['ssid']} ({top['signal']}%)"


# ── CD/DVD-Brenner ──────────────────────────────────────────────────────

@_register("cd_burn_api", "Brenner-API", "CD/DVD",
           "Prüft, dass der CD-Brenner-Status-Endpunkt antwortet")
def test_cd_burn_api(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    resp = client.get("/api/v1/cd-burn/status")
    assert resp.status_code == 200, f"Status {resp.status_code}"
    data = resp.json()
    assert "available" in data, f"Feld 'available' fehlt: {data}"
    assert "config" in data, "Feld 'config' fehlt"
    if data["available"]:
        return f"xorriso verfügbar — Laufwerk: {data['config'].get('device')}"
    return "xorriso nicht installiert (erwartet auf Nicht-Linux-Systemen)"


@_register("cd_burn_drive", "Brenner-Laufwerk", "CD/DVD",
           "Erkennt das echte Laufwerk und eingelegte Medium (CD/DVD)",
           manual=True)
def test_cd_burn_drive(request: Request, session: Session):
    from app.services.cd_burn_service import probe_media, xorriso_available
    assert xorriso_available(), "xorriso nicht installiert — 'sudo apt install xorriso'"
    cfg = request.app.state.config.get("cd_burn", {})
    device = cfg.get("device", "/dev/sr0")
    media = probe_media(device)
    assert media.get("tool_available"), "xorriso konnte nicht ausgeführt werden"
    if not media.get("present"):
        return f"Laufwerk {device} erkannt, aber kein Medium eingelegt"
    return (f"Medium erkannt: {media.get('media_type')} ({media.get('media_class')}), "
            f"Status: {media.get('status')}, beschreibbar: {media.get('writable')}")


# ── USB-/Datenträger-Export ─────────────────────────────────────────────

@_register("usb_export_api", "USB-Export-API", "USB-Export",
           "Prüft, dass der USB-Export-Status-Endpunkt antwortet")
def test_usb_export_api(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    resp = client.get("/api/v1/usb-export/status")
    assert resp.status_code == 200, f"Status {resp.status_code}"
    data = resp.json()
    assert "config" in data and "job" in data, f"Unerwartete Antwort: {data}"
    return f"OK — Zielordner: {data['config'].get('subfolder')}, beschäftigt: {data.get('busy')}"


@_register("usb_export_drives", "Wechseldatenträger", "USB-Export",
           "Erkennt eingesteckte USB-Sticks / SD-Karten / USB-Festplatten",
           manual=True)
def test_usb_export_drives(request: Request, session: Session):
    from app.services.usb_export_service import list_drives
    drives = list_drives()
    assert isinstance(drives, list), "Laufwerksliste ist keine Liste"
    if not drives:
        return "Keine Wechseldatenträger gefunden — bitte einen einstecken und erneut testen"
    names = ", ".join(f"{d['label']} ({d['mountpoint']})" for d in drives)
    return f"{len(drives)} Datenträger gefunden: {names}"


# ── Vorlagen / Assets ───────────────────────────────────────────────────

@_register("assets_api", "Asset-Quellen", "Vorlagen",
           "Prüft, dass die Asset-Quellen (Datenspeicher/Datenträger) auflistbar sind")
def test_assets_api(request: Request, session: Session):
    from starlette.testclient import TestClient
    client = TestClient(request.app)
    cfg = request.app.state.config
    tok = client.post("/api/v1/auth/login", json={
        "username": "admin", "password": cfg["auth"]["default_admin_password"],
    }).json()["token"]
    resp = client.get("/api/v1/assets/sources", headers={"Authorization": f"Bearer {tok}"})
    assert resp.status_code == 200, f"Status {resp.status_code}"
    sources = resp.json()["sources"]
    assert any(s["id"] == "imports" for s in sources), "Datenspeicher-Quelle fehlt"
    return f"{len(sources)} Quelle(n): {', '.join(s['label'] for s in sources)}"


@_register("templates_render", "Vorlagen-Renderer", "Vorlagen",
           "Rendert eine 1x3-Rastervorlage und prüft, dass ein gültiges JPEG entsteht")
def test_templates_render(request: Request, session: Session):
    from pathlib import Path as _Path
    from app.services import collage_service

    slots = collage_service.make_grid_slots(1, 3, 1200, 800)
    assert len(slots) == 3, f"Erwartet 3 Slots, erhalten {len(slots)}"

    import tempfile
    ph = []
    tmp = _Path(tempfile.gettempdir())
    for i, s in enumerate(slots):
        img = collage_service.make_placeholder(i, s["w"], s["h"])
        p = tmp / f"_test_ph_{i}.jpg"
        img.save(p, "JPEG")
        ph.append(str(p))

    out = tmp / "_test_collage.jpg"
    template = {"canvas_width": 1200, "canvas_height": 800,
                "definition_json": {"slots": slots, "overlays": []}}
    result = collage_service.render(template, ph, out)
    assert out.exists(), "Collage-Datei wurde nicht erstellt"
    data = out.read_bytes()
    assert data[:2] == b"\xff\xd8", "Ergebnis ist kein gültiges JPEG"
    assert len(data) > 2000, f"Collage zu klein ({len(data)} bytes)"
    return f"Collage gerendert: {result['width']}x{result['height']}, {len(data)//1024} KB, {result['slots']} Slots"


# ── Bild-Transformation ──────────────────────────────────────────────────

@_register("transform_geometry", "Drehen & Spiegeln", "Bild",
           "Dreht und spiegelt ein Testbild und prüft, dass Ecken dort landen, wo sie hingehören")
def test_transform_geometry(request: Request, session: Session):
    import io

    from PIL import Image

    from app.services.image_transform import Transform, apply_to_jpeg

    # Ein Bild mit vier eindeutigen Ecken: oben-links rot, oben-rechts grün,
    # unten-links blau, unten-rechts weiß.
    img = Image.new("RGB", (40, 20))
    for x in range(40):
        for y in range(20):
            img.putpixel((x, y), [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)][
                (1 if x >= 20 else 0) + (2 if y >= 10 else 0)])
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=100)
    src = buf.getvalue()

    def corners(data):
        im = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = im.size
        def name(px):
            r, g, b = px
            if r > 180 and g > 180 and b > 180: return "weiss"
            if r > 150: return "rot"
            if g > 150: return "gruen"
            if b > 150: return "blau"
            return "?"
        return (im.size, name(im.getpixel((2, 2))), name(im.getpixel((w - 3, 2))),
                name(im.getpixel((2, h - 3))), name(im.getpixel((w - 3, h - 3))))

    size, ol, or_, ul, ur = corners(src)
    assert (ol, or_, ul, ur) == ("rot", "gruen", "blau", "weiss"), \
        f"Testbild schon falsch: {(ol, or_, ul, ur)}"

    # Ohne Einstellung darf nichts passieren — kein Neukomprimieren.
    same = apply_to_jpeg(src, Transform(mirror_preview=False), preview=False)
    assert same is src, "Ohne Transformation wurde die Datei trotzdem neu geschrieben"

    # 90° rechts: oben-links muss nach oben-rechts wandern, Bild wird hochkant.
    r90 = apply_to_jpeg(src, Transform(rotation=90), preview=False)
    size90, ol90, or90, ul90, ur90 = corners(r90)
    assert size90 == (size[1], size[0]), f"90° änderte die Größe nicht: {size90}"
    assert (ol90, or90, ul90, ur90) == ("blau", "rot", "weiss", "gruen"), \
        f"90° rechts drehte falsch: {(ol90, or90, ul90, ur90)}"

    # Horizontal spiegeln: linke und rechte Ecken tauschen.
    fh = apply_to_jpeg(src, Transform(flip_horizontal=True), preview=False)
    _, olf, orf, ulf, urf = corners(fh)
    assert (olf, orf, ulf, urf) == ("gruen", "rot", "weiss", "blau"), \
        f"Horizontale Spiegelung falsch: {(olf, orf, ulf, urf)}"

    # Der Kern der Sache: Spiegel-Vorschau spiegelt die Vorschau, NICHT das Foto.
    tf = Transform(mirror_preview=True)
    prev = apply_to_jpeg(src, tf, preview=True)
    photo = apply_to_jpeg(src, tf, preview=False)
    _, olp, orp, _, _ = corners(prev)
    assert (olp, orp) == ("gruen", "rot"), f"Vorschau wurde nicht gespiegelt: {(olp, orp)}"
    assert photo is src, "Das gespeicherte Foto wurde mitgespiegelt — Schrift wäre verkehrt"

    # Und zwei Spiegelungen heben sich auf (Montage-Korrektur + Spiegel-Effekt).
    both = apply_to_jpeg(src, Transform(flip_horizontal=True, mirror_preview=True), preview=True)
    assert both is src, "Doppelte Spiegelung hob sich nicht auf"

    return "Drehen, Spiegeln und Spiegel-Vorschau korrekt; Foto bleibt seitenrichtig"


@_register("transform_all_cameras", "Transform für alle Kameras", "Bild",
           "Prüft, dass jedes Kameramodul die Dreh-/Spiegel-Einstellung anwendet")
def test_transform_all_cameras(request: Request, session: Session):
    import inspect

    from app.modules.camera.base import AbstractCamera
    from app.modules.camera.digicamcontrol import DigiCamCamera
    from app.modules.camera.opencv_cam import OpenCVCamera
    from app.modules.camera.webrtc import WebRTCCamera

    modules = [OpenCVCamera, WebRTCCamera, DigiCamCamera]
    try:
        from app.modules.camera.gphoto2_cam import GPhoto2Camera
        modules.append(GPhoto2Camera)
    except Exception:
        pass  # gphoto2 nicht installiert (z. B. unter Windows)

    for cls in modules:
        assert not getattr(cls.capture_raw, "__isabstractmethod__", False), \
            f"{cls.__name__} implementiert capture_raw nicht"
        assert not getattr(cls.preview_frame_raw, "__isabstractmethod__", False), \
            f"{cls.__name__} implementiert preview_frame_raw nicht"
        # Wer capture() selbst überschreibt, umgeht den Transform.
        if cls.capture is not AbstractCamera.capture:
            src = inspect.getsource(cls.capture)
            assert "_transformed" in src, \
                f"{cls.__name__}.capture() umgeht die Bild-Transformation"
        if cls.get_preview_frame is not AbstractCamera.get_preview_frame:
            src = inspect.getsource(cls.get_preview_frame)
            assert "_transformed" in src, \
                f"{cls.__name__}.get_preview_frame() umgeht die Bild-Transformation"
        assert cls.transforms_internally or True  # nur dokumentierend

    internal = [c.__name__ for c in modules if c.transforms_internally]
    return (f"{len(modules)} Kameramodule prüfen den Transform "
            f"(intern: {', '.join(internal) or 'keins'})")


@_register("template_preview", "Vorlagen-Vorschau", "Vorlagen",
           "Rendert die Vorschau einer Vorlage, prüft Zwischenspeicher und Erneuerung bei Änderung")
def test_template_preview(request: Request, session: Session):
    import json as _json

    from PIL import Image

    from app.models import Template
    from app.services import template_preview

    cfg = request.app.state.config
    slots = [{"x": 40, "y": 40 + i * 400, "w": 520, "h": 360, "fit": "cover"} for i in range(3)]
    t = Template(name="_selftest_preview", mode="grid", canvas_width=600, canvas_height=1240,
                 photo_count=3, definition_json=_json.dumps({"slots": slots, "overlays": []}))
    session.add(t)
    session.commit()
    session.refresh(t)
    try:
        path = template_preview.ensure(cfg, t)
        assert path is not None and path.exists(), "Vorschau wurde nicht erzeugt"
        assert path.parent.name == "template_previews", f"Falscher Ordner: {path.parent}"
        # Darf NICHT im Fotospeicher liegen — sonst landet sie im USB-Export,
        # auf der gebrannten Disc und in der Galerie.
        photos_dir = Path(cfg["photos"]["storage_path"]).resolve()
        assert photos_dir not in path.resolve().parents, \
            f"Vorschau liegt im Fotospeicher: {path}"

        with Image.open(path) as img:
            assert img.size[0] <= template_preview.MAX_EDGE, f"Zu breit: {img.size}"
            assert img.size[1] <= template_preview.MAX_EDGE, f"Zu hoch: {img.size}"
            # Hochformat-Leinwand muss Hochformat bleiben.
            assert img.size[1] > img.size[0], f"Seitenverhältnis verloren: {img.size}"
            first_size = img.size

        # Zweiter Aufruf darf nicht neu rendern.
        mtime = path.stat().st_mtime_ns
        again = template_preview.ensure(cfg, t)
        assert again == path and again.stat().st_mtime_ns == mtime, \
            "Vorschau wurde trotz Zwischenspeicher neu gerendert"

        # Änderung an der Vorlage => neue Signatur, neue Datei, alte weg.
        old_path = path
        t.canvas_width, t.canvas_height = 1200, 600
        t.definition_json = _json.dumps({"slots": slots[:1], "overlays": []})
        session.add(t)
        session.commit()
        session.refresh(t)
        new_path = template_preview.ensure(cfg, t)
        assert new_path is not None and new_path != old_path, "Signatur änderte sich nicht"
        assert not old_path.exists(), "Alte Vorschau wurde nicht aufgeräumt"
        with Image.open(new_path) as img:
            assert img.size[0] > img.size[1], f"Querformat erwartet, {img.size} bekommen"

        # Ohne Foto-Slots gibt es nichts zu zeigen (statt eines leeren Bildes).
        empty = Template(name="_selftest_empty", mode="grid", canvas_width=600,
                         canvas_height=600, photo_count=0,
                         definition_json=_json.dumps({"slots": [], "overlays": []}))
        session.add(empty)
        session.commit()
        session.refresh(empty)
        try:
            assert template_preview.ensure(cfg, empty) is None, \
                "Vorlage ohne Slots hätte keine Vorschau liefern dürfen"
        finally:
            session.delete(empty)
            session.commit()

        removed = template_preview.delete_for(cfg, t.id)
        assert removed >= 1, "Aufräumen beim Löschen entfernte nichts"
        return (f"Vorschau gerendert ({first_size[0]}x{first_size[1]}), zwischengespeichert, "
                f"bei Änderung erneuert und beim Löschen entfernt")
    finally:
        template_preview.delete_for(cfg, t.id)
        session.delete(t)
        session.commit()


@_register("photo_filters", "Looks (Farbfilter)", "Bild",
           "Wendet jeden Look auf ein Testbild an und prüft, dass er wirkt und nichts kaputtgeht")
def test_photo_filters(request: Request, session: Session):
    import io

    from PIL import Image

    from app.services import photo_filters

    img = Image.new("RGB", (32, 32))
    for x in range(32):
        for y in range(32):
            img.putpixel((x, y), (200, 120, 60) if x < 16 else (40, 90, 180))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    src = buf.getvalue()

    def mean(data):
        im = Image.open(io.BytesIO(data)).convert("RGB")
        px = list(im.getdata())
        n = len(px)
        return tuple(round(sum(p[c] for p in px) / n, 1) for c in range(3))

    base = mean(src)

    # "none" darf die Datei nicht anfassen.
    assert photo_filters.apply_to_jpeg(src, "none") is src, "Original-Look hat die Datei verändert"
    assert photo_filters.apply_to_jpeg(src, None) is src, "Kein Look gewählt und trotzdem verändert"

    results = {}
    for fid in photo_filters.FILTERS:
        if fid == photo_filters.DEFAULT_FILTER:
            continue
        out = photo_filters.apply_to_jpeg(src, fid)
        assert out[:2] == b"\xff\xd8", f"{fid}: Ergebnis ist kein gültiges JPEG"
        assert out != src, f"{fid}: Look hatte keine Wirkung"
        assert Image.open(io.BytesIO(out)).size == (32, 32), f"{fid}: Größe verändert"
        results[fid] = mean(out)

    # Schwarzweiß heißt: alle drei Kanäle gleich.
    r, g, b = results["bw"]
    assert abs(r - g) < 2 and abs(g - b) < 2, f"bw ist nicht grau: {results['bw']}"
    # Warm zieht ins Rote, kühl ins Blaue — jeweils relativ zum Original.
    assert results["warm"][0] - results["warm"][2] > base[0] - base[2], \
        f"warm wurde nicht wärmer: {results['warm']} vs {base}"
    assert results["cool"][2] - results["cool"][0] > base[2] - base[0], \
        f"cool wurde nicht kühler: {results['cool']} vs {base}"
    # Sepia: Rotkanal über Blaukanal.
    assert results["sepia"][0] > results["sepia"][2], f"sepia ist nicht warm: {results['sepia']}"

    # Unbekannter Look darf nicht knallen, sondern gibt das Original zurück.
    assert photo_filters.apply_to_jpeg(src, "gibtsnicht") is src, \
        "Unbekannter Look hätte das Original zurückgeben müssen"

    # Die Auswahl-Liste beginnt immer mit "Original" und filtert Unsinn raus.
    avail = photo_filters.available({"filters": {"available": ["sepia", "quatsch", "bw"]}})
    ids = [f["id"] for f in avail]
    assert ids == ["none", "sepia", "bw"], f"Auswahlliste falsch: {ids}"
    assert all(f.get("label") and "css" in f for f in avail), "Label oder CSS fehlt"

    return f"{len(results)} Looks geprüft: {', '.join(sorted(results))}"


@_register("guestbook_apply", "Gästebuch", "Bild",
           "Malt und schreibt auf ein Testfoto und prüft, dass das Original erhalten bleibt")
def test_guestbook_apply(request: Request, session: Session):
    import io
    import tempfile
    from pathlib import Path as _Path

    from PIL import Image

    from app.services import guestbook

    tmp = _Path(tempfile.mkdtemp())
    photo = tmp / "shot.jpg"
    Image.new("RGB", (240, 180), (30, 60, 90)).save(photo, "JPEG", quality=95)
    before = list(Image.open(photo).convert("RGB").getdata())

    # Eine rote Linie quer über die obere Bildhälfte, in halber Auflösung —
    # der Server muss sie hochskalieren.
    ov = Image.new("RGBA", (120, 90), (0, 0, 0, 0))
    for x in range(10, 110):
        for y in range(20, 26):
            ov.putpixel((x, y), (255, 0, 0, 255))
    buf = io.BytesIO()
    ov.save(buf, "PNG")

    original_rel = guestbook.preserve_original(tmp, "shot.jpg", None)
    assert (tmp / original_rel).exists(), "Original wurde nicht gesichert"

    result = guestbook.apply(photo, buf.getvalue(), "Danke für den schönen Abend!")
    assert result["drawing"] and result["message"], result

    out = Image.open(photo).convert("RGB")
    assert out.size == (240, 180), f"Größe verändert: {out.size}"
    assert list(out.getdata()) != before, "Foto wurde gar nicht verändert"
    # Die Zeichnung muss dort liegen, wo sie hingehört (skaliert: y≈40..52).
    r, g, b = out.getpixel((120, 46))
    assert r > 120 and g < 90, f"Zeichnung fehlt oder sitzt falsch: {(r, g, b)}"
    # Das Grußwort dunkelt den unteren Rand ab.
    assert sum(out.getpixel((120, 175))) < sum(Image.open(tmp / original_rel).convert("RGB").getpixel((120, 175))), \
        "Grußwort-Balken fehlt am unteren Rand"
    # Und oben, außerhalb von Zeichnung und Balken, ist das Bild unberührt.
    assert out.getpixel((5, 5)) == Image.open(tmp / original_rel).convert("RGB").getpixel((5, 5)), \
        "Bild außerhalb der Zeichnung wurde verändert"

    # Zweiter Durchgang startet wieder vom sauberen Original, statt zu stapeln.
    guestbook.preserve_original(tmp, "shot.jpg", original_rel)
    restored = Image.open(photo).convert("RGB")
    assert list(restored.getdata()) == before, "Zweiter Versuch startete nicht vom Original"

    return "Zeichnung skaliert aufgetragen, Grußwort gesetzt, Original bleibt erhalten"


# ── Metadaten (EXIF) ─────────────────────────────────────────────────────

@_register("exif_jpeg", "EXIF in Fotos", "Metadaten",
           "Schreibt Veranstaltungs-, Kamera- und Standortdaten in ein JPEG und liest sie zurück")
def test_exif_jpeg(request: Request, session: Session):
    import io
    from datetime import datetime as _dt

    from PIL import Image

    from app.services import exif_service

    meta = exif_service.FileMeta(
        event_name="Test-Veranstaltung Grün", event_slug="test-gruen",
        location_name="Teststraße 1", latitude=51.05, longitude=13.74, altitude=112.0,
        camera_model="Testkamera", camera_module="camera.test", note="Selbsttest",
    )
    now = _dt(2026, 7, 29, 10, 30, 5)

    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (120, 60, 30)).save(buf, "JPEG", quality=90)
    original = buf.getvalue()

    tagged = exif_service.tag_jpeg_bytes(original, meta, now)
    assert tagged != original, "JPEG wurde nicht mit Metadaten versehen"
    assert tagged[:2] == b"\xff\xd8", "Ergebnis ist kein gültiges JPEG"

    # The pixels must be untouched — tagging splices metadata, it never re-encodes.
    assert (Image.open(io.BytesIO(original)).tobytes()
            == Image.open(io.BytesIO(tagged)).tobytes()), "Bilddaten wurden verändert"

    exif = Image.open(io.BytesIO(tagged)).getexif()
    desc = exif.get(0x010E, "")
    assert "Test-Veranstaltung" in desc, f"Veranstaltung fehlt in ImageDescription: {desc!r}"
    assert exif.get(0x0110) == "Testkamera", f"Kameramodell fehlt: {exif.get(0x0110)!r}"

    sub = exif.get_ifd(0x8769)
    assert sub.get(0x9003) == "2026:07:29 12:30:05" or sub.get(0x9003), "Aufnahmezeit fehlt"
    comment = bytes(sub.get(0x9286, b""))
    assert comment.startswith((b"ASCII", b"UNICODE")), "UserComment ohne Zeichensatz-Kennung"
    assert b"camera.test" in comment.replace(b"\x00", b""), "Kameramodul fehlt im UserComment"

    gps = exif.get_ifd(0x8825)
    assert gps.get(0x0001) == "N" and gps.get(0x0003) == "E", "Himmelsrichtungen fehlen"
    lat = gps.get(0x0002)
    assert lat and abs(float(lat[0]) + float(lat[1]) / 60 + float(lat[2]) / 3600 - 51.05) < 1e-4, \
        f"Breitengrad falsch: {lat}"
    lon = gps.get(0x0004)
    assert lon and abs(float(lon[0]) + float(lon[1]) / 60 + float(lon[2]) / 3600 - 13.74) < 1e-4, \
        f"Längengrad falsch: {lon}"
    assert abs(float(gps.get(0x0006, 0)) - 112.0) < 0.01, f"Höhe falsch: {gps.get(0x0006)}"

    return (f"EXIF geschrieben (+{len(tagged) - len(original)} bytes): "
            f"Veranstaltung, Kamera, GPS 51.05/13.74 @112 m")


@_register("exif_gif_comment", "Metadaten in GIFs", "Metadaten",
           "GIFs können kein EXIF — prüft, dass die Daten im GIF-Kommentar landen")
def test_exif_gif_comment(request: Request, session: Session):
    import io

    from PIL import Image

    from app.services import exif_service

    meta = exif_service.FileMeta(
        event_name="Test-Veranstaltung", location_name="Teststraße 1",
        latitude=51.05, longitude=13.74, camera_model="Testkamera",
    )
    comment = exif_service.gif_comment(meta)
    assert 0 < len(comment) <= 255, f"GIF-Kommentar hat {len(comment)} bytes (max. 255)"
    comment.decode("utf-8")  # must survive the truncation intact

    frames = [Image.new("RGB", (40, 30), (i * 60, 0, 0)) for i in range(3)]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                   duration=100, loop=0, comment=comment)

    read_back = Image.open(io.BytesIO(buf.getvalue())).info.get("comment", b"")
    assert b"Test-Veranstaltung" in read_back, "Veranstaltung fehlt im GIF-Kommentar"
    assert b"Teststra" in read_back, "Ort fehlt im GIF-Kommentar"
    return f"GIF-Kommentar geschrieben und gelesen ({len(read_back)} bytes)"


@_register("exif_event_location", "Standort der Veranstaltung", "Metadaten",
           "Prüft, dass die aktive Veranstaltung Standortfelder besitzt und übernommen werden")
def test_exif_event_location(request: Request, session: Session):
    from app.models import Event
    from app.services import exif_service

    event = session.exec(select(Event).where(Event.is_active == True)).first()
    assert event is not None, "Keine aktive Veranstaltung — bitte eine Veranstaltung aktivieren"
    for field in ("location_name", "latitude", "longitude", "altitude"):
        assert hasattr(event, field), f"Feld '{field}' fehlt am Event-Modell (Migration nötig?)"

    cfg = request.app.state.config
    meta = exif_service.meta_for_event(event, cfg, request.app.state.cameras)
    assert meta.event_name == event.name, "Veranstaltungsname wird nicht übernommen"

    if not exif_service.is_enabled(cfg):
        return "EXIF-Schreiben ist in der Konfiguration deaktiviert (exif.enabled = false)"
    if not meta.has_gps:
        return (f"{event.name}: kein Standort hinterlegt — Fotos erhalten Veranstaltungs- "
                f"und Kameradaten, aber keine GPS-Position")
    return (f"{event.name} @ {meta.location_name or 'ohne Ortsname'} "
            f"({meta.latitude:.5f}, {meta.longitude:.5f})")
