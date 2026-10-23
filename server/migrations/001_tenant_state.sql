-- Each PrivRelay process is pinned to one tenant_id. Payloads are additionally
-- authenticated-encrypted by a tenant-derived key before reaching PostgreSQL.
CREATE TABLE IF NOT EXISTS privrelay_tenant_state (
    tenant_id text PRIMARY KEY CHECK (length(tenant_id) BETWEEN 1 AND 128),
    payload bytea NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
