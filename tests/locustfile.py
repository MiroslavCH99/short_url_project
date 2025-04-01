from locust import HttpUser, task, between

class ShortenerUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.client.post("/users/register", json={
            "username": "loaduser",
            "email": "loaduser@example.com",
            "password": "pass"
        })
        login_response = self.client.post("/users/login", data={
            "username": "loaduser",
            "password": "pass"
        })
        self.token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task
    def create_link(self):
        self.client.post("/links/shorten", json={
            "original_url": "https://example.com/very/long/url"
        }, headers=self.headers)
