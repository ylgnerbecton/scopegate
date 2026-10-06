-- Scopegate target schema contract. Fresh database only; not a legacy migration.
-- UUIDs are immutable. Runtime migration ownership belongs to Alembic.
BEGIN;
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  issuer TEXT NOT NULL CHECK (btrim(issuer) <> ''),
  subject TEXT NOT NULL CHECK (btrim(subject) <> ''),
  email TEXT NOT NULL CHECK (btrim(email) <> ''),
  display_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (issuer, subject)
);
CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lock_key BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
  name TEXT NOT NULL CHECK (btrim(name) <> ''),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
  access_mode TEXT NOT NULL DEFAULT 'target' CHECK (access_mode IN ('legacy','shadow','target')),
  default_locale TEXT NOT NULL DEFAULT 'en',
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
  name TEXT NOT NULL CHECK (btrim(name) <> ''),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (organization_id,id)
);
CREATE TABLE memberships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('viewer','access_manager')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
  kind TEXT NOT NULL DEFAULT 'customer' CHECK (kind IN ('customer','staff')),
  expires_at TIMESTAMPTZ,
  assignment_reason TEXT,
  can_review_migration BOOLEAN NOT NULL DEFAULT false,
  CHECK (NOT can_review_migration OR (kind = 'staff' AND role = 'access_manager')),
  access_version BIGINT NOT NULL DEFAULT 1 CHECK (access_version > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (kind <> 'staff' OR (expires_at IS NOT NULL AND assignment_reason IS NOT NULL AND btrim(assignment_reason) <> '')),
  CHECK (kind <> 'customer' OR role <> 'access_manager' OR expires_at IS NULL),
  CHECK (expires_at IS NULL OR expires_at > created_at),
  UNIQUE (organization_id,user_id),
  UNIQUE (organization_id,id)
);
CREATE INDEX memberships_user_org ON memberships(user_id,organization_id);
CREATE TABLE resources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  external_key TEXT NOT NULL UNIQUE CHECK (btrim(external_key) <> ''),
  catalog_version BIGINT NOT NULL CHECK (catalog_version > 0),
  status TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('published','archived')),
  avatar_url TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE resource_localizations (
  resource_id UUID NOT NULL REFERENCES resources(id) ON DELETE RESTRICT,
  locale TEXT NOT NULL CHECK (locale IN ('en','pt','es','fr')),
  title TEXT NOT NULL CHECK (btrim(title) <> ''),
  description TEXT,
  tags JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(tags) = 'array'),
  PRIMARY KEY (resource_id,locale)
);
CREATE INDEX localizations_locale_resource ON resource_localizations(locale,resource_id);
CREATE TABLE project_resources (
  organization_id UUID NOT NULL,
  project_id UUID NOT NULL,
  resource_id UUID NOT NULL REFERENCES resources(id) ON DELETE RESTRICT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  entitlement_version BIGINT NOT NULL DEFAULT 1 CHECK (entitlement_version > 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (organization_id,project_id,resource_id),
  FOREIGN KEY (organization_id,project_id) REFERENCES projects(organization_id,id) ON DELETE RESTRICT
);
CREATE INDEX project_resources_resource ON project_resources(resource_id);
CREATE TABLE resource_grants (
  organization_id UUID NOT NULL,
  membership_id UUID NOT NULL,
  project_id UUID NOT NULL,
  resource_id UUID NOT NULL,
  state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','revoked')),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (organization_id,membership_id,project_id,resource_id),
  FOREIGN KEY (organization_id,membership_id) REFERENCES memberships(organization_id,id) ON DELETE RESTRICT,
  FOREIGN KEY (organization_id,project_id,resource_id) REFERENCES project_resources(organization_id,project_id,resource_id) ON DELETE RESTRICT
);
CREATE INDEX resource_grants_entitlement ON resource_grants(organization_id,project_id,resource_id);
CREATE TABLE invitations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
  recipient_email TEXT NOT NULL CHECK (btrim(recipient_email) <> ''),
  recipient_email_normalized TEXT GENERATED ALWAYS AS (lower(btrim(recipient_email))) STORED,
  role TEXT NOT NULL DEFAULT 'viewer' CHECK (role = 'viewer'),
  token_hash TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
  state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','accepted','revoked')),
  created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  accepted_by UUID REFERENCES users(id) ON DELETE RESTRICT,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  accepted_at TIMESTAMPTZ,
  CHECK (expires_at > created_at),
  CHECK ((state = 'accepted' AND accepted_by IS NOT NULL AND accepted_at IS NOT NULL)
    OR (state <> 'accepted' AND accepted_by IS NULL AND accepted_at IS NULL)),
  UNIQUE (organization_id,id)
);
CREATE INDEX pending_invitations_org_recipient ON invitations(organization_id,recipient_email_normalized) WHERE state = 'pending';
CREATE TABLE invitation_resources (
  organization_id UUID NOT NULL,
  invitation_id UUID NOT NULL,
  project_id UUID NOT NULL,
  resource_id UUID NOT NULL,
  PRIMARY KEY (organization_id,invitation_id,project_id,resource_id),
  FOREIGN KEY (organization_id,invitation_id) REFERENCES invitations(organization_id,id) ON DELETE RESTRICT,
  FOREIGN KEY (organization_id,project_id,resource_id) REFERENCES project_resources(organization_id,project_id,resource_id) ON DELETE RESTRICT
);
CREATE INDEX invitation_resources_entitlement ON invitation_resources(organization_id,project_id,resource_id);
CREATE TABLE sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  verified_email TEXT,
  email_verified BOOLEAN NOT NULL DEFAULT false,
  authenticated_at TIMESTAMPTZ NOT NULL,
  claims_verified_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  CHECK (NOT email_verified OR (verified_email IS NOT NULL AND btrim(verified_email) <> '')),
  CHECK (expires_at > created_at AND expires_at <= created_at + interval '8 hours'),
  CHECK (last_seen_at >= created_at AND last_seen_at < expires_at)
);
CREATE INDEX sessions_user ON sessions(user_id);
CREATE TABLE command_receipts (
  actor_key TEXT NOT NULL,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
  operation TEXT NOT NULL,
  idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
  request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
  journal_reference TEXT CHECK (btrim(journal_reference) <> '' AND length(journal_reference) <= 200),
  response_status INTEGER NOT NULL CHECK (response_status BETWEEN 200 AND 299),
  response_body JSONB NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (actor_key,organization_id,operation,idempotency_key),
  CHECK (expires_at > created_at)
);
CREATE TABLE audit_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID REFERENCES organizations(id) ON DELETE RESTRICT,
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('user','service','migration')),
  actor_user_id UUID REFERENCES users(id) ON DELETE RESTRICT,
  actor_key TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  journal_reference TEXT CHECK (btrim(journal_reference) <> '' AND length(journal_reference) <= 200),
  safe_change_summary JSONB NOT NULL DEFAULT '{}',
  correlation_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (actor_kind <> 'user' OR actor_user_id IS NOT NULL)
);
CREATE INDEX audit_events_org_time ON audit_events(organization_id,created_at DESC,id DESC);
CREATE TABLE outbox_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
  invitation_id UUID,
  delivery_key TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','delivered','failed')),
  encrypted_payload BYTEA,
  payload_key_version INTEGER NOT NULL DEFAULT 1 CHECK (payload_key_version > 0),
  payload_purged_at TIMESTAMPTZ,
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  generation_attempts INTEGER NOT NULL DEFAULT 0 CHECK (generation_attempts BETWEEN 0 AND 8),
  replay_generation BIGINT NOT NULL DEFAULT 0 CHECK (replay_generation >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  retry_deadline_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp() + interval '30 minutes',
  available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  lease_owner TEXT,
  lease_token UUID,
  lease_expires_at TIMESTAMPTZ,
  last_attempt_at TIMESTAMPTZ,
  last_error_code TEXT CHECK (length(last_error_code) <= 64),
  delivered_at TIMESTAMPTZ,
  failed_at TIMESTAMPTZ,
  CHECK (retry_deadline_at > created_at),
  CHECK (generation_attempts <= attempts),
  CHECK ((lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
    OR (state = 'pending' AND lease_owner IS NOT NULL AND btrim(lease_owner) <> '' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)),
  CHECK ((state = 'pending' AND delivered_at IS NULL AND failed_at IS NULL)
    OR (state = 'delivered' AND delivered_at IS NOT NULL AND failed_at IS NULL)
    OR (state = 'failed' AND failed_at IS NOT NULL AND delivered_at IS NULL)),
  CHECK ((encrypted_payload IS NOT NULL AND payload_purged_at IS NULL)
    OR (encrypted_payload IS NULL AND payload_purged_at IS NOT NULL AND state <> 'pending')),
  FOREIGN KEY (organization_id,invitation_id) REFERENCES invitations(organization_id,id) ON DELETE RESTRICT
);
CREATE INDEX outbox_pending ON outbox_messages(available_at,id) WHERE state = 'pending';
CREATE TABLE report_configs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL,
  project_id UUID NOT NULL,
  name TEXT NOT NULL CHECK (btrim(name) <> ''),
  created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (organization_id,project_id,id),
  FOREIGN KEY (organization_id,project_id) REFERENCES projects(organization_id,id) ON DELETE RESTRICT
);
CREATE TABLE report_resource_refs (
  organization_id UUID NOT NULL,
  project_id UUID NOT NULL,
  report_config_id UUID NOT NULL,
  resource_id UUID NOT NULL,
  PRIMARY KEY (organization_id,project_id,report_config_id,resource_id),
  FOREIGN KEY (organization_id,project_id,report_config_id) REFERENCES report_configs(organization_id,project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY (organization_id,project_id,resource_id) REFERENCES project_resources(organization_id,project_id,resource_id) ON DELETE RESTRICT
);
CREATE INDEX report_refs_entitlement ON report_resource_refs(organization_id,project_id,resource_id);
CREATE TABLE migration_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_hash TEXT NOT NULL CHECK (length(snapshot_hash) = 64),
  policy_version TEXT NOT NULL,
  evidence_revision TEXT NOT NULL,
  baseline_manifest_hash TEXT CHECK (length(baseline_manifest_hash) = 64),
  target_manifest_hash TEXT CHECK (length(target_manifest_hash) = 64),
  state TEXT NOT NULL CHECK (state IN ('profiled','backfilled','reviewed','shadow','cutover','aborted')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE migration_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES migration_runs(id) ON DELETE RESTRICT,
  organization_id UUID REFERENCES organizations(id) ON DELETE RESTRICT,
  source_kind TEXT NOT NULL,
  source_key TEXT NOT NULL,
  source_hash TEXT NOT NULL CHECK (length(source_hash) = 64),
  transform_version TEXT NOT NULL,
  source_sequence BIGINT CHECK (source_sequence >= 0),
  result_hash TEXT CHECK (length(result_hash) = 64),
  outcome TEXT NOT NULL CHECK (outcome IN ('mapped','review_required','approved_change','retained','rejected')),
  target_kind TEXT,
  target_id TEXT,
  decision_reason TEXT,
  review_version BIGINT NOT NULL DEFAULT 1 CHECK (review_version > 0),
  assigned_owner_user_id UUID REFERENCES users(id) ON DELETE RESTRICT,
  reviewed_by UUID REFERENCES users(id) ON DELETE RESTRICT,
  reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (outcome <> 'approved_change' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND decision_reason IS NOT NULL)),
  UNIQUE (run_id,source_kind,source_key)
);
CREATE INDEX migration_ledger_org_outcome ON migration_ledger(run_id,organization_id,outcome);
CREATE TABLE migration_controls (
  organization_id UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE RESTRICT,
  writer_epoch BIGINT NOT NULL DEFAULT 1 CHECK (writer_epoch > 0),
  write_fenced BOOLEAN NOT NULL DEFAULT false,
  source_high_watermark BIGINT NOT NULL DEFAULT 0 CHECK (source_high_watermark >= 0),
  applied_high_watermark BIGINT NOT NULL DEFAULT 0 CHECK (applied_high_watermark >= 0),
  baseline_revision TEXT NOT NULL,
  current_run_id UUID REFERENCES migration_runs(id) ON DELETE RESTRICT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (applied_high_watermark <= source_high_watermark)
);
CREATE TABLE migration_decisions (
  run_id UUID NOT NULL REFERENCES migration_runs(id) ON DELETE RESTRICT,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
  principal_key TEXT NOT NULL,
  project_key TEXT NOT NULL,
  resource_key TEXT NOT NULL,
  action TEXT NOT NULL,
  baseline_allowed BOOLEAN,
  target_allowed BOOLEAN,
  reason TEXT NOT NULL,
  PRIMARY KEY (run_id,organization_id,principal_key,project_key,resource_key,action)
);
CREATE TABLE catalog_receipts (
  actor_key TEXT NOT NULL,
  external_key TEXT NOT NULL REFERENCES resources(external_key) ON DELETE RESTRICT,
  idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
  request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
  response_body JSONB NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (actor_key,external_key,idempotency_key)
);
-- Deployment must grant audit INSERT/SELECT only to the application role.
-- The application role must not own these tables or share the migration credential.
-- Foreign keys do not implement dynamic authorization or the documented locking protocol.
COMMIT;
