# short_url_project

Проект по созданию коротких ссылок. 

## Основные эндпоинты
Регистрация пользователя
```commandline
curl -X POST "http://localhost:8000/users/register" \
  -H "Content-Type: application/json" \
  -d '{
        "username": "testuser",
        "email": "test@example.com",
        "password": "yourpassword"
      }'
```
Авторизация
```commandline
curl -X POST "http://localhost:8000/users/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=testuser&password=yourpassword"
```
Создание короткой ссылки
```commandline
curl -X POST "http://localhost:8000/links/shorten" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{
        "original_url": "https://example.com/very/long/url",
        "custom_alias": "myalias",          // можно убрать, если нужен сгенерированный код
        "expires_at": "2025-12-31T23:59:00",  // опционально
        "project": "Project1"               // опционально
      }'
```
Переход по короткой ссылке (редирект)
```commandline
curl -L "http://localhost:8000/links/myalias"
```
Получение статистики по ссылке
```commandline
curl "http://localhost:8000/links/myalias/stats"
```
Обновление ссылки
```commandline
curl -X PUT "http://localhost:8000/links/myalias" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{
        "original_url": "https://example.com/new/url"
      }'
```
Удаление ссылки
```commandline
curl -X DELETE "http://localhost:8000/links/myalias" \
  -H "Authorization: Bearer <access_token>"
```
Очистка просроченных ссылок
```commandline
curl -X DELETE "http://localhost:8000/links/cleanup" \
  -H "Authorization: Bearer <access_token>"
```

## Тестирование
Стресс тестирование происходит по команде:
```commandline
locust -f tests/locustfile.py --host http://localhost:8000
```
Проверку покурытия можно сделать с помощью команды:
```commandline
python -m coverage run -m pytest tests; python -m coverage report -m
```