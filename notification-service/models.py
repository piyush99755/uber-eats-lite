from sqlalchemy import Table, Column, String, MetaData

metadata = MetaData()

notifications = Table(
    "notifications",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String),
    Column("message", String),
)
