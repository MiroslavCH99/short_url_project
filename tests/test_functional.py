import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from main import app, get_db, Base
import fakeredis

import main as main_module
main_module.redis_client = fakeredis.FakeStrictRedis(decode_responses=True)

# Создаем тестовую базу
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

def test_register_and_login():
    # Регистрация пользователя
    response = client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "yourpassword"
    })
    assert response.status_code == 200
    data = response.json()
    assert "id" in data

    # Логин
    login_response = client.post("/users/login", data={
        "username": "testuser",
        "password": "yourpassword"
    })
    assert login_response.status_code == 200
    login_data = login_response.json()
    assert "access_token" in login_data

def test_create_link_and_redirect():
    client.post("/users/register", json={
        "username": "linkuser",
        "email": "linkuser@example.com",
        "password": "pass"
    })
    login_response = client.post("/users/login", data={
        "username": "linkuser",
        "password": "pass"
    })
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post("/links/shorten", json={
        "original_url": "https://example.com/very/long/url",
        "custom_alias": "myalias"
    }, headers=headers)
    assert create_response.status_code == 200
    link_data = create_response.json()
    assert link_data["short_code"] == "myalias"

    redirect_response = client.get("/links/myalias", follow_redirects=False)
    assert redirect_response.status_code in [302, 307]
    assert redirect_response.headers["location"] == "https://example.com/very/long/url"

def test_update_and_delete_link():
    client.post("/users/register", json={
        "username": "updateuser",
        "email": "updateuser@example.com",
        "password": "pass"
    })
    login_response = client.post("/users/login", data={
        "username": "updateuser",
        "password": "pass"
    })
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post("/links/shorten", json={
        "original_url": "https://example.com/old/url",
        "custom_alias": "updatealias"
    }, headers=headers)
    assert create_response.status_code == 200

    update_response = client.put("/links/updatealias", json={
        "original_url": "https://example.com/new/url"
    }, headers=headers)
    assert update_response.status_code == 200
    updated_data = update_response.json()
    assert updated_data["original_url"] == "https://example.com/new/url"

    delete_response = client.delete("/links/updatealias", headers=headers)
    assert delete_response.status_code == 200

    get_response = client.get("/links/updatealias")
    assert get_response.status_code == 404

def test_get_stats_for_link():
    client.post("/users/register", json={
        "username": "statsuser",
        "email": "statsuser@example.com",
        "password": "pass"
    })
    login_response = client.post("/users/login", data={
        "username": "statsuser",
        "password": "pass"
    })
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post("/links/shorten", json={
        "original_url": "https://example.com/stats/url",
        "custom_alias": "statsalias"
    }, headers=headers)
    assert create_response.status_code == 200

    stats_response = client.get("/links/statsalias/stats")
    assert stats_response.status_code == 200
    stats_data = stats_response.json()
    assert stats_data["original_url"] == "https://example.com/stats/url"
    assert stats_data["click_count"] == 0

def test_search_link():
    client.post("/users/register", json={
        "username": "searchuser",
        "email": "searchuser@example.com",
        "password": "pass"
    })
    login_response = client.post("/users/login", data={
        "username": "searchuser",
        "password": "pass"
    })
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    client.post("/links/shorten", json={
        "original_url": "https://example.com/search/one",
        "custom_alias": "alias1"
    }, headers=headers)
    client.post("/links/shorten", json={
        "original_url": "https://example.com/search/two",
        "custom_alias": "alias2"
    }, headers=headers)

    search_response = client.get("/links/search?original_url=search")
    assert search_response.status_code == 200
    links = search_response.json()
    # Проверяем, что найдены как минимум 2 ссылки
    assert len(links) >= 2

def test_invalid_link_creation():
    #Создать ссылку с невалидным URL
    response = client.post("/links/shorten", json={
        "original_url": "not-a-valid-url"
    })
    assert response.status_code == 422  # Unprocessable Entity

def test_not_found_link():
    #Перейти по несуществующей ссылке
    response = client.get("/links/nonexistent", follow_redirects=False)
    assert response.status_code == 404
