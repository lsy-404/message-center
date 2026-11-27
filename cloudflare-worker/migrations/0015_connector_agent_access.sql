ALTER TABLE connector_instances ADD COLUMN agent_access TEXT NOT NULL DEFAULT 'read' CHECK(agent_access IN ('none', 'read', 'send'));
UPDATE connector_instances SET agent_access = 'send'
WHERE EXISTS (
  SELECT 1 FROM conversations c
  WHERE c.connector_id = connector_instances.id AND c.trust_tier = 'trusted'
    AND json_valid(c.agent_policy_json) AND json_extract(c.agent_policy_json, '$.enabled') = 1
);
