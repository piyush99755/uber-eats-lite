from sqlalchemy import Table, Column, String, MetaData

metadata = MetaData()

drivers = Table(
    "drivers",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String),
    Column("license_number", String),
    Column("status", String)
)
