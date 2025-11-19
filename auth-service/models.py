import sqlalchemy
from database import metadata
from enum import Enum

# -------------------------
# Role Enum
# -------------------------
class Role(str, Enum):
    user = "user"
    driver = "driver"
    admin = "admin"

# -------------------------
# Auth Users Table
# -------------------------
auth_users = sqlalchemy.Table(
    "auth_users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String),
    sqlalchemy.Column("email", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("password_hash", sqlalchemy.String),
    sqlalchemy.Column("role", sqlalchemy.String, default=Role.user.value),
    sqlalchemy.Column("vehicle", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("license_number", sqlalchemy.String, nullable=True),
)
