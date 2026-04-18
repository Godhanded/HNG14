from sqlalchemy import Column, String, Float, Integer
from database import Base


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    gender = Column(String, nullable=True)
    gender_probability = Column(Float, nullable=True)
    sample_size = Column(Integer, nullable=True)
    age = Column(Integer, nullable=True)
    age_group = Column(String, nullable=True)
    country_id = Column(String, nullable=True)
    country_probability = Column(Float, nullable=True)
    created_at = Column(String, nullable=False)
