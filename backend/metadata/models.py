from __future__ import annotations

from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase): pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="user")
    quota_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=5368709120)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Bucket(Base):
    __tablename__ = "buckets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(63), unique=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    access_policy: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Object(Base):
    __tablename__ = "objects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bucket_id: Mapped[str] = mapped_column(ForeignKey("buckets.id"), index=True)
    object_key: Mapped[str] = mapped_column(Text)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("bucket_id", "object_key"),)


class ObjectVersion(Base):
    __tablename__ = "object_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    object_id: Mapped[str] = mapped_column(ForeignKey("objects.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    stripe_size_bytes: Mapped[int] = mapped_column(BigInteger)
    data_fragment_count: Mapped[int] = mapped_column(Integer, default=4)
    parity_fragment_count: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(String(20), default="AVAILABLE")
    manifest: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Stripe(Base):
    __tablename__ = "stripes"
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("object_versions.id", ondelete="CASCADE"), index=True)
    stripe_index: Mapped[int] = mapped_column(Integer)
    original_size_bytes: Mapped[int] = mapped_column(BigInteger)
    encoded_fragment_size_bytes: Mapped[int] = mapped_column(BigInteger)
    original_sha256: Mapped[str] = mapped_column(String(64))
    coding_scheme: Mapped[str] = mapped_column(String(40), default="reed-solomon")
    coding_parameters: Mapped[dict] = mapped_column(JSONB, default=lambda: {"k": 4, "m": 2})
    status: Mapped[str] = mapped_column(String(20), default="HEALTHY")
    __table_args__ = (UniqueConstraint("version_id", "stripe_index"),)


class StorageNode(Base):
    __tablename__ = "storage_nodes"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(255))
    service_url: Mapped[str] = mapped_column(Text)
    capacity_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    available_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    failure_domain: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CapacityReservation(Base):
    __tablename__ = "capacity_reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(36), index=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("storage_nodes.id", ondelete="CASCADE"), index=True)
    stripe_id: Mapped[str] = mapped_column(String(180), index=True)
    bytes_reserved: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class UserQuotaReservation(Base):
    __tablename__ = "user_quota_reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    bytes_reserved: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"
    username: Mapped[str] = mapped_column(String(80), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Fragment(Base):
    __tablename__ = "fragments"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    stripe_id: Mapped[str] = mapped_column(ForeignKey("stripes.id", ondelete="CASCADE"), index=True)
    fragment_index: Mapped[int] = mapped_column(Integer)
    fragment_type: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_node_id: Mapped[str] = mapped_column(ForeignKey("storage_nodes.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="AVAILABLE")
    __table_args__ = (UniqueConstraint("stripe_id", "fragment_index"),)


class ClusterEvent(Base):
    __tablename__ = "cluster_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(20))
    component: Mapped[str] = mapped_column(String(80))
    node_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RepairJob(Base):
    __tablename__ = "repair_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stripe_id: Mapped[str] = mapped_column(ForeignKey("stripes.id"), index=True)
    fragment_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    source_nodes: Mapped[dict] = mapped_column(JSONB, default=dict)
    destination_node: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RebalanceJob(Base):
    __tablename__ = "rebalance_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fragment_id: Mapped[str] = mapped_column(ForeignKey("fragments.id"), index=True)
    source_node: Mapped[str] = mapped_column(String(100))
    destination_node: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="PLANNED")
    bytes_transferred: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
