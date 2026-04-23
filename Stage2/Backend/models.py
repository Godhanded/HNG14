from sqlalchemy import Column, String, Float, Integer, Index
from database import Base


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False, index=True)
    gender = Column(String, nullable=True)
    gender_probability = Column(Float, nullable=True)
    age = Column(Integer, nullable=True)
    age_group = Column(String, nullable=True)
    country_id = Column(String(2), nullable=True)
    country_name = Column(String, nullable=True)
    country_probability = Column(Float, nullable=True)
    created_at = Column(String, nullable=False)

    __table_args__ = (
        Index("ix_profiles_gender", "gender"),
        Index("ix_profiles_age_group", "age_group"),
        Index("ix_profiles_country_id", "country_id"),
        Index("ix_profiles_age", "age"),
        Index("ix_profiles_gender_prob", "gender_probability"),
        Index("ix_profiles_country_prob", "country_probability"),
        Index("ix_profiles_created_at", "created_at"),
    )
