python
from sqlalchemy import Column, BigInteger, String, DateTime, Boolean, Integer, Numeric, ForeignKey, Date
from sqlalchemy.sql import func
from app.database import Base

class User(Base):
    __tablename__ = "users"
    user_id = Column(BigInteger, primary_key=True)
    username = Column(String(255))
    first_name = Column(String(255))
    last_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"))
    plan_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ProgressStats(Base):
    __tablename__ = "progress_stats"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"))
    session_date = Column(Date, nullable=False)
    total_markers_found = Column(Integer, default=0)
    avg_confidence = Column(Numeric(5,2))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
