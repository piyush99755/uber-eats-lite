import sqlalchemy
from database import metadata

auth_users = sqlalchemy.Table(
    "auth_users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("email", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("password_hash", sqlalchemy.String),
    sqlalchemy.Column("role", sqlalchemy.String, default="user"),
)
