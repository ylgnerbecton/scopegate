-- Structural assertions only. All fixture data is synthetic and rolled back.
BEGIN;
DO $checks$
DECLARE
  identity_id UUID := gen_random_uuid();
  staff_identity_id UUID := gen_random_uuid();
  org_a UUID := gen_random_uuid();
  org_b UUID := gen_random_uuid();
  project_a UUID := gen_random_uuid();
  project_b UUID := gen_random_uuid();
  member_a UUID := gen_random_uuid();
  member_b UUID := gen_random_uuid();
  shared_resource UUID := gen_random_uuid();
  resource_b UUID := gen_random_uuid();
  invite_a UUID := gen_random_uuid();
  invite_b UUID := gen_random_uuid();
  report_a UUID := gen_random_uuid();
  report_b UUID := gen_random_uuid();
  migration_run UUID := gen_random_uuid();
  positive_count INTEGER := 0;
  negative_count INTEGER := 0;
  bad_statement TEXT;
  session_id UUID := gen_random_uuid();
BEGIN
  INSERT INTO users (id, issuer, subject, email) VALUES
    (identity_id, 'https://identity.example.test', 'subject-viewer', 'viewer@example.test'),
    (staff_identity_id, 'https://identity.example.test', 'subject-staff', 'staff@example.test');
  INSERT INTO organizations (id, name) VALUES (org_a, 'Organization Cedar'), (org_b, 'Organization Birch');
  INSERT INTO projects (id, organization_id, name) VALUES (project_a, org_a, 'Project Harbor'), (project_b, org_b, 'Project Grove');
  INSERT INTO memberships (id, organization_id, user_id) VALUES (member_a, org_a, identity_id), (member_b, org_b, identity_id);
  INSERT INTO memberships (organization_id, user_id, kind, expires_at, assignment_reason)
    VALUES (org_b, staff_identity_id, 'staff', clock_timestamp() + interval '1 day', 'Bounded support assignment');
  INSERT INTO resources (id, external_key, catalog_version) VALUES (shared_resource, 'resource-atlas', 1), (resource_b, 'resource-beacon', 1);
  INSERT INTO resource_localizations (resource_id, locale, title) VALUES (shared_resource, 'en', 'Resource Atlas');
  INSERT INTO project_resources (organization_id, project_id, resource_id) VALUES
    (org_a, project_a, shared_resource), (org_b, project_b, shared_resource), (org_b, project_b, resource_b);
  INSERT INTO resource_grants (organization_id, membership_id, project_id, resource_id) VALUES
    (org_a, member_a, project_a, shared_resource), (org_b, member_b, project_b, shared_resource);
  INSERT INTO invitations (id, organization_id, recipient_email, token_hash, created_by, expires_at) VALUES
    (invite_a, org_a, ' Viewer@Example.Test ', repeat('a', 64), identity_id, clock_timestamp() + interval '1 day'),
    (invite_b, org_b, 'viewer@example.test', repeat('b', 64), identity_id, clock_timestamp() + interval '1 day');
  INSERT INTO invitation_resources (organization_id, invitation_id, project_id, resource_id)
    VALUES (org_a, invite_a, project_a, shared_resource);
  INSERT INTO outbox_messages (organization_id, invitation_id, delivery_key, encrypted_payload)
    VALUES (org_a, invite_a, 'delivery-cedar', decode('01', 'hex'));
  INSERT INTO report_configs (id, organization_id, project_id, name, created_by) VALUES
    (report_a, org_a, project_a, 'Report Harbor', identity_id), (report_b, org_b, project_b, 'Report Grove', identity_id);
  INSERT INTO report_resource_refs (organization_id, project_id, report_config_id, resource_id)
    VALUES (org_a, project_a, report_a, shared_resource);
  INSERT INTO migration_runs (id, snapshot_hash, policy_version, evidence_revision, state)
    VALUES (migration_run, repeat('c', 64), 'policy-1', 'evidence-1', 'profiled');
  INSERT INTO migration_controls (organization_id, baseline_revision, current_run_id)
    VALUES (org_a, 'baseline-1', migration_run);

  IF (SELECT count(*) FROM memberships WHERE user_id = identity_id) <> 2 THEN
    RAISE EXCEPTION 'One verified identity did not retain two organization memberships';
  END IF;
  positive_count := positive_count + 1;

  IF (SELECT recipient_email_normalized FROM invitations WHERE id = invite_a) <> 'viewer@example.test' THEN
    RAISE EXCEPTION 'Invitation contact normalization differed from the contract';
  END IF;
  positive_count := positive_count + 1;

  UPDATE invitations SET state = 'accepted', accepted_by = identity_id, accepted_at = clock_timestamp()
    WHERE id = invite_b;
  IF NOT EXISTS (SELECT 1 FROM invitations WHERE id = invite_b AND state = 'accepted' AND accepted_by = identity_id AND accepted_at IS NOT NULL) THEN
    RAISE EXCEPTION 'Valid invitation acceptance linkage was not retained';
  END IF;
  positive_count := positive_count + 1;

  UPDATE resource_grants SET state = 'revoked'
    WHERE organization_id = org_a AND membership_id = member_a AND project_id = project_a AND resource_id = shared_resource;
  IF NOT EXISTS (SELECT 1 FROM resource_grants WHERE organization_id = org_a AND state = 'revoked')
     OR NOT EXISTS (SELECT 1 FROM resource_grants WHERE organization_id = org_b AND membership_id = member_b AND state = 'active') THEN
    RAISE EXCEPTION 'Scoped organization grant update affected another organization';
  END IF;
  positive_count := positive_count + 1;

  IF (SELECT count(*) FROM project_resources WHERE resource_id = shared_resource) <> 2 THEN
    RAISE EXCEPTION 'A shared resource could not have separate organization entitlements';
  END IF;
  positive_count := positive_count + 1;

  UPDATE memberships SET role = 'access_manager', can_review_migration = true
    WHERE organization_id = org_b AND user_id = staff_identity_id;
  IF NOT EXISTS (SELECT 1 FROM memberships WHERE organization_id = org_b AND user_id = staff_identity_id
                 AND kind = 'staff' AND role = 'access_manager' AND can_review_migration) THEN
    RAISE EXCEPTION 'Valid staff manager review capability was not retained';
  END IF;
  positive_count := positive_count + 1;

  -- Wrong organization for an otherwise valid membership.
  BEGIN
    INSERT INTO resource_grants (organization_id, membership_id, project_id, resource_id) VALUES (org_a, member_b, project_a, shared_resource);
    RAISE EXCEPTION 'Cross organization grant membership unexpectedly succeeded';
  EXCEPTION WHEN foreign_key_violation THEN negative_count := negative_count + 1;
  END;
  -- Wrong organization for an otherwise valid project and entitlement.
  BEGIN
    INSERT INTO resource_grants (organization_id, membership_id, project_id, resource_id) VALUES (org_a, member_a, project_b, resource_b);
    RAISE EXCEPTION 'Cross organization grant project unexpectedly succeeded';
  EXCEPTION WHEN foreign_key_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO resource_grants (organization_id, membership_id, project_id, resource_id) VALUES (org_a, member_a, project_a, resource_b);
    RAISE EXCEPTION 'Grant without a scoped entitlement unexpectedly succeeded';
  EXCEPTION WHEN foreign_key_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO project_resources (organization_id, project_id, resource_id) VALUES (org_a, project_b, resource_b);
    RAISE EXCEPTION 'Cross organization project entitlement unexpectedly succeeded';
  EXCEPTION WHEN foreign_key_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO memberships (organization_id, user_id) VALUES (org_a, identity_id);
    RAISE EXCEPTION 'Duplicate organization membership unexpectedly succeeded';
  EXCEPTION WHEN unique_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO users (issuer, subject, email) VALUES ('https://identity.example.test', 'subject-viewer', 'other@example.test');
    RAISE EXCEPTION 'Duplicate issuer and subject unexpectedly succeeded';
  EXCEPTION WHEN unique_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO resource_localizations (resource_id, locale, title) VALUES (shared_resource, 'en', 'Duplicate Atlas');
    RAISE EXCEPTION 'Duplicate resource locale unexpectedly succeeded';
  EXCEPTION WHEN unique_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO resources (external_key, catalog_version) VALUES ('resource-atlas', 1);
    RAISE EXCEPTION 'Duplicate external resource key unexpectedly succeeded';
  EXCEPTION WHEN unique_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO memberships (organization_id, user_id, kind, assignment_reason) VALUES (org_a, staff_identity_id, 'staff', 'Support');
    RAISE EXCEPTION 'Staff membership without expiry unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO memberships (organization_id, user_id, kind, expires_at) VALUES (org_a, staff_identity_id, 'staff', clock_timestamp() + interval '1 day');
    RAISE EXCEPTION 'Staff membership without reason unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO memberships (organization_id, user_id, kind, expires_at, assignment_reason)
      VALUES (org_a, staff_identity_id, 'staff', clock_timestamp() + interval '1 day', '   ');
    RAISE EXCEPTION 'Staff membership with blank reason unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE memberships SET role = 'access_manager', can_review_migration = true WHERE id = member_a;
    RAISE EXCEPTION 'Customer membership with migration review capability unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE memberships SET role = 'viewer', can_review_migration = true
      WHERE organization_id = org_b AND user_id = staff_identity_id;
    RAISE EXCEPTION 'Staff viewer with migration review capability unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO invitation_resources (organization_id, invitation_id, project_id, resource_id) VALUES (org_a, invite_b, project_a, shared_resource);
    RAISE EXCEPTION 'Cross organization invitation relation unexpectedly succeeded';
  EXCEPTION WHEN foreign_key_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO invitation_resources (organization_id, invitation_id, project_id, resource_id) VALUES (org_a, invite_a, project_b, resource_b);
    RAISE EXCEPTION 'Cross organization invitation entitlement unexpectedly succeeded';
  EXCEPTION WHEN foreign_key_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO outbox_messages (organization_id, invitation_id, delivery_key, encrypted_payload)
      VALUES (org_a, invite_b, 'delivery-invalid', decode('01', 'hex'));
    RAISE EXCEPTION 'Cross organization outbox invitation unexpectedly succeeded';
  EXCEPTION WHEN foreign_key_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO report_resource_refs (organization_id, project_id, report_config_id, resource_id) VALUES (org_a, project_a, report_a, resource_b);
    RAISE EXCEPTION 'Report without a scoped entitlement unexpectedly succeeded';
  EXCEPTION WHEN foreign_key_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO report_resource_refs (organization_id, project_id, report_config_id, resource_id) VALUES (org_b, project_b, report_a, resource_b);
    RAISE EXCEPTION 'Cross organization report configuration unexpectedly succeeded';
  EXCEPTION WHEN foreign_key_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO report_configs (organization_id, project_id, name, created_by) VALUES (org_a, project_b, 'Invalid report', identity_id);
    RAISE EXCEPTION 'Cross organization report project unexpectedly succeeded';
  EXCEPTION WHEN foreign_key_violation THEN negative_count := negative_count + 1;
  END;

  BEGIN
    UPDATE organizations SET status = 'invalid' WHERE id = org_a;
    RAISE EXCEPTION 'Invalid organization status unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE organizations SET access_mode = 'invalid' WHERE id = org_a;
    RAISE EXCEPTION 'Invalid access mode unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE projects SET status = 'invalid' WHERE id = project_a;
    RAISE EXCEPTION 'Invalid project status unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE memberships SET status = 'invalid' WHERE id = member_a;
    RAISE EXCEPTION 'Invalid membership status unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE memberships SET role = 'invalid' WHERE id = member_a;
    RAISE EXCEPTION 'Invalid membership role unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE memberships SET kind = 'invalid' WHERE id = member_a;
    RAISE EXCEPTION 'Invalid membership kind unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE resources SET status = 'invalid' WHERE id = shared_resource;
    RAISE EXCEPTION 'Invalid resource status unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE project_resources SET status = 'invalid' WHERE organization_id = org_a;
    RAISE EXCEPTION 'Invalid entitlement status unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE resource_grants SET state = 'invalid' WHERE organization_id = org_a;
    RAISE EXCEPTION 'Invalid grant state unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE invitations SET state = 'invalid' WHERE id = invite_a;
    RAISE EXCEPTION 'Invalid invitation state unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE invitations SET role = 'access_manager' WHERE id = invite_a;
    RAISE EXCEPTION 'Elevated customer invitation role unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE invitations SET state = 'accepted' WHERE id = invite_a;
    RAISE EXCEPTION 'Accepted invitation without identity linkage unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE invitations SET accepted_by = identity_id WHERE id = invite_a;
    RAISE EXCEPTION 'Pending invitation with a partial acceptance identity unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE invitations SET accepted_at = clock_timestamp() WHERE id = invite_a;
    RAISE EXCEPTION 'Pending invitation with a partial acceptance timestamp unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE invitations SET state = 'revoked', accepted_by = identity_id WHERE id = invite_a;
    RAISE EXCEPTION 'Revoked invitation with a partial acceptance identity unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE invitations SET state = 'revoked', accepted_at = clock_timestamp() WHERE id = invite_a;
    RAISE EXCEPTION 'Revoked invitation with a partial acceptance timestamp unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE outbox_messages SET state = 'invalid' WHERE organization_id = org_a;
    RAISE EXCEPTION 'Invalid outbox state unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE migration_runs SET state = 'invalid' WHERE id = migration_run;
    RAISE EXCEPTION 'Invalid migration state unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE migration_controls SET applied_high_watermark = 1 WHERE organization_id = org_a;
    RAISE EXCEPTION 'Applied watermark beyond captured watermark unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    UPDATE memberships SET access_version = 0 WHERE id = member_a;
    RAISE EXCEPTION 'Nonpositive membership version unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    INSERT INTO resource_localizations (resource_id, locale, title) VALUES (shared_resource, 'xx', 'Unsupported translation');
    RAISE EXCEPTION 'Unsupported locale unexpectedly succeeded';
  EXCEPTION WHEN check_violation THEN negative_count := negative_count + 1;
  END;

  -- PostgreSQL 18 reports explicit RESTRICT deletes as restrict_violation (23001).
  -- Deletion must fail instead of cascading away referenced access.
  BEGIN
    DELETE FROM users WHERE id = identity_id;
    RAISE EXCEPTION 'Referenced identity deletion unexpectedly succeeded';
  EXCEPTION WHEN restrict_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    DELETE FROM organizations WHERE id = org_a;
    RAISE EXCEPTION 'Referenced organization deletion unexpectedly succeeded';
  EXCEPTION WHEN restrict_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    DELETE FROM projects WHERE id = project_a;
    RAISE EXCEPTION 'Referenced project deletion unexpectedly succeeded';
  EXCEPTION WHEN restrict_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    DELETE FROM memberships WHERE id = member_a;
    RAISE EXCEPTION 'Referenced membership deletion unexpectedly succeeded';
  EXCEPTION WHEN restrict_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    DELETE FROM resources WHERE id = shared_resource;
    RAISE EXCEPTION 'Referenced resource deletion unexpectedly succeeded';
  EXCEPTION WHEN restrict_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    DELETE FROM project_resources WHERE organization_id = org_a AND project_id = project_a AND resource_id = shared_resource;
    RAISE EXCEPTION 'Referenced entitlement deletion unexpectedly succeeded';
  EXCEPTION WHEN restrict_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    DELETE FROM invitations WHERE id = invite_a;
    RAISE EXCEPTION 'Referenced invitation deletion unexpectedly succeeded';
  EXCEPTION WHEN restrict_violation THEN negative_count := negative_count + 1;
  END;
  BEGIN
    DELETE FROM report_configs WHERE id = report_a;
    RAISE EXCEPTION 'Referenced report deletion unexpectedly succeeded';
  EXCEPTION WHEN restrict_violation THEN negative_count := negative_count + 1;
  END;

  IF (SELECT count(*) FROM resource_grants WHERE organization_id IN (org_a, org_b)) <> 2
     OR NOT EXISTS (SELECT 1 FROM resource_grants WHERE organization_id = org_b AND state = 'active') THEN
    RAISE EXCEPTION 'Rejected deletes did not preserve existing access relationships';
  END IF;
  positive_count := positive_count + 1;
  -- Durable manager, entitlement revision, session and outbox lease/terminal guards.
  INSERT INTO sessions (id,token_hash,user_id,authenticated_at,claims_verified_at,expires_at)
    VALUES (session_id,repeat('f',64),identity_id,clock_timestamp(),clock_timestamp(),clock_timestamp()+interval '1 hour');
  FOREACH bad_statement IN ARRAY ARRAY[
    format('UPDATE memberships SET role=%L,expires_at=clock_timestamp()+interval %L WHERE id=%L','access_manager','1 day',member_a),
    format('UPDATE project_resources SET entitlement_version=0 WHERE organization_id=%L',org_a),
    format('UPDATE sessions SET expires_at=created_at+interval %L WHERE id=%L','9 hours',session_id),
    format('UPDATE sessions SET last_seen_at=created_at-interval %L WHERE id=%L','1 second',session_id),
    format('UPDATE sessions SET last_seen_at=expires_at WHERE id=%L',session_id),
    'UPDATE outbox_messages SET state=''delivered''',
    'UPDATE outbox_messages SET state=''failed''',
    'UPDATE outbox_messages SET delivered_at=clock_timestamp()',
    'UPDATE outbox_messages SET failed_at=clock_timestamp()',
    'UPDATE outbox_messages SET lease_owner=''worker-a''',
    'UPDATE outbox_messages SET lease_token=gen_random_uuid()',
    'UPDATE outbox_messages SET lease_expires_at=clock_timestamp()',
    'UPDATE outbox_messages SET payload_key_version=0',
    'UPDATE outbox_messages SET encrypted_payload=NULL',
    'UPDATE outbox_messages SET payload_purged_at=clock_timestamp()',
    'UPDATE outbox_messages SET generation_attempts=9,attempts=9',
    'UPDATE outbox_messages SET generation_attempts=1,attempts=0',
    'UPDATE outbox_messages SET replay_generation=-1',
    'UPDATE outbox_messages SET retry_deadline_at=created_at',
    'UPDATE outbox_messages SET last_error_code=repeat(''x'',65)'
  ] LOOP
    BEGIN
      EXECUTE bad_statement;
      RAISE EXCEPTION 'Invalid durability/session statement unexpectedly succeeded: %',bad_statement;
    EXCEPTION WHEN check_violation THEN negative_count:=negative_count+1;
    END;
  END LOOP;
  UPDATE outbox_messages SET lease_owner='worker-a',lease_token=gen_random_uuid(),lease_expires_at=clock_timestamp()+interval '30 seconds',attempts=1,generation_attempts=1,last_attempt_at=clock_timestamp();
  positive_count:=positive_count+1;
  UPDATE outbox_messages SET state='delivered',delivered_at=clock_timestamp(),lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL;
  positive_count:=positive_count+1;
  BEGIN
    UPDATE outbox_messages SET lease_owner='worker-a',lease_token=gen_random_uuid(),lease_expires_at=clock_timestamp()+interval '30 seconds';
    RAISE EXCEPTION 'Terminal delivery acquired lease';
  EXCEPTION WHEN check_violation THEN negative_count:=negative_count+1;
  END;
  UPDATE outbox_messages SET encrypted_payload=NULL,payload_purged_at=clock_timestamp();
  positive_count:=positive_count+1;

  -- Null/null and missing/null must not disappear from migration comparison.
  IF (WITH baseline(id,decision) AS (VALUES
      (1,NULL::boolean),(2,NULL::boolean),(3,false),(4,true),(5,false),(6,false),(7,true),(8,NULL::boolean)),
    target(id,decision) AS (VALUES
      (1,NULL::boolean),(2,false),(3,NULL::boolean),(4,false),(5,true),(6,false),(7,true),(9,NULL::boolean))
    SELECT count(*) FROM baseline b FULL JOIN target t USING(id)
    WHERE b.decision IS NULL OR t.decision IS NULL
       OR b.decision IS DISTINCT FROM t.decision) <> 7 THEN
    RAISE EXCEPTION 'Null or missing migration decision was accepted as parity';
  END IF;
  positive_count:=positive_count+1;

  RAISE NOTICE 'SCHEMA_CHECKS positive=% negative=%', positive_count, negative_count;
END;
$checks$;
ROLLBACK;
