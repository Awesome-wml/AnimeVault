"""用户认证相关API"""
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from typing import Optional
from bson import ObjectId

from models.schema import UserRegister, UserLogin, UserInfo, UserConfig, ResponseModel
from db.mongo_client import get_db
from config.settings import settings

router = APIRouter(prefix="/api/auth", tags=["认证"])
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """密码加密"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str) -> str:
    """创建JWT token"""
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {
        "user_id": user_id,
        "exp": expire
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """获取当前用户（依赖注入）"""
    token = credentials.credentials
    
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token已过期或无效")
    
    db = get_db()
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    
    return user


@router.post("/register")
async def register(data: UserRegister):
    """用户注册"""
    db = get_db()
    
    # 检查用户名是否存在
    existing = await db.users.find_one({"username": data.username})
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    # 创建用户
    user_doc = {
        "username": data.username,
        "password_hash": hash_password(data.password),
        "doubao_api_key": None,
        "doubao_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "doubao_model": "glm-4.7-flash",
        "create_time": datetime.utcnow()
    }
    
    result = await db.users.insert_one(user_doc)
    
    # 生成token
    token = create_access_token(str(result.inserted_id))
    
    return ResponseModel(
        message="注册成功",
        data={
            "token": token,
            "user": {
                "id": str(result.inserted_id),
                "username": data.username
            }
        }
    )


@router.post("/login")
async def login(data: UserLogin):
    """用户登录"""
    db = get_db()
    
    # 查找用户
    user = await db.users.find_one({"username": data.username})
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    # 验证密码
    if not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    # 生成token
    token = create_access_token(str(user["_id"]))
    
    return ResponseModel(
        message="登录成功",
        data={
            "token": token,
            "user": {
                "id": str(user["_id"]),
                "username": user["username"],
                "has_api_key": bool(user.get("doubao_api_key"))
            }
        }
    )


@router.get("/me", response_model=UserInfo)
async def get_me(user: dict = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserInfo(
        id=str(user["_id"]),
        username=user["username"],
        has_api_key=bool(user.get("doubao_api_key")),
        doubao_base_url=user.get("doubao_base_url"),
        doubao_model=user.get("doubao_model"),
        create_time=user["create_time"]
    )


@router.put("/config")
async def update_config(data: UserConfig, user: dict = Depends(get_current_user)):
    """更新用户配置（API密钥）"""
    db = get_db()
    
    update_data = {}
    if data.doubao_api_key is not None:
        update_data["doubao_api_key"] = data.doubao_api_key
    if data.doubao_base_url is not None:
        update_data["doubao_base_url"] = data.doubao_base_url
    if data.doubao_model is not None:
        update_data["doubao_model"] = data.doubao_model
    
    if update_data:
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": update_data}
        )
    
    return ResponseModel(message="配置更新成功")


@router.get("/config")
async def get_config(user: dict = Depends(get_current_user)):
    """获取用户配置"""
    return ResponseModel(
        data={
            "has_api_key": bool(user.get("doubao_api_key")),
            "doubao_base_url": user.get("doubao_base_url", "https://open.bigmodel.cn/api/paas/v4"),
            "doubao_model": user.get("doubao_model", "glm-4.7-flash")
        }
    )
