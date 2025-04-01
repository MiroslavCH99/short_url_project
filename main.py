from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, HttpUrl
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import redis
from passlib.context import CryptContext
import jwt

from datetime import datetime, timedelta
from typing import Optional, List
import random
import string
import time
import os

#БД
SQLALCHEMY_DATABASE_URL = "postgresql://user:password@postgres:5432/shortener_db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)

class Link(Base):
    __tablename__ = "links"
    id = Column(Integer, primary_key=True, index=True)
    short_code = Column(String, unique=True, index=True)
    original_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    click_count = Column(Integer, default=0)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    project = Column(String, nullable=True)

# Создание таблиц
def init_db():
    Base.metadata.create_all(bind=engine)

#Redis
redis_client = redis.Redis(host='redis', port=6379, db=0, decode_responses=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login", auto_error=False)

def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(status_code=401, detail="Не удалось пройти аутентификацию")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserOut(BaseModel):
    id: int
    username: str
    email: str

    class Config:
        orm_mode = True

class LinkCreate(BaseModel):
    original_url: HttpUrl
    custom_alias: Optional[str] = None
    expires_at: Optional[datetime] = None
    project: Optional[str] = None

class LinkUpdate(BaseModel):
    original_url: HttpUrl

class LinkOut(BaseModel):
    short_code: str
    original_url: HttpUrl
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    click_count: int
    user_id: Optional[int]
    project: Optional[str]

    class Config:
        orm_mode = True

app = FastAPI()

#Эндпоинты пользователя

@app.post("/users/register", response_model=UserOut)
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter((User.username == user.username) | (User.email == user.email)).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Пользователь с таким именем или email уже существует")
    hashed_password = get_password_hash(user.password)
    new_user = User(username=user.username, email=user.email, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/users/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Неверное имя пользователя или пароль")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

#Доп функционал

def generate_short_code(length: int = 6) -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def update_link_stats(short_code: str):
    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.short_code == short_code).first()
        if link:
            link.click_count += 1
            link.last_used_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()

def schedule_link_deletion(link_id: int, delay: float):
    """Фоновая задача для удаления ссылки по истечении expires_at."""
    time.sleep(delay)
    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.id == link_id).first()
        if link and link.expires_at and link.expires_at <= datetime.utcnow():
            redis_client.delete(f"link:{link.short_code}")
            db.delete(link)
            db.commit()
    finally:
        db.close()


# Создание ссылки
@app.post("/links/shorten", response_model=LinkOut)
def create_link(link: LinkCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db), token: Optional[str] = Depends(oauth2_scheme)):
    user = None
    if token:
        try:
            user = get_current_user(token, db)
        except Exception:
            user = None
    if link.custom_alias:
        existing = db.query(Link).filter(Link.short_code == link.custom_alias).first()
        if existing:
            raise HTTPException(status_code=400, detail="Данный custom alias уже используется")
        short_code = link.custom_alias
    else:
        short_code = generate_short_code()
        while db.query(Link).filter(Link.short_code == short_code).first():
            short_code = generate_short_code()

    new_link = Link(
        short_code=short_code,
        original_url=str(link.original_url),
        expires_at=link.expires_at,
        project=link.project,
        user_id=user.id if user else None
    )
    db.add(new_link)
    db.commit()
    db.refresh(new_link)
    redis_client.set(f"link:{short_code}", new_link.original_url)

    if new_link.expires_at:
        delay = (new_link.expires_at - datetime.utcnow()).total_seconds()
        if delay > 0:
            background_tasks.add_task(schedule_link_deletion, new_link.id, delay)

    return new_link

# Перенаправление по короткой ссылке
@app.get("/links/{short_code}")
def redirect_link(short_code: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    cached_url = redis_client.get(f"link:{short_code}")
    if cached_url:
        background_tasks.add_task(update_link_stats, short_code)
        return RedirectResponse(url=cached_url)
    link = db.query(Link).filter(Link.short_code == short_code).first()
    if not link:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    if link.expires_at and link.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Ссылка устарела")
    link.click_count += 1
    link.last_used_at = datetime.utcnow()
    db.commit()
    redis_client.set(f"link:{short_code}", link.original_url)
    return RedirectResponse(url=link.original_url)

# Получение статистики по ссылке
@app.get("/links/{short_code}/stats", response_model=LinkOut)
def get_link_stats(short_code: str, db: Session = Depends(get_db)):
    link = db.query(Link).filter(Link.short_code == short_code).first()
    if not link:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    return link

# Обновление ссылки
@app.put("/links/{short_code}", response_model=LinkOut)
def update_link(short_code: str, link_update: LinkUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    link = db.query(Link).filter(Link.short_code == short_code).first()
    if not link:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    if link.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Нет доступа для обновления данной ссылки")
    link.original_url = str(link_update.original_url)
    db.commit()
    db.refresh(link)
    redis_client.set(f"link:{short_code}", link.original_url)
    return link

# Удаление ссылки
@app.delete("/links/{short_code}")
def delete_link(short_code: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    link = db.query(Link).filter(Link.short_code == short_code).first()
    if not link:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    if link.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Нет доступа для удаления данной ссылки")
    redis_client.delete(f"link:{short_code}")
    db.delete(link)
    db.commit()
    return {"detail": "Ссылка удалена"}

# Поиск ссылки по оригинальному URL
@app.get("/links/search", response_model=List[LinkOut])
def search_links(original_url: str, db: Session = Depends(get_db)):
    links = db.query(Link).filter(Link.original_url.ilike(f"%{original_url}%")).all()
    return links

@app.delete("/links/cleanup")
def cleanup_expired_links(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    expired_links = db.query(Link).filter(Link.expires_at != None, Link.expires_at < datetime.utcnow()).all()
    count = 0
    for link in expired_links:
        redis_client.delete(f"link:{link.short_code}")
        db.delete(link)
        count += 1
    db.commit()
    return {"detail": f"Удалено {count} просроченных ссылок"}


if __name__ == "__main__":
    init_db()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)